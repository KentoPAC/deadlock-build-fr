"""In-game style tooltips for items and abilities, built from the API assets (French + English)."""
import html
import re

from common import get
from i18n import table

# Ability upgrade points per tier (T1, T2, T3).
UPGRADE_COST = {1: 1, 2: 2, 3: 5}
EMPTY_VALUES = (None, "", "0", "0.0", 0)


def item_image(item):
    """Shop illustration, as in game; falls back to the icon."""
    return item.get("shop_image_webp") or item.get("shop_image") or item.get("image_webp") or item.get("image") or ""


def clean_description(text):
    """Keep only the emphasis of the API text (no arbitrary HTML)."""
    text = re.sub(r"<svg.*?</svg>", "", text or "", flags=re.S)  # inline icons
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"<span[^>]*>", "\x01", text).replace("</span>", "\x02")
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = html.escape(re.sub(r"<[^>]+>", "", text))
    return text.replace("\x01", "<b>").replace("\x02", "</b>").replace("\n", "<br>")


def plain(text):
    """API HTML -> plain text."""
    no_svg = re.sub(r"<svg.*?</svg>", "", text or "", flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", no_svg))).strip()


def number(value):
    try:
        f = float(value)
        return str(int(f)) if f == int(f) else f"{f:g}"
    except (TypeError, ValueError):
        return str(value)


def stat_line(props, key):
    """[label, value] of an item stat, or None when empty."""
    prop = props.get(key) or {}
    value, label = prop.get("value"), prop.get("label") or prop.get("postvalue_label")
    if not label or value in EMPTY_VALUES or str(value).startswith("{"):
        return None
    try:
        f = float(value)
        sign = "+" if f > 0 and prop.get("prefix", "").find("sign") >= 0 else ""
        value = sign + (str(int(f)) if f == int(f) else str(f))
    except ValueError:
        pass
    postfix = "" if re.search(r"[a-zA-Z%]$", str(value)) else prop.get("postfix", "")
    return [html.escape(label), html.escape(f"{prop.get('prefix', '').replace('{s:sign}', '')}{value}{postfix}")]


def property_line(prop, key):
    """An ability property, with its spirit power scaling when it has one."""
    value = prop.get("value")
    if value in EMPTY_VALUES or str(value).startswith("{"):
        return None
    scale_fn = prop.get("scale_function") or {}
    scale_type = scale_fn.get("specific_stat_scale_type")
    spirit = scale_type == "ETechPower" or (
        str(scale_fn.get("class_name", "")).startswith("scale_function_tech_damage") and scale_type in (None, "ETechPower"))
    scale = scale_fn.get("stat_scale") if spirit and scale_fn.get("stat_scale") else None  # bonus per spirit power point
    shown, postfix = number(value), (prop.get("postfix") or "")
    if postfix.strip() and shown.replace("\xa0", "").endswith(postfix.strip()):
        postfix = ""
    return {"k": key, "label": prop.get("label") or prop.get("postvalue_label") or key, "v": shown + postfix,
            "scale": number(scale) if scale else None, "css": prop.get("css_class") or ""}


def tier_text(ability, tier):
    """Text of an ability upgrade (T1-T3), from its description or its property upgrades."""
    desc = ability.get("description") or {}
    if desc.get(f"t{tier}_desc"):
        # Each <br> separates one effect: keep them apart (" · ") instead of gluing them together.
        return plain(re.sub(r"<br\s*/?>", " · ", desc[f"t{tier}_desc"]))
    upgrades = ability.get("upgrades") or []
    if len(upgrades) < tier:
        return ""
    out = []
    for upgrade in upgrades[tier - 1].get("property_upgrades") or []:
        name, bonus = upgrade.get("name") or "", upgrade.get("bonus")
        try:
            f = float(bonus)
            bonus = f"+{f:g}" if f > 0 else f"{f:g}"
        except (TypeError, ValueError):
            pass
        # Upgrades without a description: localized [unit, label], else the property name split into words.
        unit, label = table("upgrade_labels").get(name, ("", re.sub(r"(?<!^)(?=[A-Z])", " ", name).lower()))
        out.append(f"{bonus}{unit} {label}".strip())
    return " · ".join(out)


def ability_tooltip(ability):
    """Ability tooltip as in game: cooldown, range, description, stats (with spirit scaling),
    then the 3 upgrades (1 / 2 / 5 points)."""
    props = ability.get("properties") or {}
    sections = []
    for section in (ability.get("tooltip_details") or {}).get("info_sections") or []:
        important = [p.get("important_property") for block in section.get("properties_block") or []
                     for p in block.get("properties") or [] if p.get("important_property")]
        text = section.get("loc_string") or ""
        if text.strip().startswith("#"):  # localisation key the API did not resolve
            text = ""
        sections.append({"d": clean_description(text),
                         "imp": [x for x in (property_line(props.get(k) or {}, k) for k in important) if x],
                         "basic": [x for x in (property_line(props.get(k) or {}, k) for k in section.get("basic_properties") or []) if x]})
    if not sections:  # fallback: plain description
        sections = [{"d": clean_description((ability.get("description") or {}).get("desc") or ""), "imp": [], "basic": []}]
    cooldown = props.get("AbilityCooldown") or {}
    cast_range = props.get("AbilityCastRange") or {}
    charges = props.get("AbilityCharges") or {}
    return {"ab": True, "n": ability.get("name"), "slot": "ability", "img": ability.get("image_webp") or ability.get("image"),
            "icon": ability.get("image_webp") or ability.get("image"), "act": False, "innate": [], "blocks": [],
            "cd": number(cooldown.get("value")) if cooldown.get("value") not in (None, "0", 0) else None,
            "range": number(cast_range.get("value")) if cast_range.get("value") not in (None, "0", 0, "0.0") else None,
            "charges": number(charges.get("value")) if charges.get("value") not in (None, "0", 0, "1", 1) else None,
            "secs": sections, "ups": [tier_text(ability, n) for n in (1, 2, 3)]}


def tooltip(item):
    if item.get("type") == "ability":
        return ability_tooltip(item)
    props = item.get("properties") or {}
    innate, blocks, seen = [], [], set()
    for section in item.get("tooltip_sections") or []:
        for attr in section.get("section_attributes") or []:
            keys = (attr.get("important_properties") or []) + (attr.get("properties") or []) + (attr.get("elevated_properties") or [])
            lines = []
            for key in keys:
                if key in seen:
                    continue
                seen.add(key)
                line = stat_line(props, key)
                if line:
                    lines.append(line)
            if section.get("section_type") == "innate":
                innate += lines
            else:
                blocks.append({"d": clean_description(attr.get("loc_string")), "s": lines})
    if not blocks and isinstance(item.get("description"), dict):
        blocks.append({"d": clean_description(item["description"].get("desc") or ""), "s": []})
    return {"n": item.get("name"), "c": item.get("cost"), "slot": item.get("item_slot_type") or "",
            "img": item_image(item) if item.get("type") == "upgrade" else (item.get("image_webp") or item.get("image")),
            "icon": item.get("image_webp") or item.get("image"), "act": bool(item.get("is_active_item")),
            "tier": item.get("item_tier"), "imb": bool(item.get("imbue")), "innate": innate, "blocks": blocks}


def english_items():
    try:
        return {i["id"]: i for i in get("/v1/assets/items", language="english")}
    except Exception:
        return {}


def item_data(all_items, used, keys=None, english=None):
    """French tooltips + English version (name, stats, description) for the page's FR/EN toggle."""
    english = english if english is not None else english_items()
    out = {}
    for item_id in used:
        if item_id not in all_items:
            continue
        data = tooltip(all_items[item_id])
        if item_id in english:
            en = tooltip(english[item_id])
            data["en"] = {"n": en["n"], "innate": en["innate"], "blocks": en["blocks"]}
            if en.get("ab"):
                data["en"].update(secs=en["secs"], ups=en["ups"])
        if keys and item_id in keys:
            data["key"] = keys[item_id]
        out[str(item_id)] = data
    return out
