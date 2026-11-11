"""Community advice for a hero, to cross-check with the measured stats.

Usage: python3 -I guides.py <search_folder> [--n 2]

Two sources, all dated and limited to after the last big patch:
  1. Builds published in game whose texts (description + categories) form a real guide
     (>= MIN_TEXT characters), by Oracle+ or very popular authors, excluding the build candidates.
  2. Serious Steam guides (title with the hero name + a guide keyword, memes filtered out),
     updated since the last big patch.
Writes <folder>/guides.json (sources shown on the page) and prints the texts, truncated, for the analysis.
"""
import datetime
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import get, rank_label, read_json, read_text, write_json, write_text  # noqa: E402

MIN_TEXT = 500
MAX_PRINT = 1500
CACHE = os.path.expanduser("~/.cache/deadlock-maxing")
STEAM_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en"}
STEAM_APP_ID = 1422450  # Deadlock
MEME = re.compile(r"marry|girlfriend|boyfriend|hentai|war crim|useless|feeding|nickname|apodos|steamhappy|console", re.I)
GUIDE = re.compile(r"guide|build|how to (play|win)|tips|playstyle|gameplay|гайд|guía", re.I)


def last_big_patch():
    """Timestamp of the last big patch (0 if the API is unavailable)."""
    try:
        return max(int(datetime.datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp())
                   for x in get("/v1/patches/big-days"))
    except Exception:
        return 0


def build_text(build):
    """All the explanation text of a build: description + category descriptions."""
    parts = [build.get("description") or ""]
    for cat in build["details"]["mod_categories"]:
        name, desc = cat.get("name") or "", cat.get("description") or ""
        if desc:
            parts.append((name if not name.startswith("#") else name.split("_")[-1]) + " : " + desc)
    return "\n".join(p.strip() for p in parts if p.strip())


def from_builds(hero_id, exclude, since, n):
    pool = {}
    for sort in ("favorites", "weekly_favorites", "updated_at"):
        try:
            for x in get("/v1/builds", hero_id=hero_id, sort_by=sort, only_latest="true", limit=80,
                         min_unix_timestamp=since):
                b = x["hero_build"]
                if b["hero_build_id"] not in exclude:
                    pool[b["hero_build_id"]] = (b, max(x.get("num_favorites") or 0, x.get("num_weekly_favorites") or 0))
        except Exception:
            pass
    pool = [(b, favorites, build_text(b)) for b, favorites in pool.values()]
    pool = [t for t in pool if len(t[2]) >= MIN_TEXT]
    if not pool:
        return []
    ranks = {}
    ids = list({b["author_account_id"] for b, _, _ in pool})
    for i in range(0, len(ids), 50):
        for r in get("/v1/players/rank", account_ids=",".join(map(str, ids[i:i + 50]))):
            ranks[r["account_id"]] = r.get("badge") or 0
    scored = []
    for b, favorites, text in pool:
        badge = ranks.get(b["author_account_id"], 0)
        if badge < 80 and favorites < 200:
            continue
        score = badge * 1.2 + min(len(text), 3000) / 60 + 6 * (favorites > 0) * len(str(favorites))
        scored.append((score, b, badge, favorites, text))
    scored.sort(key=lambda t: -t[0])
    return [{"kind": "build", "title": b["name"], "author_id": b["author_account_id"], "rank": rank_label(badge),
             "favorites": favorites, "updated": b["last_updated_timestamp"], "build_id": b["hero_build_id"],
             "language": b.get("language"), "text": text}
            for _, b, badge, favorites, text in scored[:n]]


def steam_date(text):
    """Steam date ("8 Nov @ 3:12pm", "8 Nov, 2025 @ ...") -> timestamp (0 if unparseable)."""
    text = text.split("@")[0].strip()
    if "," not in text:  # Steam omits the current year
        text += f", {datetime.date.today().year}"
    for fmt in ("%d %b, %Y", "%b %d, %Y"):
        try:
            return int(datetime.datetime.strptime(text, fmt).timestamp())
        except ValueError:
            pass
    return 0


