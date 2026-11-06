"""HTTP boundary tests use a controlled transport, never a physical device."""
import asyncio
import json
import time
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select
from backend.config import Config
from backend.main import create_app
from backend.providers import TuyaProvider, ProviderError, signed_headers
from backend.seed import DEMO_SCHEMA
from backend.storage import Device, Charge, Event


def test_tuya_http_token_schema_status_command_flow():
    calls = []
    def handler(request):
        path = request.url.raw_path.decode()
        token = '' if path.startswith('/v1.0/token?') else 'token-fixture'
        expected = signed_headers('fixture-id', 'fixture-secret', request.method, path,
                                  request.content.decode(), token, request.headers['t'])
        assert request.headers['sign'] == expected['sign']
        calls.append(path)
        if path.startswith('/v1.0/token?'):
            result = {'access_token': 'token-fixture', 'expire_time': 7200}
        elif path == '/v1.0/users/linked-uid/devices':
            result = [{'id': 'plug', 'name': 'Plug', 'online': True}]
        elif path.endswith('/specification'):
            result = DEMO_SCHEMA
        elif path == '/v1.0/devices/plug':
            result = {'id': 'plug', 'online': True}
        elif path.endswith('/status'):
            result = [{'code': 'cur_power', 'value': 450}, {'code': 'switch_1', 'value': True}]
        else:
            assert json.loads(request.content) == {'commands': [{'code': 'switch_1', 'value': False}]}
            result = True
        return httpx.Response(200, json={'success': True, 'result': result})

    async def scenario():
        provider = TuyaProvider(Config(client_id='fixture-id', client_secret='fixture-secret', uid='linked-uid'))
        await provider.http.aclose()
        provider.http = httpx.AsyncClient(base_url='https://openapi.tuyaeu.com', transport=httpx.MockTransport(handler))
        assert (await provider.devices())[0]['id'] == 'plug'
        assert (await provider.schema('plug'))['functions'][0]['code'] == 'switch_1'
        assert (await provider.status('plug'))[0]['value'] == 450
        await provider.command('plug', 'switch_1', False)
        await provider.close()
    asyncio.run(scenario())
    assert calls.count('/v1.0/token?grant_type=1') == 1


def test_failed_cloud_command_preserves_relay(tmp_path):
    cfg = Config(database_url='sqlite:///' + str(tmp_path / 'failed.db'), password='fixture-password', seed_demo=False)
    app = create_app(cfg)
    with TestClient(app) as client:
        client.headers['X-Requested-With'] = 'TuyaMonitor'
        client.post('/auth/login', json={'password': 'fixture-password'})
        engine = app.state.monitor
        with engine.db() as db:
            db.add(Device(id='plug', mode='tuya', name='Plug', schema=DEMO_SCHEMA, mapping={'switch':'switch_1'}, relay=True))
            db.commit()
        preferences = engine.preferences.model_copy(update={'mode': 'tuya'})
        client.portal.call(lambda: engine.set_preferences(preferences,allow_cloud_activation=True))
        async def command_failure(device_id, code, value):
            raise ProviderError('Cloud command failed')
        engine.provider.command = command_failure
        engine.live['plug'] = {'online': True, 'updated_at': time.time(), 'relay': True}
        response = client.post('/api/devices/plug/relay', json={'on':False})
        assert response.status_code == 400
        with engine.db() as db:
            assert db.get(Device,'plug').relay is True
            assert db.scalar(select(Event).where(Event.kind == 'command_failed')) is not None
            assert db.scalar(select(Event).where(Event.kind == 'command')) is None


def test_mode_isolation_for_history_and_csv(tmp_path):
    cfg = Config(database_url='sqlite:///' + str(tmp_path / 'isolation.db'), password='fixture-password')
    with TestClient(create_app(cfg)) as client:
        client.headers['X-Requested-With'] = 'TuyaMonitor'
        client.post('/auth/login', json={'password':'fixture-password'})
        engine = client.app.state.monitor
        with engine.db() as db:
            db.add(Charge(device_id='cloud-only', mode='tuya', started=time.time()-60, ended=time.time(), energy=100, status='completed'))
            db.commit()
        assert client.get('/api/history?device_id=cloud-only').json()['total'] == 0
        assert 'cloud-only' not in client.get('/api/export?device_id=cloud-only').text
        prefs = client.get('/api/state').json()['preferences']
        prefs['mode'] = 'tuya'
        client.portal.call(lambda: engine.set_preferences(engine.preferences.model_copy(update={'mode':'tuya'}),allow_cloud_activation=True))
        assert client.get('/api/history?device_id=cloud-only').json()['total'] == 1
        assert client.get('/api/history?device_id=demo-desk').json()['total'] == 0
        assert 'demo-desk' not in client.get('/api/export?device_id=demo-desk').text
