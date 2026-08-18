from __future__ import annotations

import json
import math
from pathlib import Path

from app.roomflow_capture import (
    CaptureValidationError,
    feet_to_meters,
    interior_angles,
    meters_to_feet,
    migrate_capture_room,
    orthogonal_snap,
    perimeter,
    polygon_area,
    serialize_capture,
    stabilize_point_samples,
    surface_measurements,
    validate_openings,
    validate_polygon,
)


FIXTURES = Path(__file__).parent / "fixtures" / "roomflow_capture" / "geometry-cases.json"


def close(actual: float, expected: float, tolerance: float = 1e-8) -> None:
    assert math.isclose(actual, expected, abs_tol=tolerance), (actual, expected)


def raises(message: str, callback) -> None:
    try:
        callback()
    except CaptureValidationError as exc:
        assert message in str(exc), str(exc)
    else:
        raise AssertionError(f"expected CaptureValidationError containing {message!r}")


def run() -> None:
    fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
    rectangle = fixtures["rectangle"]
    close(polygon_area(rectangle["vertices"]), 120)
    close(perimeter(rectangle["vertices"]), 44)
    surfaces = surface_measurements(rectangle["vertices"], 8, rectangle["openings"])
    close(surfaces["grossWallArea"], 352)
    close(surfaces["netWallArea"], 315.6)

    l_shape = fixtures["lShape"]
    close(polygon_area(l_shape["vertices"]), 75)
    close(perimeter(l_shape["vertices"]), 40)

    raises("cross", lambda: validate_polygon([(0, 0), (5, 5), (0, 5), (5, 0)]))
    raises("duplicate", lambda: validate_polygon([(0, 0), (5, 0), (5, 0), (0, 5)]))

    snapped, correction_count = orthogonal_snap([(0, 0), (10, 0), (10.1, 10), (0, 10)], 3)
    assert correction_count >= 1
    close(interior_angles(snapped)[1], 90, 1e-6)
    angled = [(0, 0), (10, 0), (13, 8), (0, 8)]
    preserved, _ = orthogonal_snap(angled, 3)
    close(preserved[2].x, 13)

    for feet in (0, 1, 12.5, 300):
        close(meters_to_feet(feet_to_meters(feet)), feet)

    stabilized = stabilize_point_samples([
        {"x": 9.7, "y": 12.1, "confidence": 0.8, "trackingState": "TRACKING", "depthValidated": True},
        {"x": 10.0, "y": 12.0, "confidence": 0.9, "trackingState": "TRACKING", "depthValidated": True},
        {"x": 10.2, "y": 11.9, "confidence": 0.85, "trackingState": "TRACKING", "depthValidated": True},
        {"x": 99, "y": 99, "confidence": 0.2, "trackingState": "PAUSED"},
    ])
    close(stabilized["x"], 10)
    close(stabilized["y"], 12)
    assert stabilized["depthValidated"] is True

    raises(
        "fit inside",
        lambda: validate_openings(
            [{"type": "door", "wallSegmentIndex": 0, "offset": 9, "width": 3, "height": 6, "sillHeight": 0}],
            rectangle["vertices"],
            8,
        ),
    )

    legacy = {"id": "legacy-room", "jobId": "job-1", "workspaceId": "workspace-1", "name": "Legacy Room", "w": 10, "l": 12, "h": 8}
    migrated = migrate_capture_room(legacy)
    assert migrated["roomId"] == "legacy-room"
    assert migrated["w"] == 10 and migrated["l"] == 12 and migrated["h"] == 8
    assert len(migrated["vertices"]) == 4
    assert migrate_capture_room(migrated) == migrated

    captured = {
        **legacy,
        "roomId": "captured-room",
        "vertices": rectangle["vertices"],
        "openings": rectangle["openings"],
        "scanMetadata": fixtures["captureMetadata"],
    }
    restored = json.loads(serialize_capture(captured))
    assert restored["scanMetadata"] == fixtures["captureMetadata"]
    assert restored["scanMetadata"]["rawCaptureRetained"] is False

    print("PASS: RoomFlow Capture schema migration and 12 geometry contracts")


if __name__ == "__main__":
    run()
