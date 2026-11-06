"""One-click local start. Build the frontend when its production bundle is absent."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]


def open_when_ready(url):
    for _ in range(60):
        try:
            with urllib.request.urlopen(url + '/health', timeout=1) as response:
                if json.load(response).get('app') == 'tuya-power-monitor':
                    webbrowser.open(url)
                    return
        except (OSError, ValueError):
            pass
        time.sleep(.5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--check', action='store_true', help='Install/check runtime without starting the server')
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        raise RuntimeError('Python 3.11 or newer is required.')
    os.chdir(ROOT)
    os.environ['PYTHONUTF8'] = '1'
    data = ROOT / 'data'
    data.mkdir(exist_ok=True)
    if not (ROOT / '.env').exists():
        shutil.copyfile(ROOT / '.env.example', ROOT / '.env')
    environment = ROOT / '.venv'
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        print('Preparing Python environment (first launch)...', flush=True)
        subprocess.run([sys.executable, '-m', 'venv', str(environment)], check=True)
    requirements = ROOT / 'backend/requirements-lock.txt'
    if not requirements.exists():
        requirements = ROOT / 'backend/requirements.txt'
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    marker = data / 'dependencies.sha256'
    if not marker.exists() or marker.read_text() != digest:
        print('Installing server dependencies (internet required on first launch)...', flush=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(requirements)], check=True)
        marker.write_text(digest)
    if not (ROOT / 'dist/index.html').exists():
        subprocess.run([sys.executable, str(ROOT / 'scripts/build_frontend.py')], check=True)
    if args.check:
        subprocess.run([str(python), '-c', 'from backend.main import create_app; create_app(); print("Runtime OK")'], check=True)
        return
    url = 'http://127.0.0.1:8000'
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1', 8000)) == 0:
            try:
                with urllib.request.urlopen(url + '/health', timeout=2) as response:
                    if json.load(response).get('app') == 'tuya-power-monitor':
                        print('TUYA POWER MONITOR is already running: ' + url)
                        if not args.no_browser:
                            webbrowser.open(url)
                        return
            except (OSError, ValueError):
                pass
            raise RuntimeError('Port 8000 is already used by another application.')
    print('\nTUYA POWER MONITOR  |  ' + url)
    print('Demo mode is ready. Keep this window open for automations. Ctrl+C to stop.\n', flush=True)
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    subprocess.run([str(python), '-m', 'uvicorn', 'backend.main:create_app', '--factory', '--host', '127.0.0.1', '--port', '8000'], check=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nServer stopped.')
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f'\nStart failed: {exc}\nSee README.md for setup and troubleshooting.', file=sys.stderr)
        sys.exit(1)
