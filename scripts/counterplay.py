"""Late-game counterplay: which item to buy depending on the enemy team (healers, tanks, spirit, gun, crowd control).

Usage: python3 -I counterplay.py <search_folder>

1. Enemy hero profiles (/v1/analytics/player-stats/metrics bucket=hero, Phantom+, 14 days; cached for a day):
   big healers (healing/min), tanks (damage taken/min); game class (mystic = spirit damage,
   marksman = gun damage).
2. Counter items classified by their technical properties in the API (not by keywords, so it holds from one
   patch to the next): anti-heal, % HP / resistance shred (anti-tank), spirit resist, bullet resist, status resist.
3. For THIS hero: keep the ones its players actually buy (purchase rate), to match its build.
Writes <folder>/counterplay.json and prints a summary.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import get, heroes, items, read_json, write_json  # noqa: E402

CACHE = os.path.expanduser("~/.cache/deadlock-maxing")
BADGE = 90
# category -> technical properties that define it (non-zero value)
CATEGORIES = {
    "antiheal": ["HealAmpReceivePenaltyPercent"],
    "antitank": ["CurrentHealthDamage", "MaxHealthPercentAsDPS", "MaxHealthDamage", "MaxHPDamage", "HealthPctDamage",
                 "DotHealthPercent", "BulletResistReduction", "BulletArmorReduction", "MagicResistReduction",
                 "TechArmorDamageReduction"],
    "spiritdef": ["TechResist", "TechResistBelowThreshold", "TechPowerReduction"],
    "bulletdef": ["BulletResist", "BulletResistBelowThreshold", "FireRateSlow"],
    "status": ["StatusResistancePercent"],
}
# Items whose healing penalty applies to their owner: not an anti-heal.
SELF_PENALTY = {"upgrade_cheat_death"}
# Outside vitality items, a small resistance does not make a defensive item: only the "counter" effects count
# (reducing enemy spirit power / fire rate).
DEFENSIVE_OUTSIDE_VITALITY = {"spiritdef": ["TechPowerReduction"], "bulletdef": ["FireRateSlow"], "status": []}


def nonzero(prop):
    value = (prop or {}).get("value")
    try:
        return float(str(value).split()[0]) != 0
    except (TypeError, ValueError):
        return False


def item_categories(all_items):
    """{category: [item ids]} for every shop item."""
    out = {k: [] for k in CATEGORIES}
    for item in all_items.values():
        if item.get("type") != "upgrade" or not item.get("shopable") or item.get("class_name") in SELF_PENALTY:
            continue
        props = item.get("properties") or {}
        for category, keys in CATEGORIES.items():
            if category in DEFENSIVE_OUTSIDE_VITALITY and item.get("item_slot_type") != "vitality":
                keys = DEFENSIVE_OUTSIDE_VITALITY[category]
            if any(nonzero(props.get(k)) for k in keys):
                out[category].append(item["id"])
    return out


def profiles():
    """{hero_id: {"heal", "taken", "dmg"}} per-minute averages (Phantom+, 14 days), cached for a day."""
    path = os.path.join(CACHE, "hero_profiles.json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 86400:
        return {int(k): v for k, v in read_json(path).items()}
    rows = get("/v1/analytics/player-stats/metrics", bucket="hero", min_average_badge=BADGE,
               min_unix_timestamp=int(time.time()) - 14 * 86400)
    out = {}
    pairs = rows.items() if isinstance(rows, dict) else ((r.get("bucket"), r) for r in rows)  # list [{bucket: hero_id, ...}]
    for hero_id, metrics in pairs:
        def avg(key):
            return (metrics.get(key) or {}).get("avg") or 0
        try:
            out[int(hero_id)] = {"heal": avg("healing_per_min") + avg("teammate_healing") / 30,
                                 "taken": avg("player_damage_taken_per_min"), "dmg": avg("player_damage_per_min")}
        except ValueError:
            continue
    os.makedirs(CACHE, exist_ok=True)
    write_json(path, out)
    return out


def top(profile, key, fraction=0.25):
    ranked = sorted(profile.items(), key=lambda x: -x[1][key])
    return [h for h, _ in ranked[:max(3, int(len(ranked) * fraction))]]


def main():
    folder = sys.argv[1]
    data = read_json(f"{folder}/candidates.json")
    hero_id = data["hero"]["id"]
    all_items, all_heroes = items(), heroes()
    try:
        all_profiles = profiles()
    except Exception as e:
        print(f"Counterplay: profiles unavailable ({e})")
        return
    playable = {i for i, h in all_heroes.items() if h.get("player_selectable") and not h.get("disabled")}
    enemies = {h: v for h, v in all_profiles.items() if h in playable and h != hero_id}
    try:
        english = {h["id"]: h for h in get("/v1/assets/heroes")}
    except Exception:
        english = {}
    try:
        mine = get("/v1/analytics/item-stats", hero_id=hero_id, min_average_badge=BADGE,
                   min_unix_timestamp=int(time.time()) - 21 * 86400)
        most = max(r["matches"] for r in mine)
        purchase_rate = {r["item_id"]: r["matches"] / most for r in mine}
    except Exception:
        purchase_rate = {}
    categories = item_categories(all_items)

    def pick(category, k=3):
        ids = sorted(categories[category], key=lambda i: (-purchase_rate.get(i, 0), -(all_items[i].get("item_tier") or 0)))
        bought = [{"id": i, "rate": round(100 * purchase_rate.get(i, 0))} for i in ids if purchase_rate.get(i, 0) >= 0.02]
        return bought[:k] or [{"id": i, "rate": 0} for i in ids[:k]]

    def by_type(hero_type):
        return sorted([h for h in enemies if (english.get(h) or {}).get("hero_type") == hero_type],
                      key=lambda h: -enemies[h]["dmg"])[:6]
    rules = [
        {"when": "heal", "heroes": top(enemies, "heal")[:6], "cat": "antiheal", "items": pick("antiheal")},
        {"when": "tank", "heroes": top(enemies, "taken")[:6], "cat": "antitank", "items": pick("antitank")},
        {"when": "spirit", "heroes": by_type("mystic"), "cat": "spiritdef", "items": pick("spiritdef")},
        {"when": "weapon", "heroes": by_type("marksman"), "cat": "bulletdef", "items": pick("bulletdef")},
        {"when": "cc", "heroes": [], "cat": "status", "items": pick("status", 2)},
    ]

    # --- Against this hero: its measured traits -> counter category -> most played late items (all heroes)
    me = all_profiles.get(hero_id) or {}

    def percentile(key):
        return round(100 * sum(v[key] < me.get(key, 0) for v in all_profiles.values()) / max(1, len(all_profiles) - 1))
    try:
        late = get("/v1/analytics/item-stats", min_average_badge=BADGE, min_unix_timestamp=int(time.time()) - 14 * 86400,
                   min_bought_at_s=1200)
        popularity = {r["item_id"]: r["matches"] for r in late}
    except Exception:
        popularity = {}

    def popular(category, k=3):
        ids = [i for i in categories[category] if (all_items[i].get("item_tier") or 0) >= 3]
        return [{"id": i, "rate": 0} for i in sorted(ids, key=lambda i: -popularity.get(i, 0))[:k]]
    hero_type = (english.get(hero_id) or {}).get("hero_type")
    against = []
    if me and percentile("heal") >= 70:
        against.append({"why": "heal", "pct": percentile("heal"), "cat": "antiheal", "items": popular("antiheal")})
    if me and percentile("taken") >= 70:
        against.append({"why": "tank", "pct": percentile("taken"), "cat": "antitank", "items": popular("antitank")})
    if hero_type == "mystic":
        against.append({"why": "spirit", "cat": "spiritdef", "items": popular("spiritdef")})
    elif hero_type == "marksman":
        against.append({"why": "weapon", "cat": "bulletdef", "items": popular("bulletdef")})
    elif me and percentile("dmg") >= 60:
        against.append({"why": "burst", "pct": percentile("dmg"), "cat": "spiritdef",
                        "items": popular("spiritdef", 2) + popular("bulletdef", 2)})
    profile = {k: percentile(k) for k in ("heal", "taken", "dmg")} if me else None
    write_json(f"{folder}/counterplay.json", {"rules": rules, "against": against, "profile": profile})

    print("Against it: " + "; ".join(f"{a['why']} -> " + ", ".join(all_items[x['id']]['name'] for x in a["items"])
                                     for a in against))

    def name(h):
        return all_heroes.get(h, {}).get("name", str(h))
    print(f"\n### Late-game counterplay for {data['hero']['name']}")
    for r in rules:
        print(f"[{r['when']}] {', '.join(map(name, r['heroes'])) or '—'} -> " +
              ", ".join(f"{all_items[x['id']]['name']} ({x['rate']} %)" for x in r["items"]))


if __name__ == "__main__":
    main()
