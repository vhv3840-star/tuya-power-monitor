import asyncio
import logging
import math
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select, delete
from .domain import SessionTracker, in_window
from .storage import SettingsRow, Device, Sample, Charge, Rule, Event
from .schemas import Preferences
from .providers import TuyaProvider, ProviderError, discover_mapping, normalize_metric, decode_readings
from .seed import seed

log = logging.getLogger('monitor')


class Engine:
    def __init__(self, config, factory):
        self.config, self.db = config, factory
        self.lock = asyncio.Lock()
        self.provider = TuyaProvider(config)
        self.live, self.trackers, self.charge_ids = {}, {}, {}
        self.demo_started, self.demo_finish, self.disconnected = {}, set(), set()
        self.previous, self.rule_low = {}, {}
        self.task = None
        self.last_poll, self.last_cleanup = 0, 0
        with self.db() as db:
            row = db.get(SettingsRow, 1)
            if not row:
                row = SettingsRow(id=1, value=Preferences().model_dump())
                db.add(row)
            self.preferences = Preferences.model_validate(row.value)
            if self.preferences.mode == 'tuya' and not config.password:
                raise ValueError('APP_PASSWORD is required in Tuya mode')
            if config.seed_demo:
                seed(db)
            for charge in db.scalars(select(Charge).where(Charge.status == 'active')):
                last = db.scalar(select(Sample.at).where(Sample.device_id == charge.device_id, Sample.mode == charge.mode).order_by(Sample.at.desc()).limit(1))
                charge.ended = max(charge.started, last or charge.started)
                charge.status = 'interrupted'
            db.commit()

    def event(self, db, kind, message, mode=None):
        db.add(Event(mode=mode or self.preferences.mode, kind=kind, message=message))
        log.info('%s: %s', kind, message)

    def start(self):
        self.task = asyncio.create_task(self.run())

    async def close(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        await self.provider.close()

    async def run(self):
        while True:
            try:
                async with self.lock:
                    now = time.time()
                    interval = 2 if self.preferences.mode == 'demo' else self.config.poll_seconds
                    if now - self.last_poll >= interval:
                        await self.poll(now)
                        self.last_poll = time.time()
                    await self.rules_tick(time.time())
                    if now - self.last_cleanup > 86400:
                        with self.db() as db:
                            db.execute(delete(Sample).where(Sample.at < now - 90 * 86400))
                            db.execute(delete(Event).where(Event.at < now - 90 * 86400))
                            db.commit()
                        self.last_cleanup = now
            except Exception:
                log.exception('Server tick failed')
            await asyncio.sleep(1)

    async def discover(self):
        if not self.config.password:
            raise ProviderError('Для Tuya задайте APP_PASSWORD в .env и перезапустите сервер.')
        devices = await self.provider.devices()
        with self.db() as db:
            allowed = set()
            for item in devices:
                did = str(item['id'])
                allowed.add(did)
                schema = await self.provider.schema(did)
                device = db.get(Device, did)
                if not device:
                    device = Device(id=did, mode='tuya', name=item.get('name', did), schema=schema, mapping=discover_mapping(schema), relay=None)
                    db.add(device)
                else:
                    device.schema = schema
                    device.name = item.get('name', did)
                    valid_codes = {s['code'] for s in schema.get('functions', []) + schema.get('status', [])}
                    device.mapping = {k: v for k, v in device.mapping.items() if v in valid_codes}
            # Previously authorized devices are kept as history but cannot be controlled.
            for old in db.scalars(select(Device).where(Device.mode == 'tuya')):
                if old.id not in allowed:
                    old.mapping = {}
                    self.live.pop(old.id, None)
            self.event(db, 'connection', f'Tuya: доступно устройств — {len(devices)}', 'tuya')
            db.commit()
        return len(devices)

    async def poll(self, now):
        with self.db() as db:
            devices = db.scalars(select(Device).where(Device.mode == self.preferences.mode)).all()
            for device in devices:
                try:
                    if device.mode == 'demo':
                        if device.id in self.disconnected:
                            raise ProviderError('Демо: потеря соединения')
                        if device.relay:
                            start = self.demo_started.setdefault(device.id, now)
                            elapsed = now - start
                            power = .7 if device.id in self.demo_finish or elapsed >= 180 else max(4, 72 * (1 - .85 * (elapsed / 180) ** 3) + math.sin(elapsed / 6) * 3)
                        else:
                            power = 0
                        values = {'power': round(power, 2), 'voltage': round(230.2 + math.sin(now / 13) * .8, 1),
                                  'current': round(power / 230.2, 4), 'energy': None, 'relay': device.relay}
                    else:
                        statuses = await self.provider.status(device.id)
                        values = decode_readings(statuses, device.schema, device.mapping)
                        device.relay = values['relay']
                    # Timestamp after completed cloud I/O, rather than before request.
                    self.ingest(db, device, time.time() if device.mode == 'tuya' else now, values)
                except ProviderError as exc:
                    old = self.live.get(device.id, {})
                    if old.get('online') is not False:
                        self.event(db, 'warning', f'{device.name}: {exc}')
                        db.add(Sample(device_id=device.id, mode=device.mode, at=time.time(), power=None, voltage=None, current=None, energy=0))
                    self.live[device.id] = {**old, 'online': False, 'error': str(exc), 'error_code': exc.code, 'error_hint': exc.hint}
                    if device.id in self.trackers:
                        self.trackers[device.id].feed(now, None)
                    self.previous.pop(device.id, None)
                    for rule in db.scalars(select(Rule).where(Rule.device_id == device.id)):
                        self.rule_low.pop(rule.id, None)
            db.commit()

    def ingest(self, db, device, now, values):
        power = values.get('power')
        energy = 0
        previous = self.previous.get(device.id)
        gap = max(90, self.config.poll_seconds * 3)
        if power is None or (previous and now - previous[0] > gap):
            for rule_id in db.scalars(select(Rule.id).where(Rule.device_id == device.id)):
                self.rule_low.pop(rule_id, None)
            if previous and now - previous[0] > gap:
                db.add(Sample(device_id=device.id, mode=device.mode, at=previous[0] + gap / 2, power=None, voltage=None, current=None, energy=0))
        if previous and power is not None:
            dt = now - previous[0]
            if 0 < dt <= gap:
                energy = (power + previous[1]) / 2 * dt / 3600000
        if power is None:
            self.previous.pop(device.id, None)
        else:
            self.previous[device.id] = (now, power)
        p = self.preferences
        tracker = self.trackers.setdefault(device.id, SessionTracker(p.start_w, p.end_w, p.hold_s, max_gap_s=gap))
        tracker.start_w, tracker.end_w, tracker.hold_s, tracker.start_hold_s = p.start_w, p.end_w, p.hold_s, p.start_hold_s
        transition = tracker.feed(now, power)
        if transition == 'started':
            charge = Charge(device_id=device.id, mode=device.mode, started=tracker.started_at)
            db.add(charge)
            db.flush()
            self.charge_ids[device.id] = charge.id
            self.event(db, 'charge', f'{device.name}: начат сеанс зарядки')
        charge_id = self.charge_ids.get(device.id)
        if charge_id:
            charge = db.get(Charge, charge_id)
            charge.energy, charge.average, charge.peak = tracker.energy_kwh, tracker.average_w, tracker.peak_w
            if transition == 'completed':
                charge.ended, charge.status = now, 'completed'
                self.charge_ids.pop(device.id, None)
                self.event(db, 'completed', f'{device.name}: сеанс завершён · {charge.energy:.4f} кВт·ч')
        db.add(Sample(device_id=device.id, mode=device.mode, at=now, power=power, voltage=values.get('voltage'), current=values.get('current'), energy=energy))
        self.live[device.id] = {**values, 'online': True, 'updated_at': now, 'error': None,
                                'session_started': tracker.started_at if tracker.active else None,
                                'session_energy': tracker.energy_kwh if tracker.active else 0,
                                'low_since': tracker.low_since if tracker.active else None}

    async def relay(self, device_id, on, source='Пользователь'):
        with self.db() as db:
            device = db.get(Device, device_id)
            if not device or device.mode != self.preferences.mode:
                raise ProviderError('Устройство не найдено в текущем режиме')
            if not device.mapping.get('switch'):
                raise ProviderError('У этой модели нет настроенной команды реле. Проверьте схему в «Устройства».')
            try:
                if device.mode == 'tuya':
                    if not self.live.get(device_id, {}).get('online'):
                        raise ProviderError('Устройство не в сети. Команда не отправлена.')
                    functions = device.schema.get('functions', [])
                    if not any(f.get('code') == device.mapping['switch'] and f.get('type', '').lower() in ('bool', 'boolean') for f in functions):
                        raise ProviderError('Команда не поддерживается текущей схемой')
                    await self.provider.command(device_id, device.mapping['switch'], on)
                    statuses = await self.provider.confirm_relay(device_id, device.mapping['switch'], on)
                    self.ingest(db, device, time.time(), decode_readings(statuses, device.schema, device.mapping))
                elif device_id in self.disconnected:
                    raise ProviderError('Демо-устройство не в сети')
            except ProviderError as exc:
                message='результат команды не подтверждён' if exc.code=='state_unconfirmed' else 'команда не выполнена'
                self.event(db, 'command_failed', f'{source}: {device.name} · {message}')
                db.commit()
                raise
            device.relay = on
            if on:
                self.demo_started[device_id] = time.time()
                self.demo_finish.discard(device_id)
            self.event(db, 'command', f'{source}: {device.name} → {"ВКЛ" if on else "ВЫКЛ"} · состояние подтверждено' if device.mode == 'tuya' else f'{source}: {device.name} → {"ВКЛ" if on else "ВЫКЛ"}')
            db.commit()
        self.last_poll = 0

    async def rules_tick(self, now):
        local = datetime.fromtimestamp(now, ZoneInfo(self.preferences.timezone))
        hhmm, day = local.strftime('%H:%M'), local.strftime('%Y-%m-%d')
        with self.db() as db:
            rules = db.scalars(select(Rule).where(Rule.mode == self.preferences.mode, Rule.enabled == True).order_by(Rule.id.desc())).all()
            for rule in rules:
                state = self.live.get(rule.device_id, {})
                if not state.get('online') or now - state.get('updated_at', 0) > max(90, self.config.poll_seconds * 3):
                    self.rule_low.pop(rule.id, None)
                    continue
                cfg, action, key = rule.config, None, None
                if rule.kind == 'timer' and rule.due_at is not None and now >= rule.due_at:
                    action = False
                elif rule.kind == 'max_duration':
                    start = state.get('session_started')
                    if start is not None and now - start >= cfg['minutes'] * 60 and state.get('relay'):
                        action, key = False, str(start)
                elif rule.kind == 'low_power':
                    power = state.get('power')
                    if state.get('relay') and power is not None and power <= cfg['threshold']:
                        observed_at = state['updated_at']
                        low = self.rule_low.setdefault(rule.id, observed_at)
                        if observed_at - low >= cfg['hold_s']:
                            action = False
                    else:
                        self.rule_low.pop(rule.id, None)
                elif rule.kind in ('schedule', 'night'):
                    if rule.kind == 'night':
                        # Enforce the window even after a server restart.
                        target = in_window(hhmm, cfg['start'], cfg['end'])
                        if state.get('relay') is not None and state['relay'] != target:
                            action = target
                    elif hhmm == cfg['start']:
                        action, key = True, day + ':on'
                    elif hhmm == cfg['end']:
                        action, key = False, day + ':off'
                if action is None or (key and rule.last_run == key):
                    continue
                try:
                    await self.relay(rule.device_id, action, rule.name)
                    rule.last_run = key or str(now)
                    if rule.kind in ('timer', 'low_power'):
                        rule.enabled = False
                    self.event(db, 'automation', f'Правило «{rule.name}» выполнено')
                except ProviderError:
                    # No success record; retry at the next poll, not every second.
                    self.live[rule.device_id] = {**state, 'online': False, 'error': 'Команда автоматизации не выполнена; ожидается повторный опрос'}
                db.commit()

    def set_preferences(self, value, *, allow_cloud_activation=False):
        if value.mode == 'tuya' and not self.config.password:
            raise ProviderError('Задайте APP_PASSWORD в .env перед включением Tuya.')
        if value.mode=='tuya' and self.preferences.mode!='tuya' and not allow_cloud_activation:
            raise ProviderError('Реальный режим включается через Connection Setup.',code='activation_required',
                                hint='Выполните диагностику и нажмите «Использовать эту розетку». Это приостановит старые реальные правила перед активацией.')
        with self.db() as db:
            if value.mode != self.preferences.mode:
                for charge in db.scalars(select(Charge).where(Charge.status == 'active')):
                    charge.status, charge.ended = 'interrupted', time.time()
                self.live.clear()
                self.trackers.clear()
                self.charge_ids.clear()
                self.previous.clear()
                self.rule_low.clear()
            db.get(SettingsRow, 1).value = value.model_dump()
            db.commit()
        self.preferences = value
        self.last_poll = 0
