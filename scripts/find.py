"""Find the best builds for a hero, from three sources:

  1. OTP         high-ranked players who mostly play this hero; the build is rebuilt from their ACTUAL
                 purchases (items, minute, share of games, ability order)
  2. Mobalytics  official builds from their experts, published in game
  3. Community   popular public builds, well explained, by high-ranked authors

Usage: python3 -I find.py <hero> <folder> [--days 60] [--otp 2] [--community 2]

Writes <folder>/candidates.json and one sub-folder per build (original.json + strings.json), then runs the
analysis modules (playstyle, guides, roles, matchups, counterplay; counters in the background).
"""
import argparse
import datetime
import math
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (GAME_LANGUAGE, LANG_FR, find_hero, get, items, rank_label, read_json, summarize,  # noqa: E402
                    text_amount, todo_list, write_candidate, write_json)
from i18n import CONTENT_LANG, t, use  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
MIN_BADGE = 90          # Fantôme (Phantom) and above for OTPs
CORE_PCT = 0.75         # an item is "core" when bought in >= 75% of games
SITUATIONAL_PCT = 0.25  # below this: ignored
EARLY_MIN, MID_MIN = 10, 22
MIN_PATCH_DAYS = 21     # the OTP window starts at the last big patch if that patch is at least 3 weeks old
ANALYSIS_MODULES = ("playstyle.py", "guides.py", "roles.py", "matchups.py", "counterplay.py")


def batch(path, ids, key="account_ids"):
    """Call an endpoint that takes a comma-separated id list, 50 ids at a time."""
    out = []
    for i in range(0, len(ids), 50):
        out += get(path, **{key: ",".join(map(str, ids[i:i + 50]))})
    return out


# --------------------------------------------------------------------- OTP

def find_otps(hero_id, since, n):
    board = get("/v1/analytics/scoreboards/players", hero_id=hero_id, sort_by="matches",
                min_average_badge=MIN_BADGE - 5, min_unix_timestamp=since, min_matches=20, limit=40)
    if not board:
        return []
    ids = [x["account_id"] for x in board]
    ranks = {r["account_id"]: r for r in batch("/v1/players/rank", ids)}
    names = {p["account_id"]: p["personaname"] for p in batch("/v1/players/steam", ids)}
    totals = {}
    for x in get("/v1/players/hero-stats", account_ids=",".join(map(str, ids)), min_unix_timestamp=since):
        totals[x["account_id"]] = totals.get(x["account_id"], 0) + x.get("matches_played", 0)
    players = []
    for x in board:
        account = x["account_id"]
        played = int(x.get("matches", x.get("value", 0)))
        badge = ranks.get(account, {}).get("badge") or 0
        share = played / max(totals.get(account, played), played)
        if badge < MIN_BADGE or share < 0.3:
            continue
        # Rank first, then specialisation and volume.
        score = badge * 2 + share * 30 + math.log10(played) * 10
        players.append(dict(account_id=account, name=names.get(account, str(account)), badge=badge,
                            matches=played, share=share, score=score))
    players.sort(key=lambda p: -p["score"])
    return players[:n]


def ability_order(hero_id, account_id, since):
    """Most frequent ability order of a player, as build currency changes (unlock, then upgrades)."""
    stats = get("/v1/analytics/ability-order-stats", hero_id=hero_id, account_id=account_id, min_unix_timestamp=since)
    if not stats:
        return []
    best = max(stats, key=lambda x: x["matches"])
    order, seen = [], {}
    for ability in best["abilities"]:
        k = seen[ability] = seen.get(ability, 0) + 1
        if k == 1:
            order.append({"ability_id": ability, "currency_type": 2, "delta": -1})
        else:
            order.append({"ability_id": ability, "currency_type": 1, "delta": -[1, 2, 5][min(k - 2, 2)]})
    return order


