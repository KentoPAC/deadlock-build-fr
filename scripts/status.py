"""Analysis state of a page: method version (data/changelog.json), what is missing, and text sources.

Labels and requests are localized (locales/): they are shown on the pages and the home page.
"""
import datetime
import os

from common import read_json
from i18n import CONTENT_LANG, current, t, table

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANGELOG = read_json(os.path.join(SKILL, "data", "changelog.json"))["changes"]
ANALYSIS_VERSION = max(c["version"] for c in CHANGELOG)  # = last entry of data/changelog.json (do not edit here)
# Required texts (summaries.json paths) and data files; their labels come from the locale ("needed_text", "needed_data").
NEEDED_TEXT = ["intro", "tldr", "plan.early", "plan.role", "plan.abilities", "plan.strengths", "plan.weaknesses", "plan.vs"]
NEEDED_DATA = ["baseline.json", "guides.json", "roles.json", "matchups.json", "counterplay.json"]
# summaries.json keys that are not written texts.
META_KEYS = ("version", "sources", "lang")


def localized(value):
    """A {"en": ..., "fr": ...} mapping -> the current language's text (plain strings are returned as is)."""
    if isinstance(value, dict):
        return value.get(current()) or value.get(CONTENT_LANG) or next(iter(value.values()), "")
    return value


def load_json(path, default=None):
    return read_json(path) if os.path.exists(path) else default


def text_paths(summaries):
    """Paths of every written text in summaries.json ("plan.vs[0]", "tldr.early"...): each one needs a source."""
    out = []

    def walk(value, path):
        if isinstance(value, str):
            out.append(path)
        elif isinstance(value, dict):
            for k, v in value.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, f"{path}[{i}]")
    for key, value in summaries.items():
        if key not in META_KEYS:
            walk(value, key)
    return [p for p in out if p != "tldr.pick" and not p.startswith("plan.counters")]


def completeness(folder):
    """What a page lacks to match the current analysis method (shown on the page and the home page)."""
    summaries = load_json(f"{folder}/summaries.json", {})
    missing = []
    for path in NEEDED_TEXT:
        node = summaries
        for part in path.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if not node:
            missing.append(table("needed_text")[path])
    missing += [table("needed_data")[f] for f in NEEDED_DATA if not os.path.exists(f"{folder}/{f}")]
    try:
        candidates = load_json(f"{folder}/candidates.json")["candidates"]
        if any(c["key"] not in summaries for c in candidates):
            missing.append(t("missing.build_summaries"))
    except Exception:
        pass
    unsourced = [p for p in text_paths(summaries) if not (summaries.get("sources") or {}).get(p)]
    if unsourced:
        paths = ", ".join(unsourced[:4]) + ("…" if len(unsourced) > 4 else "")
        missing.append(t("missing.sources", count=len(unsourced), paths=paths))
    version = summaries.get("version", 1)
    pending = [{**{k: c.get(k) for k in ("version", "date", "todo", "auto")}, "title": localized(c["title"])}
               for c in CHANGELOG if c["version"] > version]
    try:
        hero = load_json(f"{folder}/candidates.json")["hero"]["name"]
    except Exception:
        hero = os.path.basename(os.path.abspath(folder)).removeprefix("search-")
    ask = None
    if pending:
        changes = ", ".join("v%d (%s)" % (c["version"], c["title"]) for c in pending)
        ask = t("ask.update", hero=hero, folder=os.path.basename(os.path.abspath(folder)), version=version,
                current=ANALYSIS_VERSION, changes=changes)
        if missing:
            ask += t("ask.also_missing", missing=", ".join(missing))
    elif missing:
        ask = t("ask.complete", hero=hero, missing=", ".join(missing))
    return {"version": version, "current": ANALYSIS_VERSION, "missing": missing, "pending": pending, "ask": ask}


def resolve_sources(summaries, candidates, guides, roles):
    """Source references (summaries.json "sources") -> {ref, label, url, date}. Metadata only: not displayed yet.

    Formats: build:<key> · guide:<n> (guides.json, [Gn]) · video:<id>@<seconds> · stat:<module> (locale "stat_sources") ·
    roles-guide (Steam positions guide) · analyse (Claude's deduction from the other sources cited with it).
    """
    videos = (load_json(os.path.join(SKILL, "data", "videos.json"), {}) or {}).get("videos", {})
    by_key = {c["key"]: c for c in candidates}
    guide_list = (guides or {}).get("guides") or []

    def deadchaps(build_id):
        return f"https://deadchaps.gg/builds/{build_id}" if build_id else None

    def resolve(ref):
        kind, _, arg = ref.partition(":")
        if kind == "build" and arg in by_key:
            c = by_key[arg]
            return {"ref": ref, "label": t("source.build", source=c.get("source", ""), author=c.get("author", "?")),
                    "url": c.get("url") or deadchaps(c.get("build_id"))}
        if kind == "guide" and arg.isdigit() and int(arg) < len(guide_list):
            g = guide_list[int(arg)]
            updated = str(g.get("updated", ""))
            date = datetime.datetime.fromtimestamp(int(updated)).strftime("%Y-%m-%d") if updated.isdigit() else None
            return {"ref": ref, "label": t("source.guide", title=g.get("title"), author=g.get("author")),
                    "url": g.get("url") or deadchaps(g.get("build_id")), "date": date}
        if kind == "video":
            video_id, _, seconds = arg.partition("@")
            meta = videos.get(video_id) or {}
            at = f" ({int(seconds) // 60}:{int(seconds) % 60:02d})" if seconds.isdigit() else ""
            return {"ref": ref, "label": t("source.video", title=meta.get("title", video_id), author=meta.get("author", "?"), at=at),
                    "url": f"https://www.youtube.com/watch?v={video_id}" + (f"&t={seconds}s" if seconds else ""),
                    "date": meta.get("date")}
        if kind == "stat" and arg in table("stat_sources"):
            return {"ref": ref, "label": table("stat_sources")[arg], "url": "https://deadlock-api.com"}
        if ref == "roles-guide":
            community = (roles or {}).get("community") or {}
            return {"ref": ref, "label": t("source.roles_guide", title=community.get("source", "roles")),
                    "url": community.get("url")}
        if ref == "analyse":
            return {"ref": ref, "label": t("source.analysis")}
        return {"ref": ref, "label": t("source.unknown", ref=ref), "bad": True}

    out = {path: [resolve(r) for r in refs] for path, refs in (summaries.get("sources") or {}).items()}
    unknown = sorted({x["ref"] for refs in out.values() for x in refs if x.get("bad")})
    if unknown:
        print("Unknown sources: " + ", ".join(unknown))
    return out
