"""Who and what wins the lane against the hero.

Usage: python3 -I laning.py <search_folder>

/v1/analytics/lane-matchup-stats (Phantom+ games since the search window start), duos that include the hero,
grouped by enemy duo. For each enemy hero (in >= MIN_LANES lanes), the soul lead of the hero's duo at
SAMPLE_S seconds compared with its average lead over every lane: negative = that hero wins the lane against it.
Each enemy duo counts for both of its heroes, so a partner's effect is averaged out over many duos.
Ranked on the real gap (what the hero's player will face). Each enemy hero's general lane strength (its duos'
average soul lead against everyone) is kept alongside, so the page can say when it wins the lane against most heroes.
Lane items (/v1/analytics/item-stats, same_lane_filter): win rate of the items bought before SAMPLE_S by players
laning against the hero, minus their usual win rate when bought that early, minus the common shift; only gaps
of at least MIN_ITEM_GAP points and Z_MIN standard errors are "solid"; when fewer than SHOWN_ITEMS are, the best
gaps of at least MIN_TREND_GAP points and Z_TREND standard errors fill in as "trends" (flagged as uncertain on the page).
Writes <folder>/laning.json and prints a compact summary for the analysis.
"""
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import get, heroes, items, read_json, write_json  # noqa: E402

SAMPLE_S = 540     # 9 min: end of the laning phase
BADGE = 90         # Phantom+
MIN_LANES = 300    # lanes against an enemy hero before it is shown
MIN_GAP = 150      # souls: smaller gaps are noise at this sample size
SHOWN = 5
MIN_ITEM_GAMES = 400   # lane buyers of an item against the hero
MIN_ITEM_GAP = 1.5     # win-rate points
Z_MIN = 2.0            # gap / standard error
Z_TREND = 1.0          # weaker gaps, shown as trends...
MIN_TREND_GAP = 1.0    # ...when they are big enough to matter in game
SHOWN_ITEMS = 4


def lane_rows(hero_id, since, tries=3):
    for attempt in range(tries):
        try:
            return get("/v1/analytics/lane-matchup-stats", hero_ids=hero_id, group_by="enemy_hero_ids",
                       sample_time_s=SAMPLE_S, min_average_badge=BADGE, min_unix_timestamp=since,
                       stats="kills,deaths")
        except Exception:
            time.sleep(3 * (attempt + 1))
    return None


def lane_strength(since):
    """{hero: average soul lead of the duos it belongs to, against every opponent} (general lane strength)."""
    try:
        rows = get("/v1/analytics/lane-matchup-stats", group_by="hero_ids", sample_time_s=SAMPLE_S,
                   min_average_badge=BADGE, min_unix_timestamp=since)
    except Exception:
        return {}
    acc = {}
    for r in rows:
        for h in r["hero_ids"]:
            a = acc.setdefault(h, [0, 0.0])
            a[0] += r["sample_matches"]
            a[1] += r["net_worth_diff"] * r["sample_matches"]
    return {h: s / n for h, (n, s) in acc.items() if n}


