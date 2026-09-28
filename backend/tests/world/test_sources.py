"""Pure tests for publisher grouping and source-independence classification."""

from __future__ import annotations

from datetime import UTC, datetime

from app.world.sources import SourceIndependence, classify_independence, source_group
from app.world.types import SourceRef

T0 = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)


def ref(name: str, url: str | None = None, **kw) -> SourceRef:
    return SourceRef(provider="replay", source_name=name, source_url=url, retrieved_at=T0, **kw)


def test_four_distinct_publishers_all_independent():
    refs = [
        ref("Reuters", "https://www.reuters.com/a"),
        ref("Bloomberg", "https://www.bloomberg.com/b"),
        ref("Associated Press", "https://apnews.com/c"),
        ref("BBC News", "https://www.bbc.co.uk/d"),
    ]
    res = classify_independence(refs)
    assert [r.group for r in res] == ["reuters", "bloomberg", "ap", "bbc"]
    assert all(r.independent and r.syndicated_of is None for r in res)


def test_reuters_plus_three_republications_crediting_reuters():
    refs = [
        ref("Reuters", "https://reuters.com/x", headline="Hormuz tanker attacked"),
        ref(
            "Daily Local",
            "https://dailylocal.example/y",
            headline="Hormuz tanker attacked (Reuters)",
        ),
        ref(
            "Metro Post",
            "https://metropost.example/z",
            headline="Tanker attacked",
            syndicated_from="Reuters",
        ),
        ref(
            "Town Gazette",
            None,
            headline="Tanker news",
            metadata={"byline": "By Jane Doe, Reuters"},
        ),
    ]
    res = classify_independence(refs)
    assert [r.independent for r in res] == [True, False, False, False]
    assert [r.syndicated_of for r in res] == [None, "reuters", "reuters", "reuters"]
    assert [r.group for r in res][1:] == ["dailylocal.example", "metropost.example", "town_gazette"]


def test_order_independent_original_after_copies():
    refs = [
        ref("Daily Local", None, headline="Oil jumps - via Reuters"),
        ref("Reuters", "https://reuters.com/x"),
    ]
    res = classify_independence(refs)
    assert [r.independent for r in res] == [False, True]
    assert res[0].syndicated_of == "reuters"


def test_credit_copy_without_original_counts_once():
    refs = [
        ref("Daily Local", None, headline="Oil jumps (Reuters)"),
        ref("Metro Post", None, headline="Oil jumps, Reuters contributed to this report"),
    ]
    res = classify_independence(refs)
    assert [r.independent for r in res] == [True, False]
    assert [r.syndicated_of for r in res] == ["reuters", "reuters"]


def test_same_publisher_twice_is_duplicate():
    res = classify_independence(
        [
            ref("Bloomberg", "https://bloomberg.com/1"),
            ref("Bloomberg News", "https://www.bloomberg.com/2"),
        ]
    )
    assert res[0] == SourceIndependence(0, "bloomberg", True, None)
    assert res[1] == SourceIndependence(1, "bloomberg", False, "bloomberg")


def test_self_credit_is_not_syndication():
    res = classify_independence([ref("Reuters", None, headline="Oil jumps (Reuters)")])
    assert res == [SourceIndependence(0, "reuters", True, None)]


def test_url_domain_grouping():
    assert source_group("whatever", "https://feeds.reuters.com/x") == "reuters"
    assert source_group("", "https://www.bbc.co.uk/news/1") == "bbc"
    assert source_group("", "https://www.bbc.com/news/1") == "bbc"
    assert source_group("", "https://asia.nikkei.com/a") == "nikkei"
    assert source_group("", "https://english.news.cn/a") == "xinhua"
    assert source_group("", "https://www.wsj.com/a") == "dow_jones"
    assert source_group("Something", "https://blog.example.co.uk/a") == "example.co.uk"
    assert source_group("Foo", "www.Example.com:8080/x") == "example.com"
    # domain wins over a conflicting name for a known publisher domain
    assert source_group("Yahoo Finance", "https://reuters.com/x") == "reuters"


