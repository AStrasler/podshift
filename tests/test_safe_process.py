"""Regression tests for the local fallback subprocess boundary."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from podshift import safe_process


class SafeProcessTests(unittest.TestCase):
    def setUp(self):
        self.runner = patch.object(safe_process.subprocess, "run")
        self.mock_run = self.runner.start()
        self.addCleanup(self.runner.stop)

    def test_apply_uses_resolved_interpreter_and_shell_false(self):
        for args, check in (
            (("--scheduler", "fallback"), False),
            (("--dry-run", "--scheduler", "fallback"), True),
        ):
            with self.subTest(args=args):
                safe_process.run_local_script("apply.py", *args, check=check)
                positional, kw = self.mock_run.call_args
                self.assertEqual(positional[0][0], os.path.abspath(sys.executable))
                self.assertEqual(positional[0][1], str((safe_process._ROOT / "apply.py").resolve()))
                self.assertEqual(positional[0][2:], list(args))
                self.assertIs(kw["shell"], False)
                self.assertIs(kw["check"], check)
                self.assertIsInstance(kw["env"], dict)

    def test_fallback_invocation_has_only_fixed_paths(self):
        safe_process.run_local_script("fallback.py")
        positional, kw = self.mock_run.call_args
        self.assertEqual(positional[0][1], str((safe_process._ROOT / "fallback.py").resolve()))
        self.assertEqual(len(positional[0]), 2)
        self.assertIs(kw["shell"], False)

    def test_reject_traversal_and_injection(self):
        for script, args in (
            ("../apply.py", ()),
            ("malicious.py", ()),
            ("apply.py", ("--scheduler", "fallback; echo unsafe")),
            ("apply.py", ("--", "--scheduler", "fallback")),
            ("fallback.py", ("$(echo injected)",)),
            ("fallback.py", ("--dry-run",)),
        ):
            with self.subTest(script=script, args=args):
                with self.assertRaises(ValueError):
                    safe_process.run_local_script(script, *args)
        self.mock_run.assert_not_called()

    def test_venv_style_symlinked_interpreter_is_not_resolved(self):
        """A venv's bin/python is a symlink; the child must keep that path."""
        with tempfile.TemporaryDirectory() as tmp:
            link = Path(tmp) / ("venv-python.exe" if os.name == "nt" else "venv-python")
            link.symlink_to(Path(sys.executable).resolve())
            with patch.object(safe_process.sys, "executable", str(link)):
                safe_process.run_local_script("fallback.py")
            positional, _ = self.mock_run.call_args
            self.assertEqual(positional[0][0], str(link))
            self.assertNotEqual(positional[0][0], str(link.resolve()))

    def test_missing_or_non_executable_interpreter_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "nope")
            non_exec = Path(tmp) / "plain.txt"
            non_exec.write_text("x")
            for bad in ("", missing, str(non_exec)):
                with self.subTest(executable=bad):
                    with patch.object(safe_process.sys, "executable", bad):
                        with self.assertRaises(RuntimeError):
                            safe_process.run_local_script("fallback.py")
        self.mock_run.assert_not_called()

    def test_return_code_propagation(self):
        result = CompletedProcess(args=["python"], returncode=7)
        self.mock_run.return_value = result
        self.assertIs(safe_process.run_local_script("fallback.py"), result)


if __name__ == "__main__":
    unittest.main()
