"""Read-only cloud inspection. No method in this module sends a relay command."""
import copy
import hashlib
import hmac
import json
import time
from sqlalchemy import select
from .providers import ProviderError, REGIONS, decode_readings, discover_mapping, normalize_metric, properties
from .storage import ConnectionReport, Device, Rule


def fingerprint(config):
    value = json.dumps([config.region, config.client_id, config.client_secret, config.uid, config.device_ids])
    return hmac.new(config.session_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def public_report(report):
    return {k: v for k, v in report.items() if not k.startswith('_')}


def pending_report(config):
    return {'checked_at': None, 'region': config.region, 'endpoint': REGIONS[config.region], 'steps': [], 'devices': [],
            'stale': False, 'physical_verification': {'status': 'pending', 'tests': {}},
            'configuration': {'password': bool(config.password), 'client_id': bool(config.client_id),
                              'client_secret': bool(config.client_secret), 'device_source': bool(config.uid or config.device_ids)}}


def get_report(engine):
    with engine.db() as db:
        row = db.get(ConnectionReport, 1)
        if not row:
            return pending_report(engine.config)
        report = copy.deepcopy(row.value)
    with engine.db() as db:
        schema_changed=any((stored:=db.get(Device,device['id'])) is None or stored.schema!=device['schema'] or stored.mapping!=device['mapping']
                           for device in report.get('devices',[]))
    if report.get('_fingerprint') != fingerprint(engine.config) or schema_changed:
        report['stale'] = True
        report['physical_verification'] = {'status': 'pending', 'tests': {}}
        report['configuration'] = pending_report(engine.config)['configuration']
    return public_report(report)


def save_report(engine, report):
    with engine.db() as db:
        row = db.get(ConnectionReport, 1)
        payload = {**report, '_fingerprint': fingerprint(engine.config)}
        if row:
            row.value = payload
        else:
            db.add(ConnectionReport(id=1, value=payload))
        db.commit()


def error_step(stage, title, error):
    return {'id': stage, 'title': title, 'status': 'fail', 'message': str(error), 'code': error.code, 'hint': error.hint}


async def diagnose(engine, *, persist=True):
    config, provider = engine.config, engine.provider
    report = pending_report(config)
    report['checked_at'] = time.time()
    old = get_report(engine) if persist else pending_report(config)
    missing = []
    for name, value in [('APP_PASSWORD', config.password), ('TUYA_CLIENT_ID', config.client_id), ('TUYA_CLIENT_SECRET', config.client_secret)]:
        if not value:
            missing.append(name)
    if not (config.uid or config.device_ids):
        missing.append('TUYA_UID или TUYA_DEVICE_IDS')
    if missing:
        report['steps'].append({'id':'configuration', 'title':'Настройки сервера', 'status':'fail',
                                'message':'Не все параметры подключения заданы.',
                                'hint':'Заполните ' + ', '.join(missing) + ' в .env и перезапустите сервер.', 'code':'missing_configuration'})
        if persist:
            save_report(engine, report)
        return report
    report['steps'].append({'id':'configuration','title':'Настройки сервера','status':'pass',
                            'message':f'Ключи заданы только на сервере · регион {config.region.upper()}.'})
    try:
        await provider.authenticate()
        report['steps'].append({'id':'authorization','title':'Доступ к Cloud и авторизация','status':'pass',
                                'message':'Официальный API Tuya выдал токен. Токен не передаётся в браузер.'})
    except ProviderError as exc:
        report['steps'].append(error_step('authorization','Доступ к Cloud и авторизация',exc))
        if persist:
            save_report(engine,report)
        return report
    try:
        items = await provider.devices()
        report['steps'].append({'id':'devices','title':'Устройства аккаунта Smart Life','status':'pass' if items else 'warning',
                                'message':f'Найдено разрешённых устройств: {len(items)}.',
                                'hint':None if items else 'В Devices → Link Tuya App Account привяжите тот аккаунт Smart Life, где добавлена розетка. Проверьте регион и UID.'})
    except ProviderError as exc:
        report['steps'].append(error_step('devices','Устройства аккаунта Smart Life',exc))
        if persist:
            save_report(engine,report)
        return report
    authorized = set()
    for item in items:
        did = str(item['id'])
        authorized.add(did)
        result = {'id':did,'name':item.get('name',did),'online':bool(item.get('online',False)),
                  'schema':{},'mapping':{},'readings':{},'points':[],'status_readable':False,
                  'command_ready':False,'energy_supported':False,'errors':[]}
        try:
            schema = await provider.schema(did)
            if not isinstance(schema,dict) or not isinstance(schema.get('functions',[]),list) or not isinstance(schema.get('status',[]),list):
                raise ProviderError('Устройство вернуло некорректную схему.',code='invalid_schema')
            result['schema'] = schema
            mapping = discover_mapping(schema)
            if persist:
                with engine.db() as db:
                    stored = db.get(Device,did)
                    if stored and stored.mode == 'tuya':
                        functions={s['code']:s for s in schema.get('functions',[])}
                        statuses={s['code']:s for s in schema.get('status',[])}
                        for kind,code in stored.mapping.items():
                            if kind=='switch' and functions.get(code,{}).get('type','').lower() in ('boolean','bool'):
                                mapping[kind]=code
                            elif kind!='switch' and code in statuses and normalize_metric(0,statuses[code],kind) is not None:
                                mapping[kind]=code
            result['mapping']=mapping
        except ProviderError as exc:
            result['errors'].append({'message':str(exc),'code':exc.code,'hint':exc.hint})
        try:
            statuses=await provider.status(did)
            result['online'],result['status_readable']=True,True
            result['readings']=decode_readings(statuses,result['schema'],result['mapping'])
            raw={s['code']:s.get('value') for s in statuses}
            seen=set()
            for group in ('functions','status'):
                for point in result['schema'].get(group,[]):
                    if point['code'] in seen:
                        continue
                    seen.add(point['code'])
                    props=properties(point)
                    result['points'].append({'code':point['code'],'type':point.get('type',''),
                                             'scale':props.get('scale'),'unit':props.get('unit'),
                                             'raw_value':raw.get(point['code']), 'writable':any(f['code']==point['code'] for f in result['schema'].get('functions',[]))})
            result['command_ready']=bool(result['mapping'].get('switch') and isinstance(result['readings'].get('relay'),bool))
            result['energy_supported']=bool(result['mapping'].get('power') and result['readings'].get('power') is not None)
        except ProviderError as exc:
            result['online']=False if exc.code=='device_offline' else result['online']
            result['errors'].append({'message':str(exc),'code':exc.code,'hint':exc.hint})
        report['devices'].append(result)
        if persist:
            with engine.db() as db:
                stored=db.get(Device,did)
                if not stored:
                    stored=Device(id=did,mode='tuya',name=result['name'],schema=result['schema'],mapping=result['mapping'],relay=result['readings'].get('relay'))
                    db.add(stored)
                else:
                    stored.name,stored.schema,stored.mapping=result['name'],result['schema'],result['mapping']
                    if result['status_readable']:
                        stored.relay=result['readings'].get('relay')
                db.commit()
    if persist:
        with engine.db() as db:
            for device in db.scalars(select(Device).where(Device.mode=='tuya')):
                if device.id not in authorized:
                    device.mapping={}
            db.commit()
    ready=sum(d['command_ready'] for d in report['devices'])
    report['steps'].append({'id':'inspection','title':'Схема и состояние розеток','status':'pass' if ready else 'warning',
                            'message':f'Готово к проверке управления: {ready}. Диагностика не переключала реле.',
                            'hint':None if ready else 'Выберите онлайн-устройство с Boolean-командой реле и доступным status. Для нестандартных кодов откройте «Сопоставление модели» в Connection Setup.'})
    if not old.get('stale'):
        for did,tests in old['physical_verification'].get('tests',{}).items():
            old_device=next((d for d in old['devices'] if d['id']==did),None)
            new_device=next((d for d in report['devices'] if d['id']==did),None)
            if old_device and new_device and old_device['schema']==new_device['schema'] and old_device['mapping']==new_device['mapping']:
                report['physical_verification']['tests'][did]=tests
    if any(t.get('on') and t.get('off') for t in report['physical_verification']['tests'].values()):
        report['physical_verification']['status']='cloud_confirmed'
    if persist:
        save_report(engine,report)
    return report


async def activate(engine, device_id):
    # Refresh identity, permissions and state without issuing commands.
    report=await diagnose(engine)
    device=next((d for d in report['devices'] if d['id']==device_id),None)
    if not device or not device['command_ready']:
        raise ProviderError('Устройство не готово к управлению.',code='device_not_ready',
                            hint='Запустите диагностику и устраните ошибки схемы/состояния. Реле не переключалось.')
    with engine.db() as db:
        for rule in db.scalars(select(Rule).where(Rule.mode=='tuya')):
            rule.enabled=False
        db.commit()
    engine.set_preferences(engine.preferences.model_copy(update={'mode':'tuya'}),allow_cloud_activation=True)
    with engine.db() as db:
        engine.ingest(db,db.get(Device,device_id),time.time(),device['readings'])
        db.commit()
    engine.last_poll=0
    return {'ok':True,'device_id':device_id,'rules_paused':True}


def record_test(engine,device_id,on):
    report=get_report(engine)
    if report.get('stale'):
        raise ProviderError('Конфигурация изменилась. Повторите диагностику.',code='stale_diagnostics')
    target=next((d for d in report['devices'] if d['id']==device_id),None)
    if not target:
        raise ProviderError('Сначала выполните диагностику этого устройства.',code='missing_diagnostics')
    tests=report['physical_verification']['tests'].setdefault(device_id,{})
    tests['on' if on else 'off']={'confirmed_at':time.time(),'reported_relay':on,'source':'Tuya Cloud status'}
    report['physical_verification']['status']='cloud_confirmed' if tests.get('on') and tests.get('off') else 'pending'
    current=engine.live.get(device_id,{})
    target['readings']={key:current.get(key) for key in ('relay','power','voltage','current','energy')}
    for point in target['points']:
        if point['code']==target['mapping'].get('switch'):
            point['raw_value']=on
    save_report(engine,report)
    return report
