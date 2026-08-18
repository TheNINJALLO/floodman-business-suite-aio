package com.floodman.operations.roomflow.capture

import android.content.Context
import com.floodman.operations.data.SessionRepository
import kotlinx.serialization.Serializable
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.io.File
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption

@Serializable
data class PendingCaptureOperation(
    val jobId: String,
    val workspaceId: String,
    val operation: JsonObject,
    val queuedAt: String,
)

class RoomFlowCaptureOutbox(
    context: Context,
    private val json: Json = Json { ignoreUnknownKeys = true; encodeDefaults = true; explicitNulls = false },
) {
    private val directory = File(context.filesDir, "offline").apply { mkdirs() }
    private val file = File(directory, "roomflow-capture-outbox-v2.json")
    private val lock = Any()

    fun entries(): List<PendingCaptureOperation> = synchronized(lock) {
        if (!file.isFile) return@synchronized emptyList()
        json.decodeFromString<List<PendingCaptureOperation>>(file.readText(Charsets.UTF_8))
    }

    fun enqueue(value: PendingCaptureOperation) = synchronized(lock) {
        val existing = entries().toMutableList()
        val operationId = value.operation["operationId"]?.jsonPrimitive?.content.orEmpty()
        if (operationId.isBlank()) throw CaptureInputException("Capture operationId is required.")
        if (json.encodeToString(value.operation).toByteArray(Charsets.UTF_8).size > 256 * 1024) throw CaptureInputException("A room change cannot exceed 256 KB.")
        if (existing.none { it.operation["operationId"]?.jsonPrimitive?.content == operationId }) existing += value
        write(existing.takeLast(200))
    }

    fun remove(operationIds: Set<String>) = synchronized(lock) {
        if (operationIds.isEmpty()) return@synchronized
        write(entries().filterNot { it.operation["operationId"]?.jsonPrimitive?.content in operationIds })
    }

    fun forJob(jobId: String): List<PendingCaptureOperation> = entries().filter { it.jobId == jobId }

    suspend fun flush(jobId: String, repository: SessionRepository): JsonObject {
        val pending = forJob(jobId)
        if (pending.isEmpty()) return buildJsonObject { put("complete", true); put("results", JsonArray(emptyList())) }
        val response = repository.replayRoomFlowCaptureOperations(
            jobId,
            buildJsonObject { put("operations", JsonArray(pending.map { it.operation })) },
        )
        val results = response["results"] as? JsonArray ?: JsonArray(emptyList())
        val succeeded = results.mapNotNull { element ->
            val item = element.jsonObject
            item["operationId"]?.jsonPrimitive?.content?.takeIf { item["ok"]?.jsonPrimitive?.booleanOrNull == true }
        }.toSet()
        remove(succeeded)
        return response
    }

    private fun write(values: List<PendingCaptureOperation>) {
        directory.mkdirs()
        val temporary = File(directory, "${file.name}.tmp")
        temporary.writeText(json.encodeToString(values), Charsets.UTF_8)
        try {
            Files.move(temporary.toPath(), file.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
        } catch (_: AtomicMoveNotSupportedException) {
            Files.move(temporary.toPath(), file.toPath(), StandardCopyOption.REPLACE_EXISTING)
        }
    }
}
