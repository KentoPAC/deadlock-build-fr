"""Shared helpers: deadlock-api.com access, localized asset names, translatable build texts."""
import json
import os
import re
import urllib.parse
import urllib.request

from i18n import API_LANGUAGE, LANGS, current, pattern, t, table

API = "https://api.deadlock-api.com"
USER_AGENT = {"User-Agent": "deadlock-build-fr/1.0"}
LANG_FR = 2  # ELanguage: 0 English, 2 French, 6 Simplified Chinese...


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data, indent=None, compact=False):
    """Write UTF-8 JSON (non-ASCII kept as is); compact=True drops the spaces after separators."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent, separators=(",", ":") if compact else None)


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def get(path, **params):
    """GET an API path and return the decoded JSON (None-valued params are dropped)."""
    params = {k: v for k, v in params.items() if v is not None}
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    with urllib.request.urlopen(urllib.request.Request(url, headers=USER_AGENT), timeout=90) as resp:
        return json.load(resp)


_items = {}
_heroes = {}


def items(lang=None):
    """id -> item/ability asset, named in the current language (cached per language for the process)."""
    lang = lang or current()
    if lang not in _items:
        _items[lang] = {i["id"]: i for i in get("/v1/assets/items", language=API_LANGUAGE[lang])}
    return _items[lang]


def item_name(item_id):
    return items().get(item_id, {}).get("name") or f"#{item_id}"


def heroes(lang=None):
    """id -> hero asset, named in the current language (cached per language)."""
    lang = lang or current()
    if lang not in _heroes:
        _heroes[lang] = {h["id"]: h for h in get("/v1/assets/heroes", language=API_LANGUAGE[lang])}
    return _heroes[lang]


def find_hero(query):
    """Resolve a hero from an id, a French or English name, a class name, or a name fragment."""
    by_id = heroes()
    if str(query).isdigit() and int(query) in by_id:
        return by_id[int(query)]
    q = str(query).lower().replace("&", "and")
    english = {h["id"]: h["name"] for h in get("/v1/assets/heroes")}
    for h in by_id.values():
        names = [h["name"].lower(), english.get(h["id"], "").lower(), h.get("class_name", "").lower()]
        if any(q == n.replace("&", "and") for n in names):
            return h
    for h in by_id.values():
        if q in h["name"].lower() or q in english.get(h["id"], "").lower():
            return h
    raise SystemExit(f"Hero not found: {query}")


def rank_label(badge):
    """Badge number (e.g. 116) -> localized rank label ("Éternus 6"); badge // 10 = tier index."""
    if not badge:
        return t("rank.unknown")
    ranks = table("ranks")
    tier, sub = divmod(int(badge), 10)
    name = ranks[tier] if tier < len(ranks) else f"tier {tier}"
    return f"{name} {sub}" if sub else name


def make_strings(build, prefill=False):
    """List the translatable texts of a build (path + context). prefill: copy the text into "fr"."""
    out = []

    def add(path, text, context):
        if text and not text.startswith("#Citadel_"):  # labels localized by the game itself
            out.append({"path": path, "context": context, "text": text, "fr": text if prefill else ""})

    add(["name"], build.get("name"), "Build name")
    add(["description"], build.get("description"), "Build description")
    for ci, cat in enumerate(build["details"]["mod_categories"]):
        mods = ", ".join(item_name(m["ability_id"]) for m in cat.get("mods", []))
        label = cat.get("name")
        add(["details", "mod_categories", ci, "name"], label, f"Category name (items: {mods})")
        add(["details", "mod_categories", ci, "description"], cat.get("description"),
            f"Description of category \"{label}\" (items: {mods})")
        for mi, mod in enumerate(cat.get("mods", [])):
            add(["details", "mod_categories", ci, "mods", mi, "annotation"], mod.get("annotation"),
                f"Note on item \"{item_name(mod['ability_id'])}\"")
    for ai, change in enumerate((build["details"].get("ability_order") or {}).get("currency_changes", [])):
        add(["details", "ability_order", "currency_changes", ai, "annotation"], change.get("annotation"),
            f"Note on ability \"{item_name(change['ability_id'])}\"")
    return out


