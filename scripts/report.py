"""Generate the HTML page of a hero search (builds, TLDR, how to play, how to counter, comparison).

Usage: python3 -I report.py <folder> [--open]

Reads <folder>/candidates.json, each <folder>/<key>/build_fr.json + code.txt (from apply.py; otherwise
original.json, without a copy button), <folder>/summaries.json (the written analysis) and the analysis module
outputs. Writes one page per language (<folder>/index.html in English, index.<lang>.html for the others), then
refreshes the home page (hub.py).
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
from common import GAME_LANGUAGE, get, heroes, items, parse_otp_note, rank_label, read_json, read_text, write_text  # noqa: E402
from i18n import CONTENT_LANG, DEFAULT_LANG, LANGS, t, table, use  # noqa: E402
from status import completeness, load_json, resolve_sources  # noqa: E402
from textlinks import link_index, short_names, signature_abilities  # noqa: E402
from writing import filler, repeats  # noqa: E402
from tooltips import UPGRADE_COST, item_data, plain, tier_text, tooltip  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
TEMPLATE = os.path.join(SKILL, "templates", "hero.html")
GAMEPLAY_PATCH = re.compile(r"update|\d{2}-\d{2}-\d{4}|gameplay|patch", re.I)
CORE_ITEM_PCT, CORE_ITEM_COST = 90, 1600
# item power spikes: bought in >= 75% of games from tier II, or >= 60% from tier III (big late items are situational)
SPIKE_ITEM_RULES = ((75, 1600), (60, 3200))


def facts(candidate):
    """One-line facts about a build (localized)."""
    c = candidate
    parts = [t("facts.by", author=c.get("author"))]
    if c.get("rank"):
        parts.append(c["rank"])
    if c.get("matches"):
        parts.append(t("facts.matches", matches=c["matches"], share=round(100 * c.get("share", 0))))
    if c.get("winrate") is not None:
        parts.append(t("facts.winrate", winrate=c["winrate"]))
    if c.get("favorites"):
        parts.append(t("facts.favorites", favorites=c["favorites"]))
    if c.get("build_id"):
        parts.append(t("facts.build", build_id=c["build_id"]))
    if c.get("updated"):
        parts.append(t("facts.updated", date=datetime.date.fromtimestamp(c["updated"]).strftime(t("date_format"))))
    if c.get("needs_translation") and not c.get("_translated"):
        parts.append(t("facts.untranslated"))
    return parts


def mod_data(mod):
    """An item of a build; generated OTP notes become structured data (share, minute, resale)."""
    out = {"id": mod["ability_id"]}
    note = (mod.get("annotation") or "").strip()
    parsed = parse_otp_note(note)
    if parsed:
        out.update(pct=parsed[0], min=parsed[1], sold=parsed[2])
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
        for date in get("/v1/patches/big-days"):
            by_day[iso_timestamp(date) // 86400] = {"t": iso_timestamp(date), "title": t("patch.big"), "big": True}
    except Exception:
        pass
    try:
        for x in get("/v2/patches"):
            if not GAMEPLAY_PATCH.search(x.get("title") or ""):
                continue
            published = iso_timestamp(x["pub_date"])
            day = published // 86400
            same = next((d for d in (day, day - 1, day + 1) if d in by_day), None)
            if same is not None:  # same update as the big patch
                by_day[same]["title"] = x["title"].strip()
            else:
                by_day[day] = {"t": published, "title": x["title"].strip(), "big": False}
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


def minute_to_souls(net_worth, minute):
    """Average net worth at `minute`, from the curve [[minute, souls], ...]."""
    previous = (0, 0)
    for m, value in net_worth:
        if m >= minute:
            m0, v0 = previous
            return int(round(v0 + (value - v0) * (minute - m0) / max(1e-9, m - m0), -1))
        previous = (m, value)
    return int(previous[1]) if net_worth else None


def item_spikes(ref, all_items):
    """Key purchases of the reference OTP (real purchase minute) placed on its average net worth curve."""
    net_worth = (ref.get("play") or {}).get("nw") or [] if ref else []
    if not net_worth:
        return []
    spikes, seen = [], set()
    for cat in ref["cats"]:
        for mod in cat["mods"]:
            pct, minute, cost = mod.get("pct"), mod.get("min"), (all_items.get(mod["id"]) or {}).get("cost", 0)
            if pct is None or minute is None or mod["id"] in seen:
                continue
            if any(pct >= p and cost >= c for p, c in SPIKE_ITEM_RULES):
                seen.add(mod["id"])
                spikes.append({"id": mod["id"], "kind": "item", "souls": minute_to_souls(net_worth, minute),
                               "min": float(minute), "tier": 3 if cost >= 3200 else 2, "pct": pct, "cost": cost})
    return spikes


def reference_build(builds, pick):
    """Build used for power spikes: the TLDR pick first, then an OTP with a measured play style."""
    return (next((b for b in builds if b["key"] == pick and b["order"]), None)
            or next((b for b in builds if b["source"] == "OTP" and b["order"] and b.get("play")), None)
            or next((b for b in builds if b["order"]), None))


def measured(build):
    """True when the build comes from real purchases (minute and share of games per item)."""
    return bool(build) and any(m.get("pct") is not None for c in build["cats"] for m in c["mods"])


def item_reference(builds, ref):
    """Build used for key items and item power spikes: the reference build when its purchases are measured,
    otherwise an OTP with measured purchases and a net worth curve (a written build has no purchase minutes)."""
    if measured(ref) and (ref.get("play") or {}).get("nw"):
        return ref
    otps = [b for b in builds if b["source"] == "OTP" and measured(b) and (b.get("play") or {}).get("nw")]
    return max(otps, key=lambda b: b.get("badge") or 0, default=None)  # the best-ranked one-trick


def power_spikes(hero, ref, all_items):
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
        ability = all_items.get(ability_id) or {}
        spikes.append({"id": ability_id, "souls": souls,
                       "min": souls_to_minute(net_worth, souls) if net_worth else None, "tier": tier,
                       "text": tier_text(ability, tier) if tier else ""})
    return spikes


def hero_kit(hero_id, all_items, builds, pick=None):
    """The 4 ability cards + power spikes (ability order on level thresholds + key items at their real minute) + core items."""
    try:
        hero = heroes().get(hero_id) or {}
    except Exception:
        return None
    abilities = []
    for key, ability in signature_abilities(hero_id, all_items):
        desc = plain((ability.get("description") or {}).get("desc"))
        if not desc:  # some abilities only have a tooltip
            desc = plain(next((b["d"] for b in tooltip(ability)["blocks"] if b.get("d")), ""))
        abilities.append({"id": ability["id"], "key": key, "desc": desc[:420],
                          "tiers": [tier_text(ability, k) for k in (1, 2, 3)]})
    ref = reference_build(builds, pick)
    item_ref = item_reference(builds, ref)
    core, first_max = [], None
    if item_ref:
        for cat in item_ref["cats"]:
            for mod in cat["mods"]:
                if mod.get("pct") and mod["pct"] >= CORE_ITEM_PCT and (all_items.get(mod["id"]) or {}).get("cost", 0) >= CORE_ITEM_COST:
                    core.append({"id": mod["id"], "min": mod["min"], "pct": mod["pct"]})
    if ref:
        upgrades = {}
        for step in ref["order"]:
            if not step["unlock"]:
                upgrades[step["id"]] = upgrades.get(step["id"], 0) + 1
                if upgrades[step["id"]] == 3 and first_max is None:
                    first_max = step["id"]
    spikes = sorted(power_spikes(hero, ref, all_items) + item_spikes(item_ref, all_items),
                    key=lambda x: (x["souls"], x.get("kind") == "item"))
    return {"abilities": abilities, "spikes": spikes,
            "core": sorted(core, key=lambda x: x["min"])[:6], "ref": item_ref["author"] if item_ref else None,
            "abilityRef": ref["author"] if ref else None, "firstMax": first_max}


def install_assets(folder):
    """Copy the banner / emblem once into builds/_assets (referenced as ../_assets/)."""
    target = os.path.join(os.path.dirname(os.path.abspath(folder)), "_assets")
    os.makedirs(target, exist_ok=True)
    for name in ("banner.webp", "emblem.webp"):
        src = os.path.join(SKILL, "assets", name)
        if os.path.exists(src) and not os.path.exists(os.path.join(target, name)):
            shutil.copy(src, target)


def video_tips(hero_id, folder, lang):
    """Creator video tips (data/videos.json, videos.py) for this hero, in `lang` when translated, cross-checked
    with the measured items."""
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
        translated = (tip.get("translations") or {}).get(lang)
        text, text_lang = (translated, lang) if translated else (tip["text"], tip.get("lang", CONTENT_LANG))
        out.append({"video": tip["video"], "t": tip["t"], "items": tip["items"], "text": text, "lang": text_lang,
                    "title": meta.get("title"), "author": meta.get("author"), "date": meta.get("date"),
                    "prePatch": bool(big_patch and published < big_patch),
                    "check": {str(i): measured[i] for i in tip["items"] if i in measured}})
    return out


def pick_file(folder, stem, ext, lang):
    """<stem>_<lang>.<ext> (or <stem>.<lang>.<ext> for codes), else the content-language file."""
    for name in (f"{stem}_{lang}.{ext}", f"{stem}.{lang}.{ext}", f"{stem}_{CONTENT_LANG}.{ext}", f"{stem}.{ext}"):
        if os.path.exists(f"{folder}/{name}"):
            return f"{folder}/{name}"
    return None


def style_tag_ids(tags):
    """Play style tags are stored as ids; older pages stored French labels."""
    by_label = {label: key for key, label in table("style_tags", lang="fr").items()}
    return [by_label.get(x, x) for x in tags]


def load_builds(folder, candidates, summaries, lang):
    builds = []
    for c in candidates:
        build_dir = f"{folder}/{c['key']}"
        path = pick_file(build_dir, "build", "json", lang) or f"{build_dir}/original.json"
        c["_translated"] = os.path.basename(path).startswith("build_")
        build = read_json(path)
        code_path = pick_file(build_dir, "code", "txt", lang)
        code = read_text(code_path).strip() if code_path else ""
        summary = summaries.get(c["key"], {})
        cats = [{"name": cat.get("name"), "desc": cat.get("description") or "", "optional": bool(cat.get("optional")),
                 "width": round(cat.get("width") or 0), "mods": [mod_data(m) for m in cat.get("mods", [])]}
                for cat in build["details"]["mod_categories"]]
        order = [{"id": x["ability_id"], "unlock": x.get("currency_type") == 2}
                 for x in (build["details"].get("ability_order") or {}).get("currency_changes", [])]
        counters = load_json(f"{build_dir}/counters.json")
        play = load_json(f"{build_dir}/playstyle.json")
        if play:
            play["tags"] = style_tag_ids(play.get("tags") or [])
        builds.append({"key": c["key"], "play": play,
                       "counters": counters["items"] if counters else None,
                       "source": c["source"], "sourceInfo": table("source_info").get(c["source"], ""),
                       "author": c.get("author"), "rank": rank_label(c["badge"]) if c.get("badge") else c.get("rank"),
                       "name": build.get("name"),
                       "desc": "" if c["source"] == "OTP" else build.get("description") or "",  # OTP: already in facts
                       "facts": facts(c), "code": code, "winrate": c.get("winrate"), "rankImg": rank_image(c.get("badge")),
                       "badge": c.get("badge"),
                       "matches": c.get("matches"), "share": c.get("share"), "favorites": c.get("favorites"),
                       "updated": c.get("updated"), "buildId": c.get("build_id"),
                       "translated": c["_translated"] or not c.get("needs_translation"),
                       # texts in the author's own language are shown as written (never "corrected")
                       "authorWords": c["source"] != "OTP" and c.get("language") == GAME_LANGUAGE.get(lang),
                       "resume": summary.get("resume", ""), "points": summary.get("points", []),
                       "cats": cats, "order": order, "video": video_ref(c)})
    return builds


def video_ref(candidate):
    """The guide video that recommends this build: {id, t, title, author}, or None."""
    if not candidate.get("video"):
        return None
    meta = ((load_json(os.path.join(SKILL, "data", "videos.json")) or {}).get("videos") or {}).get(candidate["video"]) or {}
    return {"id": candidate["video"], "t": candidate.get("video_t") or 0, "title": meta.get("title", ""),
            "author": meta.get("author", "")}


def guide_videos(hero_id):
    """Guide videos about this hero (data/videos.json, videos.py guide), newest first."""
    videos = (load_json(os.path.join(SKILL, "data", "videos.json")) or {}).get("videos") or {}
    found = [{"id": v, "title": m["title"], "author": m["author"], "date": m["date"]}
             for v, m in videos.items() if (m.get("guide") or {}).get("hero") == hero_id]
    return sorted(found, key=lambda x: x["date"], reverse=True)

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


def written_texts(summaries, builds, tips, ours_only=False):
    """Every text of the page; ours_only leaves out build texts shown in the author's own words."""
    texts = [summaries.get("intro", "")] + list(all_strings(summaries.get("plan") or {})) + list(all_strings(summaries.get("tldr") or {}))
    for b in builds:
        if ours_only and b.get("authorWords"):
            texts += [b["resume"]] + list(b["points"])
            continue
        texts += [b["resume"], b["desc"]] + list(b["points"])
        for cat in b["cats"]:
            texts.append(cat["desc"])
            texts += [m.get("note", "") for m in cat["mods"]]
    return texts + [x["text"] for x in tips]


