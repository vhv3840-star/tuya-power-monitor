"""python -m backend.diagnose: cloud reads only; no scheduler, relay or DB writes."""
import asyncio
import json
from types import SimpleNamespace
from .config import Config
from .providers import TuyaProvider
from .diagnostics import diagnose


async def main():
    config=Config()
    provider=TuyaProvider(config)
    try:
        report=await diagnose(SimpleNamespace(config=config,provider=provider),persist=False)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 0 if any(d['command_ready'] for d in report['devices']) else 1
    finally:
        await provider.close()


if __name__=='__main__':
    raise SystemExit(asyncio.run(main()))
