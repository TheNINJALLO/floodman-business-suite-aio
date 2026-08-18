from __future__ import annotations

import json
import math
import uuid
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = 2
FEET_PER_METER = 3.280839895013123
DEFAULT_MINIMUM_SEGMENT_FEET = 0.25
DEFAULT_MAXIMUM_DIMENSION_FEET = 300.0
DEFAULT_SNAP_TOLERANCE_DEGREES = 3.0
POINT_EPSILON = 1e-7


class CaptureValidationError(ValueError):
    """A user-correctable problem in captured room geometry."""


@dataclass(frozen=True)
class Point:
    x: float
    y: float


def feet_to_meters(value: float) -> float:
    return _finite(value, "feet") / FEET_PER_METER


def meters_to_feet(value: float) -> float:
    return _finite(value, "meters") * FEET_PER_METER


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise CaptureValidationError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CaptureValidationError(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise CaptureValidationError(f"{label} must be a finite number")
    return result


def _point(value: Mapping[str, Any] | Sequence[float] | Point, index: int = 0) -> Point:
    if isinstance(value, Point):
        return value
    if isinstance(value, Mapping):
        return Point(_finite(value.get("x"), f"vertex {index + 1} x"), _finite(value.get("y"), f"vertex {index + 1} y"))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) >= 2:
        return Point(_finite(value[0], f"vertex {index + 1} x"), _finite(value[1], f"vertex {index + 1} y"))
    raise CaptureValidationError(f"vertex {index + 1} must contain x and y")


def points(vertices: Iterable[Mapping[str, Any] | Sequence[float] | Point]) -> list[Point]:
    result = [_point(value, index) for index, value in enumerate(vertices)]
    if len(result) > 1 and point_distance(result[0], result[-1]) <= POINT_EPSILON:
        result.pop()
    return result


def point_distance(first: Point, second: Point) -> float:
    return math.hypot(second.x - first.x, second.y - first.y)


def closed_vertices(vertices: Iterable[Mapping[str, Any] | Sequence[float] | Point]) -> list[Point]:
    result = points(vertices)
    return result + [result[0]] if result else []


def signed_area(vertices: Iterable[Mapping[str, Any] | Sequence[float] | Point]) -> float:
    polygon = points(vertices)
    if len(polygon) < 3:
        return 0.0
    return sum(
        polygon[index].x * polygon[(index + 1) % len(polygon)].y
        - polygon[(index + 1) % len(polygon)].x * polygon[index].y
        for index in range(len(polygon))
    ) / 2.0


def polygon_area(vertices: Iterable[Mapping[str, Any] | Sequence[float] | Point]) -> float:
    return abs(signed_area(vertices))


def normalize_winding(vertices: Iterable[Mapping[str, Any] | Sequence[float] | Point]) -> list[Point]:
    polygon = points(vertices)
    return list(reversed(polygon)) if signed_area(polygon) < 0 else polygon


def segments(vertices: Iterable[Mapping[str, Any] | Sequence[float] | Point]) -> list[tuple[Point, Point]]:
    polygon = points(vertices)
    return [(polygon[index], polygon[(index + 1) % len(polygon)]) for index in range(len(polygon))]


def segment_lengths(vertices: Iterable[Mapping[str, Any] | Sequence[float] | Point]) -> list[float]:
    return [point_distance(first, second) for first, second in segments(vertices)]


def perimeter(vertices: Iterable[Mapping[str, Any] | Sequence[float] | Point]) -> float:
    return sum(segment_lengths(vertices))


def interior_angles(vertices: Iterable[Mapping[str, Any] | Sequence[float] | Point]) -> list[float]:
    polygon = normalize_winding(vertices)
    result: list[float] = []
    for index, current in enumerate(polygon):
        previous = polygon[index - 1]
        following = polygon[(index + 1) % len(polygon)]
        a = (previous.x - current.x, previous.y - current.y)
        b = (following.x - current.x, following.y - current.y)
        denominator = math.hypot(*a) * math.hypot(*b)
        if denominator <= POINT_EPSILON:
            result.append(0.0)
            continue
        cosine = max(-1.0, min(1.0, (a[0] * b[0] + a[1] * b[1]) / denominator))
        angle = math.degrees(math.acos(cosine))
        cross = a[0] * b[1] - a[1] * b[0]
        result.append(360.0 - angle if cross > 0 else angle)
    return result