def enemy_heroes(enemy_ids):
    """Small cards (name, icon, class, colour) for the heroes shown in matchups and counters."""
    try:
        local = heroes() if enemy_ids else {}
        english = heroes("en") if enemy_ids else {}
    except Exception:
        local, english = {}, {}
    return {str(e): {"n": local.get(e, {}).get("name", str(e)),
                     "img": ((local.get(e) or {}).get("images") or {}).get("icon_image_small_webp"),
                     "type": (english.get(e) or {}).get("hero_type"),
                     "color": ((local.get(e) or {}).get("colors") or {}).get("style_hex")} for e in enemy_ids}

def localized_summaries(folder, lang):
    """The written analysis in `lang` (summaries.<lang>.json), else the content-language one; and its language."""
    path = f"{folder}/summaries.{lang}.json"
    if lang != CONTENT_LANG and os.path.exists(path):
        return read_json(path), lang
    summaries = load_json(f"{folder}/summaries.json", {})
    return summaries, summaries.get("lang", CONTENT_LANG)


def page_name(lang):
    return "index.html" if lang == DEFAULT_LANG else f"index.{lang}.html"


def language_links(lang):
    return "".join(f'<a href="{page_name(x)}" hreflang="{x}" lang="{x}"{" aria-current=\"true\"" if x == lang else ""}>'
                   f"{x.upper()}</a>" for x in LANGS)


