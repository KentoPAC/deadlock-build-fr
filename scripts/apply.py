"""Apply translations to a build and produce the in-game "Paste build" code.

Usage: python3 -I apply.py <folder> [--lang fr|en] [--tr <json|->] [--no-clipboard] [--keep-layout]

Reads <folder>/original.json and <folder>/strings.json (with the --lang field filled in, "fr" by default; --fr is
kept as a shortcut for --lang fr --tr), writes <folder>/build_<lang>.json and the code (code.txt for French,
code.<lang>.txt otherwise), and copies it to the clipboard (wl-copy / xclip). Texts already in the target language
(the author's own language, or texts generated from the locales) are filled in automatically.
"""
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from codec import encode, encode_build  # noqa: E402
from common import GAME_LANGUAGE, fill, localize_generated, read_json, write_json, write_text  # noqa: E402
from i18n import CONTENT_LANG, LANGS  # noqa: E402

MAX_BUILD_BYTES = 16000  # limit enforced by the game
# The game only offers "Paste build" when the author account id field is present, but any value works:
# 0 keeps codes anonymous (verified in game).
ANONYMOUS_AUTHOR = 0


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


def fill_known_texts(original, strings, lang):
    """Fill the `lang` texts that need no translator: the author's own language, or texts generated from the locales."""
    native = original.get("language") == GAME_LANGUAGE.get(lang)
    for s in strings:
        if not s.get(lang):
            s[lang] = s["text"] if native else localize_generated(s["text"], lang) or ""
    return strings


def output_paths(folder, lang):
    code = f"{folder}/code.txt" if lang == CONTENT_LANG else f"{folder}/code.{lang}.txt"
    return f"{folder}/build_{lang}.json", code


def option(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


def main():
    folder = sys.argv[1]
    lang = "fr" if "--fr" in sys.argv else option("--lang") or CONTENT_LANG
    if lang not in LANGS:
        sys.exit(f"Unknown language {lang!r}: expected one of {LANGS}")
    src = option("--fr") or option("--tr")
    if src:  # translations as JSON (ordered list or {n: text}): a file, or "-" for stdin
        fill(folder, json.load(sys.stdin) if src == "-" else read_json(src), lang)
    original = read_json(f"{folder}/original.json")
    strings = fill_known_texts(original, read_json(f"{folder}/strings.json"), lang)
    write_json(f"{folder}/strings.json", strings, compact=True)

    missing = [s["text"][:40] for s in strings if not s.get(lang)]
    if missing:
        sys.exit(f"Missing {lang} translations: {missing}")
    for s in strings:
        node = original
        for key in s["path"][:-1]:
            node = node[key]
        node[s["path"][-1]] = s[lang]

    if "--keep-layout" not in sys.argv:
        for cat in original["details"]["mod_categories"]:
            layout(cat)

    # Mirror exactly what the in-game "Copy to clipboard" button produces.
    build = {
        "hero_build_id": 3,
        "hero_id": original["hero_id"],
        "author_account_id": ANONYMOUS_AUTHOR,
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
    build_path, code_path = output_paths(folder, lang)
    write_json(build_path, build, indent=1)
    write_text(code_path, code)
    print(f"{len(raw)} bytes, code: {code_path}")

    if "--no-clipboard" not in sys.argv:
        if copy_to_clipboard(code):
            print("Code copied to the clipboard")
        else:
            print("No wl-copy/xclip: copy code.txt manually")


if __name__ == "__main__":
    main()
