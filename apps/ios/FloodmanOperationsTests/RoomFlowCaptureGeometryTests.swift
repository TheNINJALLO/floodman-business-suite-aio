import XCTest
@testable import FloodmanOperations

final class RoomFlowCaptureGeometryTests: XCTestCase {
    private func point(_ x: Double, _ z: Double, depth: Bool = true) -> RoomFlowCapturePoint {
        RoomFlowCapturePoint(xMeters: x, zMeters: z, confidence: 0.95, depthValidated: depth)
    }

    func testRectangleGeometryAndPrivacyMetadata() throws {
        let points = [point(0, 0), point(1, 0), point(1, 2), point(0, 2)]
        XCTAssertEqual(RoomFlowCaptureResultBuilder.polygonArea(points), 2, accuracy: 0.0001)
        let payload = try RoomFlowCapturePayload([
            "jobId": "job-1",
            "workspaceId": "workspace-1",
            "roomId": "room-1",
            "name": "Living Room",
            "roomType": "living-room",
        ])
        let result = try RoomFlowCaptureResultBuilder.build(
            payload: payload,
            points: points,
            heightFeet: 8,
            mode: "apple-roomplan",
            startedAt: Date(timeIntervalSince1970: 1_800_000_000)
        )
        let metadata = try XCTUnwrap(result["scanMetadata"] as? [String: Any])
        XCTAssertEqual(result["schemaVersion"] as? Int, 2)
        XCTAssertEqual(result["units"] as? String, "ft")
        XCTAssertEqual(try XCTUnwrap(result["w"] as? Double), roomFlowFeetPerMeter, accuracy: 0.001)
        XCTAssertEqual(try XCTUnwrap(result["l"] as? Double), 2 * roomFlowFeetPerMeter, accuracy: 0.001)
        XCTAssertEqual(metadata["rawCaptureRetained"] as? Bool, false)
    }

    func testCrossingWallsAreRejected() {
        let crossing = [point(0, 0), point(4, 3), point(0, 4), point(3, 0)]
        XCTAssertThrowsError(try RoomFlowCaptureResultBuilder.validate(crossing))
    }

    func testShortWallAndMissingScopeAreRejected() {
        XCTAssertThrowsError(try RoomFlowCaptureResultBuilder.validate([point(0, 0), point(0.01, 0), point(0, 2)]))
        XCTAssertThrowsError(try RoomFlowCapturePayload(["jobId": "job-1"]))
    }

    func testRoomPlanWallFixtureConvertsToClosedIrregularSafeOutline() throws {
        let ids = (0..<4).map { _ in UUID() }
        let walls = [
            RoomFlowMeasuredWall(id: ids[0], center: SIMD2<Float>(0.5, 0), axis: SIMD2<Float>(1, 0), lengthMeters: 1, confidence: 0.97),
            RoomFlowMeasuredWall(id: ids[1], center: SIMD2<Float>(1, 1), axis: SIMD2<Float>(0, 1), lengthMeters: 2, confidence: 0.97),
            RoomFlowMeasuredWall(id: ids[2], center: SIMD2<Float>(0.5, 2), axis: SIMD2<Float>(1, 0), lengthMeters: 1, confidence: 0.82),
            RoomFlowMeasuredWall(id: ids[3], center: SIMD2<Float>(0, 1), axis: SIMD2<Float>(0, 1), lengthMeters: 2, confidence: 0.82),
        ]
        let outline = try RoomFlowMeasuredOutlineBuilder.build(walls: walls)
        XCTAssertEqual(outline.points.count, 4)
        XCTAssertEqual(outline.wallSegments.count, 4)
        XCTAssertEqual(RoomFlowCaptureResultBuilder.polygonArea(outline.points), 2, accuracy: 0.001)
        XCTAssertTrue(outline.points.allSatisfy(\.depthValidated))
    }

    func testRoomPlanWallFixtureRejectsAnOpenOutline() {
        let walls = [
            RoomFlowMeasuredWall(id: UUID(), center: SIMD2<Float>(0.5, 0), axis: SIMD2<Float>(1, 0), lengthMeters: 1, confidence: 0.9),
            RoomFlowMeasuredWall(id: UUID(), center: SIMD2<Float>(1, 0.5), axis: SIMD2<Float>(0, 1), lengthMeters: 1, confidence: 0.9),
            RoomFlowMeasuredWall(id: UUID(), center: SIMD2<Float>(0.5, 1), axis: SIMD2<Float>(1, 0), lengthMeters: 1, confidence: 0.9),
        ]
        XCTAssertThrowsError(try RoomFlowMeasuredOutlineBuilder.build(walls: walls))
    }

    func testBridgeEnvelopeUsesVersionSessionTypeAndBoundedJSON() throws {
        let envelope: [String: Any] = [
            "version": 2,
            "sessionId": "session-1",
            "type": "roomCaptureStarted",
            "requestId": "request-1",
            "payload": ["jobId": "job-1"],
        ]
        let data = try JSONSerialization.data(withJSONObject: envelope)
        let decoded = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual((decoded["version"] as? NSNumber)?.intValue, 2)
        XCTAssertEqual(decoded["sessionId"] as? String, "session-1")
        XCTAssertEqual(decoded["type"] as? String, "roomCaptureStarted")
        XCTAssertLessThan(data.count, 256 * 1024)
    }
}
