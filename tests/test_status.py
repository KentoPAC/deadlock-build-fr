import contextlib
import io
import unittest

from tests import helpers  # noqa: F401
import status


class StatusTest(unittest.TestCase):
    def test_text_paths(self):
        summaries = {"version": 4, "intro": "x", "tldr": {"pick": "otp-1", "keys": ["a", "b"]},
                     "plan": {"abilities": {"1": "y"}, "counters": {"12": "z"}}, "sources": {"intro": ["analyse"]}}
        self.assertEqual(status.text_paths(summaries), ["intro", "tldr.keys[0]", "tldr.keys[1]", "plan.abilities.1"])

    def test_changelog_versions_are_sequential(self):
        versions = [c["version"] for c in status.CHANGELOG]
        self.assertEqual(versions, list(range(1, len(versions) + 1)))
        self.assertEqual(status.ANALYSIS_VERSION, versions[-1])

    def test_resolve_sources(self):
        candidates = [{"key": "otp-1", "source": "OTP", "author": "Kiwi"}]
        with contextlib.redirect_stdout(io.StringIO()) as out:
            resolved = status.resolve_sources({"sources": {"intro": ["build:otp-1", "stat:roles", "nope"]}}, candidates, None, None)
        self.assertIn("nope", out.getvalue())
        labels = [x["label"] for x in resolved["intro"]]
        self.assertEqual(labels[0], "Build OTP de Kiwi")
        self.assertTrue(resolved["intro"][2]["bad"])


if __name__ == "__main__":
    unittest.main()
