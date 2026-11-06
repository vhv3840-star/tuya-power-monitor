import asyncio
import time
import httpx
import pytest
from fastapi.testclient import TestClient
from backend.config import Config
from backend.main import create_app
from backend.providers import ProviderError, TuyaProvider
from backend.seed import DEMO_SCHEMA
from backend.storage import Device, Rule, Event


def test_provider_confirm_waits_for_reported_match():
    async def scenario():
        provider = TuyaProvider(Config())
        replies = iter([[{'code':'switch_1','value':False}], [{'code':'switch_1','value':True}]])
        async def status(did):
            return next(replies)
        provider.status = status
        result = await provider.confirm_relay('plug', 'switch_1', True, attempts=2, delay=0)
        assert result[0]['value'] is True
        await provider.close()
    asyncio.run(scenario())


def test_provider_confirm_rejects_mismatch_and_missing_boolean():
    async def scenario():
        provider = TuyaProvider(Config())
        async def status(did):
            return [{'code':'switch_1','value':1}]
        provider.status = status
        with pytest.raises(ProviderError, match='не подтверждено'):
            await provider.confirm_relay('plug','switch_1',True,attempts=1,delay=0)
        await provider.close()
    asyncio.run(scenario())


def test_safe_actionable_tuya_error():
    async def scenario():
        provider = TuyaProvider(Config(client_id='secret-id',client_secret='secret-value'))
        await provider.http.aclose()
        provider.http = httpx.AsyncClient(base_url='https://openapi.tuyaeu.com', transport=httpx.MockTransport(
            lambda request: httpx.Response(200,json={'success':False,'code':28841105,'msg':'secret-value'})))
        with pytest.raises(ProviderError) as raised:
            await provider.authenticate()
        assert raised.value.code == '28841105'
        assert 'API' in raised.value.hint
        assert 'secret-value' not in str(raised.value)
        await provider.close()
    asyncio.run(scenario())


@pytest.fixture
def connected(tmp_path):
    config = Config(database_url='sqlite:///'+str(tmp_path/'connection.db'), password='test-password',
                    client_id='private-client',client_secret='private-secret',uid='fixture-uid',seed_demo=False)
    with TestClient(create_app(config)) as client:
        client.headers['X-Requested-With']='TuyaMonitor'
        client.post('/auth/login',json={'password':'test-password'})
        provider=client.app.state.monitor.provider
        calls=[]
        async def authenticate():
            return True
        async def devices():
            return [{'id':'real-plug','name':'Настоящая розетка','online':True}]
        async def schema(did):
            return DEMO_SCHEMA
        async def status(did):
            return [{'code':'switch_1','value':False},{'code':'cur_power','value':450},
                    {'code':'cur_voltage','value':2301},{'code':'cur_current','value':195}]
        async def command(*args):
            calls.append(args)
        provider.authenticate=authenticate
        provider.devices=devices
        provider.schema=schema
        provider.status=status
        provider.command=command
        yield client,calls


def test_diagnostics_read_real_schema_without_commands(connected):
    client,calls=connected
    response=client.post('/api/connection/diagnose')
    assert response.status_code==200
    report=response.json()
    assert report['devices'][0]['readings']['power']==45
    assert report['devices'][0]['readings']['voltage']==230.1
    assert report['devices'][0]['id']=='real-plug'
    assert report['devices'][0]['command_ready'] is True
    assert calls==[]
    assert 'private-secret' not in response.text and 'private-client' not in response.text
    assert client.get('/api/state').json()['preferences']['mode']=='demo'
    assert report['physical_verification']['status']=='pending'


def test_diagnostics_missing_config_does_not_call_cloud(tmp_path):
    with TestClient(create_app(Config(database_url='sqlite:///'+str(tmp_path/'missing.db'),seed_demo=False,
                                     password='',client_id='',client_secret='',uid='',device_ids=[]))) as client:
        response=client.post('/api/connection/diagnose',headers={'X-Requested-With':'TuyaMonitor'})
        assert response.status_code==200
        report=response.json()
        assert report['steps'][0]['status']=='fail'
        assert report['devices']==[]
        assert 'APP_PASSWORD' in report['steps'][0]['hint']


def test_activation_pauses_rules_without_switching_relay(connected):
    client,calls=connected
    client.post('/api/connection/diagnose')
    engine=client.app.state.monitor
    with engine.db() as db:
        db.add(Rule(device_id='real-plug',mode='tuya',name='Old timer',kind='timer',enabled=True,config={'minutes':1},due_at=time.time()-1))
        db.commit()
    result=client.post('/api/connection/activate',json={'device_id':'real-plug'})
    assert result.status_code==200
    assert client.get('/api/state').json()['preferences']['mode']=='tuya'
    with engine.db() as db:
        assert db.query(Rule).one().enabled is False
    assert calls==[]


