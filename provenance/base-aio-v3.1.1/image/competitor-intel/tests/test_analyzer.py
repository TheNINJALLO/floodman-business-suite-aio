from app.analyzer import changes, deterministic_report


def test_diff_tracks_prices_claims_and_pages() -> None:
    previous = {"pages": [{"url": "https://example.com", "sha256": "a"}], "prices": ["$10"], "service_claims": ["sump pump"]}
    current = {"pages": [{"url": "https://example.com", "sha256": "b"}], "prices": ["$20"], "service_claims": ["sump pump", "financing"]}
    result = changes(previous, current)
    assert result["changed_pages"] == ["https://example.com"]
    assert result["added_prices"] == ["$20"]
    assert result["removed_prices"] == ["$10"]
    assert result["added_service_claims"] == ["financing"]


def test_deterministic_report_contains_verification_warning() -> None:
    target = {"name": "Example"}
    data = {"service_claims": ["free estimate"], "prices": [], "headings": ["Basement Waterproofing"]}
    report = deterministic_report(target, data, {"changed_pages": ["https://example.com"]})
    assert report["claims_needing_human_verification"]
