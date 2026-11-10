"""Hero role: official class, community meta position (1 to 6) and statistical profile.

Usage: python3 -I roles.py <search_folder>

1. Game class (hero_type: mystic, brawler, assassin, marksman).
2. Community position(s): the most recent Steam "positions / roles" guide (updated since the last big patch),
   in the "1 Hard Carry ... Heroes: A, B, C." format; keeps the job described for every position the hero is in.
3. Statistical profile: the hero's per-game averages compared with every hero (Phantom+ games since the last
   big patch), as percentiles: farm, damage taken, hero damage, assists, kills, deaths, objective damage.
Writes <folder>/roles.json and prints a compact summary for the analysis.
"""
import datetime
import html
import json
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import get, read_json, read_text, write_json, write_text  # noqa: E402
from guides import CACHE, STEAM_APP_ID, fetch, last_big_patch, steam_date  # noqa: E402
from i18n import t, table  # noqa: E402

QUERIES = ["roles explained position carry support", "position 1 6 carry support"]
KNOWN_GUIDE = os.path.join(CACHE, "roles_guide.txt")  # last good guide id, used when Steam rate-limits us
# key -> per-game value (labels: locale "metrics")
METRICS = {
    "farm": lambda h: h["total_net_worth"] / h["matches"],
    "tank": lambda h: h["total_player_damage_taken"] / h["matches"],
    "dmg": lambda h: h["total_player_damage"] / h["matches"],
    "assists": lambda h: h["total_assists"] / h["matches"],
    "kills": lambda h: h["total_kills"] / h["matches"],
    "deaths": lambda h: h["total_deaths"] / h["matches"],
    "obj": lambda h: h["total_boss_damage"] / h["matches"],
}


def normalize(name):
    return re.sub(r"[^a-z0-9]", "", name.lower().replace("&", "and"))


def parse_roles(text):
    """Numbered positions and their heroes, from "N Title : ..." and "Heroes: ..." patterns."""
    titles = {int(n): t.strip() for n, t in re.findall(r"\b([1-6]) ([A-Z][A-Za-z /]+?) :", text)}
    parts = re.split(r"Heroes?\s*:", text)
    if len(parts) < 4:
        return []
    out = []
    for k in range(1, len(parts)):
        heroes_text = parts[k].split(".")[0]
        names = [re.sub(r"^(sometimes|also|parfois|aussi) ", "", n.strip(), flags=re.I)
                 for n in re.split(r",| and | et ", re.sub(r"\(.*?\)", "", heroes_text)) if n.strip()]
        job = parts[k - 1]
        if k > 1:  # the text that follows the previous hero list
            job = job[len(parts[k - 1].split(".")[0]) + 1:]
        out.append({"pos": k if k in titles else None, "title": titles.get(k, f"Position {k}"),
                    "job": job.strip()[-900:], "heroes": names})
    return out


def read_guide(guide_id, title, since):
    url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={guide_id}"
    page = fetch(url)
    updated = max([steam_date(x) for x in re.findall(r'detailsStatRight">([^<]+@[^<]+)<', page)] or [0])
    if updated < since:
        return None
    text = " ".join(re.findall(r'class="subSectionDesc">(.*?)</div>', page, re.S))
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()
    if not title:
        m = re.search(r'<div class="workshopItemTitle">(.*?)</div>', page, re.S)
        title = html.unescape(m[1]).strip() if m else t("roles.default_title")
    roles = parse_roles(text)
    if len(roles) < 4:
        return None
    return {"id": guide_id, "title": title, "updated": updated, "roles": roles, "url": url}


def community_role(names, since):
    best = None
    for query in QUERIES:
        url = f"https://steamcommunity.com/app/{STEAM_APP_ID}/guides/?" + urllib.parse.urlencode(
            {"searchText": query, "browsefilter": "toprated", "browsesort": "toprated", "requiredtags[]": "-1"})
        try:
            page = fetch(url)
        except Exception:
            continue
        for m in re.finditer(r'SharedFileBindMouseHover\(\s*"[^"]+",\s*\w+,\s*(\{.*?\})\s*\);', page, re.S):
            try:
                guide = json.loads(m[1])
            except ValueError:
                continue
            if not re.search(r"role|position", guide.get("title") or "", re.I):
                continue
            try:
                parsed = read_guide(guide["id"], guide["title"].strip(), since)
            except Exception:
                continue
            if parsed and (not best or parsed["updated"] > best["updated"]):
                best = parsed
        if best:
            break
    if best:
        os.makedirs(CACHE, exist_ok=True)
        write_text(KNOWN_GUIDE, best["id"])
    elif os.path.exists(KNOWN_GUIDE):  # Steam rate limit (429): fall back to the last known roles guide
        try:
            best = read_guide(read_text(KNOWN_GUIDE).strip(), None, since)
        except Exception:
            best = None
    if not best:
        return None
    keys = {normalize(n) for n in names}
    mine = [r for r in best["roles"] if any(normalize(h) in keys for h in r["heroes"])]
    return {"source": best["title"], "url": best["url"], "updated": best["updated"],
            "positions": [{k: r[k] for k in ("pos", "title", "job")} for r in mine]}


def stat_profile(hero_id, since):
    try:
        rows = [h for h in get("/v1/analytics/hero-stats", min_average_badge=90, min_unix_timestamp=since)
                if h.get("matches", 0) >= 200]
    except Exception:
        return None
    mine = next((h for h in rows if h["hero_id"] == hero_id), None)
    if not mine:
        return None
    out = {}
    labels = table("metrics")
    for key, metric in METRICS.items():
        label = labels[key]
        values = sorted(metric(h) for h in rows)
        value = metric(mine)
        out[key] = {"label": label, "value": round(value),
                    "pct": round(100 * sum(x < value for x in values) / max(1, len(values) - 1))}
    out["winrate"] = round(100 * mine["wins"] / max(1, mine["matches"]), 1)
    out["matches"] = mine["matches"]
    return out


def main():
    folder = sys.argv[1]
    data = read_json(f"{folder}/candidates.json")
    hero_id = data["hero"]["id"]
    since = last_big_patch() or data["generated"] - 60 * 86400
    try:
        english = next((h for h in get("/v1/assets/heroes") if h["id"] == hero_id), {})
        french = next((h for h in get("/v1/assets/heroes", language="french") if h["id"] == hero_id), {})
    except Exception:
        english, french = {}, {}
    names = [x for x in (english.get("name"), french.get("name"), (english.get("class_name") or "").replace("hero_", "")) if x]
    result = {"class": english.get("hero_type"), "community": community_role(names, since),
              "stats": stat_profile(hero_id, since), "since": since}
    write_json(f"{folder}/roles.json", result, indent=1)

    print(f"\n### Role of {data['hero']['name']} (game class: {result['class'] or '?'})")
    community = result["community"]
    if community:
        when = datetime.date.fromtimestamp(community["updated"]).strftime("%Y-%m-%d")
        print(f"Community meta \"{community['source']}\" ({when}): " +
              (", ".join(f"P{p['pos']} {p['title']}" for p in community["positions"]) or "hero not listed"))
        for p in community["positions"]:
            print(f"  [P{p['pos']} {p['title']}] {p['job'][:600]}")
    else:
        print("No recent roles guide found.")
    stats = result["stats"]
    if stats:
        print("Profile (percentile among all heroes, Phantom+): " +
              ", ".join(f"{v['label']} {v['pct']}th" for v in stats.values() if isinstance(v, dict)))


if __name__ == "__main__":
    main()
