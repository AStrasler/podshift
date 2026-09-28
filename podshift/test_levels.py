import unittest

from apply import clamp, levels_from, offset_for

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


if __name__ == "__main__":
    unittest.main()
