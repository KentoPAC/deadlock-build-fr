import unittest

from tests import helpers  # noqa: F401
import writing


class WritingTest(unittest.TestCase):
    def test_filler_finds_game_basics(self):
        found = writing.filler(["Lanes are played in duos, and the lane itself matters little.",
                                "Pocket wins 50.6% of his lanes with Rat King."], "en")
        self.assertEqual([f for f, _ in found], ["Lanes are played in duos"])

    def test_filler_in_french(self):
        found = writing.filler(["Mon explication : Fléau ne tue pas."], "fr")
        self.assertEqual(len(found), 1)

    def test_repeated_weakness_and_counter_tip(self):
        plan = {"weaknesses": ["Less spirit resistance than other heroes: he suffers against spirit burst."],
                "vs": ["Burst him with spirit damage: he has less spirit resistance than average.",
                       "Buy Warp Stone to catch him after his escape."]}
        self.assertEqual(len(writing.repeats(plan)), 1)


if __name__ == "__main__":
    unittest.main()
