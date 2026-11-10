"""Finish a search in ONE call: translations + analysis -> build codes + page.

Usage: python3 -I finish.py <folder> <input.json | -> [--no-open]

Input JSON:
  {"tr": {"<key>": ["fr of text [n1]", "fr of text [n2]", ...]},   # order of the "To translate" list
   "intro": "overall analysis",
   "<key>": {"resume": "2 sentences", "points": ["Early : ...", "Mid : ...", "Late : ...", "Particularité : ..."]},
   "tldr": {...}, "plan": {...}, "sources": {"<text path>": ["<ref>", ...]},
   "en": {"intro": ..., "<key>": {...}, "tldr": {...}, "plan": {...}},       # the same texts in English
   "tr_en": {"<key>": [...]}}                                                 # English texts of non-English builds
"tr" may also be {"<n>": "fr"} to translate only some texts. "plan", "tldr" and "sources" are merged into
the existing analysis; any other key is replaced. Sources are shared by every language (same text paths).
Builds whose author wrote in English, and texts generated from the locales, need no "tr_en".
Writes strings.json, build_<lang>.json + codes for every language (apply.py), summaries[.<lang>].json, then the
pages (report.py).
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import fill, read_json, write_json  # noqa: E402
from i18n import CONTENT_LANG, LANGS  # noqa: E402
from status import ANALYSIS_VERSION, completeness  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
MERGED_KEYS = ("plan", "tldr", "sources")


def save(path, data):
    write_json(path, data, indent=1)


def merge(path, data, meta=None):
    """Merge written analysis into a summaries file ("plan", "tldr" and "sources" are merged, other keys replaced)."""
    summaries = read_json(path) if os.path.exists(path) else {}
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(summaries.get(key), dict) and key in MERGED_KEYS:
            summaries[key].update(value)
        else:
            summaries[key] = value
    for key, value in (meta or {}).items():
        summaries.setdefault(key, value)
    save(path, summaries)
    return summaries


def apply_all(folder, candidates):
    """Build codes in every language; builds still missing a translation are skipped."""
    for c in candidates:
        build_dir = f"{folder}/{c['key']}"
        for lang in LANGS:
            result = subprocess.run([sys.executable, "-I", f"{HERE}/apply.py", build_dir, "--lang", lang, "--no-clipboard"],
                                    capture_output=True, text=True)
            output = (result.stderr.strip() or result.stdout.strip())
            if result.returncode:
                print(f"{c['key']} ({lang}): {'not translated yet' if 'Missing' in output else 'ERROR ' + output}")
            elif result.stderr.strip():
                print(f"{c['key']} ({lang}): {result.stderr.strip()}")


def main():
    folder, src = sys.argv[1], sys.argv[2]
    data = json.load(sys.stdin) if src == "-" else read_json(src)
    # Build translations: "tr" for the content language, "tr_<lang>" for the others.
    for lang in LANGS:
        field = "tr" if lang == CONTENT_LANG else f"tr_{lang}"
        for key, translations in (data.pop(field, None) or {}).items():
            fill(f"{folder}/{key}", translations, lang)
    # Written analysis: top level = content language, "<lang>": {...} = the same texts in another language.
    others = {lang: data.pop(lang) for lang in LANGS if lang != CONTENT_LANG and lang in data}
    for lang, texts in others.items():
        merge(f"{folder}/summaries.{lang}.json", texts, {"lang": lang})
    summaries_path = f"{folder}/summaries.json"
    summaries = merge(summaries_path, data, {"version": 1, "lang": CONTENT_LANG})
    # The page only moves to the current method version once nothing is missing: the call must have applied
    # every pending change from data/changelog.json (see SKILL.md).
    if not completeness(folder)["missing"] and summaries["version"] != ANALYSIS_VERSION:
        summaries["version"] = ANALYSIS_VERSION
        save(summaries_path, summaries)

    candidates = read_json(f"{folder}/candidates.json")["candidates"]
    apply_all(folder, candidates)
    missing = [c["key"] for c in candidates if c["key"] not in summaries]
    if missing:
        print("No analysis for:", ", ".join(missing))
    args = [sys.executable, "-I", f"{HERE}/report.py", folder] + ([] if "--no-open" in sys.argv else ["--open"])
    subprocess.run(args, check=True)


if __name__ == "__main__":
    main()
