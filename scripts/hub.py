"""Home page: every hero, with the state of its builds page.

Usage: python3 -I hub.py [builds_folder] [--open]   (default: the project's builds/ folder)

For each playable hero: portrait, colour, class; if builds/search-<hero>/ exists, links to its page (TLDR,
counter view) and its fetch date. The page compares that date with the patches itself (live stamps:
up to date / to check / patch released / outdated analysis). Otherwise, a button copies the request to paste
to Claude. Writes <builds_folder>/index.html (English) and index.<lang>.html for the other languages;
report.py reruns it after every page.
"""
import glob
import json
import os
import subprocess
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import heroes, read_json, read_text, write_text  # noqa: E402
from i18n import DEFAULT_LANG, LANGS, table, use  # noqa: E402
from report import fill_template, language_links, page_name, patches  # noqa: E402
from status import completeness  # noqa: E402

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The skill lives in <project>/.claude/skills/<name>/: pages go to <project>/builds/.
PROJECT_BUILDS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(SKILL))), "builds")
TEMPLATE = os.path.join(SKILL, "templates", "hub.html")


def page_states(root):
    """{hero_id: state of its latest search folder}, in the current language."""
    done = {}
    for path in glob.glob(f"{root}/search-*/candidates.json"):
        try:
            candidates = read_json(path)
        except ValueError:
            continue
        hero_id = candidates["hero"]["id"]
        previous = done.get(hero_id)
        if previous and candidates["generated"] <= previous["generated"]:
            continue
        state = completeness(os.path.dirname(path))
        done[hero_id] = {"dir": os.path.basename(os.path.dirname(path)), "generated": candidates["generated"],
                         "n": len(candidates["candidates"]), "missing": state["missing"],
                         "pending": [x["title"] for x in state["pending"]], "version": state["version"],
                         "ask": state["ask"]}
    return done


def build_hub(root, lang, patch_list):
    use(lang)
    done = page_states(root)
    english = heroes("en")
    playable = [h for h in heroes().values()
                # "in_development" is not a reliable filter: released heroes such as Violet and Baba keep the flag.
                if h.get("player_selectable") and not h.get("disabled")]
    cards = []
    for h in sorted(playable, key=lambda h: h["name"]):
        images = h.get("images") or {}
        en = english.get(h["id"]) or {}
        cards.append({"id": h["id"], "name": h["name"], "en": en.get("name") or h["name"],
                      "color": (h.get("colors") or {}).get("style_hex"), "type": en.get("hero_type"),
                      "card": images.get("icon_hero_card_webp") or images.get("icon_hero_card"),
                      "nameSvg": images.get("name_image"), "page": done.get(h["id"])})
    payload = json.dumps({"heroes": cards, "patches": patch_list, "pageName": page_name(lang)},
                         ensure_ascii=False, separators=(",", ":"))
    page = fill_template(read_text(TEMPLATE), {
        "__LANG__": lang, "__LANG_LINKS__": language_links(lang), "__PAGE__": page_name(lang),
        "__UI__": json.dumps(table("ui"), ensure_ascii=False).replace("</", "<\\/"),
        "__DATA__": payload.replace("</", "<\\/")})
    path = f"{root}/{page_name(lang)}"
    write_text(path, page)
    return path, len(done), len(cards)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = os.path.abspath(args[0] if args else PROJECT_BUILDS)
    try:
        patch_list = patches()  # same patch list as the hero pages
    except Exception:
        patch_list = []
    try:
        for lang in LANGS:
            path, done, total = build_hub(root, lang, patch_list)
            print(f"Home ({lang}): {path} ({done} of {total} heroes done)")
    except urllib.error.URLError as e:
        sys.exit(f"Heroes API unavailable: {e}")
    if "--open" in sys.argv:
        subprocess.Popen(["xdg-open", f"{root}/{page_name(DEFAULT_LANG)}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
