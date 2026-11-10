"""Generate the HTML page of a hero search (builds, TLDR, how to play, how to counter, comparison).

Usage: python3 -I report.py <folder> [--open]

Reads <folder>/candidates.json, each <folder>/<key>/build_fr.json + code.txt (from apply.py; otherwise
original.json, without a copy button), <folder>/summaries.json (the written analysis) and the analysis module
outputs. Writes <folder>/index.html, then refreshes the home page (hub.py).
"""
import datetime
import html
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import get, heroes, items, read_json, read_text, write_text  # noqa: E402
from status import completeness, load_json, resolve_sources  # noqa: E402
from textlinks import link_index, short_names, signature_abilities  # noqa: E402
from tooltips import UPGRADE_COST, english_items, item_data, plain, tier_text, tooltip  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
TEMPLATE = os.path.join(SKILL, "templates", "hero.html")
# Shown on the page under each source name (French UI).
SOURCE_INFO = {
    "OTP": "reconstitué d'après les vrais achats d'un joueur qui joue surtout ce héros",
    "Mobalytics": "build officiel d'un expert Mobalytics, publié en jeu",
    "Communauté": "build public populaire, bien expliqué, d'un auteur bien classé",
}
OTP_NOTE = re.compile(r"Pris dans (\d+) % de ses parties, vers (\d+) min\.(?: Revendu vers (\d+) min\.)?$")
GAMEPLAY_PATCH = re.compile(r"update|\d{2}-\d{2}-\d{4}|gameplay|patch", re.I)
CORE_ITEM_PCT, CORE_ITEM_COST = 90, 1600


def facts(candidate):
    """One-line facts about a build (French UI)."""
    c = candidate
    parts = [f"par {c.get('author')}"]
    if c.get("rank"):
        parts.append(c["rank"])
    if c.get("matches"):
        parts.append(f"{c['matches']} parties sur le héros ({round(100 * c.get('share', 0))} % de ses parties)")
    if c.get("winrate") is not None:
        parts.append(f"{c['winrate']:.0f} % de victoires")
    if c.get("favorites"):
        parts.append(f"{c['favorites']} favoris")
    if c.get("build_id"):
        parts.append(f"build {c['build_id']}")
    if c.get("updated"):
        parts.append("mis à jour le " + datetime.date.fromtimestamp(c["updated"]).strftime("%d/%m/%Y"))
    if c.get("needs_translation") and not c.get("_translated"):
        parts.append("pas encore traduit")
    return parts


def mod_data(mod):
    """An item of a build; generated OTP notes become structured data (share, minute, resale)."""
    out = {"id": mod["ability_id"]}
    note = (mod.get("annotation") or "").strip()
    m = OTP_NOTE.match(note)
    if m:
        out.update(pct=int(m[1]), min=int(m[2]), sold=int(m[3]) if m[3] else None)
    elif note:
        out["note"] = note
    return out


def hero_info(hero):
    """Visual identity of the hero, re-read from the API on every run (colour, background, name art, portrait)."""
    out = {"name": hero["name"], "image": hero.get("image")}
    try:
        asset = heroes().get(hero["id"]) or {}
    except Exception:  # API unavailable: page without the hero theme
        return out
    images = asset.get("images") or {}
    out.update(name=asset.get("name") or hero["name"], color=(asset.get("colors") or {}).get("style_hex"),
               bg=images.get("background_image_webp") or images.get("background_image"),
               nameSvg=images.get("name_image"),
               portrait=images.get("hero_card_gloat_webp") or images.get("icon_hero_card_webp"),
               icon=images.get("icon_image_small_webp") or images.get("icon_image_small"),
               tags=asset.get("tags") or [])
    return out


def iso_timestamp(text):
    return int(datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())