def bounding_box(vertices: Iterable[Mapping[str, Any] | Sequence[float] | Point]) -> dict[str, float]:
    polygon = points(vertices)
    if not polygon:
        raise CaptureValidationError("at least one vertex is required")
    min_x, max_x = min(p.x for p in polygon), max(p.x for p in polygon)
    min_y, max_y = min(p.y for p in polygon), max(p.y for p in polygon)
    return {"minX": min_x, "minY": min_y, "maxX": max_x, "maxY": max_y, "width": max_x - min_x, "length": max_y - min_y}


def translate_to_local(vertices: Iterable[Mapping[str, Any] | Sequence[float] | Point]) -> list[Point]:
    polygon = points(vertices)
    if not polygon:
        return []
    origin = polygon[0]
    return [Point(value.x - origin.x, value.y - origin.y) for value in polygon]


def rotate(vertices: Iterable[Mapping[str, Any] | Sequence[float] | Point], degrees: float, origin: Point | None = None) -> list[Point]:
    polygon = points(vertices)
    if not polygon:
        return []
    pivot = origin or polygon[0]
    radians = math.radians(_finite(degrees, "rotation"))
    cosine, sine = math.cos(radians), math.sin(radians)
    return [
        Point(
            pivot.x + (value.x - pivot.x) * cosine - (value.y - pivot.y) * sine,
            pivot.y + (value.x - pivot.x) * sine + (value.y - pivot.y) * cosine,
        )
        for value in polygon
    ]


def near_closure(vertices: Iterable[Mapping[str, Any] | Sequence[float] | Point], tolerance_feet: float = 0.5) -> bool:
    raw = [_point(value, index) for index, value in enumerate(vertices)]
    return len(raw) >= 3 and point_distance(raw[0], raw[-1]) <= _finite(tolerance_feet, "closure tolerance")


def _orientation(a: Point, b: Point, c: Point) -> float:
    return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)


def _on_segment(a: Point, b: Point, c: Point) -> bool:
    return min(a.x, c.x) - POINT_EPSILON <= b.x <= max(a.x, c.x) + POINT_EPSILON and min(a.y, c.y) - POINT_EPSILON <= b.y <= max(a.y, c.y) + POINT_EPSILON


def _segments_intersect(first: tuple[Point, Point], second: tuple[Point, Point]) -> bool:
    a, b = first
    c, d = second
    o1, o2, o3, o4 = _orientation(a, b, c), _orientation(a, b, d), _orientation(c, d, a), _orientation(c, d, b)
    if ((o1 > POINT_EPSILON and o2 < -POINT_EPSILON) or (o1 < -POINT_EPSILON and o2 > POINT_EPSILON)) and ((o3 > POINT_EPSILON and o4 < -POINT_EPSILON) or (o3 < -POINT_EPSILON and o4 > POINT_EPSILON)):
        return True
    return (
        abs(o1) <= POINT_EPSILON and _on_segment(a, c, b)
        or abs(o2) <= POINT_EPSILON and _on_segment(a, d, b)
        or abs(o3) <= POINT_EPSILON and _on_segment(c, a, d)
        or abs(o4) <= POINT_EPSILON and _on_segment(c, b, d)
    )


def is_self_intersecting(vertices: Iterable[Mapping[str, Any] | Sequence[float] | Point]) -> bool:
    edges = segments(vertices)
    for first_index, first in enumerate(edges):
        for second_index in range(first_index + 1, len(edges)):
            if second_index in {first_index, first_index + 1} or (first_index == 0 and second_index == len(edges) - 1):
                continue
            if _segments_intersect(first, edges[second_index]):
                return True
    return False


