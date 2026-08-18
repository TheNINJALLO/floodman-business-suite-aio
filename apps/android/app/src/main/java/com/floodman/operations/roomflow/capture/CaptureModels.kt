package com.floodman.operations.roomflow.capture

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import java.time.Instant
import kotlin.math.abs
import kotlin.math.hypot

const val CAPTURE_SCHEMA_VERSION = 2
const val FEET_PER_METER = 3.280839895013123
const val MINIMUM_WALL_FEET = 0.25
const val MAXIMUM_ROOM_DIMENSION_FEET = 300.0

@Serializable
data class CaptureCapabilities(
    val supported: Boolean,
    val modes: List<String>,
    val preferredMode: String,
    val depthSupported: Boolean,
    val reason: String? = null,
    val provider: String = "android-arcore",
)

@Serializable
data class CaptureVertex(
    val id: String,
    val x: Double,
    val y: Double,
    val confidence: Double,
    val depthValidated: Boolean,
    val source: String,
)

@Serializable
data class CaptureOpening(
    val id: String,
    val type: String,
    val wallSegmentIndex: Int,
    val offset: Double,
    val width: Double,
    val height: Double,
    val sillHeight: Double = 0.0,
    val confidence: Double = 1.0,
    val source: String = "manual-corrected",
)

@Serializable
data class CaptureMetadata(
    val captureMode: String,
    val platform: String = "android",
    val startedAt: String,
    val completedAt: String,
    val pointCount: Int,
    val averageConfidence: Double,
    val depthValidatedPointCount: Int,
    val automaticCorrectionCount: Int = 0,
    val manualCorrectionCount: Int = 0,
    val verificationRequired: Boolean,
    val rawCaptureRetained: Boolean = false,
    val trackingWarnings: List<String> = emptyList(),
)

@Serializable
data class RoomCaptureResult(
    val schemaVersion: Int = CAPTURE_SCHEMA_VERSION,
    val sessionId: String,
    val jobId: String,
    val workspaceId: String,
    val levelId: String,
    val roomId: String,
    val name: String,
    val roomType: String,
    val units: String = "ft",
    val height: Double,
    val vertices: List<CaptureVertex>,
    val openings: List<CaptureOpening> = emptyList(),
    val affectedAreas: List<JsonElement> = emptyList(),
    val scanMetadata: CaptureMetadata,
    val w: Double,
    val l: Double,
    val h: Double,
)

@Serializable
data class CaptureBridgeRequest(
    val version: Int,
    val sessionId: String,
    val type: String,
    val requestId: String,
    val payload: JsonElement = JsonNull,
)

@Serializable
data class CaptureBridgeError(val code: String, val message: String)

@Serializable
data class CaptureBridgeResponse(
    val version: Int = 2,
    val sessionId: String,
    val type: String,
    val requestId: String,
    val ok: Boolean,
    val payload: JsonElement = JsonNull,
    val error: CaptureBridgeError? = null,
)

data class HitSample(
    val worldX: Double,
    val worldY: Double,
    val worldZ: Double,
    val confidence: Double,
    val depthValidated: Boolean,
    val tracking: Boolean,
    val timestampMillis: Long,
)

data class StabilizedHit(
    val worldX: Double,
    val worldY: Double,
    val worldZ: Double,
    val confidence: Double,
    val depthValidated: Boolean,
    val sampleCount: Int,
)

class CaptureInputException(message: String) : IllegalArgumentException(message)

