import os
from pathlib import Path


def home() -> Path:
    raw = os.environ.get("PODSHIFT_HOME")
    path = Path(raw).expanduser() if raw else Path.home() / ".podshift"
    path.mkdir(parents=True, exist_ok=True)
    return path