def validate_polygon(
    vertices: Iterable[Mapping[str, Any] | Sequence[float] | Point],
    *,
    minimum_segment_feet: float = DEFAULT_MINIMUM_SEGMENT_FEET,
    maximum_dimension_feet: float = DEFAULT_MAXIMUM_DIMENSION_FEET,
) -> list[Point]:
    polygon = points(vertices)
    if len(polygon) < 3:
        raise CaptureValidationError("a room requires at least three vertices")
    if len(polygon) > 128:
        raise CaptureValidationError("a room cannot contain more than 128 vertices")
    lengths = segment_lengths(polygon)
    if any(length <= POINT_EPSILON for length in lengths):
        raise CaptureValidationError("duplicate consecutive vertices are not allowed")
    minimum = _finite(minimum_segment_feet, "minimum wall length")
    if any(length < minimum for length in lengths):
        raise CaptureValidationError(f"each wall must be at least {minimum:g} ft")
    bounds = bounding_box(polygon)
    maximum = _finite(maximum_dimension_feet, "maximum room dimension")
    if bounds["width"] > maximum or bounds["length"] > maximum:
        raise CaptureValidationError(f"room dimensions cannot exceed {maximum:g} ft")
    if is_self_intersecting(polygon):
        raise CaptureValidationError("room walls cannot cross each other")
    if polygon_area(polygon) <= POINT_EPSILON:
        raise CaptureValidationError("room area must be greater than zero")
    return normalize_winding(polygon)


def orthogonal_snap(
    vertices: Iterable[Mapping[str, Any] | Sequence[float] | Point],
    tolerance_degrees: float = DEFAULT_SNAP_TOLERANCE_DEGREES,
) -> tuple[list[Point], int]:
    polygon = validate_polygon(vertices)
    tolerance = max(0.0, _finite(tolerance_degrees, "snap tolerance"))
    if len(polygon) < 3 or tolerance == 0:
        return polygon, 0
    result = [polygon[0], polygon[1]]
    previous_angle = math.atan2(polygon[1].y - polygon[0].y, polygon[1].x - polygon[0].x)
    corrections = 0
    for index in range(1, len(polygon) - 1):
        source_start, source_end = polygon[index], polygon[index + 1]
        length = point_distance(source_start, source_end)
        angle = math.atan2(source_end.y - source_start.y, source_end.x - source_start.x)
        turn = math.degrees(math.atan2(math.sin(angle - previous_angle), math.cos(angle - previous_angle)))
        nearest_quarter_turn = round(turn / 90.0) * 90.0
        if abs(turn - nearest_quarter_turn) <= tolerance:
            angle = previous_angle + math.radians(nearest_quarter_turn)
            corrections += 1
        result.append(Point(result[-1].x + length * math.cos(angle), result[-1].y + length * math.sin(angle)))
        previous_angle = angle
    try:
        return validate_polygon(result), corrections
    except CaptureValidationError:
        return polygon, 0


def stabilize_point_samples(
    samples: Iterable[Mapping[str, Any]],
    *,
    minimum_confidence: float = 0.6,
    maximum_floor_deviation_feet: float = 0.5,
) -> dict[str, Any]:
    """Return a median floor-plane point from a recent trusted sample window."""

    confidence_floor = _finite(minimum_confidence, "minimum confidence")
    floor_limit = _finite(maximum_floor_deviation_feet, "maximum floor deviation")
    accepted: list[dict[str, Any]] = []
    for index, value in enumerate(samples):
        tracking = value.get("trackingState", "TRACKING")
        confidence = _finite(value.get("confidence", 0), f"sample {index + 1} confidence")
        floor_deviation = abs(_finite(value.get("floorDeviation", 0), f"sample {index + 1} floor deviation"))
        if tracking not in {True, "TRACKING", "tracking"} or confidence < confidence_floor or floor_deviation > floor_limit:
            continue
        accepted.append({**value, "x": _finite(value.get("x"), f"sample {index + 1} x"), "y": _finite(value.get("y"), f"sample {index + 1} y"), "confidence": confidence})
    if len(accepted) < 3:
        raise CaptureValidationError("hold steady until at least three reliable samples are available")
    ordered_x = sorted(value["x"] for value in accepted)
    ordered_y = sorted(value["y"] for value in accepted)
    midpoint = len(accepted) // 2
    median_x = ordered_x[midpoint] if len(accepted) % 2 else (ordered_x[midpoint - 1] + ordered_x[midpoint]) / 2
    median_y = ordered_y[midpoint] if len(accepted) % 2 else (ordered_y[midpoint - 1] + ordered_y[midpoint]) / 2
    depth_count = sum(1 for value in accepted if value.get("depthValidated"))
    base_confidence = sum(value["confidence"] for value in accepted) / len(accepted)
    adjusted_confidence = min(1.0, base_confidence + 0.05) if depth_count >= math.ceil(len(accepted) / 2) else max(0.0, base_confidence - 0.1)
    return {
        "x": median_x,
        "y": median_y,
        "confidence": adjusted_confidence,
        "depthValidated": depth_count >= math.ceil(len(accepted) / 2),
        "sampleCount": len(accepted),
        "verificationRequired": adjusted_confidence < 0.75,
    }


