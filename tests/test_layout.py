import unittest

from tests import helpers  # noqa: F401
import apply


class LayoutTest(unittest.TestCase):
    def test_wrap_lines(self):
        self.assertEqual(apply.wrap_lines("un deux trois", 100), 1)
        self.assertEqual(apply.wrap_lines("un deux trois", 7), 2)
        self.assertEqual(apply.wrap_lines("a\nb", 100), 2)

    def test_long_description_widens_the_category(self):
        short = {"name": "Early", "description": "Court.", "mods": [{}]}
        long = {"name": "Early", "description": "Une très longue description " * 12, "mods": [{}]}
        apply.layout(short)
        apply.layout(long)
        self.assertGreater(long["width"], short["width"])
        self.assertLessEqual(long["width"], apply.MAX_W)

    def test_empty_category_has_no_card_row(self):
        cat = {"name": "Vide", "mods": []}
        apply.layout(cat)
        self.assertEqual(cat["height"], 22 + 28 + 10)


if __name__ == "__main__":
    unittest.main()
