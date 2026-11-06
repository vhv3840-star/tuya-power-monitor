"""Production entrypoint. Use one worker: it owns the automation scheduler."""
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import Config
import uvicorn

if __name__ == '__main__':
    host = os.getenv('BIND_HOST', '127.0.0.1')
    config = Config()
    if host not in ('127.0.0.1', 'localhost', '::1') and not config.password:
        raise SystemExit('Set APP_PASSWORD before binding to a network interface.')
    uvicorn.run('backend.main:create_app', factory=True, host=host, port=int(os.getenv('PORT', '8000')), workers=1)
