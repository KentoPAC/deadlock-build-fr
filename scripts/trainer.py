"""Counter-buy trainer: real high-rank games frozen at one moment; pick the best item to buy.

Usage: python3 -I trainer.py [builds_folder] [--matches 200] [--scenarios 60]

1. Recent games (/v1/matches/metadata, average badge >= MATCH_BADGE, >= 25 min) with every player's purchases and
   their state every few minutes (souls, K/D/A, damage, healing, damage taken).
2. One moment per game (15 or 20 min) and one player whose next big purchase (>= MIN_COST souls, within
   NEXT_WINDOW s) is known: that is what the pro did.
3. Item value against each enemy hero (/v1/analytics/item-stats with enemy_hero_ids, Phantom+, items bought after
   10 min): win rate minus the item's usual win rate, minus the common shift (median), cached for a day.
4. Each option's stats score = sum over enemy heroes of (gain against that hero x threat), where the threat
   grows with the hero's souls at that moment (fed heroes weigh more: (souls / average)^2).
   Only counter items (anti-heal, anti-tank, resistances, status resistance: counterplay.py categories) that
   players of the player's hero actually buy (>= MIN_SHARE of them after 10 min) can be the best answer.
   Options: the pro's buy, the best stats item, and two plausible alternatives from the same pool.
   Answer: the best stats item scores 3 points, the pro's buy 2 (5 when they are the same item).
Writes <builds>/trainer/index.html (English) and index.fr.html; no account ids or player names are kept.
"""
import html
import json
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import get, heroes, items, rank_label, read_json, read_text, write_json, write_text  # noqa: E402
from counterplay import item_categories  # noqa: E402
from i18n import LANGS, table, use  # noqa: E402
from report import language_links, page_name  # noqa: E402
from tooltips import item_data  # noqa: E402

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_BUILDS = os.path.join(os.path.dirname(os.path.dirname(SKILL)), "..", "builds")
TEMPLATE = os.path.join(SKILL, "templates", "trainer.html")
CACHE = os.path.expanduser("~/.cache/deadlock-maxing")
MATCH_BADGE = 100        # Ascendant games
STATS_BADGE = 90         # item values: Phantom+
MOMENTS = (900, 1200)    # 15 and 20 min (the API records player states at these times)
NEXT_WINDOW = 150        # the pro's "next buy" happens within 2.5 min of the moment
MIN_COST = 1600          # tier II and above
MIN_GAMES = 400          # item buyers against an enemy hero
MID_GAME_S = 600         # item values: bought after 10 min
MIN_SHARE = 0.03         # an item fits a hero when at least 3% of its players buy it after 10 min


def matches(n, days=14):
    since = int(time.time()) - days * 86400
    return get("/v1/matches/metadata", min_average_badge=MATCH_BADGE, min_unix_timestamp=since, min_duration_s=1500,
               include_player_items="true", include_player_stats="true", include_player_info="true",
               order_by="start_time", order_direction="desc", limit=n)