def otp_build(hero, player, since):
    """Rebuild a player's build from their purchase stats (localized texts: they go into the game)."""
    hero_id = hero["id"]
    all_items = items()
    stats = get("/v1/analytics/item-stats", hero_id=hero_id, account_id=player["account_id"], min_unix_timestamp=since)
    stats = [s for s in stats if all_items.get(s["item_id"], {}).get("type") == "upgrade"]
    if not stats:
        return None
    n = max(s["matches"] for s in stats)
    most_bought = max(stats, key=lambda s: s["matches"])
    winrate = 100 * most_bought["wins"] / max(1, most_bought["wins"] + most_bought["losses"])

    def note(s):
        pct = round(100 * s["matches"] / n)
        text = t("otp.note", pct=pct, minute=round(s["avg_buy_time_s"] / 60))
        if s.get("sold") and s["sold"] / s["matches"] >= 0.4 and s.get("avg_sell_time_s"):
            text += t("otp.note_sold", minute=round(s["avg_sell_time_s"] / 60))
        return text

    groups = {"early": [], "mid": [], "late": [], "situational": [], "situational_late": []}
    for s in sorted(stats, key=lambda s: s["avg_buy_time_s"]):
        pct = s["matches"] / n
        minute = s["avg_buy_time_s"] / 60
        if pct >= CORE_PCT:
            groups["early" if minute < EARLY_MIN else "mid" if minute < MID_MIN else "late"].append(s)
        elif pct >= SITUATIONAL_PCT:
            groups["situational" if minute < MID_MIN else "situational_late"].append(s)
    for k in ("situational", "situational_late"):
        groups[k].sort(key=lambda s: -s["matches"])

    def category(name, desc, group):
        return {"name": name, "description": desc,
                "mods": [{"ability_id": s["item_id"], "annotation": note(s)} for s in group]}

    who = player["name"]
    categories = [c for c in [
        category("#Citadel_HeroBuilds_EarlyGame", t("otp.cat.early", who=who, minute=EARLY_MIN), groups["early"]),
        category("#Citadel_HeroBuilds_MidGame", t("otp.cat.mid", start=EARLY_MIN, end=MID_MIN), groups["mid"]),
        category("#Citadel_HeroBuilds_LateGame", t("otp.cat.late", minute=MID_MIN), groups["late"]),
        category(t("otp.cat.situational"), t("otp.cat.situational_desc"), groups["situational"]),
        category(t("otp.cat.situational_late"), t("otp.cat.situational_late_desc"), groups["situational_late"]),
    ] if c["mods"]]

    build = {
        "hero_id": hero_id,
        "name": t("otp.name", who=who, hero=hero["name"]),
        "description": t("otp.description", who=who, rank=rank_label(player["badge"]), matches=player["matches"],
                         hero=hero["name"], share=round(100 * player["share"]), winrate=round(winrate)),
        "language": LANG_FR,
        "details": {"mod_categories": categories,
                    "ability_order": {"currency_changes": ability_order(hero_id, player["account_id"], since)}},
        "tags": [],
    }
    return build, dict(winrate=round(winrate), sample=n)


# --------------------------------------------------------------- Mobalytics

def mobalytics(hero_id):
    """Latest build from an official Mobalytics account (an account with at least 3 "Mobalytics - ..." builds)."""
    builds = get("/v1/builds", search_name="Mobalytics", only_latest="true", limit=500, sort_by="updated_at")
    count = {}
    for x in builds:
        b = x["hero_build"]
        if b["name"].lower().startswith("mobalytics -") or b["name"].lower().endswith("by mobalytics"):
            count[b["author_account_id"]] = count.get(b["author_account_id"], 0) + 1
    official = {a for a, c in count.items() if c >= 3}
    found = [x["hero_build"] for x in builds
             if x["hero_build"]["hero_id"] == hero_id and x["hero_build"]["author_account_id"] in official
             and not x["hero_build"]["name"].lower().startswith("copy")]
    found.sort(key=lambda b: -b["last_updated_timestamp"])
    return found[:1]  # only the latest one (older ones target previous patches)


# --------------------------------------------------------------- Community

def community(hero_id, n, exclude):
    since = int(time.time()) - 120 * 86400
    seen, pool = set(), []
    for sort in ("weekly_favorites", "favorites"):
        for x in get("/v1/builds", hero_id=hero_id, sort_by=sort, only_latest="true", limit=60,
                     min_unix_timestamp=since):
            b = x["hero_build"]
            if b["hero_build_id"] in seen or b["hero_build_id"] in exclude:
                continue
            seen.add(b["hero_build_id"])
            pool.append((b, x.get("num_favorites") or 0, x.get("num_weekly_favorites") or 0))
    if not pool:
        return []
    ranks = {r["account_id"]: r.get("badge") or 0
             for r in batch("/v1/players/rank", list({b["author_account_id"] for b, _, _ in pool}))}
    scored = []
    for b, favorites, weekly in pool:
        chars = text_amount(b)
        if chars < 150:  # little or no explanation: skipped
            continue
        badge = ranks.get(b["author_account_id"], 0)
        top_favorites = max(favorites, weekly)
        if badge < 80 and top_favorites < 300:  # author below Oracle: skipped unless the build is hugely popular
            continue
        # Rank matters most; text is a capped bonus (a wall of text does not make up for a low rank).
        score = badge * 1.2 + min(chars, 1500) / 30 + 8 * math.log10(1 + top_favorites)
        scored.append((score, b, badge, top_favorites, chars))
    scored.sort(key=lambda t: -t[0])
    return scored[:n]


# ---------------------------------------------------------------------- main

