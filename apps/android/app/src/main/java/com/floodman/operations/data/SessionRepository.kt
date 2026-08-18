package com.floodman.operations.data

import android.content.Context
import android.os.Build
import com.floodman.operations.BuildConfig
import com.floodman.operations.security.DeviceProof
import com.floodman.operations.security.SecureStore
import com.floodman.operations.security.StoredSession
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.JsonObject
import java.time.Instant
import java.util.UUID

class SessionRepository(context: Context) {
    val secureStore = SecureStore(context)
    val api = FloodmanApi(baseUrlProvider = { secureStore.apiBaseUrl(BuildConfig.FLOODMAN_API_BASE_URL) })
    private val refreshMutex = Mutex()
    @Volatile private var session: StoredSession? = secureStore.load()

    fun currentSession(): StoredSession? = session
    fun hasSession(): Boolean = session != null
    fun apiBaseUrl(): String = secureStore.apiBaseUrl(BuildConfig.FLOODMAN_API_BASE_URL).trimEnd('/')

    fun setApiBaseUrl(value: String) {
        val normalized = value.trim().trimEnd('/')
        require(normalized.startsWith("https://")) { "Floodman Android requires an HTTPS API address." }
        require(normalized.endsWith("/mobile-api")) { "The API address must end with /mobile-api." }
        secureStore.setApiBaseUrl(normalized)
        session = null
        secureStore.clear()
    }

    suspend fun login(email: String, password: String, useLocalAccount: Boolean): StoredSession {
        val deviceId = secureStore.deviceId()
        val result = api.login(
            email = email.trim(),
            password = password,
            authSource = if (useLocalAccount) "local" else "platform",
            deviceId = deviceId,
            deviceName = "${Build.MANUFACTURER} ${Build.MODEL}".trim(),
            appVersion = BuildConfig.VERSION_NAME,
        )
        val stored = StoredSession(
            accessToken = result.accessToken,
            accessExpiresAt = result.accessExpiresAt,
            refreshToken = result.refreshToken,
            refreshExpiresAt = result.refreshExpiresAt,
            deviceSecret = result.deviceSecret,
            deviceId = deviceId,
            userId = result.user.id,
            userEmail = result.user.email.orEmpty(),
            userName = result.user.name ?: result.user.email.orEmpty(),
            userRole = result.user.role,
        )
        secureStore.save(stored)
        session = stored
        return stored
    }

    suspend fun logout() {
        val value = session
        if (value != null) runCatching { api.logout(value.accessToken, value.refreshToken) }
        session = null
        secureStore.clear()
    }

    private fun accessStillValid(value: StoredSession): Boolean = runCatching {
        Instant.parse(value.accessExpiresAt).isAfter(Instant.now().plusSeconds(45))
    }.getOrDefault(false)

    suspend fun accessToken(forceRefresh: Boolean = false): String {
        val current = session ?: error("Not signed in")
        if (!forceRefresh && accessStillValid(current)) return current.accessToken
        return refreshMutex.withLock {
            val latest = session ?: error("Not signed in")
            if (!forceRefresh && accessStillValid(latest)) return@withLock latest.accessToken
            val timestamp = Instant.now().epochSecond
            val nonce = UUID.randomUUID().toString()
            val proof = DeviceProof.create(latest.deviceSecret, latest.deviceId, timestamp, nonce, latest.refreshToken)
            val response = api.refresh(latest.refreshToken, latest.deviceId, timestamp, nonce, proof)
            val updated = latest.copy(
                accessToken = response.accessToken,
                accessExpiresAt = response.accessExpiresAt,
                refreshToken = response.refreshToken,
                refreshExpiresAt = response.refreshExpiresAt,
            )
            secureStore.save(updated)
            session = updated
            updated.accessToken
        }
    }

    suspend fun <T> authorized(block: suspend (String) -> T): T {
        val token = accessToken()
        return try {
            block(token)
        } catch (error: ApiException) {
            if (error.statusCode != 401) throw error
            block(accessToken(forceRefresh = true))
        }
    }

