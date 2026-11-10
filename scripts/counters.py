"""OTP counter items: which situational items they buy more often depending on the enemy hero.

Usage: python3 -I counters.py <search_folder> [--otp 2] [--report]

For each OTP (the first --otp ones), queries /v1/analytics/item-stats filtered by enemy hero (one call per hero,
~7 s each, in parallel) and compares the purchase rate of their situational items (bought in 10-80% of their
games) against that hero with their overall rate. Keeps clear gaps only: >= MIN_GAMES games against the hero,
+10 points and >= 2.2 standard deviations.
Writes <folder>/<key>/counters.json; --report regenerates the page at the end.
Slow (1-2 min per player): find.py runs it in the background.
"""
import concurrent.futures
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import get, heroes, read_json, write_json  # noqa: E402

MIN_GAMES = 15
MIN_DIFF = 0.10  # at least +10 points
MIN_Z = 2.2      # and a clear gap given the number of games (limits false positives)
SITUATIONAL = (0.10, 0.80)


def stats(hero_id, account, since, enemy=None, tries=5):
    params = dict(hero_id=hero_id, account_id=account, min_unix_timestamp=since)
    if enemy:
        params["enemy_hero_ids"] = enemy
    for attempt in range(tries):
        try:
            return get("/v1/analytics/item-stats", **params)
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


def analyse(hero_id, account, since, hero_ids):
    base = stats(hero_id, account, since)
    if not base:
        return None
    n = max(s["matches"] for s in base)
    situational = {s["item_id"]: s["matches"] / n for s in base if SITUATIONAL[0] <= s["matches"] / n <= SITUATIONAL[1]}
    if not situational:
        return []
    per_enemy = {}
    with concurrent.futures.ThreadPoolExecutor(6) as pool:
        futures = {e: pool.submit(stats, hero_id, account, since, e) for e in hero_ids if e != hero_id}
        for enemy, future in futures.items():
            rows = future.result()
            if rows:
                per_enemy[enemy] = rows
    found = {}
    for enemy, rows in per_enemy.items():
        games = max((s["matches"] for s in rows), default=0)
        if games < MIN_GAMES:
            continue
        for s in rows:
            item = s["item_id"]
            if item not in situational:
                continue
            rate, p0 = s["matches"] / games, situational[item]
            z = (rate - p0) / max(1e-9, (p0 * (1 - p0) / games) ** 0.5)  # gap in standard deviations (binomial)
            if rate - p0 >= MIN_DIFF and z >= MIN_Z:
                found.setdefault(item, {"id": item, "base": round(100 * p0), "vs": []})["vs"].append(
                    {"hero": enemy, "rate": round(100 * rate), "games": games, "z": round(z, 1)})
    out = []
    for v in found.values():
        v["vs"].sort(key=lambda x: -(x["rate"] - v["base"]))
        v["vs"] = v["vs"][:5]
        out.append(v)
    out.sort(key=lambda v: -max(x["rate"] - v["base"] for x in v["vs"]))
    return out


def main():
    folder = sys.argv[1]
    count = int(sys.argv[sys.argv.index("--otp") + 1]) if "--otp" in sys.argv else 2
    data = read_json(f"{folder}/candidates.json")
    hero_id = data["hero"]["id"]
    since = data.get("since") or data["generated"] - data["days"] * 86400
    playable = {i: h for i, h in heroes().items() if h.get("player_selectable") and not h.get("disabled")}
    for c in [c for c in data["candidates"] if c["source"] == "OTP"][:count]:
        start = time.time()
        result = analyse(hero_id, c["author_id"], since, list(playable))
        if result is None:
            print(f"[{c['key']}] item-stats unavailable")
            continue
        write_json(f"{folder}/{c['key']}/counters.json", {"since": since, "items": result})
        print(f"[{c['key']}] {c.get('author')}: {len(result)} counter items ({time.time() - start:.0f} s)")
        for v in result[:6]:
            vs = ", ".join(f"{playable.get(x['hero'], {}).get('name', x['hero'])} {x['rate']}% ({x['games']} g.)" for x in v["vs"])
            print(f"   item {v['id']} (overall {v['base']}%) -> {vs}")
    if "--report" in sys.argv:
        subprocess.run([sys.executable, "-I", os.path.join(os.path.dirname(os.path.abspath(__file__)), "report.py"), folder],
                       stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