def test_name_grouping_and_unknowns():
    assert source_group("The Associated Press", None) == "ap"
    assert source_group("AP", None) == "ap"
    assert source_group("Dow Jones Newswires", None) == "dow_jones"
    assert source_group("Wall Street Journal", None) == "dow_jones"
    assert source_group("Al-Jazeera English", None) == "al_jazeera"
    assert source_group("Reuters Business", None) == "reuters"
    assert source_group("Agence France-Presse", None) == "afp"
    assert source_group("Local Herald, Inc.", None) == "local_herald"
    assert source_group("Google News", None) == "google_news"
    assert source_group("World Monitor", None) == "world_monitor"
    assert source_group("Investing.com", None) == "investing_com"
    assert source_group("", None) == "unknown"


def test_aggregator_domain_defers_to_known_name():
    assert source_group("Reuters", "https://finance.yahoo.com/news/x") == "reuters"
    assert source_group("Yahoo Finance", "https://finance.yahoo.com/news/x") == "yahoo_finance"
    assert source_group("Some Blog", "https://uk.finance.yahoo.com/x") == "yahoo_finance"
    assert source_group("", "https://news.google.com/rss/1") == "google_news"


def test_aggregator_with_origin_is_never_independent():
    refs = [
        ref("Yahoo Finance", "https://finance.yahoo.com/a", headline="Oil jumps (Reuters)"),
        ref("MSN", "https://www.msn.com/b", metadata={"byline": "Reuters"}),
        ref("World Monitor", None, syndicated_from="Bloomberg"),
    ]
    res = classify_independence(refs)
    assert [r.independent for r in res] == [False, False, False]
    assert [r.group for r in res] == ["yahoo_finance", "msn", "world_monitor"]
    assert [r.syndicated_of for r in res] == ["reuters", "reuters", "bloomberg"]


def test_aggregator_with_origin_present_does_not_add_independence():
    refs = [
        ref("Reuters", "https://reuters.com/x"),
        ref("Yahoo Finance", "https://finance.yahoo.com/a", headline="Oil jumps via Reuters"),
    ]
    res = classify_independence(refs)
    assert [r.independent for r in res] == [True, False]


def test_aggregator_without_origin_counts_independent_once():
    refs = [
        ref("Yahoo Finance", "https://finance.yahoo.com/a", headline="Oil jumps"),
        ref("Yahoo Finance", "https://finance.yahoo.com/b", headline="Oil jumps again"),
        ref("Reuters", "https://reuters.com/x"),
    ]
    res = classify_independence(refs)
    assert [r.independent for r in res] == [True, False, True]
    assert res[1].syndicated_of == "yahoo_finance"


def test_markers_and_no_false_positive_on_citation():
    refs = [
        ref("A Paper", None, headline="Oil jumps, according to Reuters"),
        ref("B Paper", None, headline="Reuters contributed to this report on oil"),
        ref("C Paper", None, headline="Oil steady", metadata={"byline": "Staff writer"}),
    ]
    res = classify_independence(refs)
    assert [r.independent for r in res] == [True, True, True]
    assert res[1].syndicated_of == "reuters"
    assert res[0].syndicated_of is None
    assert res[2].syndicated_of is None


def test_provider_source_group_override_and_syndicated_from_domain():
    refs = [
        ref("X", None, source_group="Reuters"),
        ref("Y", None, syndicated_from="https://www.reuters.com/"),
    ]
    res = classify_independence(refs)
    assert res[0].group == "reuters"
    assert [r.independent for r in res] == [True, False]


def test_missing_url_and_name_graceful():
    refs = [ref("", None), ref("   ", "not a url at all"), ref("", "https://")]
    res = classify_independence(refs)
    assert [r.group for r in res] == ["unknown", "unknown", "unknown"]
    assert [r.independent for r in res] == [True, False, False]
    assert source_group("", "http://[bad") == "unknown"


def test_empty_list_and_determinism():
    assert classify_independence([]) == []
    refs = [
        ref("Reuters", None),
        ref("Local", None, headline="x (Reuters)"),
        ref("Bloomberg", None),
    ]
    assert classify_independence(refs) == classify_independence(list(refs))
    assert [r.ref_index for r in classify_independence(refs)] == [0, 1, 2]