def fetch(url, max_age=86400):
    """Steam page, cached for a day (Steam rate-limits quickly with 429); spaced retries when limited."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + ".html")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age:
        return read_text(path)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=STEAM_HEADERS), timeout=25) as resp:
                text = resp.read().decode("utf-8", "replace")
            write_text(path, text)
            return text
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 2:
                raise
            time.sleep(8 * (attempt + 1))


def from_steam(names, since, n):
    out, seen = [], set()
    for name in names:
        url = (f"https://steamcommunity.com/app/{STEAM_APP_ID}/guides/?" + urllib.parse.urlencode(
            {"searchText": name, "browsefilter": "toprated", "browsesort": "toprated", "requiredtags[]": "-1"}))
        try:
            page = fetch(url)
        except Exception:
            continue
        for m in re.finditer(r'SharedFileBindMouseHover\(\s*"[^"]+",\s*\w+,\s*(\{.*?\})\s*\);', page, re.S):
            try:
                guide = json.loads(m[1])
            except ValueError:
                continue
            title = guide.get("title") or ""
            if guide["id"] in seen or MEME.search(title) or not GUIDE.search(title) or name.lower() not in title.lower():
                continue
            seen.add(guide["id"])
            guide_url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={guide['id']}"
            try:
                detail = fetch(guide_url)
            except Exception:
                continue
            updated = max([steam_date(x) for x in re.findall(r'detailsStatRight">([^<]+@[^<]+)<', detail)] or [0])
            if updated < since:
                continue
            text = " ".join(re.findall(r'class="subSectionDesc">(.*?)</div>', detail, re.S))
            text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()
            if len(text) < MIN_TEXT:
                continue
            out.append({"kind": "steam", "title": title.strip(), "updated": updated, "text": text, "url": guide_url})
            if len(out) >= n:
                return out
            time.sleep(0.5)
    return out


def main():
    folder = sys.argv[1]
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 2
    data = read_json(f"{folder}/candidates.json")
    hero = data["hero"]
    since = last_big_patch() or int(time.time()) - 120 * 86400
    exclude = {c.get("build_id") for c in data["candidates"]}
    try:
        english = next((h["name"] for h in get("/v1/assets/heroes") if h["id"] == hero["id"]), hero["name"])
    except Exception:
        english = hero["name"]
    names = list(dict.fromkeys([english, hero["name"]]))

    guides = from_builds(hero["id"], exclude, since, n) + from_steam(names, since, 1)
    if any(g["kind"] == "build" for g in guides):
        try:
            authors = {p["account_id"]: p["personaname"] for p in
                       get("/v1/players/steam", account_ids=",".join(str(g["author_id"]) for g in guides if g.get("author_id")))}
        except Exception:
            authors = {}
        for g in guides:
            if g.get("author_id"):
                g["author"] = authors.get(g["author_id"], str(g["author_id"]))
    write_json(f"{folder}/guides.json", {"since": since, "guides": [{k: v for k, v in g.items() if k != "text"} for g in guides]}, indent=1)

    print(f"\n### Community advice (since the big patch of {datetime.date.fromtimestamp(since):%Y-%m-%d})")
    if not guides:
        print("No recent guide with enough detail.")
    for i, g in enumerate(guides):
        date = datetime.date.fromtimestamp(g["updated"]).strftime("%Y-%m-%d")
        who = f"{g.get('author')} ({g.get('rank')}, {g.get('favorites')} fav)" if g["kind"] == "build" else "Steam guide"
        print(f"[G{i}] {g['title']} — {who}, {date}")
        print(g["text"][:MAX_PRINT] + ("…" if len(g["text"]) > MAX_PRINT else ""))


if __name__ == "__main__":
    main()
