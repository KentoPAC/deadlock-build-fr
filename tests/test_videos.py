import unittest
from unittest import mock

from tests import helpers  # noqa: F401
import videos


class VideosTest(unittest.TestCase):
    def test_video_id_from_url(self):
        self.assertEqual(videos.vid("https://www.youtube.com/watch?v=kW6zL2_22X4&t=12s"), "kW6zL2_22X4")
        self.assertEqual(videos.vid("https://youtu.be/kW6zL2_22X4"), "kW6zL2_22X4")

    def test_seconds(self):
        self.assertEqual(videos.seconds("20:51"), 1251)

    def test_guide_videos_are_filtered_by_hero(self):
        data = {"videos": {"a": {"title": "Violet guide", "guide": {"hero": 69, "builds": [{"id": 1, "t": 0}]}},
                           "b": {"title": "Counters"}, "c": {"title": "Mina guide", "guide": {"hero": 58, "builds": []}}},
                "tips": {}}
        with mock.patch.object(videos, "load", return_value=data):
            self.assertEqual([v for v, _ in videos.guide_videos(69)], ["a"])


if __name__ == "__main__":
    unittest.main()
