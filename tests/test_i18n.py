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

    def test_locales_have_the_same_keys(self):
        fr, en = i18n.strings("fr"), i18n.strings("en")
        self.assertEqual(sorted(set(fr) ^ set(en)), [])
        for key, value in fr.items():
            if isinstance(value, dict):
                self.assertEqual(sorted(set(value) ^ set(en[key])), [], key)

    def test_template_ui_keys_exist(self):
        ui = set(i18n.strings("en")["ui"])
        for name in ("hero.html", "hub.html"):
            with open(os.path.join(os.path.dirname(helpers.SCRIPTS), "templates", name), encoding="utf-8") as f:
                text = f.read()
            used = set(re.findall(r"\{\{ui:([\w.]+)\}\}", text)) | set(re.findall(r"\bL\('([\w.]+)'", text))
            self.assertEqual(sorted(k for k in used - ui if not k.endswith(".")), [], name)

    def test_no_placeholder_is_named_lang(self):
        # t(key, lang=...) selects the locale: a {lang} placeholder could never be filled.
        for lang in i18n.LANGS:
            texts = [v for v in i18n.strings(lang).values() if isinstance(v, str)] + list(i18n.strings(lang)["ui"].values())
            self.assertEqual([x for x in texts if "{lang}" in x], [], lang)

    def test_t_fills_placeholders(self):
        self.assertEqual(i18n.t("otp.note", lang="fr", pct=98, minute=4), "Pris dans 98 % de ses parties, vers 4 min.")
        self.assertEqual(i18n.t("otp.note", lang="en", pct=98, minute=4), "Bought in 98% of their games, around 4 min.")

    def test_pattern_matches_its_own_template(self):
        text = i18n.t("otp.cat.mid", start=10, end=22)
        self.assertRegex(text, "^" + i18n.pattern("otp.cat.mid") + "$")


if __name__ == "__main__":
    unittest.main()
