import time
import pytest
from fastapi.testclient import TestClient
from backend.config import Config
from backend.main import create_app
from backend.storage import Rule, Charge, Device
from backend.schemas import Preferences, RuleBody


@pytest.fixture
def client(tmp_path):
    app = create_app(Config(database_url='sqlite:///' + str(tmp_path / 'test.db'), seed_demo=True))
    with TestClient(app) as c:
        c.headers['X-Requested-With'] = 'TuyaMonitor'
        yield c


def test_demo_command_and_csv(client):
    data = client.get('/api/state').json()
    assert data['preferences']['mode'] == 'demo'
    assert len(data['devices']) == 2
    assert client.post('/api/devices/demo-desk/relay', json={'on': False}).status_code == 200
    assert client.get('/api/history?device_id=demo-desk').json()['total'] >= 90
    csv = client.get('/api/export?device_id=demo-desk')
    assert csv.status_code == 200
    assert 'mode' in csv.text and 'demo' in csv.text
    assert client.get('/api/analytics?device_id=demo-desk&period=week').json()['energy'] > 0


def test_validation_and_origin(client):
    assert client.post('/api/rules', json={'device_id': 'demo-desk', 'name': 'test', 'kind': 'timer', 'minutes': 0}).status_code == 422
    preferences = client.get('/api/state').json()['preferences']
    preferences['end_w'] = 500
    assert client.put('/api/settings', json=preferences).status_code == 422
    assert client.post('/api/devices/demo-desk/relay', json={'on': True}, headers={'Origin': 'https://evil.test'}).status_code == 403
    assert client.post('/api/demo/demo-desk', json={'action': 'finish'}, headers={'X-Requested-With': ''}).status_code == 403


def test_real_mode_requires_password(client):
    preferences = client.get('/api/state').json()['preferences']
    preferences['mode'] = 'tuya'
    assert client.put('/api/settings', json=preferences).status_code == 400


def test_password_protects_api_and_ws(tmp_path):
    app = create_app(Config(database_url='sqlite:///' + str(tmp_path / 'auth.db'), password='test-password'))
    with TestClient(app) as c:
        assert c.get('/api/state').status_code == 401
        assert c.post('/auth/login', json={'password': 'wrong'}, headers={'X-Requested-With': 'TuyaMonitor'}).status_code == 401
        assert c.post('/auth/login', json={'password': 'test-password'}, headers={'X-Requested-With': 'TuyaMonitor'}).status_code == 200
        assert c.get('/api/state').status_code == 200
        with c.websocket_connect('/ws', headers={'Origin': 'http://127.0.0.1:8000'}) as ws:
            assert ws.receive_json()['preferences']['mode'] == 'demo'


def test_no_secrets_in_state(client):
    body = client.get('/api/state').text
    assert 'client_secret' not in body and 'session_secret' not in body


def test_rule_persists_and_timer_runs(client):
    result = client.post('/api/rules', json={'device_id': 'demo-desk', 'name': 'Timer', 'kind': 'timer', 'minutes': 1})
    assert result.status_code == 200
    rule_id = result.json()['id']
    engine = client.app.state.monitor
    with engine.db() as db:
        rule = db.get(Rule, rule_id)
        rule.due_at = time.time() - 1
        db.commit()
    client.portal.call(engine.rules_tick, time.time())
    with engine.db() as db:
        assert not db.get(Rule, rule_id).enabled
        assert db.get(Device, 'demo-desk').relay is False


def test_low_power_rule_requires_continuous_readings(client):
    result = client.post('/api/rules', json={'device_id': 'demo-desk', 'name': 'Low', 'kind': 'low_power', 'hold_s': 10})
    engine = client.app.state.monitor
    rid = result.json()['id']
    now = time.time()
    engine.live['demo-desk'] = {'online': True, 'updated_at': now, 'relay': True, 'power': 1}
    client.portal.call(engine.rules_tick, now)
    with engine.db() as db:
        assert db.get(Rule, rid).enabled
    engine.live['demo-desk']['online'] = False
    client.portal.call(engine.rules_tick, now + 9)
    engine.live['demo-desk']['online'] = True
    engine.live['demo-desk']['updated_at'] = now + 11
    client.portal.call(engine.rules_tick, now + 11)
    with engine.db() as db:
        assert db.get(Rule, rid).enabled
    engine.live['demo-desk']['updated_at'] = now + 22
    client.portal.call(engine.rules_tick, now + 22)
    with engine.db() as db:
        assert not db.get(Rule, rid).enabled


def test_restart_marks_session_interrupted(tmp_path):
    cfg = Config(database_url='sqlite:///' + str(tmp_path / 'restart.db'), seed_demo=False)
    app = create_app(cfg)
    with TestClient(app) as c:
        engine = c.app.state.monitor
        with engine.db() as db:
            db.add(Charge(device_id='a', mode='demo', started=time.time() - 100, status='active'))
            db.commit()
    with TestClient(create_app(cfg)) as c:
        with c.app.state.monitor.db() as db:
            charge = db.query(Charge).one()
            assert charge.status == 'interrupted'
            assert charge.ended == charge.started


def test_low_power_rule_does_not_bridge_unobserved_gap(client):
    result = client.post('/api/rules', json={'device_id': 'demo-desk', 'name': 'Gap', 'kind': 'low_power', 'hold_s': 60})
    engine = client.app.state.monitor
    now = time.time()
    rid = result.json()['id']
    async def reproduce():
        async with engine.lock:
            with engine.db() as db:
                device = db.get(Device, 'demo-desk')
                engine.ingest(db, device, now, {'power': 1, 'relay': True})
                db.commit()
            await engine.rules_tick(now)
            with engine.db() as db:
                engine.ingest(db, db.get(Device, 'demo-desk'), now + 100, {'power': 1, 'relay': True})
                db.commit()
            await engine.rules_tick(now + 100)
    client.portal.call(reproduce)
    with engine.db() as db:
        assert db.get(Rule, rid).enabled, 'Unobserved time must not confirm low power'


def test_max_duration_requires_power(client):
    engine = client.app.state.monitor
    with engine.db() as db:
        db.get(Device, 'demo-bedroom').mapping = {'switch': 'switch_1'}
        db.commit()
    response = client.post('/api/rules', json={'device_id': 'demo-bedroom', 'name': 'Limit', 'kind': 'max_duration'})
    assert response.status_code == 422


def test_outage_records_gap_marker(client):
    from backend.storage import Sample
    from sqlalchemy import select
    client.post('/api/demo/demo-desk', json={'action': 'disconnect'})
    engine = client.app.state.monitor
    with engine.db() as db:
        last = db.scalar(select(Sample).where(Sample.device_id == 'demo-desk').order_by(Sample.at.desc()).limit(1))
        assert last.power is None


def test_low_power_waits_for_confirming_measurement(client):
    result = client.post('/api/rules', json={'device_id': 'demo-desk', 'name': 'Confirm', 'kind': 'low_power', 'hold_s': 5})
    engine = client.app.state.monitor
    now = time.time()
    rid = result.json()['id']
    async def reproduce():
        async with engine.lock:
            engine.live['demo-desk'] = {'online': True, 'updated_at': now, 'relay': True, 'power': 1}
            await engine.rules_tick(now)
            await engine.rules_tick(now + 6)
    client.portal.call(reproduce)
    with engine.db() as db:
        assert db.get(Rule, rid).enabled, 'A stale low reading is not confirmation'