def item_gains(hero_ids, days=30):
    """{enemy hero: {item: win-rate gain in points}} (cached for a day)."""
    path = os.path.join(CACHE, "trainer_gains.json")
    cached = {}
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 86400:
        cached = {int(k): {int(i): g for i, g in v.items()} for k, v in read_json(path).items()}
    since = int(time.time()) - days * 86400
    params = dict(min_average_badge=STATS_BADGE, min_unix_timestamp=since, min_bought_at_s=MID_GAME_S)
    overall = None
    for hero in sorted(set(hero_ids) - set(cached)):
        if overall is None:
            overall = {r["item_id"]: r["wins"] / max(1, r["wins"] + r["losses"])
                       for r in get("/v1/analytics/item-stats", **params) if r["wins"] + r["losses"] >= 10 * MIN_GAMES}
        rows = [(r["item_id"], r["wins"] / (r["wins"] + r["losses"]) - overall[r["item_id"]])
                for r in get("/v1/analytics/item-stats", enemy_hero_ids=hero, **params)
                if r["item_id"] in overall and r["wins"] + r["losses"] >= MIN_GAMES]
        shift = sorted(d for _, d in rows)[len(rows) // 2] if rows else 0
        cached[hero] = {i: round(100 * (d - shift), 2) for i, d in rows}
    os.makedirs(CACHE, exist_ok=True)
    write_json(path, cached)
    return cached


def hero_items(hero_ids, days=30):
    """{hero: set of items its Phantom+ players buy after 10 min (>= MIN_SHARE of them)}, cached for a day."""
    path = os.path.join(CACHE, "trainer_hero_items.json")
    cached = {}
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 86400:
        cached = {int(k): set(v) for k, v in read_json(path).items()}
    since = int(time.time()) - days * 86400
    for hero in sorted(set(hero_ids) - set(cached)):
        rows = get("/v1/analytics/item-stats", hero_id=hero, min_average_badge=STATS_BADGE, min_unix_timestamp=since,
                   min_bought_at_s=MID_GAME_S)
        games = max((r["matches"] for r in rows), default=0)  # the most bought item ~ every game of the hero
        cached[hero] = {r["item_id"] for r in rows if games and r["matches"] / games >= MIN_SHARE}
    os.makedirs(CACHE, exist_ok=True)
    write_json(path, {h: sorted(v) for h, v in cached.items()})
    return cached


def state_at(player, t):
    """The player's recorded state at time t (souls, K/D/A, damage, healing, damage taken)."""
    snap = next((s for s in player.get("stats") or [] if s["time_stamp_s"] == t), None)
    if not snap:
        return None
    return {"souls": snap["net_worth"], "k": snap["kills"], "d": snap["deaths"], "a": snap["assists"],
            "dmg": snap.get("player_damage", 0), "heal": snap.get("player_healing", 0) + snap.get("self_healing", 0),
            "taken": snap.get("player_damage_taken", 0)}


def held_items(player, t, shop):
    """Shop items owned at time t (bought before, not sold yet)."""
    return [i["item_id"] for i in player.get("items") or []
            if i["item_id"] in shop and i["game_time_s"] <= t and not (0 < i["sold_time_s"] <= t)]


def next_buy(player, t, shop):
    """The first purchase of at least MIN_COST souls within NEXT_WINDOW seconds after t."""
    for i in sorted(player.get("items") or [], key=lambda x: x["game_time_s"]):
        if t < i["game_time_s"] <= t + NEXT_WINDOW and shop.get(i["item_id"], {}).get("cost", 0) >= MIN_COST:
            return i["item_id"]
    return None


def threats(enemies):
    """{hero: weight}: (souls / average souls)^2, normalised (the fed heroes weigh the most)."""
    avg = sum(e["souls"] for e in enemies) / len(enemies)
    raw = {e["hero"]: (e["souls"] / avg) ** 2 for e in enemies}
    total = sum(raw.values())
    return {h: w / total for h, w in raw.items()}


def scenario(match, rng, shop, gains, categories, fits):
    t = rng.choice(MOMENTS)
    players = match["players"]
    candidates = [p for p in players if next_buy(p, t, shop) and state_at(p, t)]
    if not candidates or any(not state_at(p, t) for p in players):
        return None
    me = rng.choice(candidates)
    pro = next_buy(me, t, shop)
    table_ = []
    for p in players:
        s = state_at(p, t)
        table_.append(dict(s, hero=p["hero_id"], ally=p["team"] == me["team"], me=p is me,
                           items=held_items(p, t, shop)))
    enemies = [x for x in table_ if not x["ally"]]
    weights = threats(enemies)
    owned = set(next(x for x in table_ if x["me"])["items"])
    cost = shop[pro]["cost"]

    def score(item):
        return sum(w * gains.get(h, {}).get(item, 0) for h, w in weights.items())
    counters = {i for ids in categories.values() for i in ids}
    mine = fits.get(me["hero_id"], set())
    pool = [i for i in counters & mine if i not in owned and i != pro and shop[i]["cost"] >= MIN_COST
            and any(i in gains.get(h, {}) for h in weights)]
    if len(pool) < 3:
        return None
    ranked = sorted(pool, key=score, reverse=True)
    if score(ranked[0]) <= 0:
        return None
    best = score(pro) > score(ranked[0]) and pro in counters and pro or ranked[0]
    options = [pro] + [i for i in (best,) if i != pro]
    # alternatives: one middling and one weak item against this team, of a similar price
    similar = [i for i in ranked if i not in options and abs(shop[i]["cost"] - cost) <= 1600]
    third = len(similar) // 3
    for pick in (similar[third:2 * third], similar[2 * third:]):
        if pick and len(options) < 4:
            options.append(rng.choice(pick))
    for i in ranked:
        if len(options) >= 4:
            break
        if i not in options:
            options.append(i)
    rng.shuffle(options)
    # why the best item: the enemy hero that contributes the most, and the item's counter category
    top_enemy = max(weights, key=lambda h: weights[h] * gains.get(h, {}).get(best, 0))
    category = next((c for c, ids in categories.items() if best in ids), None)
    return {"t": t, "won": match["winning_team"] == me["team"], "badge": match.get("average_badge"),
            "players": table_, "options": [{"id": i, "score": round(score(i), 2)} for i in options],
            "best": best, "pro": pro, "why": {"hero": top_enemy, "gain": gains[top_enemy].get(best, 0),
                                              "share": round(100 * weights[top_enemy]), "cat": category}}


def build(root, n_matches, n_scenarios, seed=None):
    use("en")
    shop = {i: it for i, it in items().items() if it.get("type") == "upgrade" and it.get("shopable")}
    games = matches(n_matches)
    print(f"{len(games)} games")
    all_heroes = {p["hero_id"] for g in games for p in g["players"]}
    gains = item_gains(all_heroes)
    fits = hero_items(all_heroes)
    categories = item_categories(shop)
    rng = random.Random(seed)
    out = []
    for g in games:
        s = scenario(g, rng, shop, gains, categories, fits)
        if s:
            out.append(s)
        if len(out) >= n_scenarios:
            break
    print(f"{len(out)} scenarios")
    return out, shop


def page(root, scenarios, lang):
    """trainer/index.html (English) or index.<lang>.html, with heroes and item tooltips in that language."""
    use(lang)
    all_items, all_heroes = items(), heroes()
    used = {i for s in scenarios for p in s["players"] for i in p["items"]} | {o["id"] for s in scenarios for o in s["options"]}
    hero_cards = {h: {"n": all_heroes.get(h, {}).get("name", str(h)),
                      "img": ((all_heroes.get(h) or {}).get("images") or {}).get("icon_image_small_webp")}
                  for h in {p["hero"] for s in scenarios for p in s["players"]}}
    data = {"scenarios": [dict(s, rank=rank_label(s["badge"]) if s.get("badge") else "") for s in scenarios],
            "items": item_data(all_items, used), "heroes": hero_cards}
    ui = table("ui")
    out = re.sub(r"\{\{ui:([\w.]+)\}\}", lambda m: html.escape(ui[m[1]]), read_text(TEMPLATE))
    for key, value in {"__LANG__": lang, "__LANG_LINKS__": language_links(lang), "__HOME__": page_name(lang),
                       "__UI__": json.dumps(ui, ensure_ascii=False).replace("</", "<\\/"),
                       "__DATA__": json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")}.items():
        out = out.replace(key, value)
    path = f"{root}/trainer/{page_name(lang)}"
    write_text(path, out)
    return path


def main():
    args = sys.argv[1:]
    opt = {a.lstrip("-"): int(b) for a, b in zip(args, args[1:]) if a.startswith("--")}
    root = os.path.abspath(next((a for a in args if not a.startswith("--") and not a.isdigit()), PROJECT_BUILDS))
    scenarios, shop = build(root, opt.get("matches", 200), opt.get("scenarios", 60), opt.get("seed"))
    os.makedirs(f"{root}/trainer", exist_ok=True)
    write_json(f"{root}/trainer/scenarios.json", scenarios)
    for lang in LANGS:
        print(f"Trainer ({lang}): {page(root, scenarios, lang)}")


if __name__ == "__main__":
    main()
