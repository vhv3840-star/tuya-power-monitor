import os
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv
from .providers import REGIONS

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')


@dataclass
class Config:
    database_url: str = field(default_factory=lambda: os.getenv('DATABASE_URL', 'sqlite:///' + (ROOT / 'data' / 'monitor.db').as_posix()))
    password: str = field(default_factory=lambda: os.getenv('APP_PASSWORD', ''))
    session_secret: str = field(default_factory=lambda: os.getenv('SESSION_SECRET', '') or __import__('secrets').token_hex(32))
    region: str = field(default_factory=lambda: os.getenv('TUYA_REGION', 'eu'))
    client_id: str = field(default_factory=lambda: os.getenv('TUYA_CLIENT_ID', ''))
    client_secret: str = field(default_factory=lambda: os.getenv('TUYA_CLIENT_SECRET', ''))
    uid: str = field(default_factory=lambda: os.getenv('TUYA_UID', ''))
    device_ids: list = field(default_factory=lambda: [s.strip() for s in os.getenv('TUYA_DEVICE_IDS', '').split(',') if s.strip()])
    poll_seconds: float = field(default_factory=lambda: max(5, float(os.getenv('TUYA_POLL_SECONDS', '15'))))
    secure_cookie: bool = field(default_factory=lambda: os.getenv('COOKIE_SECURE', 'false').lower() == 'true')
    allowed_origins: list = field(default_factory=lambda: os.getenv('ALLOWED_ORIGINS', 'http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:5173,http://localhost:5173').split(','))
    seed_demo: bool = True

    def __post_init__(self):
        if self.region not in REGIONS:
            raise ValueError('TUYA_REGION must be eu, us, cn, in, we, ea or sg')
        (ROOT / 'data').mkdir(exist_ok=True)
