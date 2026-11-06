import time
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select, func
from .storage import Device, Sample, Charge, Rule, Event


def chart_samples(samples, maximum=180):
    """Downsample for display while retaining null outage markers and recovery."""
    stride = max(1, len(samples) // maximum)
    return [sample for i, sample in enumerate(samples)
            if i % stride == 0 or i == len(samples) - 1 or sample.power is None
            or (i > 0 and samples[i - 1].power is None)]


def device_dict(device, live):
    return {'id': device.id, 'name': device.name, 'mode': device.mode, 'mapping': device.mapping,
            'schema': device.schema, 'relay': device.relay, **live}


def state(engine):
    mode = engine.preferences.mode
    with engine.db() as db:
        devices = db.scalars(select(Device).where(Device.mode == mode)).all()
        events = db.scalars(select(Event).where(Event.mode == mode).order_by(Event.at.desc(), Event.id.desc()).limit(30)).all()
        return {
            'preferences': engine.preferences.model_dump(), 'server_time': time.time(),
            'devices': [device_dict(d, engine.live.get(d.id, {'online': False, 'relay': d.relay, 'error': 'Ожидание первого опроса'})) for d in devices],
            'events': [{'id': e.id, 'at': e.at, 'kind': e.kind, 'message': e.message} for e in events],
            'cloud': {'configured': bool(engine.config.client_id and engine.config.client_secret),
                      'region': engine.config.region, 'password_enabled': bool(engine.config.password),
                      'poll_seconds': engine.config.poll_seconds},
        }


def charge_dict(c, tariff):
    return {'id': c.id, 'device_id': c.device_id, 'mode': c.mode, 'started': c.started, 'ended': c.ended,
            'duration': (c.ended or time.time()) - c.started, 'energy': c.energy, 'cost': c.energy * tariff,
            'average': c.average, 'peak': c.peak, 'status': c.status}


def history(engine, device_id, offset=0, limit=20):
    with engine.db() as db:
        where = (Charge.mode == engine.preferences.mode, Charge.device_id == device_id)
        total = db.scalar(select(func.count()).select_from(Charge).where(*where))
        charges = db.scalars(select(Charge).where(*where).order_by(Charge.started.desc()).offset(offset).limit(limit)).all()
        return {'total': total, 'items': [charge_dict(c, engine.preferences.tariff) for c in charges]}


def analytics(engine, device_id, period):
    days = {'day': 1, 'week': 7, 'month': 30}[period]
    now = time.time()
    cutoff, previous = now - days * 86400, now - days * 86400 * 2
    mode = engine.preferences.mode
    with engine.db() as db:
        samples = db.scalars(select(Sample).where(Sample.mode == mode, Sample.device_id == device_id, Sample.at >= previous).order_by(Sample.at)).all()
        charges = db.scalars(select(Charge).where(Charge.mode == mode, Charge.device_id == device_id, Charge.started >= cutoff)).all()
    current = [s for s in samples if s.at >= cutoff]
    power_observed=any(s.power is not None for s in current)
    previous_observed=any(s.power is not None for s in samples if s.at < cutoff)
    energy = sum(s.energy for s in current)
    prev_energy = sum(s.energy for s in samples if s.at < cutoff)
    completed = [c for c in charges if c.ended is not None and c.status == 'completed']
    tz = ZoneInfo(engine.preferences.timezone)
    step = 3600 if days == 1 else 86400
    buckets = {}
    # Relative, evenly spaced intervals, labelled in configured local timezone.
    for i in range(days * 86400 // step):
        at = cutoff + i * step
        label = datetime.fromtimestamp(at, tz).strftime('%H:%M' if days == 1 else '%d.%m')
        buckets[i] = {'label': label, 'at': at, 'energy': 0, 'power': 0, 'count': 0}
    for sample in current:
        i = min(len(buckets) - 1, int((sample.at - cutoff) // step))
        bucket = buckets[i]
        bucket['energy'] += sample.energy
        if sample.power is not None:
            bucket['power'] += sample.power
            bucket['count'] += 1
    for bucket in buckets.values():
        bucket['power'] = bucket['power'] / bucket['count'] if bucket['count'] else None
        bucket['cost'] = bucket['energy'] * engine.preferences.tariff if bucket['count'] else None
        if not bucket['count']:
            bucket['energy']=None
    live_cutoff = now - 15 * 60
    # Bounded chart, retaining chronological order and genuine null gaps.
    live_samples = [s for s in current if s.at >= live_cutoff]
    live_chart = [{'at': s.at, 'label': datetime.fromtimestamp(s.at, tz).strftime('%H:%M:%S'), 'power': s.power,
                   'voltage': s.voltage, 'current': s.current} for s in chart_samples(live_samples)]
    return {'energy': energy if power_observed else None, 'previous_energy': prev_energy if previous_observed else None,
            'cost': energy * engine.preferences.tariff if power_observed else None,
            'change': (energy - prev_energy) / prev_energy * 100 if prev_energy and power_observed else None,
            'sessions': len(charges), 'average_duration': sum(c.ended - c.started for c in completed) / len(completed) if completed else 0,
            'peak': max((s.power for s in current if s.power is not None), default=None),
            'chart': list(buckets.values()), 'live_chart': live_chart, 'mode': mode,
            'energy_source': 'estimated_from_power', 'period_days': days, 'power_observed':power_observed}


def rules_list(engine):
    with engine.db() as db:
        rules = db.scalars(select(Rule).where(Rule.mode == engine.preferences.mode).order_by(Rule.id.desc())).all()
        return [{'id': r.id, 'device_id': r.device_id, 'name': r.name, 'kind': r.kind, 'enabled': r.enabled,
                 'config': r.config, 'due_at': r.due_at, 'last_run': r.last_run} for r in rules]
