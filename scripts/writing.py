"""Writing checks on the analysis texts (printed by report.py, like shortened names).

- filler: game basics and empty phrases every player already knows ("lanes are played in duos",
  "My explanation:"), from the locale's "filler_patterns" (regexes, one list per language);
- repeats: a weakness and a "how to beat them" point that say the same thing (most of their content words shared).
"""
import re

from i18n import table

MIN_WORD = 4         # shorter words (articles, "pour", "with") are ignored when comparing ideas
REPEAT_SHARE = 0.5   # share of the shorter text's content words found in the other one


def filler(texts, lang):
    """[(matched text, excerpt)] for every filler phrase found."""
    patterns = [re.compile(p, re.I) for p in table("filler_patterns", lang=lang)]
    out = []
    for text in texts:
        for pattern in patterns:
            for m in pattern.finditer(text or ""):
                out.append((m.group(0), text[max(0, m.start() - 30):m.end() + 40]))
    return out


def content_words(text):
    return {w for w in re.findall(r"\w+", (text or "").lower()) if len(w) >= MIN_WORD}


def repeats(plan):
    """[(weakness, counter tip)] pairs that share most of their content words."""
    out = []
    for weakness in plan.get("weaknesses") or []:
        for tip in plan.get("vs") or []:
            a, b = content_words(weakness), content_words(tip)
            if a and b and len(a & b) / min(len(a), len(b)) >= REPEAT_SHARE:
                out.append((weakness, tip))
    return out
