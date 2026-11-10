import glob
import os
import re
import unittest

from tests import helpers
import i18n


class I18nTest(unittest.TestCase):
    def test_every_key_used_in_the_code_exists(self):
        used = set()
        for path in glob.glob(os.path.join(helpers.SCRIPTS, "*.py")):
            with open(path, encoding="utf-8") as f:
                used |= set(re.findall(r"""\b(?:t|table|pattern)\(\s*["']([\w.]+)["']""", f.read()))
        self.assertTrue(used)
        self.assertEqual(sorted(used - set(i18n.strings())), [])

    def test_t_fills_placeholders(self):
        self.assertEqual(i18n.t("otp.note", pct=98, minute=4), "Pris dans 98 % de ses parties, vers 4 min.")

    def test_pattern_matches_its_own_template(self):
        text = i18n.t("otp.cat.mid", start=10, end=22)
        self.assertRegex(text, "^" + i18n.pattern("otp.cat.mid") + "$")


if __name__ == "__main__":
    unittest.main()
