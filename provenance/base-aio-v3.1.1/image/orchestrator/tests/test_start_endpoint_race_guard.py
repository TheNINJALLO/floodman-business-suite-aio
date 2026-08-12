from pathlib import Path


def test_start_endpoint_waits_before_opening_idempotency_transaction() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    helper_marker = "def _wait_for_start_reconciliation("
    route_marker = '@app.post("/internal/v1/jobs/{job_id}/start")'
    helper_start = source.index(helper_marker)
    route_start = source.index(route_marker, helper_start)
    route_source = source[route_start:]

    assert "time.sleep(max(0.05, poll_seconds))" in source[helper_start:route_start]
    assert "preflight_job, preflight_decision = _wait_for_start_reconciliation(job_id)" in route_source
    assert route_source.index("_wait_for_start_reconciliation(job_id)") < route_source.index(
        'return _idempotent(f"start:{job_id}"'
    )
    assert "@app.exception_handler(InvalidTransition)" in source
