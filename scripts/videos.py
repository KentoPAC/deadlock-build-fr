"""Creator YouTube videos: "how to counter each hero" tips, and hero guides (how to play, recommended builds).

Usage :
  python3 -I videos.py fetch <url_or_id>      transcript (subtitles, via yt-dlp) split by chapter
  python3 -I videos.py add <id> - <<'EOF'      save the translated tips (JSON on stdin):
     {"<English hero name>": {"t": "14:23", "text": "tip in French", "en": "the same tip in English",
                              "items": ["Slowing Hex", ...]}, ...}
     Fields left out keep their saved value: {"Mina": {"en": "..."}} only adds the English text.
  python3 -I videos.py guide <id> <English hero> [<build_id>@<mm:ss> ...]
                                               mark a video as a guide for one hero, with the builds it recommends
                                               (find.py adds them as "Vidéo" candidates; the plan cites the video)
  python3 -I videos.py list                    videos and number of heroes covered

English hero and item names are converted to ids when saving (loud failure when unknown): the page then
shows names, icons and tooltips from the API, like everywhere else.
Data: data/videos.json. Cached transcripts: ~/.cache/deadlock-maxing/videos/.
A video older than the last big patch is flagged on the page (report.py).
"""
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import get, read_json, write_json  # noqa: E402
from i18n import CONTENT_LANG, LANGS  # noqa: E402

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(SKILL, "data", "videos.json")
CACHE = os.path.expanduser("~/.cache/deadlock-maxing/videos")


def vid(s):
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", s)
    return m.group(1) if m else s


def load():
    return read_json(DATA) if os.path.exists(DATA) else {"videos": {}, "tips": {}}


def fetch(v):
    if not shutil.which("yt-dlp"):
        sys.exit("yt-dlp is not installed (e.g. `sudo pacman -S yt-dlp`)")
    os.makedirs(CACHE, exist_ok=True)
    url = f"https://www.youtube.com/watch?v={v}"
    meta = json.loads(subprocess.run(["yt-dlp", "-q", "--no-warnings", "-J", "--skip-download", url],
                                     capture_output=True, text=True, check=True).stdout)
    # Only the original English track: "en.*" also asks for every machine-translated track and YouTube answers 429.
    if not glob.glob(f"{CACHE}/{v}*.json3"):
        subprocess.run(["yt-dlp", "-q", "--no-warnings", "--skip-download", "--write-auto-subs", "--write-subs",
                        "--sub-langs", "en-orig,en", "--sub-format", "json3", "-o", f"{CACHE}/{v}.%(ext)s", url], check=True)
    f = sorted(glob.glob(f"{CACHE}/{v}*.json3"))
    if not f:
        sys.exit("No English subtitles for this video.")
    words = []
    for e in read_json(f[0])["events"]:
        for s in e.get("segs") or []:
            w = s.get("utf8", "").replace("\n", " ")
            if w.strip():
                words.append((e.get("tStartMs", 0) + s.get("tOffsetMs", 0), w))
    ch = [(int(c["start_time"]), c["title"]) for c in meta.get("chapters") or []] or [(0, "Video")]
    date = datetime.datetime.strptime(meta["upload_date"], "%Y%m%d").strftime("%Y-%m-%d")
    print(f"# {meta['title']} — {meta['uploader']} ({date}, {meta['duration'] // 60} min) [{v}]\n")
    for i, (s, name) in enumerate(ch):
        e = ch[i + 1][0] if i + 1 < len(ch) else 10 ** 9
        body = re.sub(" +", " ", "".join(w for t, w in words if s * 1000 <= t < e * 1000)).strip()
        print(f"## {name} ({s // 60}:{s % 60:02d})\n{body}\n")
    d = load()
    d["videos"][v] = dict(d["videos"].get(v) or {}, title=meta["title"], author=meta["uploader"], date=date)
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    write_json(DATA, d, indent=1)