class PointStabilizer(
    private val minimumConfidence: Double = 0.6,
    private val maximumAgeMillis: Long = 750,
    private val maximumSpreadMeters: Double = 0.10,
) {
    fun stabilize(samples: List<HitSample>, nowMillis: Long): StabilizedHit {
        val accepted = samples.filter {
            it.tracking && it.confidence >= minimumConfidence && nowMillis - it.timestampMillis in 0..maximumAgeMillis
        }
        if (accepted.size < 3) throw CaptureInputException("Hold steady until at least three reliable AR points are available.")
        fun median(values: List<Double>): Double {
            val sorted = values.sorted()
            val middle = sorted.size / 2
            return if (sorted.size % 2 == 1) sorted[middle] else (sorted[middle - 1] + sorted[middle]) / 2.0
        }
        val x = median(accepted.map { it.worldX })
        val y = median(accepted.map { it.worldY })
        val z = median(accepted.map { it.worldZ })
        val spread = accepted.maxOf { kotlin.math.sqrt((it.worldX - x) * (it.worldX - x) + (it.worldY - y) * (it.worldY - y) + (it.worldZ - z) * (it.worldZ - z)) }
        if (spread > maximumSpreadMeters) throw CaptureInputException("Hold the reticle steady on one corner before adding it.")
        val depthCount = accepted.count { it.depthValidated }
        val depthValidated = depthCount >= (accepted.size + 1) / 2
        val base = accepted.map { it.confidence }.average()
        return StabilizedHit(x, y, z, (base + if (depthValidated) 0.05 else -0.1).coerceIn(0.0, 1.0), depthValidated, accepted.size)
    }
}

interface RoomCaptureProvider {
    fun capabilities(): CaptureCapabilities
    fun recentHitSamples(): List<HitSample>
    fun cancel()
}

class FakeHitTestCaptureProvider(
    private val report: CaptureCapabilities = CaptureCapabilities(true, listOf("android-arcore-guided"), "android-arcore-guided", false),
) : RoomCaptureProvider {
    private var samples: List<HitSample> = emptyList()
    var cancelled: Boolean = false
        private set

    fun emit(vararg values: HitSample) { samples = values.toList() }
    override fun capabilities(): CaptureCapabilities = report
    override fun recentHitSamples(): List<HitSample> = samples
    override fun cancel() { cancelled = true }
}

