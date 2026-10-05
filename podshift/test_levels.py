import asyncio
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from apply import TZ, already_applied_tonight, apply_lock, away, clamp, levels_from, main, offset_for
from eight_client import STAGES, merged_smart, temperature_url

BASELINE = {
    "bedTimeLevel": 32,
    "initialSleepLevel": 30,
    "finalSleepLevel": -10,
}


class OffsetTests(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(offset_for(100), 0)
        self.assertEqual(offset_for(67), 0)
        self.assertEqual(offset_for(66.9), -5)
        self.assertEqual(offset_for(34), -5)
        self.assertEqual(offset_for(33.9), -10)
        self.assertEqual(offset_for(0), -10)

    def test_offset_uses_baseline_not_current_pod(self):
        levels, delta = levels_from(BASELINE, 50)
        self.assertEqual(delta, -5)
        self.assertEqual(levels["bedTimeLevel"], 27)
        self.assertEqual(levels["initialSleepLevel"], 25)
        self.assertEqual(levels["finalSleepLevel"], -15)

    def test_green_day_matches_baseline(self):
        levels, delta = levels_from(BASELINE, 98)
        self.assertEqual(delta, 0)
        self.assertEqual(levels["bedTimeLevel"], 32)

    def test_clamp(self):
        self.assertEqual(clamp(140), 100)
        self.assertEqual(clamp(-140), -100)
        low, _ = levels_from(
            {"bedTimeLevel": -98, "initialSleepLevel": -98, "finalSleepLevel": -98},
            10,
        )
        self.assertEqual(low["finalSleepLevel"], -100)


class AlreadyAppliedTests(unittest.TestCase):
    """Local once-per-night file lock in apply.py. The Supabase nightly function does not use it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["PODSHIFT_HOME"] = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("PODSHIFT_HOME", None)

    def test_skip_when_local_run_applied_today(self):
        now = datetime.now(TZ)
        record = {"at": now.isoformat(timespec="seconds"), "applied": True, "scheduler": "manual"}
        Path(self.tmp.name, "last_run.json").write_text(json.dumps(record))
        found = already_applied_tonight(now)
        self.assertEqual(found["scheduler"], "manual")

    def test_dry_run_does_not_count(self):
        now = datetime.now(TZ)
        record = {"at": now.isoformat(timespec="seconds"), "applied": False, "dry_run": True, "scheduler": "manual"}
        Path(self.tmp.name, "last_run.json").write_text(json.dumps(record))
        self.assertIsNone(already_applied_tonight(now))

    def test_lock_lets_second_writer_see_first_result(self):
        started = threading.Event()
        release = threading.Event()

        def holder():
            with apply_lock():
                started.set()
                release.wait(timeout=2)
                Path(self.tmp.name, "last_run.json").write_text(
                    json.dumps(
                        {
                            "at": datetime.now(TZ).isoformat(timespec="seconds"),
                            "applied": True,
                            "scheduler": "manual",
                        }
                    )
                )

        thread = threading.Thread(target=holder)
        thread.start()
        self.assertTrue(started.wait(timeout=2))
        release.set()
        with apply_lock():
            found = already_applied_tonight()
        thread.join(timeout=2)
        self.assertEqual(found["scheduler"], "manual")


class SmartWriteTests(unittest.TestCase):
    def test_stages_match_pyeight(self):
        from apply import STAGES as apply_stages

        self.assertEqual(apply_stages, STAGES)

    def test_merged_smart_keeps_other_keys_and_clamps(self):
        smart = merged_smart(
            {"bedTimeLevel": 1, "initialSleepLevel": 1, "finalSleepLevel": 1, "extra": 4},
            {"bedTimeLevel": 140, "initialSleepLevel": 25, "finalSleepLevel": -140},
        )
        self.assertEqual(smart["bedTimeLevel"], 100)
        self.assertEqual(smart["initialSleepLevel"], 25)
        self.assertEqual(smart["finalSleepLevel"], -100)
        self.assertEqual(smart["extra"], 4)

    def test_temperature_url_is_the_pyeight_user_route(self):
        self.assertEqual(
            temperature_url("user-1"),
            "https://app-api.8slp.net/v1/users/user-1/temperature",
        )

    def test_pyeight_imports_without_home_assistant(self):
        import pyeight.exceptions as exceptions

        err = exceptions.RequestError("access_token=secret", status=418)
        self.assertEqual(err.status, 418)
        self.assertNotIn("homeassistant", type(err).__mro__.__repr__())

    def test_write_smart_is_one_put_and_hides_error_bodies(self):
        from eight_client import EightPod
        from pyeight.exceptions import RequestError

        class Api:
            def __init__(self):
                self.calls = []
                self.body = {
                    "smart": {"bedTimeLevel": 1, "initialSleepLevel": 1, "finalSleepLevel": 1, "extra": 3},
                    "currentState": {"type": "off"},
                }

            async def api_request(self, method, url, data=None, return_json=True, **kwargs):
                self.calls.append((method, url, data, return_json))
                if method == "GET":
                    return self.body
                return None

        api = Api()
        pod = EightPod()
        pod._loop = asyncio.new_event_loop()
        pod._eight = api
        pod._user_id = "user-1"
        levels = {"bedTimeLevel": 32, "initialSleepLevel": 30, "finalSleepLevel": -10}
        try:
            pod.write_smart(levels)
            pod.set_power("off")
        finally:
            pod._loop.close()
            pod._loop = None
        puts = [call for call in api.calls if call[0] == "PUT"]
        self.assertEqual(len(puts), 2)
        smart_put = puts[0]
        self.assertEqual(smart_put[1], temperature_url("user-1"))
        self.assertFalse(smart_put[3])
        self.assertEqual(smart_put[2]["smart"]["bedTimeLevel"], 32)
        self.assertEqual(smart_put[2]["smart"]["extra"], 3)
        self.assertEqual(puts[1][2], {"currentState": {"type": "off"}})

        class Boom:
            async def api_request(self, *args, **kwargs):
                raise RequestError("access_token=secret", status=500)

        pod = EightPod()
        pod._loop = asyncio.new_event_loop()
        pod._eight = Boom()
        pod._user_id = "user-1"
        try:
            with self.assertRaises(SystemExit) as caught:
                pod.write_smart(levels)
        finally:
            pod._loop.close()
            pod._loop = None
        message = str(caught.exception)
        self.assertIn("500", message)
        self.assertNotIn("secret", message)


class FakePod:
    def __init__(self, body: dict, power_after_write: str | None = None):
        self.body = body
        self.power_after_write = power_after_write
        self.writes: list[dict] = []
        self.power: list[str] = []
        self.closed = False

    def read(self) -> dict:
        return self.body

    def write_smart(self, levels: dict) -> None:
        self.writes.append(dict(levels))
        smart = dict(self.body.get("smart") or {})
        smart.update(levels)
        state = dict(self.body.get("currentState") or {})
        if self.power_after_write:
            state["type"] = self.power_after_write
        self.body = {**self.body, "smart": smart, "currentState": state}

    def set_power(self, state: str) -> None:
        self.power.append(state)
        current = dict(self.body.get("currentState") or {})
        current["type"] = state
        self.body = {**self.body, "currentState": current}

    def close(self) -> None:
        self.closed = True


class ApplyPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["PODSHIFT_HOME"] = self.tmp.name
        Path(self.tmp.name, "baseline.json").write_text(json.dumps(BASELINE))
        self.pod = FakePod(
            {
                "currentState": {"type": "off"},
                "smart": {"bedTimeLevel": 10, "initialSleepLevel": 10, "finalSleepLevel": 10},
            }
        )
        self.recovery = {
            "status": "ok",
            "score_state": "SCORED",
            "user_calibrating": False,
            "recovery_score": 50,
        }

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("PODSHIFT_HOME", None)
        os.environ.pop("PODSHIFT_DISABLED", None)
        os.environ.pop("PODSHIFT_AWAY", None)

    def _run(self, *argv: str):
        with (
            patch.object(sys, "argv", ["apply.py", *argv]),
            patch("apply.latest_recovery", return_value=self.recovery),
            patch("apply.open_eight", return_value=self.pod),
            redirect_stdout(StringIO()),
        ):
            main()

    def test_dry_run_reads_and_does_not_write_or_touch_last_run(self):
        self._run("--dry-run")
        self.assertEqual(self.pod.writes, [])
        self.assertEqual(self.pod.power, [])
        self.assertTrue(self.pod.closed)
        self.assertFalse(Path(self.tmp.name, "last_run.json").exists())
        saved = json.loads(Path(self.tmp.name, "last_dry_run.json").read_text())
        self.assertTrue(saved["dry_run"])
        self.assertFalse(saved["applied"])
        self.assertEqual(saved["offset"], -5)
        self.assertEqual(saved["target"]["bedTimeLevel"], 27)
        self.assertEqual(saved["target"]["initialSleepLevel"], 25)
        self.assertEqual(saved["target"]["finalSleepLevel"], -15)
        self.assertEqual(saved["before_power"], "off")
        self.assertEqual(saved["before_smart"]["bedTimeLevel"], 10)

    def test_apply_writes_baseline_offset_and_restores_power(self):
        self.pod.power_after_write = "smart"
        self._run()
        self.assertEqual(len(self.pod.writes), 1)
        self.assertEqual(self.pod.writes[0]["bedTimeLevel"], 27)
        self.assertEqual(self.pod.writes[0]["initialSleepLevel"], 25)
        self.assertEqual(self.pod.writes[0]["finalSleepLevel"], -15)
        self.assertEqual(self.pod.power, ["off"])
        self.assertTrue(self.pod.closed)
        saved = json.loads(Path(self.tmp.name, "last_run.json").read_text())
        self.assertTrue(saved["applied"])
        self.assertTrue(saved["power_restored"])
        self.assertEqual(saved["after_power"], "off")
        self.assertFalse(Path(self.tmp.name, "last_dry_run.json").exists())

    def test_disabled_and_away_do_not_open_the_client(self):
        for name, value in (("PODSHIFT_DISABLED", "1"), ("PODSHIFT_AWAY", "true")):
            with self.subTest(name=name):
                os.environ.pop("PODSHIFT_DISABLED", None)
                os.environ.pop("PODSHIFT_AWAY", None)
                os.environ[name] = value
                self.pod.closed = False
                self._run()
                self.assertFalse(self.pod.closed)
                self.assertEqual(self.pod.writes, [])
                saved = json.loads(Path(self.tmp.name, "last_run.json").read_text())
                self.assertEqual(saved["skipped"], "disabled" if name == "PODSHIFT_DISABLED" else "away")
                self.assertFalse(saved["applied"])
                self.assertEqual(saved["target"]["finalSleepLevel"], -15)
                Path(self.tmp.name, "last_run.json").unlink()

    def test_already_applied_does_not_open_the_client(self):
        record = {
            "at": datetime.now(TZ).isoformat(timespec="seconds"),
            "applied": True,
            "scheduler": "manual",
        }
        Path(self.tmp.name, "last_run.json").write_text(json.dumps(record))
        self._run()
        self.assertFalse(self.pod.closed)
        self.assertEqual(self.pod.writes, [])

    def test_unscored_reads_and_does_not_write(self):
        self.recovery = {"status": "no_recovery"}
        self._run()
        self.assertEqual(self.pod.writes, [])
        self.assertTrue(self.pod.closed)
        saved = json.loads(Path(self.tmp.name, "last_run.json").read_text())
        self.assertEqual(saved["skipped"], "no_recovery")
        self.assertFalse(saved["applied"])
        self.assertNotIn("target", saved)

    def test_dry_run_still_reads_when_tonight_was_applied(self):
        record = {
            "at": datetime.now(TZ).isoformat(timespec="seconds"),
            "applied": True,
            "scheduler": "manual",
        }
        Path(self.tmp.name, "last_run.json").write_text(json.dumps(record))
        self._run("--dry-run")
        self.assertTrue(self.pod.closed)
        self.assertEqual(self.pod.writes, [])
        self.assertTrue(Path(self.tmp.name, "last_dry_run.json").exists())
        saved = json.loads(Path(self.tmp.name, "last_run.json").read_text())
        self.assertEqual(saved["scheduler"], "manual")
        self.assertNotIn("dry_run", saved)


class AwayTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("PODSHIFT_AWAY", None)

    def test_unset_does_not_skip(self):
        os.environ.pop("PODSHIFT_AWAY", None)
        self.assertFalse(away())

    def test_truthy_values(self):
        for value in ("1", "true", "yes", "TRUE"):
            os.environ["PODSHIFT_AWAY"] = value
            self.assertTrue(away(), value)
        os.environ["PODSHIFT_AWAY"] = "0"
        self.assertFalse(away())


if __name__ == "__main__":
    unittest.main()
