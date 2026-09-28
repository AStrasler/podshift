#!/usr/bin/env python3
"""Daily 9:25pm America/Chicago fallback. Independent of the Gamut 9:00pm task."""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from apply import TZ
from home import home

HERE = Path(__file__).resolve().parent
HOUR = 21
MINUTE = 25


def next_run(now: datetime) -> datetime:
    target = now.replace(hour=HOUR, minute=MINUTE, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return target


def paused() -> bool:
    return (home() / "fallback.paused").exists()


def write_status(target: datetime) -> None:
    path = home() / "fallback.status.json"
    path.write_text(
        json.dumps(
            {
                "host": "agent-container",
                "pid": os.getpid(),
                "paused": paused(),
                "next_run": target.isoformat(timespec="seconds"),
                "timezone": "America/Chicago",
            }
        )
    )
    path.chmod(0o600)


def main() -> None:
    pid_path = home() / "fallback.pid"
    pid_path.write_text(str(os.getpid()))
    while True:
        now = datetime.now(TZ)
        target = next_run(now)
        write_status(target)
        remaining = (target - now).total_seconds()
        if paused() or remaining > 30:
            time.sleep(30)
            continue
        if remaining > 0:
            time.sleep(remaining)
        if paused():
            continue
        subprocess.run(
            [sys.executable, str(HERE / "fallback.py")],
            check=False,
            env=os.environ.copy(),
        )
        time.sleep(90)


if __name__ == "__main__":
    main()
