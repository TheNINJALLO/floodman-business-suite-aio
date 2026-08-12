package com.floodman.operations.payments

import com.floodman.operations.data.AppGraph
import com.floodman.operations.data.PendingCardPayment
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.runBlocking
import sqip.CardEntryActivityCommand
import sqip.CardDetails

sealed interface PaymentEvent {
    data class Success(val message: String, val targetKind: String, val targetId: String) : PaymentEvent
    data class Error(val message: String) : PaymentEvent
    data object Canceled : PaymentEvent
}

object PaymentCoordinator {
    @Volatile private var pending: PendingCardPayment? = null
    private val _events = MutableSharedFlow<PaymentEvent>(extraBufferCapacity = 8)
    val events = _events.asSharedFlow()

    fun prepare(value: PendingCardPayment) { pending = value }
    fun clear() { pending = null }
    fun canceled() { pending = null; _events.tryEmit(PaymentEvent.Canceled) }

    fun handleCard(cardDetails: CardDetails): CardEntryActivityCommand {
        val request = pending ?: return CardEntryActivityCommand.ShowError("No Floodman payment is waiting for card entry.")
        return try {
            runBlocking { AppGraph.repository.cardPayment(request, cardDetails.nonce) }
            pending = null
            _events.tryEmit(PaymentEvent.Success("Payment completed.", request.targetKind, request.targetId))
            CardEntryActivityCommand.Finish()
        } catch (error: Exception) {
            val message = error.message ?: "Payment could not be completed."
            _events.tryEmit(PaymentEvent.Error(message))
            CardEntryActivityCommand.ShowError(message)
        }
    }
}