def write_candidate(folder, build, prefill=False):
    """Save original.json and strings.json for a build, keeping translations from a previous run."""
    os.makedirs(folder, exist_ok=True)
    write_json(f"{folder}/original.json", build, indent=1)
    strings = make_strings(build, prefill)
    if os.path.exists(f"{folder}/strings.json"):
        previous = {json.dumps(s["path"]) + s["text"]: s["fr"]
                    for s in read_json(f"{folder}/strings.json") if s.get("fr")}
        for s in strings:
            s["fr"] = previous.get(json.dumps(s["path"]) + s["text"], s["fr"])
    write_json(f"{folder}/strings.json", strings, compact=True)
    return strings


def text_amount(build):
    """Amount of written explanation in a build (characters)."""
    details = build["details"]
    n = len(build.get("description") or "")
    for cat in details["mod_categories"]:
        n += len(cat.get("description") or "")
        n += sum(len(m.get("annotation") or "") for m in cat.get("mods", []))
    return n


# Notes and category descriptions generated by find.py for OTP builds (localized: they go into the in-game build).
# Builds may have been generated in any language, so every locale is recognised.
OTP_NOTES = [re.compile(pattern("otp.note", lang=lang) + "(?:" + pattern("otp.note_sold", lang=lang) + ")?$") for lang in LANGS]
OTP_DESC = re.compile("^(?:" + "|".join(pattern(k, ".+", lang=lang) for lang in LANGS for k in (
    "otp.cat.early", "otp.cat.mid", "otp.cat.late", "otp.cat.situational_desc", "otp.cat.situational_late_desc")) + ")")


def parse_otp_note(note):
    """Generated OTP note -> (pct, minute, sold_minute or None), in any language; None for other notes."""
    for regex in OTP_NOTES:
        m = regex.match(note or "")
        if m:
            return int(m[1]), int(m[2]), int(m[3]) if m[3] else None
    return None


def short_note(note):
    """Generated OTP note -> "98%@4m rev9m" (bought in 98% of games around 4 min, sold around 9 min); others truncated."""
    parsed = parse_otp_note(note)
    if parsed:
        pct, minute, sold = parsed
        return f"{pct}%@{minute}m" + (f" rev{sold}m" if sold else "")
    return (note or "")[:160]


def summarize(build, strings=None):
    """Compact build summary. With strings, untranslated texts are shown as [n] references
    instead of being repeated (todo_list prints them once)."""
    ref, done = {}, {}
    for n, s in enumerate(strings or []):
        if s["fr"]:
            done[json.dumps(s["path"])] = s["fr"]
        else:
            ref[json.dumps(s["path"])] = n

    def text(path, value, cut):
        key = json.dumps(path)
        value = done.get(key, value)
        return f"[{ref[key]}]" if key in ref else short_note(value)[:cut] if value else ""

    lines = []
    for ci, cat in enumerate(build["details"]["mod_categories"]):
        base = ["details", "mod_categories", ci]
        desc = text(base + ["description"], cat.get("description"), 200)
        if OTP_DESC.match(desc):  # generated OTP descriptions carry no information for the analysis
            desc = ""
        lines.append(f"== {text(base + ['name'], cat.get('name'), 60) or cat.get('name')}" + (f" : {desc}" if desc else ""))
        mods = []
        for mi, mod in enumerate(cat.get("mods", [])):
            note = text(base + ["mods", mi, "annotation"], mod.get("annotation"), 160)
            mods.append(item_name(mod["ability_id"]) + (f" ({note})" if note else ""))
        if mods:
            lines.append("   " + " | ".join(mods))
    order = (build["details"].get("ability_order") or {}).get("currency_changes", [])
    if order:
        lines.append("Abilities: " + " > ".join(item_name(x["ability_id"]).split()[0] + ("*" if x.get("currency_type") == 2 else "")
                                                for x in order) + "  (* = unlock)")
    return "\n".join(lines)


def todo_list(strings):
    """Numbered texts still to translate (same numbering as summarize)."""
    return "\n".join(f"[{n}] {s['text']}" for n, s in enumerate(strings) if not s["fr"])


def fill(folder, translations):
    """Fill strings.json: a list in the order of the texts to translate, or a {n: fr} dict."""
    strings = read_json(f"{folder}/strings.json")
    todo = [n for n, s in enumerate(strings) if not s["fr"]]
    if not isinstance(translations, dict) and len(translations) != len(todo):
        raise SystemExit(f"{folder}: {len(translations)} translations for {len(todo)} texts")
    pairs = translations.items() if isinstance(translations, dict) else zip(todo, translations)
    for n, fr in pairs:
        strings[int(n)]["fr"] = fr
    write_json(f"{folder}/strings.json", strings, compact=True)
