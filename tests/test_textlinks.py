import re
import unittest

from tests import helpers  # noqa: F401
import textlinks

ITEMS = {
    1: {"id": 1, "type": "upgrade", "shopable": True, "name": "Dissipateur de magie"},
    2: {"id": 2, "type": "upgrade", "shopable": True, "name": "Chargeur XL"},
    3: {"id": 3, "type": "upgrade", "shopable": True, "name": "Malédiction de ralentissement"},
    4: {"id": 4, "type": "ability", "name": "Redingote volante"},
    5: {"id": 5, "type": "upgrade", "shopable": False, "name": "Objet retiré"},
}


class LooseTest(unittest.TestCase):
    def test_ignores_accents_and_first_letter_case(self):
        pattern = textlinks.loose("Élanflammé")
        self.assertTrue(re.search(pattern, "il lance élanflammé"))
        self.assertTrue(re.search(pattern, "Elanflamme"))

    def test_matches_both_kinds_of_space(self):
        pattern = textlinks.loose("Chargeur XL")
        self.assertTrue(re.search(pattern, "prends Chargeur XL vite"))
        self.assertTrue(re.search(pattern, "prends Chargeur XL vite"))


class ShortNamesTest(unittest.TestCase):
    def flagged(self, text):
        return [word for word, _, _ in textlinks.short_names(ITEMS, [text])]

    def test_full_names_pass(self):
        self.assertEqual(self.flagged("Achète Dissipateur de magie, puis Chargeur XL."), [])

    def test_shortened_names_are_flagged(self):
        self.assertEqual(self.flagged("Garde ton Dissipateur pour la Redingote."), ["Dissipateur", "Redingote"])

    def test_words_inside_full_names_and_sentence_starts_pass(self):
        items = {1: {"id": 1, "type": "upgrade", "shopable": True, "name": "Dispel Magic"},
                 2: {"id": 2, "type": "upgrade", "shopable": True, "name": "Magic Carpet"},
                 3: {"id": 3, "type": "upgrade", "shopable": True, "name": "Phantom Strike"}}
        flagged = [w for w, _, _ in textlinks.short_names(items, ["Buy Dispel Magic. Magic wins. Phantom 2 author."])]
        self.assertEqual(flagged, [])
        flagged = [w for w, _, _ in textlinks.short_names(items, ["Keep your Magic for later."])]
        self.assertEqual(flagged, ["Magic"])

    def test_possessive_map_object_is_ignored(self):
        self.assertEqual(self.flagged("Farme autour du Sinner's Malédiction."), [])


if __name__ == "__main__":
    unittest.main()
