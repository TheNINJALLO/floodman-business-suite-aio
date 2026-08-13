package com.floodman.operations.data

import com.floodman.operations.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

class ApiException(val statusCode: Int, message: String) : IOException(message)

class FloodmanApi(
    private val baseUrlProvider: () -> String = { BuildConfig.FLOODMAN_API_BASE_URL },
    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(90, TimeUnit.SECONDS)
        .writeTimeout(90, TimeUnit.SECONDS)
        .callTimeout(120, TimeUnit.SECONDS)
        .build(),
    private val json: Json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        encodeDefaults = true
    },
) {
    private val jsonMedia = "application/json; charset=utf-8".toMediaType()

    private fun publicRoot(): String = baseUrlProvider().trim().trimEnd('/')
    private fun apiRoot(): String = publicRoot() + "/v1"
    fun publicBaseUrl(): String = publicRoot()

    private suspend fun rawRequest(
        path: String,
        method: String = "GET",
        accessToken: String? = null,
        body: String? = null,
    ): String = withContext(Dispatchers.IO) {
        val requestBuilder = Request.Builder().url(apiRoot() + path)
            .header("Accept", "application/json")
            .header("X-Floodman-App", "android/${BuildConfig.VERSION_NAME}")
        if (!accessToken.isNullOrBlank()) requestBuilder.header("Authorization", "Bearer $accessToken")
        when (method) {
            "GET" -> requestBuilder.get()
            "DELETE" -> requestBuilder.delete(body?.toRequestBody(jsonMedia))
            else -> requestBuilder.method(method, (body ?: "{}").toRequestBody(jsonMedia))
        }
        client.newCall(requestBuilder.build()).execute().use { response ->
            val responseBody = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val message = responseMessage(responseBody, "Floodman request failed (${response.code})")
                if (response.code == 404 && message.equals("Not Found", ignoreCase = true)) {
                    throw ApiException(response.code, serverUpgradeMessage())
                }
                throw ApiException(response.code, message)
            }
            responseBody
        }
    }

    private fun serverUpgradeMessage(): String =
        "This Android build requires Floodman server v4.6.3. Install the matching v4.6.3 runtime and launcher, then try again."

    private fun responseMessage(value: String, fallback: String): String = runCatching {
        val obj = json.parseToJsonElement(value) as? JsonObject
        obj?.get("detail")?.toString()?.trim('"')
            ?: obj?.get("message")?.toString()?.trim('"')
            ?: value
    }.getOrDefault(value).ifBlank { fallback }

    private suspend fun rawBytes(path: String, accessToken: String, requirePdf: Boolean = false): ByteArray = withContext(Dispatchers.IO) {
        val request = Request.Builder().url(apiRoot() + path)
            .header("Accept", if (requirePdf) "application/pdf" else "*/*")
            .header("Authorization", "Bearer $accessToken")
            .header("X-Floodman-App", "android/${BuildConfig.VERSION_NAME}")
            .get().build()
        client.newCall(request).execute().use { response ->
            val bytes = response.body?.bytes() ?: byteArrayOf()
            val text = bytes.toString(Charsets.UTF_8).take(4_000)
            if (!response.isSuccessful) {
                val message = responseMessage(text, "Floodman download failed (${response.code})")
                if (response.code == 404 && message.equals("Not Found", ignoreCase = true)) {
                    throw ApiException(response.code, serverUpgradeMessage())
                }
                throw ApiException(response.code, message)
            }
            if (requirePdf) {
                val mediaType = response.header("Content-Type").orEmpty().lowercase()
                val pdfSignature = bytes.size >= 5 && bytes.copyOfRange(0, 5).contentEquals("%PDF-".toByteArray())
                if (!mediaType.contains("application/pdf") || !pdfSignature) {
                    val message = responseMessage(text, "Floodman returned a non-PDF response.")
                    if (message.equals("Not Found", ignoreCase = true) || mediaType.contains("application/json") || mediaType.contains("text/html")) {
                        throw ApiException(response.code, "${message}\n\n${serverUpgradeMessage()}")
                    }
                    throw ApiException(response.code, message)
                }
            }
            bytes
        }
    }

    private inline fun <reified T> decode(value: String): T = json.decodeFromString(value)
    private inline fun <reified T> encode(value: T): String = json.encodeToString(value)
    private fun query(value: String): String = URLEncoder.encode(value, Charsets.UTF_8.name())

    suspend fun health(): ServerHealth = decode(rawRequest("/health"))
    suspend fun config(): MobileConfig = decode(rawRequest("/config"))

    suspend fun login(
        email: String,
        password: String,
        authSource: String,
        deviceId: String,
        deviceName: String,
        appVersion: String,
    ): LoginResponse {
        val payload = buildJsonObject {
            put("email", email)
            put("password", password)
            put("auth_source", authSource)
            put("device_id", deviceId)
            put("device_name", deviceName)
            put("platform", "android")
            put("app_version", appVersion)
        }
        return decode(rawRequest("/auth/login", "POST", body = payload.toString()))
    }

    suspend fun refresh(refreshToken: String, deviceId: String, timestamp: Long, nonce: String, proof: String): RefreshResponse {
        val payload = buildJsonObject {
            put("refresh_token", refreshToken)
            put("device_id", deviceId)
            put("timestamp", timestamp)
            put("nonce", nonce)
            put("proof", proof)
        }
        return decode(rawRequest("/auth/refresh", "POST", body = payload.toString()))
    }

    suspend fun logout(accessToken: String, refreshToken: String) {
        val payload = buildJsonObject { put("refresh_token", refreshToken) }
        rawRequest("/auth/logout", "POST", accessToken, payload.toString())
    }

    suspend fun me(accessToken: String): UserSummary = decode(rawRequest("/auth/me", accessToken = accessToken))
    suspend fun dashboard(accessToken: String): Dashboard = decode(rawRequest("/dashboard", accessToken = accessToken))

    suspend fun customers(accessToken: String, search: String = "", page: Int = 1): CustomerPage =
        decode(rawRequest("/customers?q=${query(search)}&page=$page&page_size=50", accessToken = accessToken))

    suspend fun customer(accessToken: String, id: String): CustomerDetail =
        decode(rawRequest("/customers/${query(id)}", accessToken = accessToken))

    suspend fun createCustomer(accessToken: String, input: CustomerCreateInput): Customer =
        decode(rawRequest("/customers", "POST", accessToken, encode(input)))

    suspend fun addCustomerNote(accessToken: String, id: String, text: String, category: String, pinned: Boolean): NoteRecord {
        val payload = buildJsonObject { put("text", text); put("category", category); put("pinned", pinned) }
        return decode(rawRequest("/customers/${query(id)}/notes", "POST", accessToken, payload.toString()))
    }

    suspend fun updateCustomerTags(accessToken: String, id: String, tags: List<String>): Customer {
        val payload = json.encodeToString(mapOf("tags" to tags))
        return decode(rawRequest("/customers/${query(id)}/tags", "PUT", accessToken, payload))
    }

    suspend fun properties(accessToken: String, contactId: String = "", search: String = "", page: Int = 1): PropertyPage =
        decode(rawRequest("/properties?contact_id=${query(contactId)}&q=${query(search)}&page=$page&page_size=50", accessToken = accessToken))

    suspend fun createProperty(accessToken: String, input: PropertyCreateInput): PropertyRecord =
        decode(rawRequest("/properties", "POST", accessToken, encode(input)))

    suspend fun estimates(accessToken: String, search: String = "", status: String = "", page: Int = 1): EstimatePage =
        decode(rawRequest("/estimates?q=${query(search)}&status=${query(status)}&page=$page&page_size=50", accessToken = accessToken))

    suspend fun estimate(accessToken: String, id: String): EstimateDetail =
        decode(rawRequest("/estimates/${query(id)}", accessToken = accessToken))

    suspend fun createEstimate(accessToken: String, input: EstimateCreateInput): Estimate =
        decode(rawRequest("/estimates", "POST", accessToken, encode(input)))

    suspend fun invoices(accessToken: String, search: String = "", status: String = "", page: Int = 1): InvoicePage =
        decode(rawRequest("/invoices?q=${query(search)}&status=${query(status)}&page=$page&page_size=50", accessToken = accessToken))

    suspend fun invoice(accessToken: String, id: String): InvoiceDetail =
        decode(rawRequest("/invoices/${query(id)}", accessToken = accessToken))

    suspend fun catalog(accessToken: String, search: String = "", page: Int = 1): CatalogPage =
        decode(rawRequest("/catalog?q=${query(search)}&page=$page&page_size=50", accessToken = accessToken))

    suspend fun roomFlowBootstrap(accessToken: String): RoomFlowBootstrap =
        decode(rawRequest("/roomflow/bootstrap", accessToken = accessToken))

    suspend fun createRoomFlowWorkspace(accessToken: String, input: RoomFlowWorkspaceCreateInput): RoomFlowWorkspaceResponse =
        decode(rawRequest("/roomflow/workspaces", "POST", accessToken, encode(input)))

    suspend fun selectRoomFlowWorkspace(accessToken: String, workspaceId: String): RoomFlowWorkspaceResponse =
        decode(rawRequest("/roomflow/workspaces/${query(workspaceId)}/select", "POST", accessToken, "{}"))

    suspend fun importRoomFlowSupabase(accessToken: String, input: RoomFlowSupabaseImportInput): RoomFlowSupabaseImportResponse =
        decode(rawRequest("/roomflow/import/supabase", "POST", accessToken, encode(input)))

    suspend fun roomFlowJobs(accessToken: String, search: String = "", page: Int = 1): RoomFlowJobPage =
        decode(rawRequest("/roomflow/jobs?q=${query(search)}&page=$page&page_size=50", accessToken = accessToken))

    suspend fun roomFlowJob(accessToken: String, id: String): RoomFlowJobDetail =
        decode(rawRequest("/roomflow/jobs/${query(id)}", accessToken = accessToken))

    suspend fun createRoomFlowJob(accessToken: String, input: RoomFlowSaveInput): RoomFlowSaveResponse =
        decode(rawRequest("/roomflow/jobs", "POST", accessToken, encode(input)))

    suspend fun updateRoomFlowJob(accessToken: String, id: String, input: RoomFlowSaveInput): RoomFlowSaveResponse =
        decode(rawRequest("/roomflow/jobs/${query(id)}", "PUT", accessToken, encode(input)))

    suspend fun timeStatus(accessToken: String): TimeEntry? {
        val obj: JsonObject = decode(rawRequest("/time/status", accessToken = accessToken))
        val value = obj["clock"] ?: return null
        if (value.toString() == "null") return null
        return json.decodeFromJsonElement(value)
    }

    suspend fun clockIn(accessToken: String, jobReference: String, note: String): TimeEntry {
        val payload = buildJsonObject { put("job_reference", jobReference); put("note", note) }
        return decode(rawRequest("/time/clock-in", "POST", accessToken, payload.toString()))
    }

    suspend fun clockOut(accessToken: String, note: String): TimeEntry {
        val payload = buildJsonObject { put("note", note); put("job_reference", "") }
        return decode(rawRequest("/time/clock-out", "POST", accessToken, payload.toString()))
    }

    suspend fun cardPayment(
        accessToken: String,
        targetKind: String,
        targetId: String,
        sourceId: String,
        amountCents: Long,
        saveCard: Boolean,
        authorizationReference: String,
        note: String,
    ): PaymentResponse {
        val payload = buildJsonObject {
            put("target_kind", targetKind)
            put("target_id", targetId)
            put("source_id", sourceId)
            put("amount_cents", amountCents)
            put("save_card", saveCard)
            put("authorization_reference", authorizationReference)
            put("note", note)
        }
        return decode(rawRequest("/payments/card", "POST", accessToken, payload.toString()))
    }

    suspend fun manualPayment(accessToken: String, input: ManualPaymentInput): PaymentResponse {
        val payload = buildJsonObject {
            put("target_kind", input.targetKind)
            put("target_id", input.targetId)
            put("amount_cents", input.amountCents)
            put("method", input.method)
            put("reference", input.reference)
            put("note", input.note)
            put("check_date", input.checkDate)
            put("bank_name", input.bankName)
            put("check_status", input.checkStatus)
        }
        return decode(rawRequest("/payments/manual", "POST", accessToken, payload.toString()))
    }

    suspend fun projectPlans(accessToken: String): ProjectPlanPage =
        decode(rawRequest("/project-plans", accessToken = accessToken))

    suspend fun projectPlan(accessToken: String, category: String): ProjectPlan =
        decode(rawRequest("/project-plans/${query(category)}", accessToken = accessToken))

    suspend fun updateEstimate(accessToken: String, id: String, input: EstimateCreateInput): Estimate =
        decode(rawRequest("/estimates/${query(id)}", "PATCH", accessToken, encode(input)))

    suspend fun estimateAction(accessToken: String, id: String, action: String, message: String = ""): EstimateActionResponse {
        val payload = buildJsonObject { put("action", action); put("message", message); put("force", false) }
        return decode(rawRequest("/estimates/${query(id)}/action", "POST", accessToken, payload.toString()))
    }

    suspend fun estimatePdf(accessToken: String, id: String): ByteArray = rawBytes("/estimates/${query(id)}/pdf", accessToken, requirePdf = true)

    suspend fun createInvoice(accessToken: String, input: InvoiceCreateInput): Invoice =
        decode(rawRequest("/invoices", "POST", accessToken, encode(input)))

    suspend fun updateInvoice(accessToken: String, id: String, input: InvoiceCreateInput): Invoice =
        decode(rawRequest("/invoices/${query(id)}", "PATCH", accessToken, encode(input)))

    suspend fun invoiceAction(accessToken: String, id: String, action: String): InvoiceActionResponse {
        val payload = buildJsonObject { put("action", action); put("message", ""); put("force", false) }
        return decode(rawRequest("/invoices/${query(id)}/action", "POST", accessToken, payload.toString()))
    }

    suspend fun invoicePdf(accessToken: String, id: String): ByteArray = rawBytes("/invoices/${query(id)}/pdf", accessToken, requirePdf = true)

    suspend fun employees(accessToken: String, search: String = ""): EmployeePage =
        decode(rawRequest("/employees?q=${query(search)}", accessToken = accessToken))

    suspend fun calendar(accessToken: String, start: String = "", end: String = "", employeeId: String = ""): CalendarPage =
        decode(rawRequest("/calendar?start=${query(start)}&end=${query(end)}&employee_id=${query(employeeId)}", accessToken = accessToken))

    suspend fun createAppointment(accessToken: String, input: AppointmentInput): AppointmentResponse =
        decode(rawRequest("/appointments", "POST", accessToken, encode(input)))

    suspend fun updateAppointment(accessToken: String, id: String, input: AppointmentInput): AppointmentResponse =
        decode(rawRequest("/appointments/${query(id)}", "PATCH", accessToken, encode(input)))

    suspend fun deleteAppointment(accessToken: String, id: String) {
        rawRequest("/appointments/${query(id)}", "DELETE", accessToken)
    }

    suspend fun createCalendarSubscription(accessToken: String): CalendarSubscriptionResponse =
        decode(rawRequest("/calendar/subscription", "POST", accessToken, "{}"))

    suspend fun tasks(accessToken: String, assignedToMe: Boolean = false): TaskPage =
        decode(rawRequest("/tasks?assigned_to_me=$assignedToMe&page=1&page_size=100", accessToken = accessToken))

    suspend fun createTask(accessToken: String, input: TaskInput): TaskRecord =
        decode(rawRequest("/tasks", "POST", accessToken, encode(input)))

    suspend fun updateTask(accessToken: String, id: String, input: TaskInput): TaskRecord =
        decode(rawRequest("/tasks/${query(id)}", "PATCH", accessToken, encode(input)))

    suspend fun announcements(accessToken: String): AnnouncementPage =
        decode(rawRequest("/announcements", accessToken = accessToken))

    suspend fun notifications(accessToken: String, unreadOnly: Boolean = false): NotificationPage =
        decode(rawRequest("/notifications?unread_only=$unreadOnly", accessToken = accessToken))

    suspend fun markNotificationRead(accessToken: String, id: String): NotificationRecord =
        decode(rawRequest("/notifications/${query(id)}/read", "POST", accessToken, "{}"))


    suspend fun documents(accessToken: String, contactId: String = "", propertyId: String = "", page: Int = 1): DocumentPage =
        decode(rawRequest("/documents?contact_id=${query(contactId)}&property_id=${query(propertyId)}&page=$page&page_size=100", accessToken = accessToken))

    suspend fun documentBytes(accessToken: String, id: String, signed: Boolean = false): ByteArray =
        rawBytes("/documents/${query(id)}/download?signed=$signed", accessToken)

}
