"""User-facing strings, per language (locales/<lang>.json).

Everything shown on the pages or written into in-game builds comes from here, so a new language only needs a new
locale file. Pages are generated once per language (English by default). Written content carries its own "lang" tag.
"""
import functools
import json
import os
import re

LANGS = ("en", "fr")
DEFAULT_LANG = "en"
# Language the analysis and translated builds are written in (pages in other languages fall back to it).
CONTENT_LANG = "fr"
# deadlock-api "language" parameter for each locale.
API_LANGUAGE = {"en": "english", "fr": "french"}
LOCALES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locales")

_current = DEFAULT_LANG


def use(lang):
    """Switch the language used by t(), table() and pattern() (and by the API helpers in common)."""
    global _current
    if lang not in LANGS:
        raise ValueError(f"unknown language {lang!r}, expected one of {LANGS}")
    _current = lang


def current():
    return _current


@functools.cache
def strings(lang=None):
    with open(os.path.join(LOCALES, f"{lang or _current}.json"), encoding="utf-8") as f:
        return json.load(f)


def t(key, lang=None, **values):
    """Localized string, with str.format() placeholders filled in."""
    text = strings(lang or _current)[key]
    return text.format(**values) if values else text


def table(key, lang=None):
    """Localized list or mapping (rank names, labels...)."""
    return strings(lang or _current)[key]


def pattern(key, placeholder=r"(\d+)", lang=None):
    """Regex matching a localized template, its {placeholders} replaced by `placeholder`."""
    return re.sub(r"\\\{\w+\\\}", lambda _: placeholder, re.escape(strings(lang or _current)[key]))
