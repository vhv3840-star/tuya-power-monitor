import asyncio
import csv
import hashlib
import hmac
import io
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI, Request, Response, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from .config import Config, ROOT
from .storage import connect, Device, Rule, Sample, Charge
from .schemas import Preferences, RelayBody, DemoBody, RuleBody, RuleToggle, MappingBody, LoginBody, ActivateBody, TestRelayBody
from .providers import ProviderError, normalize_metric
from .engine import Engine
from .analytics import state, history, analytics, rules_list, chart_samples
from .diagnostics import diagnose, get_report, activate, record_test

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')


def create_app(config=None):
    cfg = config or Config()
    database_engine, factory = connect(cfg.database_url)
    login_attempts = defaultdict(list)

    @asynccontextmanager
    async def lifespan(app):
        monitor = Engine(cfg, factory)
        app.state.monitor = monitor
        monitor.start()
        try:
            yield
        finally:
            await monitor.close()
            database_engine.dispose()

    app = FastAPI(title='TUYA POWER MONITOR', version='1.0.0', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def authenticated(cookie):
        if not cfg.password:
            return True
        try:
            expiry, signature = cookie.split('.')
            expected = hmac.new(cfg.session_secret.encode(), (expiry + ':' + cfg.password).encode(), hashlib.sha256).hexdigest()
            return int(expiry) > time.time() and hmac.compare_digest(expected, signature)
        except (ValueError, AttributeError):
            return False

    @app.middleware('http')
    async def protection(request, call_next):
        path = request.url.path
        if path.startswith(('/api/', '/auth/')):
            origin = request.headers.get('origin')
            if origin and origin not in cfg.allowed_origins:
                return JSONResponse({'detail': 'Недопустимый источник запроса'}, status_code=403)
            if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('x-requested-with') != 'TuyaMonitor':
                return JSONResponse({'detail': 'Отсутствует защитный заголовок'}, status_code=403)
            if path.startswith('/api/') and not authenticated(request.cookies.get('monitor_session', '')):
                return JSONResponse({'detail': 'Требуется вход'}, status_code=401)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        if path.startswith(('/api/', '/auth/')):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        return JSONResponse({'detail': str(exc), 'code': exc.code, 'hint': exc.hint}, status_code=400)

    @app.get('/health')
    def health():
        return {'status': 'ok', 'app': 'tuya-power-monitor'}

    @app.get('/auth/status')
    def auth_status(request: Request):
        return {'authenticated': authenticated(request.cookies.get('monitor_session', '')), 'required': bool(cfg.password)}

    @app.post('/auth/login')
    def login(body: LoginBody, request: Request, response: Response):
        ip = request.client.host if request.client else 'unknown'
        now = time.time()
        login_attempts[ip] = [t for t in login_attempts[ip] if now - t < 60]
        if len(login_attempts[ip]) >= 10:
            raise HTTPException(429, 'Слишком много попыток. Повторите через минуту.')
        login_attempts[ip].append(now)
        if not hmac.compare_digest(body.password.encode(), cfg.password.encode()):
            raise HTTPException(401, 'Неверный пароль')
        expiry = str(int(now + 86400))
        signature = hmac.new(cfg.session_secret.encode(), (expiry + ':' + cfg.password).encode(), hashlib.sha256).hexdigest()
        response.set_cookie('monitor_session', expiry + '.' + signature, max_age=86400, httponly=True,
                            secure=cfg.secure_cookie, samesite='strict')
        login_attempts.pop(ip, None)
        return {'ok': True}

    @app.post('/auth/logout')
    def logout(response: Response):
        response.delete_cookie('monitor_session')
        return {'ok': True}

    def monitor():
        return app.state.monitor

    def get_device(db, device_id):
        device = db.get(Device, device_id)
        if not device or device.mode != monitor().preferences.mode:
            raise HTTPException(404, 'Устройство не найдено в текущем режиме')
        return device

    def apply_mapping(device,body):
        statuses={s['code']:s for s in device.schema.get('status',[])}
        functions={s['code']:s for s in device.schema.get('functions',[])}
        result={k:v for k,v in body.model_dump().items() if v}
        for kind,code in result.items():
            if kind=='switch':
                if code not in functions or functions[code].get('type','').lower() not in ('boolean','bool'):
                    raise HTTPException(422,'Реле должно быть Boolean из functions этой модели')
            elif code not in statuses or normalize_metric(0,statuses[code],kind) is None:
                raise HTTPException(422,f'{kind}: код не найден или единица измерения не поддерживается')
        device.mapping=result

    @app.get('/api/state')
    def get_state():
        return state(monitor())

    @app.get('/api/connection')
    def connection_report():
        return get_report(monitor())

    @app.post('/api/connection/diagnose')
    async def connection_diagnose():
        async with monitor().lock:
            return await diagnose(monitor())

    @app.post('/api/connection/activate')
    async def connection_activate(body: ActivateBody):
        async with monitor().lock:
            return await activate(monitor(),body.device_id)

    @app.put('/api/connection/devices/{device_id}/mapping')
    async def connection_mapping(device_id:str,body:MappingBody):
        async with monitor().lock:
            report=get_report(monitor())
            if report.get('stale') or not any(d['id']==device_id for d in report['devices']):
                raise HTTPException(409,'Повторите диагностику текущей конфигурации перед сопоставлением.')
            with monitor().db() as db:
                device=db.get(Device,device_id)
                if not device or device.mode!='tuya':
                    raise HTTPException(404,'Реальное устройство не найдено')
                apply_mapping(device,body)
                db.commit()
        return {'ok':True,'rediagnose_required':True}

    @app.post('/api/connection/devices/{device_id}/test')
    async def connection_test(device_id:str,body:TestRelayBody):
        async with monitor().lock:
            report=get_report(monitor())
            if report.get('stale') or not any(d['id']==device_id and d['command_ready'] for d in report['devices']):
                raise HTTPException(409,'Сначала выполните диагностику и активируйте устройство.')
            with monitor().db() as db:
                if get_device(db,device_id).mode!='tuya':
                    raise HTTPException(400,'Проверка предназначена только для физического устройства Tuya.')
            await monitor().relay(device_id,body.on,'Подтверждённый тест ON' if body.on else 'Подтверждённый тест OFF')
            return {'ok':True,'confirmed':True,'report':record_test(monitor(),device_id,body.on)}

    @app.put('/api/settings')
    async def update_settings(body: Preferences):
        async with monitor().lock:
            monitor().set_preferences(body)
        return {'ok': True}

    @app.post('/api/devices/discover')
    async def discover():
        async with monitor().lock:
            count = await monitor().discover()
            monitor().last_poll = 0
        return {'count': count}

    @app.post('/api/devices/{device_id}/relay')
    async def relay(device_id: str, body: RelayBody):
        async with monitor().lock:
            await monitor().relay(device_id, body.on)
            if monitor().preferences.mode=='demo':
                await monitor().poll(time.time())
        return {'ok': True}

    @app.put('/api/devices/{device_id}/mapping')
    async def mapping(device_id: str, body: MappingBody):
        async with monitor().lock:
            with monitor().db() as db:
                device = get_device(db, device_id)
                apply_mapping(device,body)
                db.commit()
            monitor().last_poll = 0
        return {'ok': True}

    @app.post('/api/demo/{device_id}')
    async def demo(device_id: str, body: DemoBody):
        if monitor().preferences.mode != 'demo':
            raise HTTPException(400, 'Симуляция доступна только в деморежиме')
        async with monitor().lock:
            with monitor().db() as db:
                get_device(db, device_id)
            if body.action == 'charge':
                await monitor().relay(device_id, True, 'Демо')
            elif body.action == 'finish':
                monitor().demo_finish.add(device_id)
            elif body.action == 'disconnect':
                monitor().disconnected.add(device_id)
            else:
                monitor().disconnected.discard(device_id)
            await monitor().poll(time.time())
        return {'ok': True}

    @app.get('/api/history')
    def get_history(device_id: str, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=500)):
        return history(monitor(), device_id, offset, limit)

    @app.get('/api/history/{charge_id}/samples')
    def charge_samples(charge_id: int):
        with monitor().db() as db:
            charge = db.get(Charge, charge_id)
            if not charge or charge.mode != monitor().preferences.mode:
                raise HTTPException(404, 'Сеанс не найден')
            samples = db.scalars(select(Sample).where(Sample.device_id == charge.device_id, Sample.mode == charge.mode,
                                Sample.at >= charge.started, Sample.at <= (charge.ended or time.time())).order_by(Sample.at)).all()
            return [{'at': s.at, 'power': s.power} for s in chart_samples(samples, 400)]

    @app.get('/api/analytics')
    def get_analytics(device_id: str, period: Literal['day', 'week', 'month'] = 'day'):
        return analytics(monitor(), device_id, period)

    @app.get('/api/export')
    def export(device_id: str):
        result = io.StringIO(newline='')
        writer = csv.writer(result)
        writer.writerow(['session_id', 'device_id', 'mode', 'started_utc', 'ended_utc', 'duration_s', 'energy_kwh_estimated', 'cost_kzt_at_current_tariff', 'average_w', 'peak_w', 'status'])
        from datetime import datetime, timezone
        with monitor().db() as db:
            rows = db.scalars(select(Charge).where(Charge.mode == monitor().preferences.mode, Charge.device_id == device_id).order_by(Charge.started.desc()))
            for c in rows:
                writer.writerow([c.id, c.device_id, c.mode, datetime.fromtimestamp(c.started, timezone.utc).isoformat(),
                                 datetime.fromtimestamp(c.ended, timezone.utc).isoformat() if c.ended else '',
                                 round((c.ended or time.time()) - c.started), round(c.energy, 6), round(c.energy * monitor().preferences.tariff, 4),
                                 round(c.average, 2), round(c.peak, 2), c.status])
        return Response('\ufeff' + result.getvalue(), media_type='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename="tuya-charging-history.csv"'})

    @app.get('/api/rules')
    def get_rules():
        return rules_list(monitor())

    @app.post('/api/rules')
    async def add_rule(body: RuleBody):
        async with monitor().lock:
            with monitor().db() as db:
                device = get_device(db, body.device_id)
                if not device.mapping.get('switch'):
                    raise HTTPException(422, 'Устройство не поддерживает управление реле')
                if body.kind in ('low_power', 'max_duration') and not device.mapping.get('power'):
                    raise HTTPException(422, 'Устройство не предоставляет мощность')
                row = Rule(device_id=body.device_id, mode=monitor().preferences.mode, name=body.name, kind=body.kind, enabled=body.enabled,
                           config=body.model_dump(exclude={'device_id', 'name', 'kind', 'enabled'}),
                           due_at=time.time() + body.minutes * 60 if body.kind == 'timer' else None)
                db.add(row)
                db.commit()
                return {'id': row.id}

    @app.patch('/api/rules/{rule_id}')
    async def toggle_rule(rule_id: int, body: RuleToggle):
        async with monitor().lock:
            with monitor().db() as db:
                row = db.get(Rule, rule_id)
                if not row or row.mode != monitor().preferences.mode:
                    raise HTTPException(404, 'Правило не найдено')
                row.enabled = body.enabled
                row.last_run = None
                monitor().rule_low.pop(rule_id, None)
                if row.kind == 'timer' and body.enabled:
                    row.due_at = time.time() + row.config['minutes'] * 60
                db.commit()
        return {'ok': True}

    @app.delete('/api/rules/{rule_id}')
    async def delete_rule(rule_id: int):
        async with monitor().lock:
            with monitor().db() as db:
                row = db.get(Rule, rule_id)
                if not row or row.mode != monitor().preferences.mode:
                    raise HTTPException(404, 'Правило не найдено')
                db.delete(row)
                db.commit()
            monitor().rule_low.pop(rule_id, None)
        return {'ok': True}

    @app.websocket('/ws')
    async def websocket(ws: WebSocket):
        origin = ws.headers.get('origin')
        if (origin and origin not in cfg.allowed_origins) or not authenticated(ws.cookies.get('monitor_session', '')):
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            while True:
                if not authenticated(ws.cookies.get('monitor_session', '')):
                    await ws.close(code=1008)
                    return
                await ws.send_json(state(monitor()))
                await asyncio.sleep(2)
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass

    if (ROOT / 'dist').exists():
        app.mount('/assets', StaticFiles(directory=ROOT / 'dist' / 'assets'), name='assets')

        @app.get('/{path:path}')
        def frontend(path: str):
            return FileResponse(ROOT / 'dist' / 'index.html')

    return app