def override_wall_length(
    vertices: Iterable[Mapping[str, Any] | Sequence[float] | Point], wall_segment_index: int, length_feet: float
) -> list[Point]:
    polygon = validate_polygon(vertices)
    if wall_segment_index < 0 or wall_segment_index >= len(polygon):
        raise CaptureValidationError("wall segment does not exist")
    target_length = _finite(length_feet, "wall length")
    if target_length < DEFAULT_MINIMUM_SEGMENT_FEET:
        raise CaptureValidationError(f"wall length must be at least {DEFAULT_MINIMUM_SEGMENT_FEET:g} ft")
    start_index = wall_segment_index
    end_index = (wall_segment_index + 1) % len(polygon)
    start, end = polygon[start_index], polygon[end_index]
    current_length = point_distance(start, end)
    replacement = Point(start.x + (end.x - start.x) * target_length / current_length, start.y + (end.y - start.y) * target_length / current_length)
    adjusted = list(polygon)
    adjusted[end_index] = replacement
    return validate_polygon(adjusted)


def validate_openings(
    openings: Iterable[Mapping[str, Any]], vertices: Iterable[Mapping[str, Any] | Sequence[float] | Point], height_feet: float
) -> list[dict[str, Any]]:
    polygon = validate_polygon(vertices)
    lengths = segment_lengths(polygon)
    room_height = _finite(height_feet, "room height")
    if room_height <= 0:
        raise CaptureValidationError("room height must be greater than zero")
    result: list[dict[str, Any]] = []
    for index, source in enumerate(openings):
        opening = dict(source)
        segment_index = int(opening.get("wallSegmentIndex", -1))
        if segment_index < 0 or segment_index >= len(lengths):
            raise CaptureValidationError(f"opening {index + 1} must reference an existing wall")
        offset = _finite(opening.get("offset", 0), f"opening {index + 1} offset")
        width = _finite(opening.get("width"), f"opening {index + 1} width")
        sill = _finite(opening.get("sillHeight", 0), f"opening {index + 1} sill height")
        opening_height = _finite(opening.get("height", room_height if opening.get("type") == "open-wall" else 0), f"opening {index + 1} height")
        if offset < 0 or width <= 0 or offset + width > lengths[segment_index] + POINT_EPSILON:
            raise CaptureValidationError(f"opening {index + 1} must fit inside its wall")
        if sill < 0 or opening_height <= 0 or sill + opening_height > room_height + POINT_EPSILON:
            raise CaptureValidationError(f"opening {index + 1} must fit between floor and ceiling")
        opening.update(
            {
                "id": str(opening.get("id") or f"opening-{index + 1}"),
                "type": str(opening.get("type") or "opening"),
                "wallSegmentIndex": segment_index,
                "offset": offset,
                "width": width,
                "height": opening_height,
                "sillHeight": sill,
                "confidence": max(0.0, min(1.0, _finite(opening.get("confidence", 1), f"opening {index + 1} confidence"))),
                "source": str(opening.get("source") or "manual"),
            }
        )
        result.append(opening)
    return result


def surface_measurements(
    vertices: Iterable[Mapping[str, Any] | Sequence[float] | Point], height_feet: float, openings: Iterable[Mapping[str, Any]] = ()
) -> dict[str, float]:
    polygon = validate_polygon(vertices)
    height = _finite(height_feet, "room height")
    normalized_openings = validate_openings(openings, polygon, height)
    floor = polygon_area(polygon)
    gross_wall = perimeter(polygon) * height
    deductions = sum(value["width"] * value["height"] for value in normalized_openings)
    return {
        "floorArea": floor,
        "ceilingArea": floor,
        "perimeter": perimeter(polygon),
        "grossWallArea": gross_wall,
        "openingDeductions": deductions,
        "netWallArea": max(0.0, gross_wall - deductions),
    }


