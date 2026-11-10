"""User-facing strings, per language (locales/<lang>.json).

Everything shown on the pages or written into in-game builds comes from here, so a new language only needs a new
locale file. French is the only language today. Written content (analysis, video tips) carries its own "lang" tag.
"""
import functools
import json
import os
import re

LANG = "fr"
LOCALES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locales")


@functools.cache
def strings(lang=LANG):
    with open(os.path.join(LOCALES, f"{lang}.json"), encoding="utf-8") as f:
        return json.load(f)


def t(key, **values):
    """Localized string, with str.format() placeholders filled in."""
    text = strings()[key]
    return text.format(**values) if values else text


def table(key):
    """Localized list or mapping (rank names, labels...)."""
    return strings()[key]


def pattern(key, placeholder=r"(\d+)"):
    """Regex matching a localized template, its {placeholders} replaced by `placeholder`."""
    return re.sub(r"\\\{\w+\\\}", lambda _: placeholder, re.escape(strings()[key]))