def last_big_patch_since(since):
    """Move the window start to the last big patch when that patch is old enough to have data."""
    try:
        last_big = max(int(datetime.datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp())
                       for x in get("/v1/patches/big-days"))
    except Exception:
        return since
    if since < last_big <= time.time() - MIN_PATCH_DAYS * 86400:
        print(f"(games since the big patch of {datetime.date.fromtimestamp(last_big):%Y-%m-%d})")
        return last_big
    return since


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("hero")
    parser.add_argument("out")
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--otp", type=int, default=2)
    parser.add_argument("--community", type=int, default=2)
    args = parser.parse_args()
    use(CONTENT_LANG)  # builds are written and translated in the content language
    hero = find_hero(args.hero)
    since = last_big_patch_since(int(time.time()) - args.days * 86400)
    os.makedirs(args.out, exist_ok=True)
    candidates = []

    print(f"### {hero['name']} (id {hero['id']})\n")
    for player in find_otps(hero["id"], since, args.otp):
        result = otp_build(hero, player, since)
        if not result:
            continue
        build, extra = result
        key = f"otp-{player['account_id']}"
        write_candidate(f"{args.out}/{key}", build, prefill=True)
        candidates.append(dict(key=key, source="OTP", title=build["name"], author=player["name"],
                               author_id=player["account_id"], rank=rank_label(player["badge"]), badge=player["badge"],
                               matches=player["matches"], share=round(player["share"], 2), **extra,
                               language=LANG_FR, needs_translation=False))

    for b in mobalytics(hero["id"]):
        key = f"moba-{b['hero_build_id']}"
        write_candidate(f"{args.out}/{key}", b, prefill=b.get("language") == LANG_FR)
        by = b["name"].rsplit(" by ", 1)
        candidates.append(dict(key=key, source="Mobalytics", title=b["name"], build_id=b["hero_build_id"],
                               author=by[1].strip() if len(by) == 2 else "Mobalytics",
                               author_id=b["author_account_id"], updated=b["last_updated_timestamp"],
                               language=b.get("language"), needs_translation=b.get("language") != LANG_FR))

    exclude = {c.get("build_id") for c in candidates}
    for _, b, badge, favorites, chars in community(hero["id"], args.community, exclude):
        key = f"comm-{b['hero_build_id']}"
        write_candidate(f"{args.out}/{key}", b, prefill=b.get("language") == LANG_FR)
        # "Communauté" is a display value shown on the French pages.
        candidates.append(dict(key=key, source="Communauté", title=b["name"], build_id=b["hero_build_id"],
                               author_id=b["author_account_id"], rank=rank_label(badge), badge=badge,
                               favorites=favorites, text_chars=chars, updated=b["last_updated_timestamp"],
                               language=b.get("language"), needs_translation=b.get("language") != LANG_FR))

    names = {p["account_id"]: p["personaname"] for p in
             batch("/v1/players/steam", [c["author_id"] for c in candidates if "author" not in c])} if candidates else {}
    for c in candidates:
        c.setdefault("author", names.get(c["author_id"], str(c["author_id"])))
    write_json(f"{args.out}/candidates.json", {"hero": {"id": hero["id"], "name": hero["name"],
                        "image": (hero.get("images") or {}).get("icon_hero_card_webp")},
               "days": args.days, "since": since, "generated": int(time.time()), "candidates": candidates}, indent=1)

    # Compact output (read by Claude): each text appears once, numbered [n].
    for c in candidates:
        build_dir = f"{args.out}/{c['key']}"
        b = read_json(f"{build_dir}/original.json")
        strings = read_json(f"{build_dir}/strings.json")
        meta = " · ".join(str(x) for x in [c["source"], c.get("author"), c.get("rank"),
                                           c.get("matches") and f"{c['matches']} games ({round(100 * c['share'])} %)",
                                           c.get("winrate") is not None and f"{c['winrate']} % W",
                                           c.get("favorites") and f"{c['favorites']} fav"] if x)
        print(f"\n## [{c['key']}] {meta}")
        if c["source"] != "OTP":
            desc = [s for s in strings if s["path"] == ["description"]]
            if desc and desc[0]["fr"]:
                print(desc[0]["fr"][:300])
        print(summarize(b, strings))
        todo = todo_list(strings)
        if todo:
            print(f"-- To translate ({sum(1 for s in strings if not s['fr'])}):\n{todo}")
        else:  # already French: generate the code right away
            subprocess.run([sys.executable, "-I", f"{HERE}/apply.py", build_dir, "--no-clipboard"],
                           check=True, stdout=subprocess.DEVNULL)
        # English texts come for free from English authors and generated OTP texts; list the others.
        if c["source"] != "OTP" and b.get("language") != GAME_LANGUAGE["en"]:
            print(f"-- To translate into English, \"tr_en\" ({len(strings)}):\n{todo_list(strings, 'en')}")
    # Measured play style + community advice (for the "how to play" view).
    sys.stdout.flush()  # keep our output before the modules' output when piped
    for module in ANALYSIS_MODULES:
        subprocess.run([sys.executable, "-I", f"{HERE}/{module}", args.out])
    # Counter items are slow (1-2 min per OTP): run in the background, the page regenerates when done.
    subprocess.Popen([sys.executable, "-I", f"{HERE}/counters.py", args.out, "--report"],
                     stdout=open(f"{args.out}/counters.log", "w"), stderr=subprocess.STDOUT, start_new_session=True)
    print(f"\n{len(candidates)} candidates -> {args.out}/candidates.json")
    print("Next: finish.py <folder> - with {\"tr\": ..., \"intro\": ..., \"tldr\": ..., \"plan\": ..., "
          "\"sources\": ..., <key>: {resume, points}}")


if __name__ == "__main__":
    main()
