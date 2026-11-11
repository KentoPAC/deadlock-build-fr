"""Measured play style (lane / jungle farm, fights, objectives) of the players behind a search.

Usage: python3 -I playstyle.py <search_folder>

For every candidate whose author plays the hero enough (OTPs, and community build authors with
>= MIN_MATCHES games in the window), reads their average minute-by-minute curve
(/v1/analytics/player-performance-curve) and compares it with the Phantom+ average on that hero.
Writes <folder>/<key>/playstyle.json and <folder>/baseline.json, and prints a compact summary.
"""
import concurrent.futures
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import get, read_json, write_json  # noqa: E402

PHASES = [("Early", 0, 540), ("Mid", 540, 1200), ("Late", 1200, 1800)]  # game seconds
MIN_MATCHES = 10    # non-OTP authors: fewer games than that on the hero = no measure
SMALL_SAMPLE = 20   # below this, the page flags the measure as a small sample
FOCUS_GAP = 1.15    # a phase leans towards lane / jungle / fights / objectives when >= 15% above the average
BASE_BADGE = 90  # reference average: Phantom+ games
SOURCES = {  # where the souls come from
    "lane": ["gold_lane_creep", "gold_denied"],
    "jungle": ["gold_neutral_creep", "gold_breakable", "gold_treasure"],
    "fights": ["gold_player", "gold_assists"],
    "obj": ["gold_boss"],
}
STATS = ["net_worth", "kills", "deaths", "assists", "player_damage", "boss_damage", "neutral_damage", "denies"]


def curve(hero_id, since, account=None, badge=None, tries=4):
    """{game_second: averaged point}, or None when the API keeps failing."""
    params = dict(hero_ids=hero_id, min_unix_timestamp=since, resolution=0)
    if account:
        params["account_ids"] = account
    if badge:
        params["min_average_badge"] = badge
    for attempt in range(tries):
        try:
            points = get("/v1/analytics/player-performance-curve", **params)
            return {int(p["game_time"]): p for p in points}
        except Exception:  # frequent 504s: retry
            time.sleep(3 * (attempt + 1))
    return None


def value_at(points, t, key):
    if t == 0:
        return 0.0
    point = points.get(t)
    return float(point.get(key + "_avg") or 0) if point else None


def phases(points):
    """Per phase: souls/min, share per source, per-minute stats."""
    out = []
    for name, start, end in PHASES:
        if end not in points:
            continue
        minutes = (end - start) / 60
        delta = {k: (value_at(points, end, k) - value_at(points, start, k)) / minutes for k in STATS}
        sources = {s: sum((value_at(points, end, k) or 0) - (value_at(points, start, k) or 0) for k in keys) / minutes
                   for s, keys in SOURCES.items()}
        total = sum(sources.values()) or 1
        out.append({"name": name, "from": start // 60, "to": end // 60, "spm": round(delta["net_worth"]),
                    "src": {s: round(100 * v / total) for s, v in sources.items()},
                    "src_spm": {s: round(v) for s, v in sources.items()},
                    "kpm": round(delta["kills"] * 10, 2), "dpm": round(delta["deaths"] * 10, 2),
                    "apm": round(delta["assists"] * 10, 2), "hero_dmg": round(delta["player_damage"]),
                    "obj_dmg": round(delta["boss_damage"]), "denies": round(delta["denies"] * 10, 2)})
    return out


def ratio(player, base, key, sub=None, idx=None):
    """Player / baseline ratio of a phase stat, summed over the selected phases."""
    def value(phase):
        return phase[key] if sub is None else phase[key][sub]
    player_phases = [x for i, x in enumerate(player) if idx is None or i in idx]
    base_phases = [x for i, x in enumerate(base) if idx is None or i in idx]
    if not player_phases or not base_phases:
        return None
    player_value, base_value = sum(map(value, player_phases)), sum(map(value, base_phases))
    return player_value / base_value if base_value else None


def tags(player, base):
    """Style tag ids from the gap to the Phantom+ average (deliberately clear-cut thresholds).
    Labels come from the locale ("style_tags") when the page is rendered."""
    out = []

    def r(*args, **kwargs):
        return ratio(player, base, *args, **kwargs) or 1.0
    early_fight = (r("kpm", idx=[0]) + r("apm", idx=[0])) / 2
    if early_fight >= 1.3 or r("denies", idx=[0]) >= 1.5:
        out.append("lane_aggressive")
    elif early_fight <= 0.7:
        out.append("lane_passive")
    if r("src_spm", "jungle", idx=[1, 2]) >= 1.25:
        out.append("jungle_farmer")
    objectives = r("obj_dmg", idx=[1, 2])
    team = r("apm", idx=[1, 2])
    if objectives >= 1.3 and team <= 0.95:
        out.append("split_pusher")
    elif objectives >= 1.3:
        out.append("pushes_objectives")
    if team >= 1.25:
        out.append("teamfight")
    deaths = r("dpm")
    if deaths <= 0.8:
        out.append("dies_little")
    elif deaths >= 1.25:
        out.append("takes_risks")
    if r("hero_dmg") >= 1.2:
        out.append("hero_damage")
    if r("spm") >= 1.1:
        out.append("farm_above")
    elif r("spm") <= 0.9:
        out.append("farm_below")
    return out


