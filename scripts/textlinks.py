"""Turn item and ability names found in written texts into hoverable links, and flag shortened names."""
import re

from common import heroes

ACCENTS = {"a": "aàâä", "e": "eéèêë", "i": "iîï", "o": "oôö", "u": "uùûü", "c": "cç", "y": "yÿ"}
SPACES = "   "  # the API sometimes uses non-breaking spaces ("Chargeur XL")


def loose(name):
    """Regex for a name that ignores accents, the case of the first letter, and the kind of space."""
    out = []
    for k, ch in enumerate(name):
        base = next((b for b, variants in ACCENTS.items() if ch.lower() in variants), None)
        if base:
            variants = ACCENTS[base] + (ACCENTS[base].upper() if k == 0 or ch.isupper() else "")
            out.append("[" + re.escape(variants) + "]")
        elif ch in SPACES:
            out.append(f"[{SPACES}]")
        elif k == 0 and ch.isalpha():
            out.append("[" + re.escape(ch.lower() + ch.upper()) + "]")
        else:
            out.append(re.escape(ch))
    return "".join(out)


def signature_abilities(hero_id, all_items):
    """[(key 1-4, ability)] of a hero."""
    try:
        signatures = (heroes().get(hero_id) or {}).get("items") or {}
    except Exception:
        return []
    by_class = {i.get("class_name"): i for i in all_items.values()}
    return [(n, by_class[signatures[f"signature{n}"]]) for n in range(1, 5)
            if by_class.get(signatures.get(f"signature{n}"))]


def link_index(hero_id, all_items, texts):
    """The hero's abilities (keys 1-4) and the items quoted in the texts -> links on the page.
    An item named like one of the hero's abilities (e.g. Fléau) loses to the ability."""
    blob = "\n".join(t for t in texts if t)
    candidates = [{"id": a["id"], "name": a["name"], "key": n} for n, a in signature_abilities(hero_id, all_items)
                  if a.get("name")]
    ability_names = {c["name"].lower() for c in candidates}
    for item in all_items.values():
        if (item.get("type") == "upgrade" and item.get("shopable") and item.get("name")
                and item["name"].lower() not in ability_names):
            candidates.append({"id": item["id"], "name": item["name"]})
    found = []
    for c in candidates:  # every spelling found in the texts becomes a link
        variants = {m.group(0) for m in re.finditer(r"(?<![\w])" + loose(c["name"]) + r"(?![\w])", blob)}
        found += [dict(c, name=v) for v in variants]
    return found


def short_names(all_items, texts):
    """Shortened item / ability names ("Dissipateur" for "Dissipateur de magie"): they get no link and no English
    translation, which produces mixed-language sentences. Returns [(word, possible full names, excerpt)]."""
    def unspace(text):
        return text.replace(" ", " ").replace(" ", " ")
    full = sorted({unspace(i["name"]) for i in all_items.values()
                   if i.get("name") and (i.get("type") == "ability" or (i.get("type") == "upgrade" and i.get("shopable")))},
                  key=len, reverse=True)
    heads = {}
    for name in full:
        words = name.split()
        if len(words) > 1 and len(words[0]) >= 5 and words[0][0].isupper():
            heads.setdefault(words[0], []).append(name)
    single_word = {n for n in full if " " not in n}
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, heads)) + r")\b")
    out = []
    for text in texts:
        text = unspace(text or "")
        for m in pattern.finditer(text):
            word = m.group(1)
            if (word in single_word or text[:m.start()].endswith("'s ")  # "Sinner's Sacrifice": a map object
                    or any(text.startswith(n, m.start()) for n in heads[word])):
                continue
            out.append((word, heads[word][:3], text[max(0, m.start() - 30):m.end() + 30]))
    return out
