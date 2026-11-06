"""Build from sources using a standard Node installation or Codex's bundled pnpm."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def build():
    os.chdir(ROOT)
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
    pnpm = shutil.which('pnpm.cmd' if os.name == 'nt' else 'pnpm')
    bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies'
    if not npm and not pnpm and os.name == 'nt' and (bundled / 'bin/fallback/pnpm.cmd').exists():
        pnpm = str(bundled / 'bin/fallback/pnpm.cmd')
        os.environ['PATH'] = str(bundled / 'node/bin') + os.pathsep + os.environ['PATH']
    if npm:
        subprocess.run([npm, 'ci' if (ROOT / 'package-lock.json').exists() else 'install'], check=True)
        subprocess.run([npm, 'run', 'build'], check=True)
    elif pnpm:
        subprocess.run([pnpm, 'install', '--frozen-lockfile'], check=True)
        subprocess.run([pnpm, 'run', 'build'], check=True)
    else:
        raise RuntimeError('Install Node.js 20.19+ LTS (includes npm) from https://nodejs.org/')


if __name__ == '__main__':
    try:
        build()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'Frontend build failed: {exc}', file=sys.stderr)
        sys.exit(1)
