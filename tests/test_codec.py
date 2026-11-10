import unittest

from tests import helpers  # noqa: F401
import codec

BUILD = {
    "hero_build_id": 3, "hero_id": 63, "author_account_id": 1234, "last_updated_timestamp": 1700000000,
    "name": "OTP test (Mina)", "description": "Build reconstitué d'après les vrais achats.", "language": 0, "version": 0,
    "details": {
        "mod_categories": [
            {"name": "#Citadel_HeroBuilds_EarlyGame", "description": "Avant 10 min.", "width": 400.0, "height": 190.0,
             "mods": [{"ability_id": 1001, "annotation": "Pris dans 98 % de ses parties, vers 4 min."}, {"ability_id": 1002}]},
            {"name": "Situationnel", "optional": True, "mods": [{"ability_id": 1003}]},
        ],
        "ability_order": {"currency_changes": [{"ability_id": 2001, "currency_type": 2, "delta": -1},
                                               {"ability_id": 2001, "currency_type": 1, "delta": -1}]},
    },
    "tags": [7],
}


class CodecTest(unittest.TestCase):
    def test_varint(self):
        self.assertEqual(codec.varint(1), b"\x01")
        self.assertEqual(codec.varint(300), b"\xac\x02")
        self.assertEqual(codec.read_varint(codec.varint(123456789), 0), (123456789, 4))

    def test_round_trip(self):
        fields = dict(codec.decode(codec.encode(BUILD)))
        self.assertEqual(fields[2], 63)
        self.assertEqual(fields[3], 1234)
        self.assertEqual(fields[5], "OTP test (Mina)")
        self.assertEqual(fields[6], "Build reconstitué d'après les vrais achats.")
        details = fields[10]
        categories = [value for num, value in details if num == 1]
        self.assertEqual(len(categories), 2)
        self.assertIn((6, 1), categories[1])  # optional flag

    def test_no_trailing_newline(self):
        self.assertFalse(codec.encode(BUILD).endswith("\n"))

    def test_optional_fields_are_omitted(self):
        self.assertEqual(codec.encode_mod({"ability_id": 5}), codec.field_varint(1, 5))


if __name__ == "__main__":
    unittest.main()
