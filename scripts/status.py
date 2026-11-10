"""Analysis state of a page: method version (data/changelog.json), what is missing, and text sources.

The labels and requests built here are French on purpose: they are shown on the pages and the home page.
"""
import datetime
import os

from common import read_json

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANGELOG = read_json(os.path.join(SKILL, "data", "changelog.json"))["changes"]
ANALYSIS_VERSION = max(c["version"] for c in CHANGELOG)  # = last entry of data/changelog.json (do not edit here)
# Required texts (summaries.json path -> label shown when missing).
NEEDED_TEXT = {"intro": "analyse globale", "tldr": "TLDR", "plan.early": "plan early/mid/late", "plan.role": "rôle",
               "plan.abilities": "conseils par compétence", "plan.strengths": "forces", "plan.weaknesses": "faiblesses",
               "plan.vs": "comment le contrer"}
# Required data files (file -> label shown when missing).
NEEDED_DATA = {"baseline.json": "style de jeu mesuré (playstyle.py)", "guides.json": "conseils commu (guides.py)",
               "roles.json": "rôle (roles.py)", "matchups.json": "matchups (matchups.py)",
               "counterplay.json": "counterplay de fin de partie (counterplay.py)"}
# "stat:<module>" source references -> description.
STAT_SOURCES = {"playstyle": "Style de jeu mesuré (deadlock-api, courbes de performance des OTP et auteurs)",
                "baseline": "Moyennes Fantôme+ du même rôle (deadlock-api)",
                "roles": "Percentiles du héros vs tous les héros (deadlock-api hero-stats)",
                "matchups": "Matchups et objets de contre mesurés (deadlock-api hero-counter-stats / item-stats)",
                "counterplay": "Profils des héros et objets de contre par catégorie (deadlock-api)",
                "counters": "Objets achetés par les OTP contre certains héros (deadlock-api)",
                "kit": "Données du jeu : compétences, recharges, paliers, pics de puissance (API assets)",
                "items": "Données du jeu : objets, coûts, effets (API assets)",
                "patch": "Notes de patch officielles (liste des patchs de l'API)"}


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
        if key not in ("version", "sources"):
            walk(value, key)
    return [p for p in out if p != "tldr.pick" and not p.startswith("plan.counters")]


def completeness(folder):
    """What a page lacks to match the current analysis method (shown on the page and the home page)."""
    summaries = load_json(f"{folder}/summaries.json", {})
    missing = []
    for path, label in NEEDED_TEXT.items():
        node = summaries
        for part in path.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if not node:
            missing.append(label)
    missing += [label for f, label in NEEDED_DATA.items() if not os.path.exists(f"{folder}/{f}")]
    try:
        candidates = load_json(f"{folder}/candidates.json")["candidates"]
        if any(c["key"] not in summaries for c in candidates):
            missing.append("résumé de chaque build")
    except Exception:
        pass
    unsourced = [p for p in text_paths(summaries) if not (summaries.get("sources") or {}).get(p)]
    if unsourced:
        missing.append(f"sources de {len(unsourced)} texte(s) ({', '.join(unsourced[:4])}{'…' if len(unsourced) > 4 else ''})")
    version = summaries.get("version", 1)
    pending = [{k: c.get(k) for k in ("version", "date", "title", "todo", "auto")} for c in CHANGELOG if c["version"] > version]
    try:
        hero = load_json(f"{folder}/candidates.json")["hero"]["name"]
    except Exception:
        hero = os.path.basename(os.path.abspath(folder)).removeprefix("search-")
    ask = None
    if pending:
        changes = ", ".join("v%d (%s)" % (c["version"], c["title"]) for c in pending)
        ask = (f"Mets à jour la page {hero} ({os.path.basename(os.path.abspath(folder))}) de la méthode v{version} à "
               f"v{ANALYSIS_VERSION} : applique seulement les changements {changes} décrits dans data/changelog.json, "
               f"sans refaire le reste." + (f" Il manque aussi : {', '.join(missing)}." if missing else ""))
    elif missing:
        ask = f"Complète la page {hero} : il manque {', '.join(missing)}."
    return {"version": version, "current": ANALYSIS_VERSION, "missing": missing, "pending": pending, "ask": ask}


def resolve_sources(summaries, candidates, guides, roles):
    """Source references (summaries.json "sources") -> {ref, label, url, date}. Metadata only: not displayed yet.

    Formats: build:<key> · guide:<n> (guides.json, [Gn]) · video:<id>@<seconds> · stat:<module> (STAT_SOURCES) ·
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
            return {"ref": ref, "label": f"Build {c.get('source', '')} de {c.get('author', '?')}",
                    "url": c.get("url") or deadchaps(c.get("build_id"))}
        if kind == "guide" and arg.isdigit() and int(arg) < len(guide_list):
            g = guide_list[int(arg)]
            updated = str(g.get("updated", ""))
            date = datetime.datetime.fromtimestamp(int(updated)).strftime("%Y-%m-%d") if updated.isdigit() else None
            return {"ref": ref, "label": f"« {g.get('title')} » de {g.get('author')}",
                    "url": g.get("url") or deadchaps(g.get("build_id")), "date": date}
        if kind == "video":
            video_id, _, seconds = arg.partition("@")
            meta = videos.get(video_id) or {}
            at = f" ({int(seconds) // 60}:{int(seconds) % 60:02d})" if seconds.isdigit() else ""
            return {"ref": ref, "label": f"Vidéo « {meta.get('title', video_id)} » de {meta.get('author', '?')}{at}",
                    "url": f"https://www.youtube.com/watch?v={video_id}" + (f"&t={seconds}s" if seconds else ""),
                    "date": meta.get("date")}
        if kind == "stat" and arg in STAT_SOURCES:
            return {"ref": ref, "label": STAT_SOURCES[arg], "url": "https://deadlock-api.com"}
        if ref == "roles-guide":
            community = (roles or {}).get("community") or {}
            return {"ref": ref, "label": f"Guide Steam « {community.get('source', 'roles')} »", "url": community.get("url")}
        if ref == "analyse":
            return {"ref": ref, "label": "Déduction de Claude à partir des autres sources citées"}
        return {"ref": ref, "label": f"Source inconnue : {ref}", "bad": True}

    out = {path: [resolve(r) for r in refs] for path, refs in (summaries.get("sources") or {}).items()}
    unknown = sorted({x["ref"] for refs in out.values() for x in refs if x.get("bad")})
    if unknown:
        print("Unknown sources: " + ", ".join(unknown))
    return out
