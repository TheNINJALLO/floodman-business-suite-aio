package com.floodman.operations.roomflow

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.PermissionRequest
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.lifecycleScope
import androidx.webkit.WebViewAssetLoader
import androidx.webkit.WebViewClientCompat
import com.floodman.operations.data.*
import com.floodman.operations.roomflow.capture.CaptureBridgeError
import com.floodman.operations.roomflow.capture.CaptureBridgeRequest
import com.floodman.operations.roomflow.capture.CaptureBridgeResponse
import com.floodman.operations.roomflow.capture.PendingCaptureOperation
import com.floodman.operations.roomflow.capture.RoomCaptureActivity
import com.floodman.operations.roomflow.capture.RoomFlowCaptureOutbox
import com.google.ar.core.ArCoreApk
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.time.Instant

class RoomFlowActivity : FragmentActivity() {
    private data class CaptureRequestContext(val sessionId: String, val type: String)

    private val repository get() = AppGraph.repository
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true; explicitNulls = false }
    private lateinit var webView: WebView
    private var jobId: String? = null
    private var activeWorkspaceId: String = ""
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private var pendingWebPermission: PermissionRequest? = null
    private var pendingCaptureRequestId: String? = null
    private val captureRequests = java.util.concurrent.ConcurrentHashMap<String, CaptureRequestContext>()
    private val captureOutbox by lazy { RoomFlowCaptureOutbox(applicationContext) }

    private val filePicker = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val uri = result.data?.data
        fileCallback?.onReceiveValue(if (result.resultCode == RESULT_OK && uri != null) arrayOf(uri) else emptyArray())
        fileCallback = null
    }
    private val webPermissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { grants ->
        val request = pendingWebPermission ?: return@registerForActivityResult
        pendingWebPermission = null
        val resources = request.resources.filter { resource ->
            when (resource) {
                PermissionRequest.RESOURCE_VIDEO_CAPTURE -> grants[Manifest.permission.CAMERA] == true
                PermissionRequest.RESOURCE_AUDIO_CAPTURE -> grants[Manifest.permission.RECORD_AUDIO] == true
                else -> false
            }
        }.toTypedArray()
        if (resources.isEmpty()) request.deny() else request.grant(resources)
    }
    private val roomCapture = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val requestId = pendingCaptureRequestId ?: return@registerForActivityResult
        pendingCaptureRequestId = null
        when (result.resultCode) {
            RESULT_OK -> {
                val value = result.data?.getStringExtra(RoomCaptureActivity.EXTRA_RESULT_JSON)
                val element = runCatching { json.parseToJsonElement(value.orEmpty()) }.getOrNull()
                if (element == null) respondCaptureError(requestId, "INVALID_CAPTURE_RESULT", "The device returned an invalid room. Enter it manually and try again.")
                else respondCapture(requestId, element)
            }
            RESULT_CANCELED -> respondCaptureError(requestId, "CAPTURE_CANCELLED", "Room scanning was cancelled. Your existing job was not changed.")
            else -> respondCaptureError(
                requestId,
                result.data?.getStringExtra(RoomCaptureActivity.EXTRA_ERROR_CODE) ?: "CAPTURE_FAILED",
                result.data?.getStringExtra(RoomCaptureActivity.EXTRA_ERROR_MESSAGE) ?: "Room scanning failed. Enter the room manually and try again.",
            )
        }
    }

    @SuppressLint("SetJavaScriptEnabled", "JavascriptInterface")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        jobId = intent.getStringExtra(EXTRA_JOB_ID)?.takeIf { it.isNotBlank() && it != "new" }
        val assetLoader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()
        webView = WebView(this)
        setContentView(webView)
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (::webView.isInitialized && webView.canGoBack()) {
                    webView.goBack()
                } else {
                    finishAfterTransition()
                }
            }
        })
        with(webView.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = true
            mediaPlaybackRequiresUserGesture = false
            setSupportZoom(true)
            builtInZoomControls = true
            displayZoomControls = false
        }
        webView.addJavascriptInterface(Bridge(), "FloodmanNative")
        webView.webViewClient = object : WebViewClientCompat() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest) = assetLoader.shouldInterceptRequest(request.url)
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val uri = request.url
                if (uri.host == "appassets.androidplatform.net") return false
                return if (uri.scheme in listOf("https", "mailto", "tel")) {
                    startActivity(Intent(Intent.ACTION_VIEW, uri)); true
                } else false
            }
        }
        webView.webChromeClient = object : WebChromeClient() {
            override fun onPermissionRequest(request: PermissionRequest) {
                runOnUiThread {
                    if (request.origin.host != "appassets.androidplatform.net") {
                        request.deny()
                        return@runOnUiThread
                    }
                    val allowed = request.resources.filter {
                        it == PermissionRequest.RESOURCE_VIDEO_CAPTURE || it == PermissionRequest.RESOURCE_AUDIO_CAPTURE
                    }
                    val needed = buildList {
                        if (allowed.contains(PermissionRequest.RESOURCE_VIDEO_CAPTURE) && ContextCompat.checkSelfPermission(this@RoomFlowActivity, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) add(Manifest.permission.CAMERA)
                        if (allowed.contains(PermissionRequest.RESOURCE_AUDIO_CAPTURE) && ContextCompat.checkSelfPermission(this@RoomFlowActivity, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) add(Manifest.permission.RECORD_AUDIO)
                    }
                    if (needed.isNotEmpty()) {
                        pendingWebPermission?.deny()
                        pendingWebPermission = request
                        webPermissions.launch(needed.toTypedArray())
                    } else {
                        request.grant(allowed.toTypedArray())
                    }
                }
            }
            override fun onShowFileChooser(view: WebView?, callback: ValueCallback<Array<Uri>>?, params: FileChooserParams?): Boolean {
                fileCallback?.onReceiveValue(emptyArray())
                fileCallback = callback
                filePicker.launch(params?.createIntent() ?: Intent(Intent.ACTION_OPEN_DOCUMENT).apply { type = "*/*"; addCategory(Intent.CATEGORY_OPENABLE) })
                return true
            }
        }
        webView.loadUrl("https://appassets.androidplatform.net/assets/roomflow/index.html?floodman_mobile=1")
    }

    private fun responseType(requestType: String, failed: Boolean): String = when (requestType) {
        "capabilitiesRequested" -> "capabilitiesReported"
        "roomCaptureStarted" -> if (failed) "sessionFailed" else "roomCaptureCompleted"
        "roomCaptureCancelled" -> "sessionCancelled"
        "captureRoomsRequested" -> if (failed) "captureRoomsFailed" else "captureRoomsReported"
        "captureOperationQueued" -> if (failed) "captureOperationFailed" else "captureOperationSaved"
        "captureOutboxReplayRequested" -> if (failed) "captureOutboxReplayFailed" else "captureOutboxReplayed"
        else -> if (failed) "sessionFailed" else "sessionCompleted"
    }

    private fun respondCapture(requestId: String, result: kotlinx.serialization.json.JsonElement = JsonNull) {
        val context = captureRequests.remove(requestId) ?: return
        val response = CaptureBridgeResponse(
            sessionId = context.sessionId,
            type = responseType(context.type, false),
            requestId = requestId,
            ok = true,
            payload = result,
        )
        webView.post {
            webView.evaluateJavascript(
                "window.RoomFlowCaptureBridgeV2?.receive(${json.encodeToString(response)});",
                null,
            )
        }
    }

    private fun respondCaptureError(requestId: String, code: String, message: String) {
        val context = captureRequests.remove(requestId) ?: return
        val response = CaptureBridgeResponse(
            sessionId = context.sessionId,
            type = if (code == "CAPTURE_CANCELLED") "sessionCancelled" else responseType(context.type, true),
            requestId = requestId,
            ok = false,
            error = CaptureBridgeError(code = code, message = message),
        )
        webView.post {
            webView.evaluateJavascript(
                "window.RoomFlowCaptureBridgeV2?.receive(${json.encodeToString(response)});",
                null,
            )
        }
    }


    inner class Bridge {
        private fun evaluate(method: String, encodedPayload: String) {
            webView.post {
                webView.evaluateJavascript(
                    "window.FloodmanRoomFlow?.$method(${json.encodeToString(encodedPayload)});",
                    null,
                )
            }
        }

        @JavascriptInterface fun ready() {
            lifecycleScope.launch {
                runCatching {
                    val bootstrap = repository.roomFlowBootstrap()
                    activeWorkspaceId = bootstrap.activeWorkspace?.id ?: bootstrap.selectedWorkspaceId
                    evaluate("receiveBootstrap", json.encodeToString(bootstrap))
                    val detail = jobId?.let { repository.roomFlowJob(it) }
                    evaluate("receiveContext", json.encodeToString(detail))
                }.onFailure { error ->
                    evaluate("bootstrapFailed", error.message ?: "Floodman RoomFlow could not load its cloud data.")
                }
            }
        }

        @JavascriptInterface fun refreshBootstrap() {
            lifecycleScope.launch {
                runCatching { repository.roomFlowBootstrap() }
                    .onSuccess {
                        activeWorkspaceId = it.activeWorkspace?.id ?: it.selectedWorkspaceId
                        evaluate("receiveBootstrap", json.encodeToString(it))
                    }
                    .onFailure { evaluate("bootstrapFailed", it.message ?: "RoomFlow refresh failed.") }
            }
        }

        @JavascriptInterface fun selectWorkspace(workspaceId: String) {
            val selected = workspaceId.trim()
            if (selected.isEmpty()) {
                evaluate("workspaceFailed", "Choose a Floodman workspace.")
                return
            }
            lifecycleScope.launch {
                runCatching { repository.selectRoomFlowWorkspace(selected) }
                    .onSuccess { response ->
                        jobId = null
                        activeWorkspaceId = response.bootstrap.activeWorkspace?.id ?: response.bootstrap.selectedWorkspaceId
                        evaluate("workspaceSelected", json.encodeToString(response))
                    }
                    .onFailure { error -> evaluate("workspaceFailed", error.message ?: "Workspace selection failed.") }
            }
        }

        @JavascriptInterface fun createWorkspace(payload: String) {
            val input = runCatching { json.decodeFromString<RoomFlowWorkspaceCreateInput>(payload) }
                .getOrElse {
                    evaluate("workspaceFailed", "Enter a company or workspace name.")
                    return
                }
            lifecycleScope.launch {
                runCatching { repository.createRoomFlowWorkspace(input) }
                    .onSuccess { response ->
                        jobId = null
                        activeWorkspaceId = response.bootstrap.activeWorkspace?.id ?: response.bootstrap.selectedWorkspaceId
                        evaluate("workspaceCreated", json.encodeToString(response))
                    }
                    .onFailure { error -> evaluate("workspaceFailed", error.message ?: "Workspace creation failed.") }
            }
        }

        @JavascriptInterface fun importOriginalRoomFlow(payload: String) {
            val input = runCatching { json.decodeFromString<RoomFlowSupabaseImportInput>(payload) }
                .getOrElse {
                    evaluate("importFailed", "Enter the RoomFlow Supabase email and password.")
                    return
                }
            lifecycleScope.launch {
                runCatching { repository.importRoomFlowSupabase(input) }
                    .onSuccess { response ->
                        evaluate("importCompleted", json.encodeToString(response))
                    }
                    .onFailure { error ->
                        evaluate("importFailed", error.message ?: "Original RoomFlow import failed.")
                    }
            }
        }

        @JavascriptInterface fun selectJob(id: String) {
            jobId = id.trim().takeIf { it.isNotEmpty() }
        }

        @JavascriptInterface fun searchCustomers(query: String): String = runBlocking(Dispatchers.IO) { json.encodeToString(repository.customers(query, 1, activeWorkspaceId).items) }
        @JavascriptInterface fun searchProperties(contactId: String, query: String): String = runBlocking(Dispatchers.IO) { json.encodeToString(repository.properties(contactId, query, 1, activeWorkspaceId).items) }
        @JavascriptInterface fun saveJob(payload: String) {
            lifecycleScope.launch {
                runCatching { repository.saveRoomFlowJob(jobId, json.decodeFromString<RoomFlowSaveInput>(payload)) }
                    .onSuccess { response ->
                        jobId = response.job.id
                        evaluate("saveCompleted", json.encodeToString(response))
                    }
                    .onFailure { error -> evaluate("saveFailed", error.message ?: "RoomFlow synchronization failed") }
            }
        }

        @JavascriptInterface fun roomFlowCaptureV2(envelope: String) {
            if (envelope.toByteArray(Charsets.UTF_8).size > 256 * 1024) return
            val request = runCatching { json.decodeFromString<CaptureBridgeRequest>(envelope) }.getOrElse {
                return
            }
            if (request.requestId.isBlank() || request.sessionId.isBlank()) return
            captureRequests[request.requestId] = CaptureRequestContext(request.sessionId, request.type)
            if (request.version != 2) {
                respondCaptureError(request.requestId, "UNSUPPORTED_BRIDGE_VERSION", "This Floodman build supports RoomFlow Capture bridge version 2.")
                return
            }
            when (request.type) {
                "capabilitiesRequested" -> captureCapabilities(request.requestId)
                "roomCaptureStarted" -> startRoomCapture(request)
                "captureRoomsRequested" -> listCaptureRooms(request)
                "captureOperationQueued" -> saveCaptureOperation(request)
                "captureOutboxReplayRequested" -> replayCaptureOutbox(request)
                "roomCaptureCancelled" -> {
                    if (pendingCaptureRequestId == null) respondCapture(request.requestId, buildJsonObject { put("cancelled", true) })
                    else respondCaptureError(request.requestId, "CAPTURE_ACTIVE", "Use Close in the room scanner to discard the active scan.")
                }
                else -> respondCaptureError(request.requestId, "UNSUPPORTED_MESSAGE_TYPE", "This Floodman build does not support ${request.type}.")
            }
        }

        private fun captureCapabilities(requestId: String) {
            val availability = ArCoreApk.getInstance().checkAvailability(this@RoomFlowActivity)
            val supported = availability.isSupported
            respondCapture(requestId, buildJsonObject {
                put("supported", supported)
                put("modes", JsonArray((if (supported) listOf("android-arcore-guided", "manual") else listOf("manual")).map(::JsonPrimitive)))
                put("preferredMode", if (supported) "android-arcore-guided" else "manual")
                put("depthSupported", false)
                put("provider", "android-arcore")
                if (!supported) put("reason", "ARCore is unavailable on this device. Manual room entry remains available.")
            })
        }

        private fun startRoomCapture(request: CaptureBridgeRequest) {
            val payload = request.payload as? JsonObject
            if (payload == null) {
                respondCaptureError(request.requestId, "INVALID_CAPTURE", "The room scan request is missing its job details.")
                return
            }
            val requestedJobId = payload["jobId"]?.jsonPrimitive?.content.orEmpty().trim()
            val requestedWorkspaceId = payload["workspaceId"]?.jsonPrimitive?.content.orEmpty().trim()
            if (requestedJobId.isBlank() || requestedWorkspaceId.isBlank()) {
                respondCaptureError(request.requestId, "JOB_REQUIRED", "Save the job and choose its Floodman company before scanning a room.")
                return
            }
            if (jobId != null && requestedJobId != jobId) {
                respondCaptureError(request.requestId, "JOB_SCOPE_MISMATCH", "The requested room does not belong to the open Floodman job.")
                return
            }
            if (activeWorkspaceId.isNotBlank() && requestedWorkspaceId != activeWorkspaceId) {
                respondCaptureError(request.requestId, "WORKSPACE_SCOPE_MISMATCH", "The requested room does not belong to the selected Floodman company.")
                return
            }
            if (pendingCaptureRequestId != null) {
                respondCaptureError(request.requestId, "CAPTURE_BUSY", "Finish or close the current room scan first.")
                return
            }
            pendingCaptureRequestId = request.requestId
            runCatching { roomCapture.launch(RoomCaptureActivity.intent(this@RoomFlowActivity, payload)) }
                .onFailure {
                    pendingCaptureRequestId = null
                    respondCaptureError(request.requestId, "ARCORE_UNAVAILABLE", it.message ?: "ARCore is unavailable. Enter the room manually.")
                }
        }

        private fun listCaptureRooms(request: CaptureBridgeRequest) {
            val requestedJobId = (request.payload as? JsonObject)?.get("jobId")?.jsonPrimitive?.content.orEmpty().trim()
            if (!validCaptureScope(request.requestId, requestedJobId, null)) return
            lifecycleScope.launch {
                runCatching { captureOutbox.flush(requestedJobId, repository) }
                runCatching { repository.roomFlowCaptureRooms(requestedJobId) }
                    .onSuccess { respondCapture(request.requestId, it) }
                    .onFailure { respondCaptureError(request.requestId, "CAPTURE_LOAD_FAILED", it.message ?: "Saved rooms could not be loaded.") }
            }
        }

        private fun saveCaptureOperation(request: CaptureBridgeRequest) {
            val payload = request.payload as? JsonObject
            val requestedJobId = payload?.get("jobId")?.jsonPrimitive?.content.orEmpty().trim()
            val requestedWorkspaceId = payload?.get("workspaceId")?.jsonPrimitive?.content.orEmpty().trim()
            val operation = payload?.get("operation") as? JsonObject
            if (!validCaptureScope(request.requestId, requestedJobId, requestedWorkspaceId)) return
            if (operation == null) {
                respondCaptureError(request.requestId, "INVALID_CAPTURE", "The room change is missing its operation payload.")
                return
            }
            lifecycleScope.launch {
                runCatching {
                    captureOutbox.enqueue(PendingCaptureOperation(requestedJobId, requestedWorkspaceId, operation, Instant.now().toString()))
                    captureOutbox.flush(requestedJobId, repository)
                }.onSuccess { response ->
                    val result = (response["results"] as? kotlinx.serialization.json.JsonArray)?.lastOrNull()?.jsonObject
                    if (result?.get("ok")?.jsonPrimitive?.content == "true") respondCapture(request.requestId, result)
                    else respondCaptureError(
                        request.requestId,
                        result?.get("code")?.jsonPrimitive?.content ?: "CAPTURE_SAVE_FAILED",
                        result?.get("message")?.jsonPrimitive?.content ?: "The room could not be saved. It remains queued on this device.",
                    )
                }.onFailure {
                    val expected = operation["expectedRevision"]?.jsonPrimitive?.content?.toIntOrNull() ?: 0
                    respondCapture(request.requestId, buildJsonObject {
                        put("queued", true)
                        put("operationId", operation["operationId"] ?: JsonNull)
                        put("revision", expected + 1)
                        put("room", operation["room"] ?: JsonNull)
                    })
                }
            }
        }

        private fun replayCaptureOutbox(request: CaptureBridgeRequest) {
            val requestedJobId = (request.payload as? JsonObject)?.get("jobId")?.jsonPrimitive?.content.orEmpty().trim()
            if (!validCaptureScope(request.requestId, requestedJobId, null)) return
            lifecycleScope.launch {
                runCatching { captureOutbox.flush(requestedJobId, repository) }
                    .onSuccess { respondCapture(request.requestId, it) }
                    .onFailure { respondCaptureError(request.requestId, "OFFLINE", "Room changes remain safely queued on this device.") }
            }
        }

        private fun validCaptureScope(requestId: String, requestedJobId: String, requestedWorkspaceId: String?): Boolean {
            if (requestedJobId.isBlank() || (jobId != null && requestedJobId != jobId)) {
                respondCaptureError(requestId, "JOB_SCOPE_MISMATCH", "The room request does not match the open Floodman job.")
                return false
            }
            if (!requestedWorkspaceId.isNullOrBlank() && activeWorkspaceId.isNotBlank() && requestedWorkspaceId != activeWorkspaceId) {
                respondCaptureError(requestId, "WORKSPACE_SCOPE_MISMATCH", "The room request does not match the selected Floodman company.")
                return false
            }
            return true
        }
        @JavascriptInterface fun close() { finish() }
        @JavascriptInterface fun notify(message: String) { runOnUiThread { Toast.makeText(this@RoomFlowActivity, message, Toast.LENGTH_SHORT).show() } }
    }

    companion object {
        private const val EXTRA_JOB_ID = "roomflow_job_id"
        fun intent(context: Context, jobId: String? = null) = Intent(context, RoomFlowActivity::class.java).putExtra(EXTRA_JOB_ID, jobId ?: "new")
    }
}
