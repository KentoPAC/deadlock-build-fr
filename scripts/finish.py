"""Finish a search in ONE call: translations + analysis -> build codes + page.

Usage: python3 -I finish.py <folder> <input.json | -> [--no-open]

Input JSON:
  {"tr": {"<key>": ["fr of text [n1]", "fr of text [n2]", ...]},   # order of the "To translate" list
   "intro": "overall analysis",
   "<key>": {"resume": "2 sentences", "points": ["Early : ...", "Mid : ...", "Late : ...", "Particularité : ..."]},
   "tldr": {...}, "plan": {...}, "sources": {"<text path>": ["<ref>", ...]}}
"tr" may also be {"<n>": "fr"} to translate only some texts. "plan", "tldr" and "sources" are merged into
the existing analysis; any other key is replaced.
Writes strings.json, build_fr.json + code.txt (apply.py), summaries.json, then index.html (report.py).
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import fill, read_json, write_json  # noqa: E402
from i18n import CONTENT_LANG  # noqa: E402
from status import ANALYSIS_VERSION, completeness  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
MERGED_KEYS = ("plan", "tldr", "sources")


def save(path, data):
    write_json(path, data, indent=1)


def main():
    folder, src = sys.argv[1], sys.argv[2]
    data = json.load(sys.stdin) if src == "-" else read_json(src)
    for key, translations in (data.pop("tr", None) or {}).items():
        fill(f"{folder}/{key}", translations)

    summaries_path = f"{folder}/summaries.json"
    summaries = read_json(summaries_path) if os.path.exists(summaries_path) else {}
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(summaries.get(key), dict) and key in MERGED_KEYS:
            summaries[key].update(value)
        else:
            summaries[key] = value
    summaries.setdefault("version", 1)
    summaries.setdefault("lang", CONTENT_LANG)  # language of every written text in this file
    save(summaries_path, summaries)
    # The page only moves to the current method version once nothing is missing: the call must have applied
    # every pending change from data/changelog.json (see SKILL.md).
    if not completeness(folder)["missing"] and summaries["version"] != ANALYSIS_VERSION:
        summaries["version"] = ANALYSIS_VERSION
        save(summaries_path, summaries)

    candidates = read_json(f"{folder}/candidates.json")["candidates"]
    for c in candidates:
        build_dir = f"{folder}/{c['key']}"
        strings = read_json(f"{build_dir}/strings.json")
        if any(not s["fr"] for s in strings):
            print(f"{c['key']}: not translated yet (skipped)")
            continue
        result = subprocess.run([sys.executable, "-I", f"{HERE}/apply.py", build_dir, "--no-clipboard"],
                                capture_output=True, text=True)
        if result.returncode:
            print(f"{c['key']}: ERROR {result.stderr.strip() or result.stdout.strip()}")
        elif result.stderr.strip():
            print(f"{c['key']}: {result.stderr.strip()}")
    missing = [c["key"] for c in candidates if c["key"] not in summaries]
    if missing:
        print("No analysis for:", ", ".join(missing))
    args = [sys.executable, "-I", f"{HERE}/report.py", folder] + ([] if "--no-open" in sys.argv else ["--open"])
    subprocess.run(args, check=True)


if __name__ == "__main__":
    main()
