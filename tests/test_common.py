import unittest

from tests import helpers  # noqa: F401
import common


class CommonTest(unittest.TestCase):
    def test_short_note(self):
        self.assertEqual(common.short_note("Pris dans 98 % de ses parties, vers 4 min. Revendu vers 9 min."), "98%@4m rev9m")
        self.assertEqual(common.short_note("Pris dans 60 % de ses parties, vers 12 min."), "60%@12m")
        self.assertEqual(common.short_note("Une note d'auteur"), "Une note d'auteur")

    def test_rank_label(self):
        self.assertEqual(common.rank_label(114), "Éternus 4")
        self.assertEqual(common.rank_label(90), "Fantôme")
        self.assertEqual(common.rank_label(None), "rang inconnu")

    def test_make_strings_skips_game_labels(self):
        common._items = {1: {"name": "Objet"}}
        build = {"name": "Build", "details": {"mod_categories": [
            {"name": "#Citadel_HeroBuilds_EarlyGame", "description": "Desc", "mods": [{"ability_id": 1, "annotation": "Note"}]}]}}
        texts = [s["text"] for s in common.make_strings(build)]
        self.assertEqual(texts, ["Build", "Desc", "Note"])


if __name__ == "__main__":
    unittest.main()
