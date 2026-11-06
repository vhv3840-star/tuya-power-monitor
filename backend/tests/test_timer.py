"""Timer lifecycle through the API, using the isolated demo engine."""
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import backend.main as main
from backend.config import Config
from backend.engine import Engine
from backend.main import create_app
from backend.storage import Device, Rule


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Advance the scheduler explicitly: tests neither wait a minute nor use Tuya.
    monkeypatch.setattr(Engine, 'start', lambda self: None)
    cfg = Config(database_url='sqlite:///' + str(tmp_path / 'timer.db'), password='',
                 client_id='', client_secret='', uid='', device_ids=[])
    with TestClient(create_app(cfg)) as client:
        client.headers['X-Requested-With'] = 'TuyaMonitor'
        client.portal.call(client.app.state.monitor.poll, time.time())
        assert client.post('/api/devices/demo-desk/relay', json={'on': False}).status_code == 200
        yield client


def create_timer(client, **overrides):
    return client.post('/api/rules', json={
        'device_id': 'demo-desk', 'name': 'Timer', 'kind': 'timer', 'minutes': 1,
        **overrides,
    })


def relay_state(client):
    with client.app.state.monitor.db() as db:
        return db.get(Device, 'demo-desk').relay


def test_timer_turns_on_then_off_at_deadline(client):
    before = time.time()
    response = create_timer(client)
    assert response.status_code == 200
    assert relay_state(client) is True
    engine = client.app.state.monitor
    rid = response.json()['id']
    with engine.db() as db:
        row = db.get(Rule, rid)
        due = row.due_at
        assert row.enabled and before + 60 <= due <= time.time() + 60
    client.portal.call(engine.rules_tick, due - .01)
    assert relay_state(client) is True
    client.portal.call(engine.rules_tick, due)
    assert relay_state(client) is False
    with engine.db() as db:
        assert not db.get(Rule, rid).enabled
        assert db.get(Rule, rid).last_run is not None


def test_countdown_begins_after_on_confirmation(client, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(main, 'time', SimpleNamespace(time=lambda: clock[0]))
    engine = client.app.state.monitor
    original = engine.relay

    async def delayed_confirmation(*args, **kwargs):
        await original(*args, **kwargs)
        clock[0] += 7

    monkeypatch.setattr(engine, 'relay', delayed_confirmation)
    result = create_timer(client)
    assert result.status_code == 200
    with engine.db() as db:
        assert db.get(Rule, result.json()['id']).due_at == clock[0] + 60
    assert relay_state(client) is True


def test_disabled_timer_starts_only_when_enabled_and_can_restart(client):
    rid = create_timer(client, enabled=False).json()['id']
    assert relay_state(client) is False
    engine = client.app.state.monitor
    with engine.db() as db:
        assert db.get(Rule, rid).due_at is None
    for _ in range(2):
        assert client.patch(f'/api/rules/{rid}', json={'enabled': True}).status_code == 200
        assert relay_state(client) is True
        with engine.db() as db:
            due = db.get(Rule, rid).due_at
        client.portal.call(engine.rules_tick, due)
        assert relay_state(client) is False
        with engine.db() as db:
            assert not db.get(Rule, rid).enabled


def test_repeated_enable_does_not_restart_running_timer(client):
    rid = create_timer(client).json()['id']
    engine = client.app.state.monitor
    with engine.db() as db:
        due = db.get(Rule, rid).due_at
    # A duplicate/retried request must not undo the user's manual OFF.
    client.post('/api/devices/demo-desk/relay', json={'on': False})
    assert client.patch(f'/api/rules/{rid}', json={'enabled': True}).status_code == 200
    assert relay_state(client) is False
    with engine.db() as db:
        assert db.get(Rule, rid).due_at == due


def test_offline_device_cannot_start_timer(client):
    client.post('/api/demo/demo-desk', json={'action': 'disconnect'})
    response = create_timer(client)
    assert response.status_code == 400
    assert relay_state(client) is False
    assert client.get('/api/rules').json() == []


def test_failed_restart_preserves_disabled_rule(client):
    rid = create_timer(client, enabled=False).json()['id']
    client.post('/api/demo/demo-desk', json={'action': 'disconnect'})
    assert client.patch(f'/api/rules/{rid}', json={'enabled': True}).status_code == 400
    with client.app.state.monitor.db() as db:
        row = db.get(Rule, rid)
        assert not row.enabled and row.due_at is None and row.last_run is None
    assert relay_state(client) is False


def test_disabling_timer_keeps_current_power_state(client):
    rid = create_timer(client).json()['id']
    assert client.patch(f'/api/rules/{rid}', json={'enabled': False}).status_code == 200
    assert relay_state(client) is True
    engine = client.app.state.monitor
    with engine.db() as db:
        due = db.get(Rule, rid).due_at
    client.portal.call(engine.rules_tick, due)
    assert relay_state(client) is True


def test_other_rule_kinds_do_not_switch_on_when_created(client):
    for kind in ('low_power', 'max_duration', 'schedule', 'night'):
        assert create_timer(client, kind=kind).status_code == 200
        assert relay_state(client) is False
