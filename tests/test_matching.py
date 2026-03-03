"""Tests for the fuzzy answer matching engine."""

from trivia.matching.fuzzy import MatchResult, check_answer
from trivia.matching.normalizer import (
    extract_last_name,
    is_year,
    normalize,
    try_parse_number,
)
from trivia.matching.aliases import are_aliases, get_aliases


class TestNormalizer:
    def test_basic_normalization(self):
        assert normalize("  Hello, World!  ") == "hello world"

    def test_strips_leading_articles(self):
        assert normalize("The United States") == "united states"
        assert normalize("A cat") == "cat"
        assert normalize("An apple") == "apple"

    def test_collapses_whitespace(self):
        assert normalize("too   many    spaces") == "too many spaces"

    def test_strips_punctuation(self):
        assert normalize("it's a test!") == "its a test"

    def test_unicode_normalization(self):
        assert normalize("café") == "cafe"

    def test_is_year(self):
        assert is_year("1969") is True
        assert is_year("2024") is True
        assert is_year("500") is False
        assert is_year("hello") is False
        assert is_year("12345") is False

    def test_try_parse_number(self):
        assert try_parse_number("42") == 42.0
        assert try_parse_number("3.14") == 3.14
        assert try_parse_number("1,000") == 1000.0
        assert try_parse_number("hello") is None

    def test_extract_last_name(self):
        assert extract_last_name("Albert Einstein") == "einstein"
        assert extract_last_name("Einstein") is None
        assert extract_last_name("Martin Luther King Jr") == "jr"


class TestAliases:
    def test_known_aliases(self):
        assert are_aliases("USA", "United States of America") is True
        assert are_aliases("uk", "United Kingdom") is True
        assert are_aliases("NYC", "New York City") is True

    def test_unknown_not_aliased(self):
        assert are_aliases("Paris", "London") is False

    def test_same_string(self):
        assert are_aliases("hello", "hello") is True

    def test_get_aliases_returns_set(self):
        aliases = get_aliases("usa")
        assert "united states" in aliases
        assert "america" in aliases


class TestFuzzyMatching:
    def test_exact_match(self):
        result = check_answer("Paris", "Paris")
        assert result.is_correct

    def test_case_insensitive(self):
        result = check_answer("paris", "Paris")
        assert result.is_correct

    def test_with_article(self):
        result = check_answer("The Beatles", "Beatles")
        assert result.is_correct

    def test_fuzzy_partial(self):
        result = check_answer("Return of the King", "The Lord of the Rings: The Return of the King")
        assert result.is_correct

    def test_last_name_match(self):
        result = check_answer("Einstein", "Albert Einstein")
        assert result.is_correct

    def test_year_exact_only(self):
        result = check_answer("1968", "1969")
        assert not result.is_correct
        assert not result.is_close

    def test_year_correct(self):
        result = check_answer("1969", "1969")
        assert result.is_correct

    def test_alias_match(self):
        result = check_answer("USA", "United States of America")
        assert result.is_correct

    def test_number_match(self):
        result = check_answer("42", "42")
        assert result.is_correct

    def test_wrong_answer(self):
        result = check_answer("Tokyo", "Paris")
        assert not result.is_correct
        assert not result.is_close

    def test_close_answer(self):
        result = check_answer("Pari", "Paris")
        assert result.is_correct or result.is_close

    def test_empty_answer(self):
        result = check_answer("", "Paris")
        assert not result.is_correct

    def test_alternate_answers(self):
        result = check_answer("NYC", "New York City", ["NYC", "Big Apple"])
        assert result.is_correct

    def test_dna_alias(self):
        result = check_answer("DNA", "Deoxyribonucleic Acid")
        assert result.is_correct