def lane_items(hero_id, since):
    """Items bought before SAMPLE_S in lane against the hero that win clearly more than usual."""
    params = dict(min_average_badge=BADGE, min_unix_timestamp=since, max_bought_at_s=SAMPLE_S)
    try:
        vs = get("/v1/analytics/item-stats", enemy_hero_ids=hero_id, same_lane_filter="true", **params)
        overall = get("/v1/analytics/item-stats", **params)
    except Exception:
        return None
    base = {r["item_id"]: r["wins"] / max(1, r["wins"] + r["losses"]) for r in overall
            if r["wins"] + r["losses"] >= 10 * MIN_ITEM_GAMES}
    rows = []
    for r in vs:
        games = r["wins"] + r["losses"]
        if r["item_id"] in base and games >= MIN_ITEM_GAMES:
            rows.append((r["item_id"], games, r["wins"] / games - base[r["item_id"]], base[r["item_id"]]))
    if not rows:
        return []
    # a hero that loses many lanes makes every item of its opponents "win" more: remove the median shift
    shift = sorted(d for _, _, d, _ in rows)[len(rows) // 2]
    solid, trends = [], []
    for item, games, delta, p in rows:
        gap = delta - shift
        z = gap / math.sqrt(p * (1 - p) / games)
        entry = {"id": item, "delta": round(100 * gap, 1), "games": games, "z": round(z, 1)}
        if 100 * gap >= MIN_ITEM_GAP and z >= Z_MIN:
            solid.append(dict(entry, solid=True))
        elif 100 * gap >= MIN_TREND_GAP and z >= Z_TREND:
            trends.append(dict(entry, solid=False))
    solid.sort(key=lambda x: -x["delta"])
    trends.sort(key=lambda x: -x["delta"])
    return solid[:SHOWN_ITEMS] + trends[:max(0, SHOWN_ITEMS - len(solid))]


def by_enemy(hero_id, rows, strength=None):
    """Average soul lead of the hero's duo, overall and against each enemy hero (gap to the usual lead, with the
    enemy's general lane strength removed when known)."""
    strength = strength or {}
    total = sum(r["sample_matches"] for r in rows)
    if not total:
        return None
    base = sum(r["net_worth_diff"] * r["sample_matches"] for r in rows) / total
    acc = {}
    for r in rows:
        n = r["sample_matches"]
        kd = (r["stats"]["kills"]["diff"] - r["stats"]["deaths"]["diff"]) if r.get("stats") else 0
        for enemy in r["enemy_hero_ids"]:
            if enemy == hero_id:
                continue
            a = acc.setdefault(enemy, [0, 0.0, 0.0])
            a[0] += n
            a[1] += r["net_worth_diff"] * n
            a[2] += kd * n
    enemies = [{"hero": h, "lanes": n, "souls": round(s / n - base), "general": round(strength[h]) if h in strength else None,
                "kd": round(k / n, 2)} for h, (n, s, k) in acc.items() if n >= MIN_LANES]
    return {"sample_s": SAMPLE_S, "lanes": total, "base": round(base),
            "beaten_by": sorted([e for e in enemies if e["souls"] <= -MIN_GAP], key=lambda e: e["souls"])[:SHOWN],
            "beats": sorted([e for e in enemies if e["souls"] >= MIN_GAP], key=lambda e: -e["souls"])[:SHOWN]}


def main():
    folder = sys.argv[1]
    data = read_json(f"{folder}/candidates.json")
    hero_id = data["hero"]["id"]
    since = data.get("since") or data["generated"] - data["days"] * 86400
    rows = lane_rows(hero_id, since)
    result = by_enemy(hero_id, rows or [], lane_strength(since))
    if not result:
        print("Lanes: no data (API)")
        return
    result["items"] = lane_items(hero_id, since)
    write_json(f"{folder}/laning.json", dict(result, since=since))
    names = {h: x["name"] for h, x in heroes().items()}
    fmt = lambda e: f"{names.get(e['hero'], e['hero'])} {e['souls']:+} souls (usual lead {e['general'] if e['general'] is not None else '?'}, K-D {e['kd']:+}, {e['lanes']} lanes)"  # noqa: E731
    print(f"\n### Lanes at {SAMPLE_S // 60} min (soul lead of the hero's duo vs its average {result['base']:+}, "
          f"{result['lanes']} lanes)")
    print("Win the lane against it: " + (", ".join(map(fmt, result["beaten_by"])) or "none"))
    print("Lose the lane against it: " + (", ".join(map(fmt, result["beats"])) or "none"))
    all_items = items()
    print("Items bought in lane against it that win more (before 9 min, gain beyond the usual gain): " +
          (", ".join(f"{all_items.get(x['id'], {}).get('name', x['id'])} +{x['delta']} pts ({x['games']} games"
                     f"{'' if x['solid'] else ', trend: uncertain'})"
                     for x in result["items"] or []) or "none"))


if __name__ == "__main__":
    main()