def hero_ids():
    """English hero name (lower case) -> id."""
    heroes = {h["name"].lower(): h["id"] for h in get("/v1/assets/heroes")}
    heroes.update({"mo and krill": heroes.get("mo & krill"), "doorman": heroes.get("the doorman")})
    return heroes


def seconds(timestamp):
    mm, ss = map(int, timestamp.split(":"))
    return mm * 60 + ss


def guide(v, hero, builds):
    """Mark video `v` as a guide for `hero`, recommending `builds` ("<build_id>@<mm:ss>")."""
    d = load()
    if v not in d["videos"]:
        sys.exit(f"Run first: videos.py fetch {v}")
    h = hero_ids().get(hero.lower())
    if not h:
        sys.exit(f"Unknown hero: {hero}")
    recommended = []
    for b in builds:
        build_id, _, at = b.partition("@")
        if not get("/v1/builds", build_id=int(build_id)):
            sys.exit(f"Build {build_id} not found")
        recommended.append({"id": int(build_id), "t": seconds(at) if at else 0})
    d["videos"][v]["guide"] = {"hero": h, "builds": recommended}
    write_json(DATA, d, indent=1)
    print(f"{v}: guide for {hero} ({len(recommended)} recommended builds)")


def guide_videos(hero_id):
    """[(video id, video metadata)] of the guides about this hero (data/videos.json)."""
    return [(v, m) for v, m in load()["videos"].items() if (m.get("guide") or {}).get("hero") == hero_id]


def add(v, src):
    d = load()
    if v not in d["videos"]:
        sys.exit(f"Run first: videos.py fetch {v}")
    heroes = hero_ids()
    items = {}
    for i in get("/v1/assets/items"):
        if i.get("type") == "upgrade" and i.get("shopable"):
            items[i["name"].lower()] = i["id"]
    bad = []
    for name, tip in json.loads(src).items():
        h = heroes.get(name.lower())
        ids = [items.get(x.lower()) for x in tip.get("items", [])]
        miss = [x for x, i in zip(tip.get("items", []), ids) if not i]
        if not h or miss:
            bad.append(f"{name}: {'unknown hero' if not h else 'unknown items ' + ', '.join(miss)}")
            continue
        previous = next((x for x in d["tips"].get(str(h), []) if x["video"] == v), {})
        translations = dict(previous.get("translations") or {})
        translations.update({lang: tip[lang] for lang in LANGS if lang != CONTENT_LANG and tip.get(lang)})
        entry = {"video": v, "t": seconds(tip["t"]) if "t" in tip else previous.get("t", 0), "text": tip.get("text", previous.get("text")),
                 "lang": tip.get("lang", previous.get("lang", CONTENT_LANG)),
                 "items": ids if "items" in tip else previous.get("items", [])}
        if translations:
            entry["translations"] = translations
        d["tips"][str(h)] = [x for x in d["tips"].get(str(h), []) if x["video"] != v] + [entry]
    write_json(DATA, d, indent=1)
    print(f"{len(d['tips'])} heroes with at least one video tip.")
    if bad:
        sys.exit("Not saved:\n  " + "\n  ".join(bad))


def main():
    a = sys.argv[1:]
    if a[:1] == ["fetch"] and len(a) > 1:
        fetch(vid(a[1]))
    elif a[:1] == ["add"] and len(a) > 1:
        add(vid(a[1]), sys.stdin.read())
    elif a[:1] == ["guide"] and len(a) > 2:
        guide(vid(a[1]), a[2], a[3:])
    elif a[:1] == ["list"]:
        d = load()
        for v, m in d["videos"].items():
            n = sum(any(x["video"] == v for x in t) for t in d["tips"].values())
            kind = f"guide, {len(m['guide']['builds'])} builds" if m.get("guide") else f"{n} heroes"
            print(f"{v}  {m['date']}  {m['author']} — {m['title']} ({kind})")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
