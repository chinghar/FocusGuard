"""Regression tests for DistractionListManager normalization.

Pure Python, no macOS/AppKit dependencies, so these run anywhere with
`python -m unittest` — no extra tooling required.
"""

from __future__ import annotations

import unittest

from focusguard.distraction_list import DistractionListManager, normalize_domain


class NormalizeDomainTests(unittest.TestCase):
    def test_strips_scheme_and_www_and_path(self) -> None:
        self.assertEqual(normalize_domain("https://www.Reddit.com/r/all"), "reddit.com")

    def test_lowercases_and_trims_whitespace(self) -> None:
        self.assertEqual(normalize_domain("  TikTok.com  "), "tiktok.com")


class DistractionListManagerRemovalTests(unittest.TestCase):
    def _manager(self) -> DistractionListManager:
        config = {"distractions": {"apps": ["Instagram"], "domains": ["reddit.com"]}}
        return DistractionListManager(config)

    def test_remove_domain_normalizes_input(self) -> None:
        manager = self._manager()
        manager.remove_domain("https://Reddit.com/")
        self.assertEqual(manager.domains, [])

    def test_remove_app_normalizes_input(self) -> None:
        manager = self._manager()
        manager.remove_app("  Instagram  ")
        self.assertEqual(manager.apps, [])


if __name__ == "__main__":
    unittest.main()
