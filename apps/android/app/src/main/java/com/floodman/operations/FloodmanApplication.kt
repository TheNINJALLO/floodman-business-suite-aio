package com.floodman.operations

import android.app.Application
import com.floodman.operations.data.AppGraph
import com.floodman.operations.payments.PaymentCoordinator
import sqip.CardDetails
import sqip.CardEntry
import sqip.CardEntryActivityCommand
import sqip.CardNonceBackgroundHandler

class FloodmanApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        AppGraph.initialize(this)
        CardEntry.setCardNonceBackgroundHandler(
            object : CardNonceBackgroundHandler {
                override fun handleEnteredCardInBackground(cardDetails: CardDetails): CardEntryActivityCommand =
                    PaymentCoordinator.handleCard(cardDetails)
            },
        )
    }
}