def patches():
    """Game updates (big patches flagged): the page compares build dates with these."""
    by_day = {}
    try:
        for t in get("/v1/patches/big-days"):
            by_day[iso_timestamp(t) // 86400] = {"t": iso_timestamp(t), "title": "Gros patch", "big": True}
    except Exception:
        pass
    try:
        for x in get("/v2/patches"):
            if not GAMEPLAY_PATCH.search(x.get("title") or ""):
                continue
            t = iso_timestamp(x["pub_date"])
            day = t // 86400
            same = next((d for d in (day, day - 1, day + 1) if d in by_day), None)
            if same is not None:  # same update as the big patch
                by_day[same]["title"] = x["title"].strip()
            else:
                by_day[day] = {"t": t, "title": x["title"].strip(), "big": False}
    except Exception:
        pass
    return sorted(by_day.values(), key=lambda p: -p["t"])[:40]


_rank_images = None


def rank_image(badge):
    """Official rank emblem (sub-rank included) for a badge (e.g. 114 = Éternus 4)."""
    global _rank_images
    if not badge:
        return None
    if _rank_images is None:
        try:
            _rank_images = {r["tier"]: r.get("images") or {} for r in get("/v1/assets/ranks")}
        except Exception:
            _rank_images = {}
    tier, sub = divmod(int(badge), 10)
    images = _rank_images.get(tier) or {}
    return images.get(f"large_subrank{sub}_webp") or images.get("large_webp") or images.get("large")


def souls_to_minute(net_worth, souls):
    """Approximate minute a player reaches `souls`, from their average curve [[minute, souls], ...]."""
    previous = (0, 0)
    for minute, value in net_worth:
        if value >= souls:
            m0, v0 = previous
            return round(m0 + (minute - m0) * (souls - v0) / max(1, value - v0), 1)
        previous = (minute, value)
    return None


def reference_build(builds, pick):
    """Build used for power spikes: the TLDR pick first, then an OTP with a measured play style."""
    return (next((b for b in builds if b["key"] == pick and b["order"]), None)
            or next((b for b in builds if b["source"] == "OTP" and b["order"] and b.get("play")), None)
            or next((b for b in builds if b["order"]), None))


def power_spikes(hero, ref, all_items, english):
    """Ability unlocks and upgrades of the reference build, placed on the game's level thresholds."""
    levels = sorted(((int(k), v) for k, v in (hero.get("level_info") or {}).items()), key=lambda x: x[0])
    if not ref or not levels:
        return []
    thresholds = {"EAbilityUnlocks": [], "EAbilityPoints": []}
    for _, level in levels:
        for currency in level.get("bonus_currencies") or []:
            thresholds.setdefault(currency, []).append(level.get("required_gold") or 0)
    spent = {"EAbilityUnlocks": 0, "EAbilityPoints": 0}
    tiers, souls = {}, 0
    net_worth = (ref.get("play") or {}).get("nw") or []
    spikes = []
    for step in ref["order"]:
        ability_id = step["id"]
        currency = "EAbilityUnlocks" if step["unlock"] else "EAbilityPoints"
        spent[currency] += 1 if step["unlock"] else UPGRADE_COST.get(tiers.get(ability_id, 0) + 1, 1)
        pool = thresholds.get(currency) or []
        if spent[currency] > len(pool):
            break
        souls = max(souls, pool[spent[currency] - 1])
        tier = tiers[ability_id] = 0 if step["unlock"] else tiers.get(ability_id, 0) + 1
        fr, en = all_items.get(ability_id) or {}, english.get(ability_id) or {}
        spikes.append({"id": ability_id, "souls": souls,
                       "min": souls_to_minute(net_worth, souls) if net_worth else None, "tier": tier,
                       "text": tier_text(fr, tier) if tier else "",
                       "text_en": tier_text(en, tier) if tier and en else ""})
    return spikes


def hero_kit(hero_id, all_items, english, builds, pick=None):
    """The 4 ability cards + power spikes (game level thresholds x an OTP's ability order) + core items."""
    try:
        hero = heroes().get(hero_id) or {}
    except Exception:
        return None
    abilities = []
    for key, ability in signature_abilities(hero_id, all_items):
        en = english.get(ability["id"]) or {}
        desc = plain((ability.get("description") or {}).get("desc"))
        if not desc:  # some abilities only have a tooltip
            desc = plain(next((b["d"] for b in tooltip(ability)["blocks"] if b.get("d")), ""))
        abilities.append({"id": ability["id"], "key": key, "desc": desc[:420],
                          "desc_en": plain((en.get("description") or {}).get("desc"))[:420],
                          "tiers": [tier_text(ability, k) for k in (1, 2, 3)],
                          "tiers_en": [tier_text(en, k) for k in (1, 2, 3)] if en else []})
    ref = reference_build(builds, pick)
    core, first_max = [], None
    if ref:
        for cat in ref["cats"]:
            for mod in cat["mods"]:
                if mod.get("pct") and mod["pct"] >= CORE_ITEM_PCT and (all_items.get(mod["id"]) or {}).get("cost", 0) >= CORE_ITEM_COST:
                    core.append({"id": mod["id"], "min": mod["min"], "pct": mod["pct"]})
        upgrades = {}
        for step in ref["order"]:
            if not step["unlock"]:
                upgrades[step["id"]] = upgrades.get(step["id"], 0) + 1
                if upgrades[step["id"]] == 3 and first_max is None:
                    first_max = step["id"]
    return {"abilities": abilities, "spikes": power_spikes(hero, ref, all_items, english),
            "core": sorted(core, key=lambda x: x["min"])[:6], "ref": ref["author"] if ref else None, "firstMax": first_max}


def install_assets(folder):
    """Copy the banner / emblem once into builds/_assets (referenced as ../_assets/)."""
    target = os.path.join(os.path.dirname(os.path.abspath(folder)), "_assets")
    os.makedirs(target, exist_ok=True)
    for name in ("banner.webp", "emblem.webp"):
        src = os.path.join(SKILL, "assets", name)
        if os.path.exists(src) and not os.path.exists(os.path.join(target, name)):
            shutil.copy(src, target)


def video_tips(hero_id, folder):
    """Creator video tips (data/videos.json, videos.py) for this hero, cross-checked with the measured items."""
    videos = load_json(os.path.join(SKILL, "data", "videos.json"))
    if not videos:
        return []
    try:
        from guides import last_big_patch
        big_patch = last_big_patch()
    except Exception:
        big_patch = None
    measured = {}
    for name in ("matchups.json", "counterplay.json"):
        data = load_json(os.path.join(folder, name))
        if data:
            for x in data.get("items") or []:
                measured[x["id"]] = {"delta": x["delta"]}
            for group in data.get("against") or []:
                for x in group["items"]:
                    measured.setdefault(x["id"], {"against": True})
    out = []
    for tip in videos["tips"].get(str(hero_id), []):
        meta = videos["videos"].get(tip["video"]) or {}
        published = datetime.datetime.strptime(meta.get("date", "1970-01-01"), "%Y-%m-%d").timestamp()
        out.append({**tip, "title": meta.get("title"), "author": meta.get("author"), "date": meta.get("date"),
                    "prePatch": bool(big_patch and published < big_patch),
                    "check": {str(i): measured[i] for i in tip["items"] if i in measured}})
    return out


def load_builds(folder, candidates, summaries):
    builds = []
    for c in candidates:
        build_dir = f"{folder}/{c['key']}"
        path = f"{build_dir}/build_fr.json" if os.path.exists(f"{build_dir}/build_fr.json") else f"{build_dir}/original.json"
        c["_translated"] = path.endswith("build_fr.json")
        build = read_json(path)
        code = read_text(f"{build_dir}/code.txt").strip() if os.path.exists(f"{build_dir}/code.txt") else ""
        summary = summaries.get(c["key"], {})
        cats = [{"name": cat.get("name"), "desc": cat.get("description") or "", "optional": bool(cat.get("optional")),
                 "width": round(cat.get("width") or 0), "mods": [mod_data(m) for m in cat.get("mods", [])]}
                for cat in build["details"]["mod_categories"]]
        order = [{"id": x["ability_id"], "unlock": x.get("currency_type") == 2}
                 for x in (build["details"].get("ability_order") or {}).get("currency_changes", [])]
        counters = load_json(f"{build_dir}/counters.json")
        builds.append({"key": c["key"], "play": load_json(f"{build_dir}/playstyle.json"),
                       "counters": counters["items"] if counters else None,
                       "source": c["source"], "sourceInfo": SOURCE_INFO.get(c["source"], ""),
                       "author": c.get("author"), "rank": c.get("rank"), "name": build.get("name"),
                       "desc": "" if c["source"] == "OTP" else build.get("description") or "",  # OTP: already in facts
                       "facts": facts(c), "code": code, "winrate": c.get("winrate"), "rankImg": rank_image(c.get("badge")),
                       "matches": c.get("matches"), "share": c.get("share"), "favorites": c.get("favorites"),
                       "updated": c.get("updated"), "buildId": c.get("build_id"),
                       "translated": c["_translated"] or not c.get("needs_translation"),
                       "resume": summary.get("resume", ""), "points": summary.get("points", []),
                       "cats": cats, "order": order})
    return builds


def all_strings(value):
    """Every string inside nested dicts / lists."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from all_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from all_strings(v)


def written_texts(summaries, builds, tips):
    texts = [summaries.get("intro", "")] + list(all_strings(summaries.get("plan") or {})) + list(all_strings(summaries.get("tldr") or {}))
    for b in builds:
        texts += [b["resume"], b["desc"]] + list(b["points"])
        for cat in b["cats"]:
            texts.append(cat["desc"])
            texts += [m.get("note", "") for m in cat["mods"]]
    return texts + [x["text"] for x in tips]


def enemy_heroes(enemy_ids):
    """Small cards (name, icon, class, colour) for the heroes shown in matchups and counters."""
    try:
        french = heroes() if enemy_ids else {}
    except Exception:
        french = {}
    try:
        english = {h["id"]: h for h in get("/v1/assets/heroes")} if enemy_ids else {}
    except Exception:
        english = {}
    return {str(e): {"n": french.get(e, {}).get("name", str(e)),
                     "img": ((french.get(e) or {}).get("images") or {}).get("icon_image_small_webp"),
                     "type": (english.get(e) or {}).get("hero_type"),
                     "color": ((french.get(e) or {}).get("colors") or {}).get("style_hex")} for e in enemy_ids}


def main():
    folder = sys.argv[1]
    data = read_json(f"{folder}/candidates.json")
    hero_id = data["hero"]["id"]
    summaries = load_json(f"{folder}/summaries.json", {})
    all_items = items()
    builds = load_builds(folder, data["candidates"], summaries)
    used = {m["id"] for b in builds for cat in b["cats"] for m in cat["mods"]} | {o["id"] for b in builds for o in b["order"]}
    hero = hero_info(data["hero"])

    tips = video_tips(hero_id, folder)
    texts = written_texts(summaries, builds, tips)
    used.update(i for x in tips for i in x["items"])
    for word, names, excerpt in short_names(all_items, texts):
        print(f"Shortened name \"{word}\" ({' / '.join(names)}?): …{excerpt}…")
    links = link_index(hero_id, all_items, texts)
    keys = {link["id"]: link["key"] for link in links if link.get("key")}
    used.update(link["id"] for link in links)
    keys.update({a["id"]: n for n, a in signature_abilities(hero_id, all_items)})  # also for the ability order grid

    since = data.get("since") or data["generated"] - data["days"] * 86400
    english = english_items()
    kit = hero_kit(hero_id, all_items, english, builds, (summaries.get("tldr") or {}).get("pick"))
    if kit:
        used.update(a["id"] for a in kit["abilities"])
        used.update(c["id"] for c in kit["core"])
    guides = load_json(f"{folder}/guides.json")
    roles = load_json(f"{folder}/roles.json")
    matchups = load_json(f"{folder}/matchups.json")
    counterplay = load_json(f"{folder}/counterplay.json")
    enemies = {x["hero"] for b in builds for v in (b.get("counters") or []) for x in v["vs"]}
    if counterplay:
        used.update(x["id"] for group in counterplay["rules"] + counterplay.get("against", []) for x in group["items"])
        enemies |= {h for rule in counterplay["rules"] for h in rule["heroes"]}
    if matchups and matchups.get("matchups"):
        enemies |= {x["hero"] for x in matchups["matchups"]["best"] + matchups["matchups"]["worst"]}
    if matchups and matchups.get("items"):
        used.update(x["id"] for x in matchups["items"])
    used.update(v["id"] for b in builds for v in (b.get("counters") or []))

    state = completeness(folder)
    payload = {"sources": resolve_sources(summaries, data["candidates"], guides, roles), "videoTips": tips,
               "counterplay": counterplay, "completeness": state, "kit": kit, "heroes": enemy_heroes(enemies),
               "roles": roles, "matchups": matchups, "tldr": summaries.get("tldr"), "hero": hero,
               "baseline": load_json(f"{folder}/baseline.json"), "guides": guides, "plan": summaries.get("plan"),
               "generatedTs": data["generated"], "since": since, "patches": patches(), "intro": summaries.get("intro", ""),
               "days": data["days"],
               "generated": datetime.datetime.fromtimestamp(data["generated"]).strftime("%d/%m/%Y %H:%M"),
               "builds": builds, "items": item_data(all_items, used, keys, english), "links": links}
    template = read_text(TEMPLATE)
    payload_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = (template.replace("__HERO__", html.escape(hero["name"]))
            .replace("__ICON__", html.escape(hero.get("icon") or "../_assets/emblem.webp"))
            .replace("__DATA__", payload_js))
    write_text(f"{folder}/index.html", page)
    install_assets(folder)
    print(f"Page: {os.path.abspath(folder)}/index.html")
    if state["missing"]:
        print("To complete for an up-to-date analysis: " + ", ".join(state["missing"]))
    try:  # home page of all heroes, in the parent folder
        subprocess.run([sys.executable, "-I", os.path.join(HERE, "hub.py"), os.path.dirname(os.path.abspath(folder))],
                       stdout=subprocess.DEVNULL, timeout=120)
    except Exception:
        pass
    if "--open" in sys.argv:
        subprocess.Popen(["xdg-open", f"{folder}/index.html"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