def focus(player, base):
    """Per phase, what the player does clearly more than the Phantom+ average (at most two, strongest first):
    "lane" / "jungle" farm, "fights" (kills + assists) or "objectives". No lean = balanced phase.
    [{"phase", "lean": [{"k", "gap" (% above the average)}]}]; labels come from the locale ("focus")."""
    def gap(value, average):
        return value / average if average else 1.0
    out = []
    for p, b in zip(player, base):
        scores = {"lane": gap(p["src_spm"]["lane"], b["src_spm"]["lane"]),
                  "jungle": gap(p["src_spm"]["jungle"], b["src_spm"]["jungle"]),
                  "fights": gap(p["kpm"] + p["apm"], b["kpm"] + b["apm"]),
                  "objectives": gap(p["obj_dmg"], b["obj_dmg"])}
        lean = sorted((k for k, v in scores.items() if v >= FOCUS_GAP), key=scores.get, reverse=True)[:2]
        out.append({"phase": p["name"], "lean": [{"k": k, "gap": round(100 * (scores[k] - 1))} for k in lean]})
    return out


def matches_on_hero(ids, hero_id, since):
    out = {}
    for x in get("/v1/players/hero-stats", account_ids=",".join(map(str, ids)), min_unix_timestamp=since):
        if x.get("hero_id") == hero_id:
            out[x["account_id"]] = x.get("matches_played", 0)
    return out


def format_phase(phase, base=None):
    s = phase["src"]
    line = (f"{phase['name']} {phase['from']}-{phase['to']}m: {phase['spm']} souls/min (lane {s['lane']}% jungle {s['jungle']}% "
            f"fights {s['fights']}% obj {s['obj']}%) K/D/A per 10 min {phase['kpm']}/{phase['dpm']}/{phase['apm']} "
            f"hero damage {phase['hero_dmg']}/min obj {phase['obj_dmg']}/min")
    if base:
        line += (f" | avg {base['spm']} souls/min, jungle {base['src']['jungle']}%, "
                 f"K/D/A {base['kpm']}/{base['dpm']}/{base['apm']}")
    return line


def main():
    folder = sys.argv[1]
    data = read_json(f"{folder}/candidates.json")
    hero_id = data["hero"]["id"]
    since = data.get("since") or data["generated"] - data["days"] * 86400
    candidates = data["candidates"]

    wanted = {c["key"]: c["author_id"] for c in candidates if c["source"] == "OTP"}
    games = {c["key"]: c.get("matches") for c in candidates if c["source"] == "OTP"}
    others = {c["key"]: c["author_id"] for c in candidates if c["source"] != "OTP" and c.get("author_id")}
    if others:
        played = matches_on_hero(list(set(others.values())), hero_id, since)
        wanted.update({k: a for k, a in others.items() if played.get(a, 0) >= MIN_MATCHES})
        games.update({k: played.get(a, 0) for k, a in others.items()})

    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        base_future = pool.submit(curve, hero_id, since, None, BASE_BADGE)
        futures = {k: pool.submit(curve, hero_id, since, a) for k, a in wanted.items()}
        base_curve = base_future.result()
        curves = {k: f.result() for k, f in futures.items()}
    if not base_curve:
        print("Play style: hero average unavailable (API), section skipped")
        return
    base = phases(base_curve)
    write_json(f"{folder}/baseline.json", {"phases": base, "badge": BASE_BADGE, "since": since})
    print("\n### Measured play style (vs Phantom+ average on the hero)")
    for c in candidates:
        key = c["key"]
        if key not in wanted:
            continue
        if not curves.get(key):
            print(f"[{key}] curve unavailable")
            continue
        player = phases(curves[key])
        style = tags(player, base)
        phase_focus = focus(player, base)
        net_worth = [[t // 60, round(float(v.get("net_worth_avg") or 0))] for t, v in sorted(curves[key].items())]
        write_json(f"{folder}/{key}/playstyle.json", {"phases": player, "tags": style, "focus": phase_focus,
                                                      "matches": games.get(key), "nw": net_worth})
        small = " (small sample)" if (games.get(key) or 0) < SMALL_SAMPLE else ""
        print(f"[{key}] {c.get('author')} — {games.get(key)} games{small} — {', '.join(style) or 'close to the average'}")
        print("  focus: " + " · ".join(f"{f['phase']} " + (", ".join(f"{x['k']} +{x['gap']}%" for x in f["lean"]) or "balanced")
                                       for f in phase_focus))
        for phase, base_phase in zip(player, base):
            print("  " + format_phase(phase, base_phase))


if __name__ == "__main__":
    main()
