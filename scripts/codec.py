"""Encode and decode Deadlock build codes (the in-game "Paste build" clipboard format).

Format: base64(zstd(protobuf CMsgHeroBuild)), without a trailing newline (the game rejects it otherwise).

Usage:
    python3 -I codec.py build.json > code.txt     encode a build (JSON shaped like the API's hero_build)
    python3 -I codec.py --decode CODE             dump the raw protobuf fields of a code copied in game
"""
import base64
import json
import struct
import sys
from compression import zstd  # Python 3.14+


# ---------- minimal protobuf encoder ----------


def varint(n):
    n &= (1 << 64) - 1
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def field_varint(num, value):
    return varint(num << 3) + varint(value)


def field_bytes(num, value):
    if isinstance(value, str):
        value = value.encode("utf-8")
    return varint((num << 3) | 2) + varint(len(value)) + value


def field_float(num, value):
    return varint((num << 3) | 5) + struct.pack("<f", value)


def optional(encoder, num, value):
    return b"" if value is None else encoder(num, value)


def encode_mod(mod):
    return (optional(field_varint, 1, mod.get("ability_id"))
            + optional(field_bytes, 2, mod.get("annotation"))
            + optional(field_varint, 3, mod.get("required_flex_slots"))
            + optional(field_varint, 4, mod.get("sell_priority"))
            + optional(field_varint, 5, mod.get("imbue_target_ability_id")))


def encode_category(cat):
    out = b"".join(field_bytes(1, encode_mod(m)) for m in cat.get("mods", []))
    out += optional(field_bytes, 2, cat.get("name"))
    out += optional(field_bytes, 3, cat.get("description"))
    out += optional(field_float, 4, cat.get("width"))
    out += optional(field_float, 5, cat.get("height"))
    if cat.get("optional"):
        out += field_varint(6, 1)
    return out


def encode_currency_change(change):
    return (optional(field_varint, 1, change.get("ability_id"))
            + optional(field_varint, 2, change.get("currency_type"))
            + optional(field_varint, 3, change.get("delta"))
            + optional(field_bytes, 4, change.get("annotation")))


def encode_build(build):
    details_in = build["details"]
    details = b"".join(field_bytes(1, encode_category(c)) for c in details_in["mod_categories"])
    ability_order = details_in.get("ability_order")
    if ability_order:
        changes = b"".join(field_bytes(1, encode_currency_change(x)) for x in ability_order["currency_changes"])
        details += field_bytes(2, changes)
    out = b""
    for num, key in [(1, "hero_build_id"), (2, "hero_id"), (3, "author_account_id"), (4, "last_updated_timestamp")]:
        out += optional(field_varint, num, build.get(key))
    out += optional(field_bytes, 5, build.get("name"))
    out += optional(field_bytes, 6, build.get("description"))
    out += optional(field_varint, 7, build.get("language"))
    out += optional(field_varint, 8, build.get("version"))
    out += optional(field_varint, 9, build.get("origin_build_id"))
    out += field_bytes(10, details)
    for tag in build.get("tags") or []:
        out += field_varint(11, tag)
    return out


def encode(build):
    """Build dict -> clipboard code accepted by the game."""
    return base64.b64encode(zstd.compress(encode_build(build))).decode()


# ---------- decoder (to inspect a code copied in game) ----------


def read_varint(buf, i):
    value, shift = 0, 0
    while True:
        byte = buf[i]
        i += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if byte < 0x80:
            return value, i


def decode_message(buf):
    """Schema-less protobuf dump: [(field_number, value), ...]; nested messages are decoded recursively."""
    i, out = 0, []
    while i < len(buf):
        key, i = read_varint(buf, i)
        num, wire_type = key >> 3, key & 7
        if wire_type == 0:
            value, i = read_varint(buf, i)
        elif wire_type == 2:
            length, i = read_varint(buf, i)
            value = buf[i:i + length]
            i += length
            try:
                text = value.decode("utf-8")
                value = decode_message(value) if value and not text.isprintable() else text
            except Exception:
                try:
                    value = decode_message(value)
                except Exception:
                    value = value.hex()
        elif wire_type == 5:
            value = struct.unpack("<f", buf[i:i + 4])[0]
            i += 4
        elif wire_type == 1:
            value = struct.unpack("<d", buf[i:i + 8])[0]
            i += 8
        else:
            raise ValueError(f"unsupported wire type {wire_type}")
        out.append((num, value))
    return out


def decode(code):
    """Clipboard code -> raw field dump."""
    return decode_message(zstd.decompress(base64.b64decode(code.strip())))


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--decode":
        print(json.dumps(decode(sys.argv[2]), ensure_ascii=False, indent=1))
    elif len(sys.argv) == 2:
        with open(sys.argv[1], encoding="utf-8") as f:
            sys.stdout.write(encode(json.load(f)))
    else:
        sys.exit(__doc__)
