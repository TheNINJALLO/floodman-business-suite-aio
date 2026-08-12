package com.floodman.operations

import android.content.Intent
import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import com.floodman.operations.payments.PaymentCoordinator
import com.floodman.operations.ui.FloodmanApp
import com.floodman.operations.ui.MainViewModel
import com.floodman.operations.ui.theme.FloodmanTheme
import sqip.CardEntry
import sqip.CardEntryActivityResult
import sqip.handleActivityResult

class MainActivity : FragmentActivity() {
    private val viewModel: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            FloodmanTheme(mode = viewModel.appearanceMode) {
                FloodmanApp(
                    viewModel = viewModel,
                    requestDeviceUnlock = ::requestDeviceUnlock,
                    startCardEntry = { CardEntry.startCardEntryActivity(this, true) },
                )
            }
        }
    }

    private fun requestDeviceUnlock() {
        val authenticators = BiometricManager.Authenticators.BIOMETRIC_STRONG or
            BiometricManager.Authenticators.DEVICE_CREDENTIAL
        val prompt = BiometricPrompt(
            this,
            ContextCompat.getMainExecutor(this),
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    viewModel.unlock()
                }
            },
        )
        prompt.authenticate(
            BiometricPrompt.PromptInfo.Builder()
                .setTitle("Unlock Floodman Operations")
                .setSubtitle("Use your fingerprint, face, or device PIN")
                .setAllowedAuthenticators(authenticators)
                .build(),
        )
    }

    @Deprecated("Square's current card-entry SDK still reports through onActivityResult")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != CardEntry.DEFAULT_CARD_ENTRY_REQUEST_CODE) return
        CardEntry.handleActivityResult(data) { result: CardEntryActivityResult ->
            when (result) {
                is CardEntryActivityResult.Success -> Unit
                is CardEntryActivityResult.Canceled -> PaymentCoordinator.canceled()
            }
        }
    }
}
