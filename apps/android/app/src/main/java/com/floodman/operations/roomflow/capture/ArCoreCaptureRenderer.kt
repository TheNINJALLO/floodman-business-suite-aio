package com.floodman.operations.roomflow.capture

import android.opengl.GLES11Ext
import android.opengl.GLES20
import android.opengl.GLSurfaceView
import com.google.ar.core.DepthPoint
import com.google.ar.core.Frame
import com.google.ar.core.Plane
import com.google.ar.core.Point
import com.google.ar.core.Session
import com.google.ar.core.TrackingState
import com.google.ar.core.exceptions.CameraNotAvailableException
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer
import java.util.ArrayDeque
import javax.microedition.khronos.egl.EGLConfig
import javax.microedition.khronos.opengles.GL10

class ArCoreCaptureRenderer(
    private val sessionProvider: () -> Session?,
    private val displayRotation: () -> Int,
    private val statusListener: (String, Boolean) -> Unit,
) : GLSurfaceView.Renderer, RoomCaptureProvider {
    private val quadCoordinates = direct(floatArrayOf(-1f, -1f, 1f, -1f, -1f, 1f, 1f, 1f))
    private val textureCoordinates = direct(FloatArray(8))
    private val recentSamples = ArrayDeque<HitSample>()
    private var viewportWidth = 1
    private var viewportHeight = 1
    private var cameraTexture = 0
    private var shaderProgram = 0
    private var textureAttachedSession: Session? = null
    private var depthSupported = false
    private var status = "Move slowly while ARCore finds the room surfaces."

    fun onSessionConfigured(session: Session, supportsDepth: Boolean) {
        depthSupported = supportsDepth
        textureAttachedSession = null
        synchronized(recentSamples) { recentSamples.clear() }
        status = if (supportsDepth) "Depth is active. Aim the center reticle at a floor-level wall corner." else "ARCore is active without depth. Verify every wall after capture."
    }

    override fun capabilities(): CaptureCapabilities = CaptureCapabilities(
        supported = true,
        modes = if (depthSupported) listOf("android-arcore-depth", "android-arcore-guided") else listOf("android-arcore-guided"),
        preferredMode = if (depthSupported) "android-arcore-depth" else "android-arcore-guided",
        depthSupported = depthSupported,
    )

    override fun recentHitSamples(): List<HitSample> = synchronized(recentSamples) { recentSamples.toList() }

    override fun cancel() = synchronized(recentSamples) { recentSamples.clear() }

    override fun onSurfaceCreated(gl: GL10?, config: EGLConfig?) {
        GLES20.glClearColor(0f, 0f, 0f, 1f)
        cameraTexture = createExternalTexture()
        shaderProgram = createProgram(VERTEX_SHADER, FRAGMENT_SHADER)
    }

    override fun onSurfaceChanged(gl: GL10?, width: Int, height: Int) {
        viewportWidth = width.coerceAtLeast(1)
        viewportHeight = height.coerceAtLeast(1)
        GLES20.glViewport(0, 0, viewportWidth, viewportHeight)
    }

    override fun onDrawFrame(gl: GL10?) {
        GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT or GLES20.GL_DEPTH_BUFFER_BIT)
        val session = sessionProvider() ?: return
        if (textureAttachedSession !== session) {
            session.setCameraTextureNames(intArrayOf(cameraTexture))
            textureAttachedSession = session
        }
        session.setDisplayGeometry(displayRotation(), viewportWidth, viewportHeight)
        val frame = try {
            session.update()
        } catch (_: CameraNotAvailableException) {
            statusListener("The camera became unavailable. Close other camera apps and try again.", false)
            return
        }
        if (frame.timestamp != 0L) drawCamera(frame)
        val camera = frame.camera
        if (camera.trackingState != TrackingState.TRACKING) {
            synchronized(recentSamples) { recentSamples.clear() }
            statusListener("Move slowly while ARCore finds the room surfaces.", false)
            return
        }
        val sample = centerHit(frame)
        if (sample == null) {
            synchronized(recentSamples) { recentSamples.clear() }
            statusListener("Aim the center reticle at a visible wall or floor corner.", false)
        } else {
            synchronized(recentSamples) {
                recentSamples.addLast(sample)
                while (recentSamples.size > 20) recentSamples.removeFirst()
                while (recentSamples.isNotEmpty() && sample.timestampMillis - recentSamples.first().timestampMillis > 900) recentSamples.removeFirst()
            }
            val message = if (sample.depthValidated) "Depth lock ready — tap Add corner." else "ARCore point ready — hold steady, then tap Add corner."
            if (message != status) { status = message; statusListener(message, true) }
        }
    }

    private fun centerHit(frame: Frame): HitSample? {
        val hit = frame.hitTest(viewportWidth / 2f, viewportHeight / 2f).firstOrNull { result ->
            when (val trackable = result.trackable) {
                is DepthPoint -> true
                is Plane -> trackable.isPoseInPolygon(result.hitPose)
                is Point -> trackable.orientationMode == Point.OrientationMode.ESTIMATED_SURFACE_NORMAL
                else -> false
            }
        } ?: return null
        val pose = hit.hitPose
        val isDepth = hit.trackable is DepthPoint
        return HitSample(
            worldX = pose.tx().toDouble(),
            worldY = pose.ty().toDouble(),
            worldZ = pose.tz().toDouble(),
            confidence = if (isDepth) 0.95 else if (hit.trackable is Plane) 0.85 else 0.7,
            depthValidated = isDepth,
            tracking = true,
            timestampMillis = System.currentTimeMillis(),
        )
    }

    private fun drawCamera(frame: Frame) {
        frame.transformCoordinates2d(
            com.google.ar.core.Coordinates2d.OPENGL_NORMALIZED_DEVICE_COORDINATES,
            quadCoordinates,
            com.google.ar.core.Coordinates2d.TEXTURE_NORMALIZED,
            textureCoordinates,
        )
        GLES20.glDisable(GLES20.GL_DEPTH_TEST)
        GLES20.glDepthMask(false)
        GLES20.glUseProgram(shaderProgram)
        val position = GLES20.glGetAttribLocation(shaderProgram, "a_Position")
        val texture = GLES20.glGetAttribLocation(shaderProgram, "a_TexCoord")
        GLES20.glEnableVertexAttribArray(position)
        GLES20.glVertexAttribPointer(position, 2, GLES20.GL_FLOAT, false, 0, quadCoordinates)
        GLES20.glEnableVertexAttribArray(texture)
        GLES20.glVertexAttribPointer(texture, 2, GLES20.GL_FLOAT, false, 0, textureCoordinates)
        GLES20.glActiveTexture(GLES20.GL_TEXTURE0)
        GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, cameraTexture)
        GLES20.glUniform1i(GLES20.glGetUniformLocation(shaderProgram, "u_Texture"), 0)
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4)
        GLES20.glDisableVertexAttribArray(position)
        GLES20.glDisableVertexAttribArray(texture)
        GLES20.glDepthMask(true)
    }

    private fun createExternalTexture(): Int {
        val textures = IntArray(1)
        GLES20.glGenTextures(1, textures, 0)
        GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, textures[0])
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_LINEAR)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_LINEAR)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_CLAMP_TO_EDGE)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_CLAMP_TO_EDGE)
        return textures[0]
    }

    private fun createProgram(vertexSource: String, fragmentSource: String): Int {
        fun shader(type: Int, source: String): Int = GLES20.glCreateShader(type).also {
            GLES20.glShaderSource(it, source)
            GLES20.glCompileShader(it)
            val result = IntArray(1)
            GLES20.glGetShaderiv(it, GLES20.GL_COMPILE_STATUS, result, 0)
            check(result[0] == GLES20.GL_TRUE) { "Room capture shader failed: ${GLES20.glGetShaderInfoLog(it)}" }
        }
        val vertex = shader(GLES20.GL_VERTEX_SHADER, vertexSource)
        val fragment = shader(GLES20.GL_FRAGMENT_SHADER, fragmentSource)
        return GLES20.glCreateProgram().also {
            GLES20.glAttachShader(it, vertex)
            GLES20.glAttachShader(it, fragment)
            GLES20.glLinkProgram(it)
            val result = IntArray(1)
            GLES20.glGetProgramiv(it, GLES20.GL_LINK_STATUS, result, 0)
            check(result[0] == GLES20.GL_TRUE) { "Room capture shader link failed: ${GLES20.glGetProgramInfoLog(it)}" }
            GLES20.glDeleteShader(vertex)
            GLES20.glDeleteShader(fragment)
        }
    }

    companion object {
        private fun direct(values: FloatArray): FloatBuffer = ByteBuffer.allocateDirect(values.size * 4).order(ByteOrder.nativeOrder()).asFloatBuffer().apply { put(values); position(0) }
        private const val VERTEX_SHADER = "attribute vec2 a_Position; attribute vec2 a_TexCoord; varying vec2 v_TexCoord; void main(){ gl_Position=vec4(a_Position,0.0,1.0); v_TexCoord=a_TexCoord; }"
        private const val FRAGMENT_SHADER = "#extension GL_OES_EGL_image_external : require\nprecision mediump float; varying vec2 v_TexCoord; uniform samplerExternalOES u_Texture; void main(){ gl_FragColor=texture2D(u_Texture,v_TexCoord); }"
    }
}
