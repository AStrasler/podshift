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


def _interpreter() -> str:
    """Return an absolute path to the running interpreter WITHOUT following symlinks.

    A virtual environment's ``bin/python`` is a symlink to the base interpreter;
    resolving it would launch children outside the venv (no site-packages).
    ``is_file``/``os.access`` follow the link only to confirm it is usable.
    """
    if not sys.executable:
        raise RuntimeError("Python interpreter path unavailable")
    interpreter = os.path.abspath(sys.executable)
    candidate = Path(interpreter)
    # On Windows, os.access(X_OK) can report non-executable files as executable.
    # A Windows Python interpreter must be an .exe, including venv symlink paths.
    if (
        not candidate.is_file()
        or not os.access(interpreter, os.X_OK)
        or (os.name == "nt" and candidate.suffix.lower() != ".exe")
    ):
        raise RuntimeError("Python interpreter does not exist or is not executable")
    return interpreter


def run_local_script(script: str, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run only known sibling scripts with fixed argument tuples and no shell."""
    if script not in _ALLOWED or args not in _ALLOWED[script]:
        raise ValueError("Unapproved local script or arguments")

    resolved_script = (_ROOT / script).resolve(strict=True)
    if resolved_script.parent != _ROOT or not resolved_script.is_file():
        raise ValueError("Local script is not a regular repository-local file")
    interpreter = _interpreter()

    # nosec B603: fixed resolved interpreter, allowlisted script and args, shell disabled
    return subprocess.run(
        [interpreter, str(resolved_script), *args],
        check=check,
        shell=False,
        env=os.environ.copy(),
    )