    suspend fun config(): MobileConfig = api.config()
    suspend fun dashboard(): Dashboard = authorized(api::dashboard)
    suspend fun customers(search: String = "", page: Int = 1, workspaceId: String = ""): CustomerPage = authorized { api.customers(it, search, page, workspaceId) }
    suspend fun customer(id: String): CustomerDetail = authorized { api.customer(it, id) }
    suspend fun createCustomer(input: CustomerCreateInput): Customer = authorized { api.createCustomer(it, input) }
    suspend fun addNote(id: String, text: String, category: String, pinned: Boolean): NoteRecord = authorized { api.addCustomerNote(it, id, text, category, pinned) }
    suspend fun updateTags(id: String, tags: List<String>): Customer = authorized { api.updateCustomerTags(it, id, tags) }
    suspend fun properties(contactId: String = "", search: String = "", page: Int = 1, workspaceId: String = ""): PropertyPage = authorized { api.properties(it, contactId, search, page, workspaceId) }
    suspend fun createProperty(input: PropertyCreateInput): PropertyRecord = authorized { api.createProperty(it, input) }
    suspend fun estimates(search: String = "", status: String = "", page: Int = 1): EstimatePage = authorized { api.estimates(it, search, status, page) }
    suspend fun estimate(id: String): EstimateDetail = authorized { api.estimate(it, id) }
    suspend fun createEstimate(input: EstimateCreateInput): Estimate = authorized { api.createEstimate(it, input) }
    suspend fun invoices(search: String = "", status: String = "", page: Int = 1): InvoicePage = authorized { api.invoices(it, search, status, page) }
    suspend fun invoice(id: String): InvoiceDetail = authorized { api.invoice(it, id) }
    suspend fun catalog(search: String = "", page: Int = 1): CatalogPage = authorized { api.catalog(it, search, page) }
    suspend fun roomFlowBootstrap(): RoomFlowBootstrap = authorized(api::roomFlowBootstrap)
    suspend fun createRoomFlowWorkspace(input: RoomFlowWorkspaceCreateInput): RoomFlowWorkspaceResponse = authorized { api.createRoomFlowWorkspace(it, input) }
    suspend fun selectRoomFlowWorkspace(workspaceId: String): RoomFlowWorkspaceResponse = authorized { api.selectRoomFlowWorkspace(it, workspaceId) }
    suspend fun importRoomFlowSupabase(input: RoomFlowSupabaseImportInput): RoomFlowSupabaseImportResponse = authorized { api.importRoomFlowSupabase(it, input) }
    suspend fun roomFlowJobs(search: String = "", page: Int = 1): RoomFlowJobPage = authorized { api.roomFlowJobs(it, search, page) }
    suspend fun roomFlowJob(id: String): RoomFlowJobDetail = authorized { api.roomFlowJob(it, id) }
    suspend fun saveRoomFlowJob(id: String?, input: RoomFlowSaveInput): RoomFlowSaveResponse = authorized { token ->
        if (id.isNullOrBlank()) api.createRoomFlowJob(token, input) else api.updateRoomFlowJob(token, id, input)
    }
    suspend fun roomFlowCaptureRooms(jobId: String): JsonObject = authorized { api.roomFlowCaptureRooms(it, jobId) }
    suspend fun replayRoomFlowCaptureOperations(jobId: String, payload: JsonObject): JsonObject = authorized { api.replayRoomFlowCaptureOperations(it, jobId, payload) }
    suspend fun timeStatus(): TimeEntry? = authorized(api::timeStatus)
    suspend fun clockIn(jobReference: String, note: String): TimeEntry = authorized { api.clockIn(it, jobReference, note) }
    suspend fun clockOut(note: String): TimeEntry = authorized { api.clockOut(it, note) }
    suspend fun cardPayment(pending: PendingCardPayment, sourceId: String): PaymentResponse = authorized {
        api.cardPayment(
            accessToken = it,
            targetKind = pending.targetKind,
            targetId = pending.targetId,
            sourceId = sourceId,
            amountCents = pending.amountCents,
            saveCard = pending.saveCard,
            authorizationReference = pending.authorizationReference,
            note = pending.note,
        )
    }
    suspend fun manualPayment(input: ManualPaymentInput): PaymentResponse = authorized { api.manualPayment(it, input) }

    fun appearanceMode(): String = secureStore.appearanceMode()
    fun setAppearanceMode(value: String) = secureStore.setAppearanceMode(value)
    suspend fun projectPlans(): ProjectPlanPage = authorized(api::projectPlans)
    suspend fun projectPlan(category: String): ProjectPlan = authorized { api.projectPlan(it, category) }
    suspend fun updateEstimate(id: String, input: EstimateCreateInput): Estimate = authorized { api.updateEstimate(it, id, input) }
    suspend fun estimateAction(id: String, action: String, message: String = ""): EstimateActionResponse = authorized { api.estimateAction(it, id, action, message) }
    suspend fun estimatePdf(id: String): ByteArray = authorized { api.estimatePdf(it, id) }
    suspend fun createInvoice(input: InvoiceCreateInput): Invoice = authorized { api.createInvoice(it, input) }
    suspend fun updateInvoice(id: String, input: InvoiceCreateInput): Invoice = authorized { api.updateInvoice(it, id, input) }
    suspend fun invoiceAction(id: String, action: String): InvoiceActionResponse = authorized { api.invoiceAction(it, id, action) }
    suspend fun invoicePdf(id: String): ByteArray = authorized { api.invoicePdf(it, id) }
    suspend fun employees(search: String = ""): EmployeePage = authorized { api.employees(it, search) }
    suspend fun calendar(start: String = "", end: String = "", employeeId: String = ""): CalendarPage = authorized { api.calendar(it, start, end, employeeId) }
    suspend fun createAppointment(input: AppointmentInput): AppointmentResponse = authorized { api.createAppointment(it, input) }
    suspend fun updateAppointment(id: String, input: AppointmentInput): AppointmentResponse = authorized { api.updateAppointment(it, id, input) }
    suspend fun deleteAppointment(id: String) = authorized { api.deleteAppointment(it, id) }
    suspend fun createCalendarSubscription(): CalendarSubscriptionResponse = authorized { api.createCalendarSubscription(it) }
    suspend fun tasks(assignedToMe: Boolean = false): TaskPage = authorized { api.tasks(it, assignedToMe) }
    suspend fun createTask(input: TaskInput): TaskRecord = authorized { api.createTask(it, input) }
    suspend fun updateTask(id: String, input: TaskInput): TaskRecord = authorized { api.updateTask(it, id, input) }
    suspend fun announcements(): AnnouncementPage = authorized(api::announcements)
    suspend fun notifications(unreadOnly: Boolean = false): NotificationPage = authorized { api.notifications(it, unreadOnly) }
    suspend fun markNotificationRead(id: String): NotificationRecord = authorized { api.markNotificationRead(it, id) }

    suspend fun documents(contactId: String = "", propertyId: String = ""): DocumentPage = authorized { api.documents(it, contactId, propertyId) }
    suspend fun documentBytes(id: String, signed: Boolean = false): ByteArray = authorized { api.documentBytes(it, id, signed) }

}
