package com.floodman.operations.security

import java.nio.charset.StandardCharsets
import java.util.Base64
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

object DeviceProof {
    fun sha256(value: String): String = java.security.MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray(StandardCharsets.UTF_8))
        .joinToString("") { "%02x".format(it) }

    fun create(deviceSecret: String, deviceId: String, timestamp: Long, nonce: String, refreshToken: String): String {
        val rawSecret = Base64.getUrlDecoder().decode(pad(deviceSecret))
        val canonical = "$deviceId.$timestamp.$nonce.${sha256(refreshToken)}"
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(rawSecret, "HmacSHA256"))
        return Base64.getUrlEncoder().withoutPadding().encodeToString(mac.doFinal(canonical.toByteArray(StandardCharsets.UTF_8)))
    }

    private fun pad(value: String): String = value + "=".repeat((4 - value.length % 4) % 4)
}
