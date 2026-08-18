import Foundation
import simd

let roomFlowCaptureSchemaVersion = 2
let roomFlowFeetPerMeter = 3.280839895013123

struct RoomFlowCapturePayload {
    let sessionID: String
    let jobID: String
    let workspaceID: String
    let levelID: String
    let roomID: String
    let name: String
    let roomType: String
    let defaultHeightFeet: Double
    let requestedMode: String

    init(_ value: [String: Any]) throws {
        func text(_ name: String) -> String {
            (value[name] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        }
        jobID = text("jobId")
        workspaceID = text("workspaceId")
        guard !jobID.isEmpty, !workspaceID.isEmpty else {
            throw RoomFlowCaptureError.invalid("Save the job and choose its Floodman company before scanning a room.")
        }
        sessionID = text("sessionId").isEmpty ? UUID().uuidString : text("sessionId")
        levelID = text("levelId").isEmpty ? "main" : text("levelId")
        roomID = text("roomId").isEmpty ? UUID().uuidString : text("roomId")
        name = text("name").isEmpty ? "Room" : text("name")
        roomType = text("roomType").isEmpty ? "other" : text("roomType")
        defaultHeightFeet = (value["defaultHeightFeet"] as? NSNumber)?.doubleValue ?? 8
        requestedMode = text("mode")
    }
}

struct RoomFlowCapturePoint {
    let xMeters: Double
    let zMeters: Double
    let confidence: Double
    let depthValidated: Bool
}

struct RoomFlowMeasuredWall {
    let id: UUID
    let center: SIMD2<Float>
    let axis: SIMD2<Float>
    let lengthMeters: Float
    let confidence: Double
}

struct RoomFlowMeasuredOutline {
    let points: [RoomFlowCapturePoint]
    let wallSegments: [UUID: Int]
}

enum RoomFlowMeasuredOutlineBuilder {
    private struct Node {
        var position: SIMD2<Float>
        var confidenceTotal: Double
        var sampleCount: Int
    }

    private struct Edge {
        let first: Int
        let second: Int
        let wallID: UUID
    }

    static func build(walls: [RoomFlowMeasuredWall]) throws -> RoomFlowMeasuredOutline {
        var nodes: [Node] = []
        var edges: [Edge] = []
        func nodeIndex(_ point: SIMD2<Float>, confidence: Double) -> Int {
            if let index = nodes.indices.min(by: { simd_distance(nodes[$0].position, point) < simd_distance(nodes[$1].position, point) }),
               simd_distance(nodes[index].position, point) <= 0.25 {
                let count = Float(nodes[index].sampleCount)
                nodes[index].position = (nodes[index].position * count + point) / (count + 1)
                nodes[index].confidenceTotal += confidence
                nodes[index].sampleCount += 1
                return index
            }
            nodes.append(Node(position: point, confidenceTotal: confidence, sampleCount: 1))
            return nodes.count - 1
        }
        for wall in walls where wall.lengthMeters >= 0.075 && simd_length(wall.axis) > 0.001 {
            let axis = simd_normalize(wall.axis)
            let half = axis * (wall.lengthMeters / 2)
            let first = nodeIndex(wall.center - half, confidence: wall.confidence)
            let second = nodeIndex(wall.center + half, confidence: wall.confidence)
            if first != second { edges.append(Edge(first: first, second: second, wallID: wall.id)) }
        }
        guard nodes.count >= 3, edges.count >= 3 else {
            throw RoomFlowCaptureError.invalid("RoomPlan did not find a complete room outline. Scan every wall or enter the room manually.")
        }
        let start = nodes.indices.min { left, right in
            nodes[left].position.x == nodes[right].position.x
                ? nodes[left].position.y < nodes[right].position.y
                : nodes[left].position.x < nodes[right].position.x
        }!
        var ordered: [Int] = []
        var wallSegments: [UUID: Int] = [:]
        var used = Set<Int>()
        var current = start
        while ordered.count <= nodes.count {
            ordered.append(current)
            guard let edgeIndex = edges.indices.first(where: { index in
                !used.contains(index) && (edges[index].first == current || edges[index].second == current)
            }) else { break }
            used.insert(edgeIndex)
            wallSegments[edges[edgeIndex].wallID] = ordered.count - 1
            current = edges[edgeIndex].first == current ? edges[edgeIndex].second : edges[edgeIndex].first
            if current == start { break }
        }
        guard current == start, ordered.count >= 3, used.count == edges.count else {
            throw RoomFlowCaptureError.invalid("RoomPlan found gaps or overlapping walls. Rescan the room or enter it manually.")
        }
        let points = ordered.map { index in
            RoomFlowCapturePoint(
                xMeters: Double(nodes[index].position.x),
                zMeters: Double(nodes[index].position.y),
                confidence: nodes[index].confidenceTotal / Double(nodes[index].sampleCount),
                depthValidated: true
            )
        }
        try RoomFlowCaptureResultBuilder.validate(points)
        return RoomFlowMeasuredOutline(points: points, wallSegments: wallSegments)
    }
}

enum RoomFlowCaptureError: Error, LocalizedError {
    case cancelled
    case interrupted
    case invalid(String)

    var errorDescription: String? {
        switch self {
        case .cancelled:
            return "Room scanning was cancelled. Your existing job was not changed."
        case .interrupted:
            return "Room scanning stopped when Floodman left the foreground. Start again or enter the room manually."
        case .invalid(let message):
            return message
        }
    }

