"""Fetch one Deadlock build and prepare its texts for translation.

Usage: python3 -I fetch.py <build_id or URL> <output_folder>

Writes to <output_folder>:
  original.json  the build (latest version) as returned by the API
  strings.json   the texts to translate, with context (French item names); fill in each "fr" field
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import LANG_FR, get, heroes, summarize, todo_list, write_candidate  # noqa: E402


def parse_build_id(arg):
    """Accept a numeric id or any URL ending with one (deadchaps.gg, etc.)."""
    m = re.search(r"(\d{3,})", arg.split("?")[0].rstrip("/").split("/")[-1]) or re.search(r"(\d{3,})", arg)
    if not m:
        sys.exit(f"No build id in: {arg}")
    return int(m.group(1))


def main():
    build_id, out = parse_build_id(sys.argv[1]), sys.argv[2]
    versions = get("/v1/builds", build_id=build_id)
    if not versions:
        sys.exit(f"Build {build_id} not found")
    build = max((v["hero_build"] for v in versions), key=lambda b: b.get("version") or 0)
    strings = write_candidate(out, build, prefill=build.get("language") == LANG_FR)

    print(f"Hero: {heroes()[build['hero_id']]['name']} | build {build_id} v{build.get('version')}")
    print(summarize(build, strings))
    todo = todo_list(strings)
    if todo:
        print(f"\nTo translate (JSON list in this order -> apply.py {out} --fr -):\n{todo}")


if __name__ == "__main__":
    main()