class CaptureSessionController(
    private val provider: RoomCaptureProvider,
    private val stabilizer: PointStabilizer = PointStabilizer(),
    private val nowMillis: () -> Long = System::currentTimeMillis,
) {
    private val captured = mutableListOf<CaptureVertex>()
    private var origin: StabilizedHit? = null
    var lastPointConfidence: Double? = null
        private set
    private val startedAt = Instant.now().toString()
    private val warnings = linkedSetOf<String>()

    val vertices: List<CaptureVertex> get() = captured.toList()

    fun capturePoint(): CaptureVertex {
        val hit = stabilizer.stabilize(provider.recentHitSamples(), nowMillis())
        lastPointConfidence = hit.confidence
        val localOrigin = origin ?: hit.also { origin = it }
        val x = (hit.worldX - localOrigin.worldX) * FEET_PER_METER
        val y = (hit.worldZ - localOrigin.worldZ) * FEET_PER_METER
        val floorDeviation = abs(hit.worldY - localOrigin.worldY) * FEET_PER_METER
        if (floorDeviation > 0.5) warnings += "One or more points differed from the starting floor height by more than 0.5 ft."
        if (!hit.depthValidated) warnings += "Depth was unavailable for one or more points; verify those walls manually."
        if (captured.isNotEmpty()) {
            val previous = captured.last()
            if (hypot(x - previous.x, y - previous.y) < MINIMUM_WALL_FEET) throw CaptureInputException("Move to the next corner; this point is too close to the previous point.")
        }
        val maxDistance = captured.maxOfOrNull { hypot(x - it.x, y - it.y) } ?: 0.0
        if (maxDistance > MAXIMUM_ROOM_DIMENSION_FEET) throw CaptureInputException("This point exceeds the 300 ft room limit. Reset and scan again.")
        if (captured.size >= 3 && hypot(x - captured.first().x, y - captured.first().y) <= 0.75) {
            throw CaptureInputException("The outline is close enough to finish. Tap Finish room instead of adding the first point again.")
        }
        return CaptureVertex(
            id = "vertex-${captured.size + 1}", x = x, y = y, confidence = hit.confidence,
            depthValidated = hit.depthValidated, source = if (hit.depthValidated) "android-arcore-depth" else "android-arcore-guided",
        ).also { captured += it }
    }

    fun undo(): CaptureVertex? = if (captured.isEmpty()) null else captured.removeAt(captured.lastIndex)

    fun reset() {
        captured.clear()
        origin = null
        warnings.clear()
        lastPointConfidence = null
    }

    fun cancel() {
        reset()
        provider.cancel()
    }

    fun closureDistanceFeet(): Double? = if (captured.size < 2) null else hypot(captured.last().x - captured.first().x, captured.last().y - captured.first().y)

    fun currentSegmentLengthFeet(): Double? = if (captured.size < 2) null else hypot(captured.last().x - captured[captured.lastIndex - 1].x, captured.last().y - captured[captured.lastIndex - 1].y)

    fun complete(
        sessionId: String,
        jobId: String,
        workspaceId: String,
        levelId: String,
        roomId: String,
        name: String,
        roomType: String,
        heightFeet: Double,
        depthEnabled: Boolean,
    ): RoomCaptureResult {
        validatePolygon(captured)
        if (heightFeet <= 0.0 || heightFeet > 40.0) throw CaptureInputException("Ceiling height must be between 0 and 40 ft.")
        val minX = captured.minOf { it.x }; val maxX = captured.maxOf { it.x }
        val minY = captured.minOf { it.y }; val maxY = captured.maxOf { it.y }
        val depthCount = captured.count { it.depthValidated }
        val averageConfidence = captured.map { it.confidence }.average()
        return RoomCaptureResult(
            sessionId = sessionId,
            jobId = jobId,
            workspaceId = workspaceId,
            levelId = levelId,
            roomId = roomId,
            name = name.trim().ifBlank { "Room" },
            roomType = roomType.trim().ifBlank { "other" },
            height = heightFeet,
            vertices = captured.toList(),
            scanMetadata = CaptureMetadata(
                captureMode = if (depthEnabled) "android-arcore-depth" else "android-arcore-guided",
                startedAt = startedAt,
                completedAt = Instant.now().toString(),
                pointCount = captured.size,
                averageConfidence = averageConfidence,
                depthValidatedPointCount = depthCount,
                verificationRequired = averageConfidence < 0.9 || depthCount < captured.size,
                trackingWarnings = warnings.toList(),
            ),
            w = maxX - minX,
            l = maxY - minY,
            h = heightFeet,
        )
    }

    companion object {
        fun validatePolygon(values: List<CaptureVertex>) {
            if (values.size < 3) throw CaptureInputException("Capture at least three room corners.")
            if (values.size > 128) throw CaptureInputException("A room cannot contain more than 128 corners.")
            values.indices.forEach { index ->
                val next = values[(index + 1) % values.size]
                if (hypot(next.x - values[index].x, next.y - values[index].y) < MINIMUM_WALL_FEET) throw CaptureInputException("Every wall must be at least 0.25 ft.")
            }
            if (polygonArea(values) <= 0.000001) throw CaptureInputException("Room area must be greater than zero.")
            if (selfIntersects(values)) throw CaptureInputException("Room walls cannot cross each other.")
        }

        fun polygonArea(values: List<CaptureVertex>): Double = abs(values.indices.sumOf { index ->
            val next = values[(index + 1) % values.size]
            values[index].x * next.y - next.x * values[index].y
        }) / 2.0

        private fun selfIntersects(values: List<CaptureVertex>): Boolean {
            fun orientation(a: CaptureVertex, b: CaptureVertex, c: CaptureVertex) = (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)
            fun intersects(a: CaptureVertex, b: CaptureVertex, c: CaptureVertex, d: CaptureVertex): Boolean {
                val first = orientation(a, b, c); val second = orientation(a, b, d)
                val third = orientation(c, d, a); val fourth = orientation(c, d, b)
                return ((first > 0 && second < 0) || (first < 0 && second > 0)) && ((third > 0 && fourth < 0) || (third < 0 && fourth > 0))
            }
            for (first in values.indices) for (second in first + 1 until values.size) {
                if (second == first + 1 || (first == 0 && second == values.lastIndex)) continue
                if (intersects(values[first], values[(first + 1) % values.size], values[second], values[(second + 1) % values.size])) return true
            }
            return false
        }
    }
}
