package com.floodman.operations.security

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test
import java.util.Base64
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

class DeviceProofTest {
    @Test
    fun proofMatchesServerCanonicalHmac() {
        val rawSecret = "01234567890123456789012345678901".toByteArray()
        val encodedSecret = Base64.getUrlEncoder().withoutPadding().encodeToString(rawSecret)
        val deviceId = "android-test-device"
        val timestamp = 1_800_000_000L
        val nonce = "nonce-12345678"
        val refresh = "refresh-token-value"
        val canonical = "$deviceId.$timestamp.$nonce.${DeviceProof.sha256(refresh)}"
        val mac = Mac.getInstance("HmacSHA256").apply { init(SecretKeySpec(rawSecret, "HmacSHA256")) }
        val expected = Base64.getUrlEncoder().withoutPadding().encodeToString(mac.doFinal(canonical.toByteArray()))

        assertEquals(expected, DeviceProof.create(encodedSecret, deviceId, timestamp, nonce, refresh))
        assertNotEquals(expected, DeviceProof.create(encodedSecret, deviceId, timestamp, "different-nonce", refresh))
    }
}
