"""Reproducible synthetic records, always mode=demo."""
import math
import random
import time
from sqlalchemy import select
from .storage import Device, Sample, Charge

DEMO_SCHEMA = {
    'functions': [{'code': 'switch_1', 'type': 'Boolean', 'values': '{}'}],
    'status': [
        {'code': 'cur_power', 'type': 'Integer', 'values': '{"scale":1,"unit":"W"}'},
        {'code': 'cur_voltage', 'type': 'Integer', 'values': '{"scale":1,"unit":"V"}'},
        {'code': 'cur_current', 'type': 'Integer', 'values': '{"scale":0,"unit":"mA"}'}
    ]
}


def seed(db):
    if db.get(Device, 'demo-desk'):
        return
    from .providers import discover_mapping
    for did, name, relay in [('demo-desk', 'Рабочее место', True), ('demo-bedroom', 'Спальня', False)]:
        db.add(Device(id=did, mode='demo', name=name, schema=DEMO_SCHEMA, mapping=discover_mapping(DEMO_SCHEMA), relay=relay))
    rng = random.Random(2026)
    now = time.time()
    for day in range(30):
        for index in range(3):
            start = now - day * 86400 - (index + 1) * 7200 - 3600
            duration = rng.randint(1800, 5600)
            peak = rng.uniform(55, 110)
            energy = 0
            for point in range(31):
                at = start + duration * point / 30
                power = max(.8, peak * (1 - .82 * (point / 30) ** 3) + math.sin(point) * 2)
                interval = power * duration / 30 / 3600000 if point else 0
                energy += interval
                db.add(Sample(device_id='demo-desk', mode='demo', at=at, power=round(power, 2), voltage=230.1, current=round(power / 230.1, 4), energy=interval))
            db.add(Charge(device_id='demo-desk', mode='demo', started=start, ended=start + duration,
                         energy=energy, average=energy * 3600000 / duration, peak=peak, status='completed'))
    db.commit()
