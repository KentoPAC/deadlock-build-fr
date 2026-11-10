"""Hero strengths and weaknesses: matchups and the items that beat it (to play it... or against it).

Usage: python3 -I matchups.py <search_folder>

1. Matchups (/v1/analytics/hero-counter-stats, Phantom+ games since the last big patch): the hero's win rate
   against each opponent (>= MIN_GAMES games), relative to what is expected.
2. Items that beat it (/v1/analytics/item-stats, last 14 days, Phantom+): items whose win rate rises the most
   when facing this hero, compared with their usual win rate (>= MIN_ITEM games).
Writes <folder>/matchups.json and prints a compact summary for the analysis.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import get, heroes, items, read_json, write_json  # noqa: E402
from guides import last_big_patch  # noqa: E402

MIN_GAMES = 300
MIN_ITEM = 1500
BADGE = 90
LATE_GAME_S = 1200  # "late" items: bought after 20 min


def retry(path, tries=3, **params):
    for attempt in range(tries):
        try:
            return get(path, **params)
        except Exception:
            time.sleep(3 * (attempt + 1))
    return None


def matchups(hero_id, since):
    rows = retry("/v1/analytics/hero-counter-stats", min_average_badge=BADGE, min_unix_timestamp=since,
                 same_lane_filter="false")
    if not rows:
        return None
    mine = [r for r in rows if r["hero_id"] == hero_id and r["matches_played"] >= MIN_GAMES]
    if not mine:
        return None
    # Win rate of every hero against each opponent: a real matchup is the gap to that
    # (otherwise we only see heroes that are strong or weak against everyone).
    vs_all = {}
    for r in rows:
        wins, games = vs_all.get(r["enemy_hero_id"], (0, 0))
        vs_all[r["enemy_hero_id"]] = (wins + r["wins"], games + r["matches_played"])
    base = sum(r["wins"] for r in mine) / sum(r["matches_played"] for r in mine)
    out = []
    for r in mine:
        enemy = r["enemy_hero_id"]
        winrate = r["wins"] / r["matches_played"]
        wins, games = vs_all.get(enemy, (0, 0))
        reference = wins / games if games else 0.5
        out.append({"hero": enemy, "wr": round(100 * winrate, 1), "ref": round(100 * reference, 1),
                    "delta": round(100 * (winrate - base - (reference - 0.5)), 1), "games": r["matches_played"]})
    out.sort(key=lambda x: x["delta"])
    return {"base": round(100 * base, 1), "worst": out[:5], "best": out[::-1][:5]}


def items_vs(hero_id):
    since = int(time.time()) - 14 * 86400
    # Late-game items only: bought after 20 min, tier III-IV.
    vs = retry("/v1/analytics/item-stats", enemy_hero_ids=hero_id, min_average_badge=BADGE, min_unix_timestamp=since,
               min_bought_at_s=LATE_GAME_S)
    overall = retry("/v1/analytics/item-stats", min_average_badge=BADGE, min_unix_timestamp=since,
                    min_bought_at_s=LATE_GAME_S)
    if not vs or not overall:
        return None
    base = {r["item_id"]: r["wins"] / max(1, r["wins"] + r["losses"]) for r in overall if r["matches"] >= MIN_ITEM}
    all_items = items()
    from counterplay import item_categories  # only real counter items (anti-heal, anti-tank, defences, status)
    counter_ids = {i for ids in item_categories(all_items).values() for i in ids}
    out = []
    for r in vs:
        item = r["item_id"]
        games = r["wins"] + r["losses"]
        if (item not in base or item not in counter_ids or games < MIN_ITEM // 3
                or (all_items.get(item) or {}).get("item_tier", 0) < 3):
            continue
        winrate = r["wins"] / games
        out.append({"id": item, "wr": round(100 * winrate, 1), "base": round(100 * base[item], 1),
                    "delta": round(100 * (winrate - base[item]), 1), "games": games})
    if not out:
        return []
    # Remove the common shift (a weak hero makes every item of its opponents "win" more), computed over ALL
    # late items, not only the counter items.
    deltas = sorted(round(100 * (r["wins"] / max(1, r["wins"] + r["losses"]) - base[r["item_id"]]), 1) for r in vs
                    if r["item_id"] in base and r["wins"] + r["losses"] >= MIN_ITEM // 3)
    shift = deltas[len(deltas) // 2] if deltas else 0
    for x in out:
        x["delta"] = round(x["delta"] - shift, 1)
    out = [x for x in out if x["delta"] >= 1.5]
    out.sort(key=lambda x: -x["delta"])
    return out[:8]


def main():
    folder = sys.argv[1]
    data = read_json(f"{folder}/candidates.json")
    hero_id = data["hero"]["id"]
    since = last_big_patch() or data["generated"] - 60 * 86400
    result = {"since": since, "matchups": matchups(hero_id, since), "items": items_vs(hero_id)}
    write_json(f"{folder}/matchups.json", result, indent=1)
    all_heroes, all_items = heroes(), items()

    def name(h):
        return all_heroes.get(h, {}).get("name", str(h))
    print(f"\n### Strengths / weaknesses of {data['hero']['name']} (Phantom+)")
    m = result["matchups"]
    if m:
        print(f"Overall win rate {m['base']} %. Best against: " +
              ", ".join(f"{name(x['hero'])} {x['wr']} % ({x['delta']:+} pts vs expected)" for x in m["best"]) +
              ". Worst against: " + ", ".join(f"{name(x['hero'])} {x['wr']} % ({x['delta']:+} pts)" for x in m["worst"]))
    if result["items"]:
        print("Late-game items that beat it (bought after 20 min, gain beyond the average gain): " +
              ", ".join(f"{all_items.get(x['id'], {}).get('name', x['id'])} +{x['delta']} pts" for x in result["items"]))


if __name__ == "__main__":
    main()
