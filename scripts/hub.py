"""Home page: every hero, with the state of its builds page.

Usage: python3 -I hub.py [builds_folder] [--open]   (default: the project's builds/ folder)

For each playable hero: portrait, colour, class; if builds/search-<hero>/ exists, links to its page (TLDR,
counter view) and its fetch date. The page compares that date with the patches itself (live stamps:
up to date / to check / patch released / outdated analysis). Otherwise, a button copies the request to paste
to Claude. Writes <builds_folder>/index.html; report.py reruns it after every page.
"""
import glob
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import get, read_json, read_text, write_text  # noqa: E402

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The skill lives in <project>/.claude/skills/<name>/: pages go to <project>/builds/.
PROJECT_BUILDS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(SKILL))), "builds")
TEMPLATE = os.path.join(SKILL, "templates", "hub.html")


def page_states(root):
    """{hero_id: state of its latest search folder}."""
    from status import completeness
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


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = os.path.abspath(args[0] if args else PROJECT_BUILDS)
    done = page_states(root)
    try:
        english = {h["id"]: h for h in get("/v1/assets/heroes")}
        playable = [h for h in get("/v1/assets/heroes", language="french")
                    if h.get("player_selectable") and not h.get("disabled") and not h.get("in_development")]
    except Exception as e:
        sys.exit(f"Heroes API unavailable: {e}")
    try:
        from report import patches  # same patch list as the hero pages
        patch_list = patches()
    except Exception:
        patch_list = []
    cards = []
    for h in sorted(playable, key=lambda h: h["name"]):
        images = h.get("images") or {}
        en = english.get(h["id"]) or {}
        cards.append({"id": h["id"], "name": h["name"], "en": en.get("name") or h["name"],
                      "color": (h.get("colors") or {}).get("style_hex"), "type": en.get("hero_type"),
                      "card": images.get("icon_hero_card_webp") or images.get("icon_hero_card"),
                      "nameSvg": images.get("name_image"), "page": done.get(h["id"])})
    template = read_text(TEMPLATE)
    payload = json.dumps({"heroes": cards, "patches": patch_list}, ensure_ascii=False, separators=(",", ":"))
    write_text(f"{root}/index.html", template.replace("__DATA__", payload.replace("</", "<\\/")))
    print(f"Home: {root}/index.html ({len(done)} of {len(cards)} heroes done)")
    if "--open" in sys.argv:
        subprocess.Popen(["xdg-open", f"{root}/index.html"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
