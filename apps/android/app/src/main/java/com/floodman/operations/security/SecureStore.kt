package com.floodman.operations.security

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import kotlinx.serialization.Serializable
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

@Serializable
data class StoredSession(
    val accessToken: String,
    val accessExpiresAt: String,
    val refreshToken: String,
    val refreshExpiresAt: String,
    val deviceSecret: String,
    val deviceId: String,
    val userId: String,
    val userEmail: String,
    val userName: String,
    val userRole: String,
)

class SecureStore(context: Context) {
    private val prefs = context.getSharedPreferences("floodman_secure", Context.MODE_PRIVATE)
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }
    private val alias = "floodman.operations.session.v1"

    private fun key(): SecretKey {
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (keyStore.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").run {
            init(
                KeyGenParameterSpec.Builder(
                    alias,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .setRandomizedEncryptionRequired(true)
                    .build(),
            )
            generateKey()
        }
    }

    fun save(session: StoredSession) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val payload = json.encodeToString(session).toByteArray(Charsets.UTF_8)
        val encrypted = cipher.doFinal(payload)
        prefs.edit()
            .putString("session_iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .putString("session_data", Base64.encodeToString(encrypted, Base64.NO_WRAP))
            .apply()
    }

    fun load(): StoredSession? = runCatching {
        val iv = Base64.decode(prefs.getString("session_iv", null), Base64.NO_WRAP)
        val data = Base64.decode(prefs.getString("session_data", null), Base64.NO_WRAP)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv))
        json.decodeFromString<StoredSession>(cipher.doFinal(data).toString(Charsets.UTF_8))
    }.getOrNull()

    fun clear() {
        prefs.edit().remove("session_iv").remove("session_data").apply()
    }

    fun deviceId(): String {
        val existing = prefs.getString("device_id", null)
        if (!existing.isNullOrBlank()) return existing
        val value = "android-${java.util.UUID.randomUUID()}"
        prefs.edit().putString("device_id", value).apply()
        return value
    }


    fun apiBaseUrl(defaultValue: String): String = prefs.getString("api_base_url", null)?.trim()?.takeIf { it.isNotBlank() } ?: defaultValue

    fun setApiBaseUrl(value: String) {
        prefs.edit().putString("api_base_url", value.trim().trimEnd('/') + "/").apply()
    }

    fun biometricEnabled(): Boolean = prefs.getBoolean("biometric_enabled", true)
    fun setBiometricEnabled(enabled: Boolean) = prefs.edit().putBoolean("biometric_enabled", enabled).apply()

    fun appearanceMode(): String = prefs.getString("appearance_mode", "SYSTEM") ?: "SYSTEM"
    fun setAppearanceMode(value: String) = prefs.edit().putString("appearance_mode", value.uppercase()).apply()
}