def _vertex_dict(value: Mapping[str, Any] | Sequence[float] | Point, index: int) -> dict[str, Any]:
    source = dict(value) if isinstance(value, Mapping) else {}
    value_point = _point(value, index)
    source.update(
        {
            "id": str(source.get("id") or f"vertex-{index + 1}"),
            "x": value_point.x,
            "y": value_point.y,
            "confidence": max(0.0, min(1.0, _finite(source.get("confidence", 1), f"vertex {index + 1} confidence"))),
            "depthValidated": bool(source.get("depthValidated", False)),
            "source": str(source.get("source") or "manual"),
        }
    )
    return source


def _stable_room_id(room: Mapping[str, Any]) -> str:
    key = json.dumps(
        {name: room.get(name) for name in ("jobId", "levelId", "name", "w", "l", "h")},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"floodman:roomflow-capture:{key}"))


def migrate_capture_room(room: Mapping[str, Any]) -> dict[str, Any]:
    """Idempotently migrate legacy rectangle rooms into capture schema v2."""

    result = deepcopy(dict(room))
    raw_vertices = result.get("vertices") or []
    if not raw_vertices:
        width = _finite(result.get("w", result.get("width")), "legacy room width")
        length = _finite(result.get("l", result.get("length")), "legacy room length")
        if width <= 0 or length <= 0:
            raise CaptureValidationError("legacy room dimensions must be greater than zero")
        raw_vertices = [(0, 0), (width, 0), (width, length), (0, length)]
    normalized_points = validate_polygon(raw_vertices)
    raw_by_coordinate: dict[tuple[float, float], Mapping[str, Any]] = {}
    for index, value in enumerate(raw_vertices):
        if isinstance(value, Mapping):
            source_point = _point(value, index)
            raw_by_coordinate[(source_point.x, source_point.y)] = value
    normalized_vertices = [
        _vertex_dict(raw_by_coordinate.get((value.x, value.y), {"x": value.x, "y": value.y}), index)
        for index, value in enumerate(normalized_points)
    ]
    height = _finite(result.get("height", result.get("h", 8)), "room height")
    if height <= 0 or height > 40:
        raise CaptureValidationError("room height must be between 0 and 40 ft")
    legacy_openings = result.get("openings") or []
    if not legacy_openings:
        legacy_openings = [
            {**value, "type": kind.rstrip("s")}
            for kind in ("doors", "windows")
            for value in result.get(kind, [])
            if isinstance(value, Mapping)
        ]
    normalized_openings = validate_openings(legacy_openings, normalized_points, height)
    bounds = bounding_box(normalized_points)
    metadata = dict(result.get("scanMetadata") or {})
    capture_mode = str(metadata.get("captureMode") or "legacy-manual")
    metadata.update(
        {
            "captureMode": capture_mode,
            "platform": str(metadata.get("platform") or "web"),
            "startedAt": metadata.get("startedAt"),
            "completedAt": metadata.get("completedAt"),
            "pointCount": len(normalized_vertices),
            "averageConfidence": max(0.0, min(1.0, _finite(metadata.get("averageConfidence", 1), "average confidence"))),
            "depthValidatedPointCount": int(metadata.get("depthValidatedPointCount", 0) or 0),
            "automaticCorrectionCount": int(metadata.get("automaticCorrectionCount", 0) or 0),
            "manualCorrectionCount": int(metadata.get("manualCorrectionCount", 0) or 0),
            "verificationRequired": bool(metadata.get("verificationRequired", capture_mode != "manual")),
            "rawCaptureRetained": False,
        }
    )
    result.update(
        {
            "schemaVersion": SCHEMA_VERSION,
            "sessionId": str(result.get("sessionId") or result.get("roomId") or _stable_room_id(result)),
            "jobId": str(result.get("jobId") or ""),
            "workspaceId": str(result.get("workspaceId") or ""),
            "levelId": str(result.get("levelId") or "main"),
            "roomId": str(result.get("roomId") or result.get("id") or _stable_room_id(result)),
            "name": str(result.get("name") or "Room"),
            "roomType": str(result.get("roomType") or result.get("type") or "other"),
            "units": "ft",
            "height": height,
            "vertices": normalized_vertices,
            "openings": normalized_openings,
            "affectedAreas": deepcopy(result.get("affectedAreas") or []),
            "scanMetadata": metadata,
            "w": bounds["width"],
            "l": bounds["length"],
            "h": height,
            "measurements": surface_measurements(normalized_points, height, normalized_openings),
        }
    )
    return result


def serialize_capture(room: Mapping[str, Any]) -> str:
    return json.dumps(migrate_capture_room(room), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