    var code: String {
        switch self {
        case .cancelled: return "CAPTURE_CANCELLED"
        case .interrupted: return "CAPTURE_INTERRUPTED"
        case .invalid: return "INVALID_CAPTURE"
        }
    }
}

enum RoomFlowCaptureResultBuilder {
    static func build(
        payload: RoomFlowCapturePayload,
        points: [RoomFlowCapturePoint],
        heightFeet: Double,
        mode: String,
        platform: String = "ios",
        openings: [[String: Any]] = [],
        warnings: [String] = [],
        startedAt: Date
    ) throws -> [String: Any] {
        try validate(points)
        guard heightFeet > 0, heightFeet <= 40 else {
            throw RoomFlowCaptureError.invalid("Ceiling height must be between 0 and 40 ft.")
        }
        let origin = points[0]
        let vertices: [[String: Any]] = points.enumerated().map { index, point in
            [
                "id": "vertex-\(index + 1)",
                "x": (point.xMeters - origin.xMeters) * roomFlowFeetPerMeter,
                "y": (point.zMeters - origin.zMeters) * roomFlowFeetPerMeter,
                "confidence": min(1, max(0, point.confidence)),
                "depthValidated": point.depthValidated,
                "source": mode,
            ]
        }
        let xs = vertices.compactMap { $0["x"] as? Double }
        let ys = vertices.compactMap { $0["y"] as? Double }
        let averageConfidence = points.map(\.confidence).reduce(0, +) / Double(points.count)
        let depthCount = points.filter(\.depthValidated).count
        let formatter = ISO8601DateFormatter()
        return [
            "schemaVersion": roomFlowCaptureSchemaVersion,
            "sessionId": payload.sessionID,
            "jobId": payload.jobID,
            "workspaceId": payload.workspaceID,
            "levelId": payload.levelID,
            "roomId": payload.roomID,
            "name": payload.name,
            "roomType": payload.roomType,
            "units": "ft",
            "height": heightFeet,
            "vertices": vertices,
            "openings": openings,
            "affectedAreas": [],
            "scanMetadata": [
                "captureMode": mode,
                "platform": platform,
                "startedAt": formatter.string(from: startedAt),
                "completedAt": formatter.string(from: Date()),
                "pointCount": points.count,
                "averageConfidence": averageConfidence,
                "depthValidatedPointCount": depthCount,
                "automaticCorrectionCount": 0,
                "manualCorrectionCount": 0,
                "verificationRequired": averageConfidence < 0.9 || depthCount < points.count,
                "rawCaptureRetained": false,
                "trackingWarnings": warnings,
            ],
            "w": (xs.max() ?? 0) - (xs.min() ?? 0),
            "l": (ys.max() ?? 0) - (ys.min() ?? 0),
            "h": heightFeet,
        ]
    }

    static func validate(_ points: [RoomFlowCapturePoint]) throws {
        guard points.count >= 3 else { throw RoomFlowCaptureError.invalid("Capture at least three room corners.") }
        guard points.count <= 128 else { throw RoomFlowCaptureError.invalid("A room cannot contain more than 128 corners.") }
        for index in points.indices {
            let next = points[(index + 1) % points.count]
            if distance(points[index], next) * roomFlowFeetPerMeter < 0.25 {
                throw RoomFlowCaptureError.invalid("Every wall must be at least 0.25 ft.")
            }
        }
        guard polygonArea(points) > 0.000001 else { throw RoomFlowCaptureError.invalid("Room area must be greater than zero.") }
        guard !selfIntersects(points) else { throw RoomFlowCaptureError.invalid("Room walls cannot cross each other.") }
    }

    static func distance(_ first: RoomFlowCapturePoint, _ second: RoomFlowCapturePoint) -> Double {
        hypot(second.xMeters - first.xMeters, second.zMeters - first.zMeters)
    }

    static func polygonArea(_ points: [RoomFlowCapturePoint]) -> Double {
        abs(points.indices.reduce(0) { result, index in
            let next = points[(index + 1) % points.count]
            return result + points[index].xMeters * next.zMeters - next.xMeters * points[index].zMeters
        }) / 2
    }

    private static func selfIntersects(_ points: [RoomFlowCapturePoint]) -> Bool {
        func orientation(_ a: RoomFlowCapturePoint, _ b: RoomFlowCapturePoint, _ c: RoomFlowCapturePoint) -> Double {
            (b.xMeters - a.xMeters) * (c.zMeters - a.zMeters) - (b.zMeters - a.zMeters) * (c.xMeters - a.xMeters)
        }
        func intersects(_ a: RoomFlowCapturePoint, _ b: RoomFlowCapturePoint, _ c: RoomFlowCapturePoint, _ d: RoomFlowCapturePoint) -> Bool {
            let values = (orientation(a, b, c), orientation(a, b, d), orientation(c, d, a), orientation(c, d, b))
            return ((values.0 > 0 && values.1 < 0) || (values.0 < 0 && values.1 > 0))
                && ((values.2 > 0 && values.3 < 0) || (values.2 < 0 && values.3 > 0))
        }
        for first in points.indices {
            for second in (first + 1)..<points.count {
                if second == first + 1 || (first == 0 && second == points.count - 1) { continue }
                if intersects(points[first], points[(first + 1) % points.count], points[second], points[(second + 1) % points.count]) { return true }
            }
        }
        return false
    }
}