def fill_template(template, values):
    """Page shell: language, links, {{ui:key}} interface strings, then the data."""
    ui = table("ui")
    out = re.sub(r"\{\{ui:([\w.]+)\}\}", lambda m: html.escape(ui[m[1]]), template)
    for key, value in values.items():
        out = out.replace(key, value)
    return out


def build_page(folder, data, lang):
    """Generate the page of one language; returns (path, completeness state)."""
    use(lang)
    hero_id = data["hero"]["id"]
    summaries, content_lang = localized_summaries(folder, lang)
    all_items = items()
    builds = load_builds(folder, data["candidates"], summaries, lang)
    used = {m["id"] for b in builds for cat in b["cats"] for m in cat["mods"]} | {o["id"] for b in builds for o in b["order"]}
    hero = hero_info(data["hero"])

    tips = video_tips(hero_id, folder, lang)
    texts = written_texts(summaries, builds, tips)
    used.update(i for x in tips for i in x["items"])
    # Texts quote item names in their own language: links are matched with that language's names.
    text_items = items(content_lang)
    if content_lang == lang:  # check the writing once per language, not on fallback content
        for word, names, excerpt in short_names(text_items, written_texts(summaries, builds, tips, ours_only=True)):
            print(f"Shortened name ({lang}) \"{word}\" ({' / '.join(names)}?): …{excerpt}…")
    own = [summaries.get("intro", "")] + list(all_strings(summaries.get("plan") or {})) + list(all_strings(summaries.get("tldr") or {}))
    if summaries.get("lang", content_lang) == lang:  # our own analysis, in the language it is written in
        for found, excerpt in filler(own, lang):
            print(f"Filler ({lang}) \"{found}\": game basics or an empty phrase, write something specific to the hero: …{excerpt}…")
        for weakness, tip in repeats(summaries.get("plan") or {}):
            print(f"Repeated idea ({lang}): the weakness \"{weakness[:70]}…\" and the counter tip \"{tip[:70]}…\" say the same thing")
    links = link_index(hero_id, text_items, texts)
    keys = {link["id"]: link["key"] for link in links if link.get("key")}
    used.update(link["id"] for link in links)
    keys.update({a["id"]: n for n, a in signature_abilities(hero_id, all_items)})  # also for the ability order grid

    since = data.get("since") or data["generated"] - data["days"] * 86400
    kit = hero_kit(hero_id, all_items, builds, (summaries.get("tldr") or {}).get("pick"))
    if kit:
        used.update(a["id"] for a in kit["abilities"])
        used.update(c["id"] for c in kit["core"])
    guides = load_json(f"{folder}/guides.json")
    roles = load_json(f"{folder}/roles.json")
    if roles and roles.get("stats"):
        for key, value in roles["stats"].items():
            if isinstance(value, dict):
                value["label"] = table("metrics").get(key, value.get("label"))
    matchups = load_json(f"{folder}/matchups.json")
    laning = load_json(f"{folder}/laning.json")
    counterplay = load_json(f"{folder}/counterplay.json")
    enemies = {x["hero"] for b in builds for v in (b.get("counters") or []) for x in v["vs"]}
    if counterplay:
        used.update(x["id"] for group in counterplay["rules"] + counterplay.get("against", []) for x in group["items"])
        enemies |= {h for rule in counterplay["rules"] for h in rule["heroes"]}
    if matchups and matchups.get("matchups"):
        enemies |= {x["hero"] for x in matchups["matchups"]["best"] + matchups["matchups"]["worst"]}
    if laning:
        enemies |= {x["hero"] for x in laning["beaten_by"] + laning["beats"]}
        used.update(x["id"] for x in laning.get("items") or [])
    if matchups and matchups.get("items"):
        used.update(x["id"] for x in matchups["items"])
    used.update(v["id"] for b in builds for v in (b.get("counters") or []))

    state = completeness(folder)
    payload = {"sources": resolve_sources(summaries, data["candidates"], guides, roles), "videoTips": tips,
               "guideVideos": guide_videos(hero_id),
               "counterplay": counterplay, "completeness": state, "kit": kit, "heroes": enemy_heroes(enemies),
               "roles": roles, "matchups": matchups, "laning": laning, "tldr": summaries.get("tldr"), "hero": hero,
               "baseline": load_json(f"{folder}/baseline.json"), "guides": guides, "plan": summaries.get("plan"),
               "generatedTs": data["generated"], "since": since, "patches": patches(), "intro": summaries.get("intro", ""),
               "days": data["days"],
               "generated": datetime.datetime.fromtimestamp(data["generated"]).strftime(t("datetime_format")),
               "builds": builds, "items": item_data(all_items, used, keys), "links": links,
               "lang": content_lang, "contentFallback": content_lang != lang}
    ui = {**table("ui"), "style_tags": table("style_tags")}
    page = fill_template(read_text(TEMPLATE), {
        "__LANG__": lang, "__HOME__": page_name(lang), "__LANG_LINKS__": language_links(lang),
        "__HERO__": html.escape(hero["name"]), "__ICON__": html.escape(hero.get("icon") or "../_assets/emblem.webp"),
        "__UI__": json.dumps(ui, ensure_ascii=False).replace("</", "<\\/"),
        "__DATA__": json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")})
    path = f"{folder}/{page_name(lang)}"
    write_text(path, page)
    return path, state


def main():
    folder = sys.argv[1]
    data = read_json(f"{folder}/candidates.json")
    for lang in LANGS:
        path, state = build_page(folder, data, lang)
        print(f"Page ({lang}): {os.path.abspath(path)}")
    use(DEFAULT_LANG)
    install_assets(folder)
    if state["missing"]:
        print("To complete for an up-to-date analysis: " + ", ".join(state["missing"]))
    try:  # home page of all heroes, in the parent folder
        subprocess.run([sys.executable, "-I", os.path.join(HERE, "hub.py"), os.path.dirname(os.path.abspath(folder))],
                       stdout=subprocess.DEVNULL, timeout=120)
    except Exception:
        pass
    if "--open" in sys.argv:
        subprocess.Popen(["xdg-open", f"{folder}/{page_name(DEFAULT_LANG)}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

if __name__ == "__main__":
    main()
