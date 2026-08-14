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
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

class RoomFlowActivity : FragmentActivity() {
    private val repository get() = AppGraph.repository
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true; explicitNulls = false }
    private lateinit var webView: WebView
    private var jobId: String? = null
    private var activeWorkspaceId: String = ""
    private var fileCallback: ValueCallback<Array<Uri>>? = null

    private val filePicker = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val uri = result.data?.data
        fileCallback?.onReceiveValue(if (result.resultCode == RESULT_OK && uri != null) arrayOf(uri) else emptyArray())
        fileCallback = null
    }
    private val cameraPermission = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { }

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
                    val needed = buildList {
                        if (request.resources.contains(PermissionRequest.RESOURCE_VIDEO_CAPTURE) && ContextCompat.checkSelfPermission(this@RoomFlowActivity, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) add(Manifest.permission.CAMERA)
                        if (request.resources.contains(PermissionRequest.RESOURCE_AUDIO_CAPTURE) && ContextCompat.checkSelfPermission(this@RoomFlowActivity, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) add(Manifest.permission.RECORD_AUDIO)
                    }
                    if (needed.isNotEmpty()) cameraPermission.launch(needed.toTypedArray())
                    request.grant(request.resources)
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
        @JavascriptInterface fun close() { finish() }
        @JavascriptInterface fun notify(message: String) { runOnUiThread { Toast.makeText(this@RoomFlowActivity, message, Toast.LENGTH_SHORT).show() } }
    }

    companion object {
        private const val EXTRA_JOB_ID = "roomflow_job_id"
        fun intent(context: Context, jobId: String? = null) = Intent(context, RoomFlowActivity::class.java).putExtra(EXTRA_JOB_ID, jobId ?: "new")
    }
}
