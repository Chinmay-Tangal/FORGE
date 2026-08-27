"""
tests/test_utils.py — Tests for forge.utils shared helpers.
"""
from __future__ import annotations

from forge.utils import count_tokens


class TestCountTokens:
    def test_empty_string(self):
        assert count_tokens("") == 0

    def test_single_word(self):
        # 1 word * 1.3 = 1 (int truncation)
        assert count_tokens("hello") == 1

    def test_ten_words(self):
        text = " ".join(["word"] * 10)
        assert count_tokens(text) == int(10 * 1.3)  # 13

    def test_scales_linearly(self):
        text_100 = " ".join(["x"] * 100)
        text_200 = " ".join(["x"] * 200)
        assert count_tokens(text_200) == 2 * count_tokens(text_100)

    def test_returns_int(self):
        assert isinstance(count_tokens("a b c"), int)
