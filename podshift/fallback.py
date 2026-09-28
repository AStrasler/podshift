#!/usr/bin/env python3
"""Run apply.py only if tonight's setting was not already applied."""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from apply import TZ, already_applied_tonight, append_scheduler_log, apply_lock

HERE = Path(__file__).resolve().parent


def decision(now: datetime | None = None) -> dict:
    prior = already_applied_tonight(now)
    if prior:
        return {
            "action": "skip",
            "reason": "already_applied",
            "handled_by": prior.get("scheduler", "unknown"),
            "applied_at": prior.get("at"),
        }
    return {"action": "apply", "reason": "not_applied_tonight"}


def main() -> None:
    os.environ["PODSHIFT_SCHEDULER"] = "fallback"
    check_only = "--check-only" in sys.argv
    dry_run = "--dry-run" in sys.argv
    now = datetime.now(TZ).isoformat(timespec="seconds")
    with apply_lock():
        result = decision()
    result["at"] = now
    result["scheduler"] = "fallback"
    if result["action"] == "skip" or check_only or dry_run:
        if result["action"] == "skip":
            append_scheduler_log(result)
        print(json.dumps(result))
        if result["action"] == "apply" and dry_run:
            subprocess.run(
                [sys.executable, str(HERE / "apply.py"), "--dry-run", "--scheduler", "fallback"],
                check=True,
                env=os.environ.copy(),
            )
        return
    completed = subprocess.run(
        [sys.executable, str(HERE / "apply.py"), "--scheduler", "fallback"],
        check=False,
        env=os.environ.copy(),
    )
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