def test_test_command_requires_explicit_confirmation(connected):
    client,calls=connected
    result=client.post('/api/connection/devices/real-plug/test',json={'on':True,'confirmed':False})
    assert result.status_code==422
    assert calls==[]


def test_acknowledgement_without_status_match_is_not_success(connected):
    client,calls=connected
    client.post('/api/connection/diagnose')
    client.post('/api/connection/activate',json={'device_id':'real-plug'})
    provider=client.app.state.monitor.provider
    async def unconfirmed(*args,**kwargs):
        raise ProviderError('Состояние реле не подтверждено',code='state_unconfirmed',hint='Проверьте розетку')
    provider.confirm_relay=unconfirmed
    response=client.post('/api/devices/real-plug/relay',json={'on':True})
    assert response.status_code==400
    engine=client.app.state.monitor
    with engine.db() as db:
        assert db.get(Device,'real-plug').relay is False
        assert db.query(Event).filter(Event.kind=='command').count()==0
    assert len(calls)==1


def test_no_observations_are_not_zero_energy(connected):
    client,_=connected
    stats=client.get('/api/analytics?device_id=not-yet-observed').json()
    assert stats['energy'] is None and stats['cost'] is None
    assert all(point['energy'] is None for point in stats['chart'])


def test_diagnostic_and_activation_do_not_send_commands_and_proofs_require_tests(connected):
    client,calls=connected
    report=client.post('/api/connection/diagnose').json()
    assert report['physical_verification']['tests']=={}
    assert client.post('/api/connection/activate',json={'device_id':'real-plug'}).status_code==200
    provider=client.app.state.monitor.provider
    async def command(did,code,on):
        calls.append((did,code,on))
    async def confirmed(did,code,on):
        return [{'code':code,'value':on},{'code':'cur_power','value':120}]
    provider.command=command
    provider.confirm_relay=confirmed
    for on in (True,False):
        result=client.post('/api/connection/devices/real-plug/test',json={'on':on,'confirmed':True})
        assert result.status_code==200
        assert result.json()['confirmed'] is True
    assert len(calls)==2
    report=client.get('/api/connection').json()
    assert report['physical_verification']['status']=='cloud_confirmed'
    assert report['physical_verification']['tests']['real-plug']['on']['reported_relay'] is True
    assert report['physical_verification']['tests']['real-plug']['off']['reported_relay'] is False
    assert report['devices'][0]['readings']['relay'] is False


def test_changed_mapping_invalidates_setup_proof(connected):
    client,calls=connected
    client.post('/api/connection/diagnose')
    engine=client.app.state.monitor
    with engine.db() as db:
        db.get(Device,'real-plug').mapping={}
        db.commit()
    report=client.get('/api/connection').json()
    assert report['stale'] is True
    assert client.post('/api/connection/devices/real-plug/test',json={'on':False,'confirmed':True}).status_code==409
    assert calls==[]


def test_settings_cannot_bypass_safe_cloud_activation(connected):
    client,calls=connected
    prefs=client.get('/api/state').json()['preferences']
    prefs['mode']='tuya'
    result=client.put('/api/settings',json=prefs)
    assert result.status_code==400
    assert result.json()['code']=='activation_required'
    assert client.get('/api/state').json()['preferences']['mode']=='demo'
    assert calls==[]


def test_custom_schema_relay_can_be_mapped_without_activating(connected):
    client,calls=connected
    provider=client.app.state.monitor.provider
    async def schema(did):
        return {'functions':[{'code':'relay_main','type':'Boolean','values':'{}'}],
                'status':[{'code':'relay_main','type':'Boolean','values':'{}'}]}
    async def status(did):
        return [{'code':'relay_main','value':False}]
    provider.schema=schema
    provider.status=status
    report=client.post('/api/connection/diagnose').json()
    assert not report['devices'][0]['command_ready']
    assert client.put('/api/connection/devices/real-plug/mapping',json={'switch':'relay_main'}).status_code==200
    assert client.get('/api/state').json()['preferences']['mode']=='demo'
    report=client.post('/api/connection/diagnose').json()
    assert report['devices'][0]['command_ready']
    assert report['devices'][0]['readings']['power'] is None
    assert not report['devices'][0]['energy_supported']
    assert client.post('/api/connection/activate',json={'device_id':'real-plug'}).status_code==200
    assert calls==[]
