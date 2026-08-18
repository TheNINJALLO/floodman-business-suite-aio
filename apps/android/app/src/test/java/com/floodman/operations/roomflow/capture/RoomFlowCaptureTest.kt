package com.floodman.operations.roomflow.capture

import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class RoomFlowCaptureTest {
    private val now = 10_000L

    private fun sample(
        x: Double,
        y: Double = 0.0,
        z: Double,
        confidence: Double = 0.9,
        depth: Boolean = true,
        timestamp: Long = now,
    ) = HitSample(x, y, z, confidence, depth, true, timestamp)

    private fun providerAt(provider: FakeHitTestCaptureProvider, x: Double, z: Double, depth: Boolean = true) {
        provider.emit(
            sample(x - 0.005, z = z + 0.003, depth = depth),
            sample(x, z = z, depth = depth),
            sample(x + 0.004, z = z - 0.002, depth = depth),
        )
    }

    private fun vertex(id: String, x: Double, y: Double) = CaptureVertex(id, x, y, 1.0, true, "test")

    @Test
    fun capabilitiesDescribeSupportedAndManualFallbackModes() {
        val supported = CaptureCapabilities(true, listOf("android-arcore-depth", "android-arcore-guided", "manual"), "android-arcore-depth", true)
        val unsupported = CaptureCapabilities(false, listOf("manual"), "manual", false, "ARCore unavailable")

        assertTrue(supported.supported)
        assertTrue(supported.depthSupported)
        assertEquals("manual", unsupported.preferredMode)
        assertFalse(unsupported.supported)
    }

    @Test
    fun bridgeV2RequestAndResponseRoundTripWithoutLosingIds() {
        val json = Json { encodeDefaults = true; explicitNulls = false }
        val request = CaptureBridgeRequest(2, "session-123", "roomCaptureStarted", "request-123", buildJsonObject { put("jobId", "job-1") })
        val decoded = json.decodeFromString<CaptureBridgeRequest>(json.encodeToString(request))
        val response = CaptureBridgeResponse(sessionId = decoded.sessionId, type = "roomCaptureCompleted", requestId = decoded.requestId, ok = true, payload = decoded.payload)
        val responseJson = json.parseToJsonElement(json.encodeToString(response)).jsonObject

        assertEquals(2, decoded.version)
        assertEquals("session-123", responseJson["sessionId"]?.jsonPrimitive?.content)
        assertEquals("roomCaptureCompleted", responseJson["type"]?.jsonPrimitive?.content)
        assertEquals("request-123", responseJson["requestId"]?.jsonPrimitive?.content)
        assertEquals("job-1", responseJson["payload"]?.jsonObject?.get("jobId")?.jsonPrimitive?.content)
    }

    @Test
    fun stabilizerUsesMedianAndDepthMajority() {
        val value = PointStabilizer().stabilize(
            listOf(sample(1.0, z = 2.0), sample(1.01, z = 2.01), sample(0.99, z = 1.99, depth = false)),
            now,
        )

        assertEquals(1.0, value.worldX, 0.0001)
        assertEquals(2.0, value.worldZ, 0.0001)
        assertTrue(value.depthValidated)
        assertEquals(3, value.sampleCount)
    }

    @Test
    fun stabilizerRejectsWeakOrScatteredHits() {
        expectCaptureFailure("reliable AR points") {
            PointStabilizer().stabilize(listOf(sample(0.0, z = 0.0, confidence = 0.2)), now)
        }
        expectCaptureFailure("reticle steady") {
            PointStabilizer().stabilize(listOf(sample(0.0, z = 0.0), sample(1.0, z = 0.0), sample(2.0, z = 0.0)), now)
        }
    }

    @Test
    fun captureSupportsUndoResetAndCancel() {
        val provider = FakeHitTestCaptureProvider()
        val controller = CaptureSessionController(provider, nowMillis = { now })
        providerAt(provider, 0.0, 0.0)
        controller.capturePoint()
        providerAt(provider, 1.0, 0.0)
        controller.capturePoint()

        assertEquals(2, controller.vertices.size)
        assertEquals("vertex-2", controller.undo()?.id)
        controller.reset()
        assertTrue(controller.vertices.isEmpty())
        controller.cancel()
        assertTrue(provider.cancelled)
    }

    @Test
    fun completedCaptureUsesFeetAndNeverClaimsRawRetention() {
        val provider = FakeHitTestCaptureProvider()
        val controller = CaptureSessionController(provider, nowMillis = { now })
        listOf(0.0 to 0.0, 1.0 to 0.0, 1.0 to 2.0, 0.0 to 2.0).forEach { (x, z) ->
            providerAt(provider, x, z)
            controller.capturePoint()
        }

        val room = controller.complete("session-1", "job-1", "workspace-1", "main", "room-1", "Living Room", "living-room", 8.0, true)

        assertEquals(CAPTURE_SCHEMA_VERSION, room.schemaVersion)
        assertEquals("ft", room.units)
        assertEquals(FEET_PER_METER, room.w, 0.03)
        assertEquals(2 * FEET_PER_METER, room.l, 0.03)
        assertEquals(4, room.scanMetadata.depthValidatedPointCount)
        assertFalse(room.scanMetadata.rawCaptureRetained)
    }

    @Test
    fun polygonValidationRejectsCrossingAndDuplicateWalls() {
        expectCaptureFailure("cannot cross") {
            CaptureSessionController.validatePolygon(listOf(vertex("1", 0.0, 0.0), vertex("2", 4.0, 3.0), vertex("3", 0.0, 4.0), vertex("4", 3.0, 0.0)))
        }
        expectCaptureFailure("at least 0.25") {
            CaptureSessionController.validatePolygon(listOf(vertex("1", 0.0, 0.0), vertex("2", 0.1, 0.0), vertex("3", 0.0, 3.0)))
        }
    }

    private fun expectCaptureFailure(message: String, action: () -> Unit) {
        try {
            action()
            fail("Expected CaptureInputException containing '$message'")
        } catch (error: CaptureInputException) {
            assertTrue(error.message.orEmpty().contains(message))
        }
    }
}
