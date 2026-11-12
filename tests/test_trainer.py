import unittest

from tests import helpers  # noqa: F401
import trainer

SHOP = {1: {"cost": 800}, 2: {"cost": 3200}, 3: {"cost": 1600}}
PLAYER = {"items": [{"item_id": 1, "game_time_s": 100, "sold_time_s": 950},
                    {"item_id": 3, "game_time_s": 300, "sold_time_s": 0},
                    {"item_id": 2, "game_time_s": 1000, "sold_time_s": 0},
                    {"item_id": 99, "game_time_s": 50, "sold_time_s": 0}],  # an ability, not a shop item
          "stats": [{"time_stamp_s": 900, "net_worth": 15000, "kills": 3, "deaths": 1, "assists": 4,
                     "player_damage": 9000, "player_healing": 500, "self_healing": 700, "player_damage_taken": 8000}]}


class TrainerTest(unittest.TestCase):
    def test_held_items_skip_sold_and_abilities(self):
        self.assertEqual(trainer.held_items(PLAYER, 900, SHOP), [1, 3])
        self.assertEqual(trainer.held_items(PLAYER, 960, SHOP), [3])

    def test_next_buy_is_the_next_big_purchase(self):
        self.assertEqual(trainer.next_buy(PLAYER, 900, SHOP), 2)
        self.assertIsNone(trainer.next_buy(PLAYER, 1200, SHOP))

    def test_state_at(self):
        self.assertEqual(trainer.state_at(PLAYER, 900)["heal"], 1200)
        self.assertIsNone(trainer.state_at(PLAYER, 1200))

    def test_fed_heroes_weigh_more(self):
        w = trainer.threats([{"hero": 1, "souls": 30000}, {"hero": 2, "souls": 15000}, {"hero": 3, "souls": 15000}])
        self.assertAlmostEqual(sum(w.values()), 1)
        self.assertGreater(w[1], 2 * w[2])


if __name__ == "__main__":
    unittest.main()
