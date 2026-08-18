package com.floodman.operations.roomflow.capture

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.OnBackPressedCallback
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import com.google.ar.core.ArCoreApk
import com.google.ar.core.Config
import com.google.ar.core.Session
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.util.UUID
import java.util.Locale

class RoomCaptureActivity : FragmentActivity() {
    private val json = Json { encodeDefaults = true; explicitNulls = false }
    private var arSession: Session? = null
    private lateinit var surfaceView: android.opengl.GLSurfaceView
    private lateinit var renderer: ArCoreCaptureRenderer
    private lateinit var controller: CaptureSessionController
    private lateinit var status: TextView
    private lateinit var summary: TextView
    private lateinit var finishButton: Button
    private var installRequested = false
    private var permissionRequested = false
    private var depthEnabled = false
    private var resumed = false
    private var soundEnabled = true
    private var tone: ToneGenerator? = null
    private var heightFeet = 8.0

    private val cameraPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) resumeCapture() else fail("CAMERA_PERMISSION_DENIED", "Camera permission is required for AR room scanning. You can still enter the room manually.")
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        renderer = ArCoreCaptureRenderer(
            sessionProvider = { arSession },
            displayRotation = ::currentDisplayRotation,
            statusListener = { message, ready -> runOnUiThread { status.text = message; status.setTextColor(if (ready) Color.rgb(218, 255, 235) else Color.WHITE) } },
        )
        controller = CaptureSessionController(renderer)
        heightFeet = intent.getDoubleExtra(EXTRA_HEIGHT_FEET, 8.0)
        setContentView(buildUi())
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() = confirmCancelCapture()
        })
    }

    private fun buildUi(): View {
        val root = FrameLayout(this).apply { setBackgroundColor(Color.BLACK) }
        surfaceView = android.opengl.GLSurfaceView(this).apply {
            preserveEGLContextOnPause = true
            setEGLContextClientVersion(2)
            setRenderer(renderer)
            renderMode = android.opengl.GLSurfaceView.RENDERMODE_CONTINUOUSLY
        }
        root.addView(surfaceView, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))

        val shade = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(14), dp(16), dp(14))
            setBackgroundColor(Color.argb(190, 7, 28, 43))
        }
        status = TextView(this).apply {
            text = "Starting ARCore…"
            setTextColor(Color.WHITE)
            textSize = 15f
        }
        val privacy = TextView(this).apply {
            text = "Uses Google Play Services for AR (ARCore). No camera image or depth map is saved or uploaded."
            setTextColor(Color.rgb(190, 210, 222))
            textSize = 11f
            setPadding(0, dp(5), 0, 0)
        }
        shade.addView(status)
        shade.addView(privacy)
        root.addView(shade, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.TOP))

        val close = Button(this).apply {
            text = "Close"
            contentDescription = "Close room scanner"
            setOnClickListener { confirmCancelCapture() }
        }
        root.addView(close, FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(48), Gravity.TOP or Gravity.END).apply { topMargin = dp(86); marginEnd = dp(12) })

        val reticle = TextView(this).apply {
            text = "+"
            textSize = 42f
            gravity = Gravity.CENTER
            setTextColor(Color.WHITE)
            setShadowLayer(6f, 0f, 1f, Color.BLACK)
            contentDescription = "Center measurement reticle"
        }
        root.addView(reticle, FrameLayout.LayoutParams(dp(72), dp(72), Gravity.CENTER))

        val controls = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(dp(12), dp(12), dp(12), dp(12))
            setBackgroundColor(Color.argb(210, 7, 28, 43))
        }
        summary = TextView(this).apply {
            text = "0 corners · Aim at the first floor-level wall corner."
            setTextColor(Color.WHITE)
            textSize = 14f
            gravity = Gravity.CENTER
            setPadding(0, 0, 0, dp(8))
        }
        controls.addView(summary, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER }
        val undo = button("Undo") { surfaceView.queueEvent { controller.undo(); runOnUiThread { feedback(HapticFeedbackConstants.CLOCK_TICK); updateSummary() } } }
        val add = button("Add corner") { captureCorner() }
        finishButton = button("Finish room") { finishCapture() }.apply { isEnabled = false }
        val reset = button("Reset") { surfaceView.queueEvent { controller.reset(); runOnUiThread { feedback(HapticFeedbackConstants.CLOCK_TICK); updateSummary("Scan reset. Aim at the first corner.") } } }
        listOf(undo, add, finishButton, reset).forEach { row.addView(it, LinearLayout.LayoutParams(0, dp(52), 1f).apply { marginStart = dp(2); marginEnd = dp(2) }) }
        controls.addView(row, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        val utilityRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER; setPadding(0, dp(6), 0, 0) }
        val height = button("Height ${String.format(Locale.US, "%.2f", heightFeet)} ft") { view -> editHeight(view as Button) }
        val sound = button("Sound on") {
            soundEnabled = !soundEnabled
            (it as Button).text = if (soundEnabled) "Sound on" else "Sound off"
            it.contentDescription = if (soundEnabled) "Capture sound is on" else "Capture sound is off"
        }
        listOf(height, sound).forEach { utilityRow.addView(it, LinearLayout.LayoutParams(0, dp(48), 1f).apply { marginStart = dp(2); marginEnd = dp(2) }) }
        controls.addView(utilityRow, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        root.addView(controls, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM))
        return root
    }

    private fun button(label: String, action: (View) -> Unit) = Button(this).apply {
        text = label
        contentDescription = label
        isAllCaps = false
        setOnClickListener { view -> action(view) }
    }

    private fun captureCorner() {
        surfaceView.queueEvent {
            runCatching { controller.capturePoint() }
                .onSuccess { runOnUiThread { feedback(HapticFeedbackConstants.VIRTUAL_KEY, true); updateSummary("Corner ${controller.vertices.size} added.") } }
                .onFailure { error -> runOnUiThread { status.text = error.message ?: "Hold steady and try again." } }
        }
    }

    private fun updateSummary(message: String = "") {
        val closure = controller.closureDistanceFeet()
        val segment = controller.currentSegmentLengthFeet()
        val confidence = controller.lastPointConfidence
        summary.text = buildString {
            append("${controller.vertices.size} corner${if (controller.vertices.size == 1) "" else "s"}")
            if (closure != null && controller.vertices.size >= 3) append(" · ${"%.2f".format(closure)} ft from closure")
            if (segment != null) append(" · last wall ${"%.2f".format(segment)} ft")
            if (confidence != null) append(" · ${"%.0f".format(confidence * 100)}% confidence")
            if (message.isNotBlank()) append(" · $message")
        }
        finishButton.isEnabled = controller.vertices.size >= 3
    }

    private fun finishCapture() {
        surfaceView.queueEvent {
            val result = runCatching {
                controller.complete(
                    sessionId = intent.getStringExtra(EXTRA_SESSION_ID).orEmpty().ifBlank { UUID.randomUUID().toString() },
                    jobId = intent.getStringExtra(EXTRA_JOB_ID).orEmpty(),
                    workspaceId = intent.getStringExtra(EXTRA_WORKSPACE_ID).orEmpty(),
                    levelId = intent.getStringExtra(EXTRA_LEVEL_ID).orEmpty().ifBlank { "main" },
                    roomId = intent.getStringExtra(EXTRA_ROOM_ID).orEmpty().ifBlank { UUID.randomUUID().toString() },
                    name = intent.getStringExtra(EXTRA_ROOM_NAME).orEmpty(),
                    roomType = intent.getStringExtra(EXTRA_ROOM_TYPE).orEmpty(),
                    heightFeet = heightFeet,
                    depthEnabled = depthEnabled,
                )
            }
            runOnUiThread {
                result.onSuccess {
                    feedback(HapticFeedbackConstants.LONG_PRESS, true)
                    setResult(Activity.RESULT_OK, Intent().putExtra(EXTRA_RESULT_JSON, json.encodeToString(it)))
                    finish()
                }.onFailure { error -> status.text = error.message ?: "Review the room outline and try again." }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        resumed = true
        resumeCapture()
    }

    private fun resumeCapture() {
        if (!resumed) return
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            if (!permissionRequested) { permissionRequested = true; cameraPermission.launch(Manifest.permission.CAMERA) }
            return
        }
        try {
            if (arSession == null) {
                when (ArCoreApk.getInstance().requestInstall(this, !installRequested)) {
                    ArCoreApk.InstallStatus.INSTALL_REQUESTED -> { installRequested = true; status.text = "Install or update Google Play Services for AR, then return to Floodman."; return }
                    ArCoreApk.InstallStatus.INSTALLED -> Unit
                }
                val session = Session(this)
                val config = session.config.apply {
                    planeFindingMode = Config.PlaneFindingMode.HORIZONTAL_AND_VERTICAL
                    focusMode = Config.FocusMode.AUTO
                    updateMode = Config.UpdateMode.LATEST_CAMERA_IMAGE
                }
                depthEnabled = session.isDepthModeSupported(Config.DepthMode.AUTOMATIC)
                config.depthMode = if (depthEnabled) Config.DepthMode.AUTOMATIC else Config.DepthMode.DISABLED
                session.configure(config)
                arSession = session
                renderer.onSessionConfigured(session, depthEnabled)
            }
            arSession?.resume()
            surfaceView.onResume()
        } catch (error: Exception) {
            fail("ARCORE_UNAVAILABLE", error.message ?: "ARCore is not available on this device. Enter the room manually.")
        }
    }

    override fun onPause() {
        resumed = false
        if (::surfaceView.isInitialized) surfaceView.onPause()
        runCatching { arSession?.pause() }
        super.onPause()
    }

    override fun onDestroy() {
        runCatching { arSession?.close() }
        arSession = null
        tone?.release()
        tone = null
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        super.onDestroy()
    }

    private fun cancelCapture() {
        controller.cancel()
        setResult(Activity.RESULT_CANCELED)
        finish()
    }

    private fun confirmCancelCapture() {
        if (controller.vertices.isEmpty()) {
            cancelCapture()
            return
        }
        android.app.AlertDialog.Builder(this)
            .setTitle("Discard this room scan?")
            .setMessage("The corners in this unfinished scan will be cleared. Your existing Floodman job will not change.")
            .setNegativeButton("Keep scanning", null)
            .setPositiveButton("Discard scan") { _, _ -> cancelCapture() }
            .show()
    }

    private fun editHeight(button: Button) {
        val input = android.widget.EditText(this).apply {
            inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
            setText(String.format(Locale.US, "%.2f", heightFeet))
            contentDescription = "Ceiling height in feet"
            selectAll()
        }
        android.app.AlertDialog.Builder(this)
            .setTitle("Ceiling height")
            .setMessage("Enter the measured ceiling height in decimal feet.")
            .setView(input)
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Use height") { _, _ ->
                val value = input.text.toString().toDoubleOrNull()
                if (value == null || value <= 0 || value > 40) {
                    status.text = "Ceiling height must be between 0 and 40 ft."
                } else {
                    heightFeet = value
                    button.text = "Height ${String.format(Locale.US, "%.2f", heightFeet)} ft"
                    feedback(HapticFeedbackConstants.CLOCK_TICK)
                }
            }
            .show()
    }

    private fun feedback(haptic: Int, sound: Boolean = false) {
        surfaceView.performHapticFeedback(haptic)
        if (sound && soundEnabled) {
            val generator = tone ?: ToneGenerator(AudioManager.STREAM_NOTIFICATION, 70).also { tone = it }
            generator.startTone(ToneGenerator.TONE_PROP_BEEP, 80)
        }
    }

    private fun fail(code: String, message: String) {
        setResult(Activity.RESULT_FIRST_USER, Intent().putExtra(EXTRA_ERROR_CODE, code).putExtra(EXTRA_ERROR_MESSAGE, message))
        finish()
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    @Suppress("DEPRECATION")
    private fun currentDisplayRotation(): Int = windowManager.defaultDisplay.rotation

    companion object {
        const val EXTRA_RESULT_JSON = "capture_result_json"
        const val EXTRA_ERROR_CODE = "capture_error_code"
        const val EXTRA_ERROR_MESSAGE = "capture_error_message"
        private const val EXTRA_SESSION_ID = "capture_session_id"
        private const val EXTRA_JOB_ID = "capture_job_id"
        private const val EXTRA_WORKSPACE_ID = "capture_workspace_id"
        private const val EXTRA_LEVEL_ID = "capture_level_id"
        private const val EXTRA_ROOM_ID = "capture_room_id"
        private const val EXTRA_ROOM_NAME = "capture_room_name"
        private const val EXTRA_ROOM_TYPE = "capture_room_type"
        private const val EXTRA_HEIGHT_FEET = "capture_height_feet"

        fun intent(context: Context, payload: kotlinx.serialization.json.JsonObject): Intent = Intent(context, RoomCaptureActivity::class.java).apply {
            fun text(name: String) = payload[name]?.toString()?.trim('"').orEmpty()
            putExtra(EXTRA_SESSION_ID, text("sessionId"))
            putExtra(EXTRA_JOB_ID, text("jobId"))
            putExtra(EXTRA_WORKSPACE_ID, text("workspaceId"))
            putExtra(EXTRA_LEVEL_ID, text("levelId"))
            putExtra(EXTRA_ROOM_ID, text("roomId"))
            putExtra(EXTRA_ROOM_NAME, text("name"))
            putExtra(EXTRA_ROOM_TYPE, text("roomType"))
            putExtra(EXTRA_HEIGHT_FEET, payload["defaultHeightFeet"]?.toString()?.toDoubleOrNull() ?: 8.0)
        }
    }
}
