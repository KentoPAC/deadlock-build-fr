"""Apply translations to a build and produce the in-game "Paste build" code.

Usage: python3 -I apply.py <folder> [--fr <json|->] [--no-clipboard] [--keep-layout]

Reads <folder>/original.json and <folder>/strings.json (with "fr" filled in), writes
<folder>/build_fr.json and <folder>/code.txt, and copies the code to the clipboard (wl-copy / xclip).
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from codec import encode, encode_build  # noqa: E402
from common import fill, read_json, write_json, write_text  # noqa: E402

DEADLOCK_DIRS = [
    "~/.local/share/Steam/steamapps/common/Deadlock/game/citadel",
    "~/.steam/steam/steamapps/common/Deadlock/game/citadel",
]
MAX_BUILD_BYTES = 16000  # limit enforced by the game


def account_id():
    """The local player's account id, read from the game's stats file name (never stored in the repo)."""
    for folder in DEADLOCK_DIRS:
        for f in glob.glob(os.path.expanduser(folder) + "/account_*.stats"):
            return int(os.path.basename(f)[len("account_"):-len(".stats")])
    return None


# --- Category layout ----------------------------------------------------------
# The game draws each category with the width/height stored in the build (UI pixels) and cuts
# overflowing text with "...". A translation longer than the original therefore needs new sizes.
# Constants calibrated on an in-game screenshot (1 unit ~ 1 px):
CHAR_W = 7.2      # average width of a description character (spacing included)
LABEL_CHAR_W = 8  # width of a category title character
LINE_H = 19       # height of a description line
MOD_W = 82        # width of an item card
CARD_H = 125      # height of an item card (icon + two-line name)
MAX_W = 1000      # maximum category width
BUILTIN_LABELS = {"#Citadel_HeroBuilds_EarlyGame": "Early Game",
                  "#Citadel_HeroBuilds_MidGame": "Mid Game",
                  "#Citadel_HeroBuilds_LateGame": "Late Game"}


def wrap_lines(text, chars_per_line):
    """Number of lines the text takes once word-wrapped."""
    lines = 0
    for paragraph in text.split("\n"):
        lines += 1
        current = 0
        for word in paragraph.split():
            if current and current + 1 + len(word) > chars_per_line:
                lines += 1
                current = len(word)
            else:
                current += (1 if current else 0) + len(word)
    return lines


def layout(cat):
    """Set the category width/height so its (translated) text is not cut by the game."""
    label = BUILTIN_LABELS.get(cat.get("name") or "", cat.get("name") or "")
    desc = (cat.get("description") or "").strip()
    n = len(cat.get("mods") or [])
    label_w = 30 + len(label) * LABEL_CHAR_W
    min_w = max(label_w + 20, 20 + n * MOD_W, 100)

    def lines_for(width):
        return wrap_lines(desc, max(5, int((width - label_w - 25) / CHAR_W))) if desc else 0

    # Narrowest width that keeps the description within 4 lines (MAX_W otherwise).
    width = min_w
    if desc:
        while width < MAX_W and lines_for(width) > 4:
            width += 20
        width = min(width, MAX_W)
    header_h = max(28, lines_for(width) * LINE_H)
    height = 22 + header_h + (12 + CARD_H if n else 0) + 10
    cat["width"] = float(width)
    cat["height"] = float(height)


def has_cjk(text):
    return any("぀" <= ch <= "鿿" or "가" <= ch <= "힯" for ch in text)


def copy_to_clipboard(code):
    for cmd in (["wl-copy", "-n"], ["xclip", "-selection", "clipboard"]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, input=code.encode(), check=True)
            return True
    return False


def main():
    folder = sys.argv[1]
    if "--fr" in sys.argv:  # translations as JSON (ordered list or {n: fr}): a file, or "-" for stdin
        src = sys.argv[sys.argv.index("--fr") + 1]
        fill(folder, json.load(sys.stdin) if src == "-" else read_json(src))
    original = read_json(f"{folder}/original.json")
    strings = read_json(f"{folder}/strings.json")

    missing = [s["text"][:40] for s in strings if not s.get("fr")]
    if missing:
        sys.exit(f"Missing translations: {missing}")
    for s in strings:
        node = original
        for key in s["path"][:-1]:
            node = node[key]
        node[s["path"][-1]] = s["fr"]

    if "--keep-layout" not in sys.argv:
        for cat in original["details"]["mod_categories"]:
            layout(cat)

    # Mirror exactly what the in-game "Copy to clipboard" button produces.
    build = {
        "hero_build_id": 3,
        "hero_id": original["hero_id"],
        "author_account_id": account_id(),
        "last_updated_timestamp": int(time.time()),
        "name": original.get("name"),
        "description": original.get("description") or "",
        "language": 0,
        "version": 0,
        "details": original["details"],
        "tags": original.get("tags") or [],
    }
    leftovers = [t for t in json.dumps(build, ensure_ascii=False).split('"') if has_cjk(t)]
    if leftovers:
        print("WARNING, untranslated text left:", leftovers[:5], file=sys.stderr)

    raw = encode_build(build)
    if len(raw) > MAX_BUILD_BYTES:
        sys.exit(f"Build too large ({len(raw)} bytes > {MAX_BUILD_BYTES}): shorten the texts")
    code = encode(build)  # no trailing newline: the game rejects it
    write_json(f"{folder}/build_fr.json", build, indent=1)
    write_text(f"{folder}/code.txt", code)
    print(f"{len(raw)} bytes, code: {folder}/code.txt")

    if "--no-clipboard" not in sys.argv:
        if copy_to_clipboard(code):
            print("Code copied to the clipboard")
        else:
            print("No wl-copy/xclip: copy code.txt manually")


if __name__ == "__main__":
    main()
