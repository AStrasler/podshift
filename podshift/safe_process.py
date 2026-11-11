"""Allowlisted, non-shell subprocess entrypoints for legacy local schedulers.

These scripts are not the active Supabase scheduler. Keep execution narrowly
scoped to repository-local programs and the known fallback arguments.
"""
import os
import subprocess  # nosec B404 - only used by the allowlisted runner below
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_ALLOWED = {
    "apply.py": {
        ("--scheduler", "fallback"),
        ("--dry-run", "--scheduler", "fallback"),
    },
    "fallback.py": {()},
}


def run_local_script(script: str, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run only known sibling scripts with fixed argument tuples and no shell."""
    if script not in _ALLOWED or args not in _ALLOWED[script]:
        raise ValueError("Unapproved local script or arguments")

    resolved_script = (_ROOT / script).resolve(strict=True)
    if resolved_script.parent != _ROOT or not resolved_script.is_file():
        raise ValueError("Local script is not a regular repository-local file")
    if not sys.executable:
        raise RuntimeError("Python interpreter path unavailable")
    interpreter = Path(sys.executable).resolve(strict=True)
    if not interpreter.is_file():
        raise RuntimeError("Python interpreter does not exist")

    # nosec B603: fixed resolved interpreter, allowlisted script and args, shell disabled
    return subprocess.run(
        [str(interpreter), str(resolved_script), *args],
        check=check,
        shell=False,
        env=os.environ.copy(),
    )
