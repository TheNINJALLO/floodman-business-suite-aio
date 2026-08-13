package com.floodman.operations.data

import android.content.Context

object AppGraph {
    lateinit var repository: SessionRepository
        private set

    fun initialize(context: Context) {
        if (!::repository.isInitialized) repository = SessionRepository(context.applicationContext)
    }
}
