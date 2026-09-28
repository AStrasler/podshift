import json
import os
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path

from apply import TZ, already_applied_tonight, apply_lock, clamp, levels_from, offset_for

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
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["PODSHIFT_HOME"] = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("PODSHIFT_HOME", None)

    def test_skip_when_gamut_applied_today(self):
        now = datetime.now(TZ)
        record = {"at": now.isoformat(timespec="seconds"), "applied": True, "scheduler": "gamut"}
        Path(self.tmp.name, "last_run.json").write_text(json.dumps(record))
        found = already_applied_tonight(now)
        self.assertEqual(found["scheduler"], "gamut")

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
                            "scheduler": "gamut",
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
        self.assertEqual(found["scheduler"], "gamut")


if __name__ == "__main__":
    unittest.main()
