"""Headline parsing and ticker tagging.

Tagging is pattern matching, not entity resolution, so these tests pin the
precision/recall trade-offs that were chosen deliberately. Every "should NOT
tag" case here is a false positive that actually appeared in a live feed.
"""

import pytest

from app.services import newsfeed as nf

MATCHERS = nf.build_matchers(
    [
        ("MAS", "Masco"),
        ("NVDA", "NVIDIA"),
        ("ROL", "Rollins"),
        ("IT", "Gartner"),
        ("A", "Agilent Technologies"),
        ("PANW", "Palo Alto Networks"),
        ("DELL", "Dell Technologies"),
    ]
)


def tag(text: str) -> list[str]:
    return nf.tag_symbols(text, MATCHERS)


class TestFalsePositives:
    """Real headlines that used to tag the wrong company."""

    def test_lowercase_plural_does_not_match_a_ticker(self):
        # "MAs" = moving averages. Case-insensitive matching made this MAS.
        assert tag("Nikkei 225 slides below all major MAs") == []

    def test_a_persons_surname_does_not_match_a_company(self):
        # Brooke Rollins is the USDA Secretary, not Rollins Inc.
        assert tag("Tyson disputes claim by USDA's Rollins") == []

    def test_common_word_tickers_are_never_matched(self):
        # "IT" and "A" would otherwise tag most headlines ever written.
        assert tag("The IT department bought a new server") == []
        assert tag("A quiet day for markets") == []


class TestTruePositives:
    def test_uppercase_ticker_matches(self):
        assert "MAS" in tag("MAS reports quarterly earnings")

    def test_company_name_matches_case_insensitively(self):
        assert "NVDA" in tag("Nvidia could seal a deal this week")
        assert "NVDA" in tag("NVIDIA beats estimates")

    def test_multiword_names_match(self):
        assert "PANW" in tag("Palo Alto Networks stock falls despite demand")

    def test_multiple_symbols_in_one_headline(self):
        hits = tag("Monday's biggest analyst calls: Nvidia, Dell Technologies")
        assert set(hits) >= {"NVDA", "DELL"}


class TestParsing:
    def test_canonical_url_drops_tracking_parameters(self):
        a = nf._canonical("https://example.com/story?utm_source=x&utm_medium=y")
        b = nf._canonical("https://example.com/story/")
        assert a == b

    def test_same_link_produces_the_same_guid(self):
        """Deduplication key must be stable, or every run re-inserts everything."""
        h1 = nf._hash(nf._canonical("https://example.com/a?utm=1"))
        h2 = nf._hash(nf._canonical("https://example.com/a"))
        assert h1 == h2

    def test_html_is_stripped_from_summaries(self):
        assert nf._clean("<p>Hello <b>world</b></p>") == "Hello world"

    @pytest.mark.parametrize(
        "raw",
        ["Mon, 01 Sep 2026 12:00:00 GMT", "2026-09-01T12:00:00Z", "2026-09-01T12:00:00+00:00"],
    )
    def test_date_formats_parse_to_aware_datetimes(self, raw):
        dt = nf._parse_date(raw)
        assert dt is not None and dt.tzinfo is not None

    def test_unparseable_date_is_none_not_an_exception(self):
        assert nf._parse_date("not a date") is None
        assert nf._parse_date(None) is None
