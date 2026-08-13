package com.floodman.operations.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

@Serializable
data class UserSummary(
    val id: String,
    val email: String? = null,
    val name: String? = null,
    val role: String = "VIEWER",
    val permissions: List<String> = emptyList(),
)

@Serializable
data class DeviceRecord(
    val id: String,
    @SerialName("user_id") val userId: String? = null,
    val name: String = "Android device",
    val platform: String = "android",
    @SerialName("app_version") val appVersion: String = "",
    val status: String = "ACTIVE",
    @SerialName("last_seen_at") val lastSeenAt: String? = null,
)

@Serializable
data class LoginResponse(
    @SerialName("access_token") val accessToken: String,
    @SerialName("access_expires_at") val accessExpiresAt: String,
    @SerialName("refresh_token") val refreshToken: String,
    @SerialName("refresh_expires_at") val refreshExpiresAt: String,
    @SerialName("device_secret") val deviceSecret: String,
    @SerialName("token_type") val tokenType: String,
    val user: UserSummary,
    val device: DeviceRecord,
)

@Serializable
data class RefreshResponse(
    @SerialName("access_token") val accessToken: String,
    @SerialName("access_expires_at") val accessExpiresAt: String,
    @SerialName("refresh_token") val refreshToken: String,
    @SerialName("refresh_expires_at") val refreshExpiresAt: String,
    @SerialName("token_type") val tokenType: String,
)

@Serializable
data class MobileConfig(
    @SerialName("api_version") val apiVersion: String,
    val company: String,
    @SerialName("time_zone") val timeZone: String,
    val payments: PaymentConfig = PaymentConfig(),
    @SerialName("customer_public_url") val customerPublicUrl: String = "",
    @SerialName("minimum_android_version") val minimumAndroidVersion: String = "",
    val capabilities: List<String> = emptyList(),
    @SerialName("roomflow_import") val roomFlowImport: RoomFlowImportCapability = RoomFlowImportCapability(),
)

@Serializable
data class RoomFlowImportCapability(
    val enabled: Boolean = false,
    val source: String = "",
)

@Serializable
data class ServerHealth(
    val status: String = "",
    val service: String = "",
    @SerialName("api_version") val apiVersion: String = "",
    @SerialName("server_release") val serverRelease: String = "",
    @SerialName("authentication_configured") val authenticationConfigured: Boolean = false,
    @SerialName("time_zone") val timeZone: String = "America/Detroit",
    @SerialName("minimum_android_version") val minimumAndroidVersion: String = "",
    val capabilities: List<String> = emptyList(),
)

@Serializable
data class PaymentConfig(
    val enabled: Boolean = false,
    val environment: String? = null,
    @SerialName("application_id") val applicationId: String = "",
    @SerialName("native_card_entry") val nativeCardEntry: Boolean = false,
)

@Serializable
data class Dashboard(
    val customers: Int = 0,
    val properties: Int = 0,
    @SerialName("open_estimates") val openEstimates: Int = 0,
    @SerialName("open_invoices") val openInvoices: Int = 0,
    @SerialName("outstanding_balance_cents") val outstandingBalanceCents: Long = 0,
    @SerialName("assigned_tasks") val assignedTasks: Int = 0,
    val clock: TimeEntry? = null,
    @SerialName("recent_estimates") val recentEstimates: List<Estimate> = emptyList(),
    @SerialName("recent_invoices") val recentInvoices: List<Invoice> = emptyList(),
    @SerialName("upcoming_appointments") val upcomingAppointments: List<Appointment> = emptyList(),
    @SerialName("active_announcements") val activeAnnouncements: List<Announcement> = emptyList(),
    @SerialName("unread_notifications") val unreadNotifications: Int = 0,
)

@Serializable
data class Customer(
    val id: String,
    @SerialName("first_name") val firstName: String? = null,
    @SerialName("last_name") val lastName: String? = null,
    val name: String? = null,
    val company: String? = null,
    val email: String? = null,
    @SerialName("email_2") val email2: String? = null,
    val phone: String? = null,
    @SerialName("mobile_phone") val mobilePhone: String? = null,
    @SerialName("mailing_street") val mailingStreet: String? = null,
    @SerialName("mailing_city") val mailingCity: String? = null,
    @SerialName("mailing_state") val mailingState: String? = null,
    @SerialName("mailing_postal_code") val mailingPostalCode: String? = null,
    val address: String? = null,
    @SerialName("lead_source") val leadSource: String? = null,
    val status: String? = null,
    val tags: List<String> = emptyList(),
    val notes: String? = null,
    @SerialName("square_customer_id") val squareCustomerId: String? = null,
    @SerialName("default_square_card_id") val defaultSquareCardId: String? = null,
)

@Serializable
data class PropertyRecord(
    val id: String,
    @SerialName("contact_id") val contactId: String? = null,
    val name: String? = null,
    @SerialName("property_name") val propertyName: String? = null,
    @SerialName("property_type") val propertyType: String? = null,
    @SerialName("service_street") val serviceStreet: String? = null,
    @SerialName("service_city") val serviceCity: String? = null,
    @SerialName("service_state") val serviceState: String? = null,
    @SerialName("service_postal_code") val servicePostalCode: String? = null,
    @SerialName("insurance_company") val insuranceCompany: String? = null,
    @SerialName("claim_number") val claimNumber: String? = null,
    val notes: String? = null,
    val status: String? = null,
)

@Serializable
data class NoteRecord(
    val id: String,
    @SerialName("contact_id") val contactId: String? = null,
    val text: String? = null,
    val note: String? = null,
    val category: String? = null,
    val pinned: Boolean = false,
    @SerialName("author_name") val authorName: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
)

@Serializable
data class Estimate(
    val id: String,
    @SerialName("estimate_number") val estimateNumber: String? = null,
    @SerialName("contact_id") val contactId: String? = null,
    @SerialName("property_id") val propertyId: String? = null,
    val title: String? = null,
    val status: String? = null,
    @SerialName("project_category") val projectCategory: String? = null,
    @SerialName("recommended_project_title") val recommendedProjectTitle: String? = null,
    @SerialName("total_cents") val totalCents: Long = 0,
    @SerialName("deposit_cents") val depositCents: Long = 0,
    @SerialName("deposit_balance_cents") val depositBalanceCents: Long = 0,
    @SerialName("project_summary") val projectSummary: String? = null,
    @SerialName("estimated_duration") val estimatedDuration: String? = null,
    val assumptions: String? = null,
    val exclusions: String? = null,
    @SerialName("customer_notes") val customerNotes: String? = null,
    val terms: String? = null,
    @SerialName("project_outcomes") val projectOutcomes: List<ProjectOutcome> = emptyList(),
    val protections: List<String> = emptyList(),
    @SerialName("optional_upgrades") val optionalUpgrades: List<String> = emptyList(),
    @SerialName("deposit_type") val depositType: String = "PERCENT",
    @SerialName("deposit_percent") val depositPercent: Double = 50.0,
    @SerialName("deposit_fixed_cents") val depositFixedCents: Long = 0,
    @SerialName("deposit_due_stage") val depositDueStage: String = "AFTER_AUTHORIZATION",
    @SerialName("deposit_payable") val depositPayable: Boolean = false,
    @SerialName("converted_invoice_id") val convertedInvoiceId: String? = null,
    val sections: List<EstimateSectionModel> = emptyList(),
    @SerialName("line_items") val lineItems: List<EstimateLineModel> = emptyList(),
    @SerialName("public_url") val publicUrl: String? = null,
    @SerialName("public_pay_url") val publicPayUrl: String? = null,
    @SerialName("public_pdf_url") val publicPdfUrl: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
)

@Serializable
data class Invoice(
    val id: String,
    @SerialName("invoice_number") val invoiceNumber: String? = null,
    @SerialName("contact_id") val contactId: String? = null,
    @SerialName("property_id") val propertyId: String? = null,
    @SerialName("estimate_id") val estimateId: String? = null,
    val title: String? = null,
    val status: String? = null,
    val terms: String? = null,
    @SerialName("customer_notes") val customerNotes: String? = null,
    @SerialName("allow_partial_payments") val allowPartialPayments: Boolean = true,
    @SerialName("allow_customer_to_save_card") val allowCustomerToSaveCard: Boolean = true,
    @SerialName("total_cents") val totalCents: Long = 0,
    @SerialName("paid_cents") val paidCents: Long = 0,
    @SerialName("balance_cents") val balanceCents: Long = 0,
    val sections: List<EstimateSectionModel> = emptyList(),
    @SerialName("line_items") val lineItems: List<EstimateLineModel> = emptyList(),
    @SerialName("public_url") val publicUrl: String? = null,
    @SerialName("public_pay_url") val publicPayUrl: String? = null,
    @SerialName("public_pdf_url") val publicPdfUrl: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
)

@Serializable
data class EstimateSectionModel(
    val id: String? = null,
    val title: String = "Scope of Work",
    val description: String = "",
    @SerialName("sort_order") val sortOrder: Int = 0,
    @SerialName("subtotal_cents") val subtotalCents: Long = 0,
)

@Serializable
data class EstimateLineModel(
    val id: String? = null,
    @SerialName("section_id") val sectionId: String? = null,
    @SerialName("section_name") val sectionName: String? = null,
    @SerialName("catalog_item_id") val catalogItemId: String? = null,
    val name: String = "",
    val description: String = "",
    val category: String = "General Services",
    val unit: String = "each",
    val quantity: Double = 1.0,
    @SerialName("unit_price_cents") val unitPriceCents: Long = 0,
    @SerialName("line_total_cents") val lineTotalCents: Long = 0,
    val taxable: Boolean = false,
    val optional: Boolean = false,
)

@Serializable
data class CatalogItem(
    val id: String,
    val name: String,
    val description: String? = null,
    val category: String? = null,
    val unit: String? = null,
    @SerialName("unit_price_cents") val unitPriceCents: Long = 0,
    val taxable: Boolean = false,
)

@Serializable
data class PaymentRecord(
    val id: String,
    @SerialName("amount_cents") val amountCents: Long = 0,
    val currency: String = "USD",
    val method: String? = null,
    val status: String? = null,
    @SerialName("payment_date") val paymentDate: String? = null,
    @SerialName("processor_payment_id") val processorPaymentId: String? = null,
    @SerialName("receipt_url") val receiptUrl: String? = null,
    @SerialName("card_brand") val cardBrand: String? = null,
    @SerialName("last_4") val last4: String? = null,
)

@Serializable
data class DocumentRecord(
    val id: String,
    val title: String? = null,
    val kind: String? = null,
    val status: String? = null,
    val filename: String? = null,
    @SerialName("mime_type") val mimeType: String? = null,
    @SerialName("download_url") val downloadUrl: String? = null,
    @SerialName("signed_download_url") val signedDownloadUrl: String? = null,
    @SerialName("completed_at") val completedAt: String? = null,
)

@Serializable
data class TimeEntry(
    val id: String,
    @SerialName("job_reference") val jobReference: String? = null,
    val note: String? = null,
    @SerialName("clock_in") val clockIn: String? = null,
    @SerialName("clock_out") val clockOut: String? = null,
    val status: String? = null,
    @SerialName("duration_seconds") val durationSeconds: Long? = null,
)

@Serializable
data class RoomFlowWorkspace(
    val id: String,
    val name: String = "Floodman",
    val timezone: String = "America/Detroit",
    val status: String = "ACTIVE",
    val source: String? = null,
    val imported: Boolean = false,
    @SerialName("is_default") val isDefault: Boolean = false,
    @SerialName("roomflow_organization_id") val roomFlowOrganizationId: String? = null,
    @SerialName("source_organization_id") val sourceOrganizationId: String? = null,
)

@Serializable
data class RoomFlowJob(
    val id: String,
    val name: String? = null,
    @SerialName("job_name") val jobName: String? = null,
    @SerialName("roomflow_job_id") val roomFlowJobId: String? = null,
    @SerialName("roomflow_source_id") val roomFlowSourceId: String? = null,
    @SerialName("workspace_id") val workspaceId: String? = null,
    @SerialName("roomflow_organization_name") val roomFlowOrganizationName: String? = null,
    @SerialName("contact_id") val contactId: String? = null,
    @SerialName("property_id") val propertyId: String? = null,
    @SerialName("estimate_id") val estimateId: String? = null,
    @SerialName("customer_name") val customerName: String? = null,
    @SerialName("property_address") val propertyAddress: String? = null,
    val status: String? = null,
    @SerialName("project_category") val projectCategory: String? = null,
    @SerialName("estimate_number") val estimateNumber: String? = null,
    val snapshot: JsonObject = JsonObject(emptyMap()),
    val summary: JsonObject = JsonObject(emptyMap()),
    val sections: List<EstimateSectionInput> = emptyList(),
    @SerialName("layout_capture_required") val layoutCaptureRequired: Boolean = false,
    val source: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
)


@Serializable
data class RoomFlowJobDetail(
    val job: RoomFlowJob,
    val customer: Customer? = null,
    val property: PropertyRecord? = null,
    val estimate: Estimate? = null,
    val workspace: RoomFlowWorkspace? = null,
    @SerialName("layout_available") val layoutAvailable: Boolean = false,
    @SerialName("layout_url") val layoutUrl: String? = null,
    @SerialName("layout_capture_required") val layoutCaptureRequired: Boolean = false,
)

@Serializable
data class RoomFlowImportRecord(
    val id: String,
    val status: String = "",
    @SerialName("email_hint") val emailHint: String = "",
    val counts: Map<String, Int> = emptyMap(),
    val warnings: List<String> = emptyList(),
    val error: String? = null,
    @SerialName("started_at") val startedAt: String? = null,
    @SerialName("completed_at") val completedAt: String? = null,
)

@Serializable
data class RoomFlowBootstrap(
    @SerialName("api_version") val apiVersion: String = "",
    @SerialName("server_release") val serverRelease: String = "",
    @SerialName("minimum_android_version") val minimumAndroidVersion: String = "",
    val capabilities: List<String> = emptyList(),
    val workspaces: List<RoomFlowWorkspace> = emptyList(),
    @SerialName("selected_workspace_id") val selectedWorkspaceId: String = "",
    @SerialName("active_workspace") val activeWorkspace: RoomFlowWorkspace? = null,
    val jobs: List<RoomFlowJobDetail> = emptyList(),
    val catalog: List<CatalogItem> = emptyList(),
    val imports: List<RoomFlowImportRecord> = emptyList(),
)

@Serializable
data class RoomFlowWorkspaceCreateInput(
    val name: String,
    val timezone: String = "America/Detroit",
)

@Serializable
data class RoomFlowWorkspaceResponse(
    val workspace: RoomFlowWorkspace,
    val bootstrap: RoomFlowBootstrap = RoomFlowBootstrap(),
)

@Serializable
data class RoomFlowSupabaseImportInput(
    val email: String,
    val password: String,
)

@Serializable
data class RoomFlowSupabaseImportResponse(
    val status: String = "",
    @SerialName("run_id") val runId: String = "",
    val counts: Map<String, Int> = emptyMap(),
    val warnings: List<String> = emptyList(),
    @SerialName("layout_capture_required") val layoutCaptureRequired: Int = 0,
    @SerialName("selected_workspace_id") val selectedWorkspaceId: String = "",
    val workspaces: List<RoomFlowWorkspace> = emptyList(),
    val bootstrap: RoomFlowBootstrap = RoomFlowBootstrap(),
)

@Serializable
data class RoomFlowSaveInput(
    @SerialName("workspace_id") val workspaceId: String? = null,
    @SerialName("roomflow_job_id") val roomFlowJobId: String? = null,
    @SerialName("job_name") val jobName: String = "",
    @SerialName("contact_id") val contactId: String? = null,
    @SerialName("property_id") val propertyId: String? = null,
    @SerialName("estimate_id") val estimateId: String? = null,
    @SerialName("estimate_number") val estimateNumber: String = "",
    val status: String = "DRAFT",
    @SerialName("project_category") val projectCategory: String = "general-restoration",
    val title: String = "",
    @SerialName("customer_name") val customerName: String = "",
    @SerialName("customer_email") val customerEmail: String = "",
    @SerialName("customer_phone") val customerPhone: String = "",
    @SerialName("property_address") val propertyAddress: String = "",
    val snapshot: JsonObject = JsonObject(emptyMap()),
    val summary: JsonObject = JsonObject(emptyMap()),
    @SerialName("layout_data_url") val layoutDataUrl: String = "",
    val sections: List<EstimateSectionInput> = emptyList(),
    @SerialName("sync_estimate") val syncEstimate: Boolean = true,
)

@Serializable
data class RoomFlowSaveResponse(
    val job: RoomFlowJob,
    val customer: Customer? = null,
    val property: PropertyRecord? = null,
    val estimate: Estimate? = null,
    val workspace: RoomFlowWorkspace? = null,
    @SerialName("layout_available") val layoutAvailable: Boolean = false,
)

@Serializable data class CustomerPage(val items: List<Customer> = emptyList(), val page: Int = 1, @SerialName("page_size") val pageSize: Int = 50, val total: Int = 0, @SerialName("has_more") val hasMore: Boolean = false)
@Serializable data class PropertyPage(val items: List<PropertyRecord> = emptyList(), val page: Int = 1, @SerialName("page_size") val pageSize: Int = 50, val total: Int = 0, @SerialName("has_more") val hasMore: Boolean = false)
@Serializable data class EstimatePage(val items: List<Estimate> = emptyList(), val page: Int = 1, @SerialName("page_size") val pageSize: Int = 50, val total: Int = 0, @SerialName("has_more") val hasMore: Boolean = false)
@Serializable data class InvoicePage(val items: List<Invoice> = emptyList(), val page: Int = 1, @SerialName("page_size") val pageSize: Int = 50, val total: Int = 0, @SerialName("has_more") val hasMore: Boolean = false)
@Serializable data class CatalogPage(val items: List<CatalogItem> = emptyList(), val page: Int = 1, @SerialName("page_size") val pageSize: Int = 50, val total: Int = 0, @SerialName("has_more") val hasMore: Boolean = false)
@Serializable data class RoomFlowJobPage(val items: List<RoomFlowJob> = emptyList(), val page: Int = 1, @SerialName("page_size") val pageSize: Int = 50, val total: Int = 0, @SerialName("has_more") val hasMore: Boolean = false)
@Serializable data class DocumentPage(val items: List<DocumentRecord> = emptyList(), val page: Int = 1, @SerialName("page_size") val pageSize: Int = 50, val total: Int = 0, @SerialName("has_more") val hasMore: Boolean = false)

@Serializable
data class CustomerDetail(
    val customer: Customer,
    val properties: List<PropertyRecord> = emptyList(),
    val notes: List<NoteRecord> = emptyList(),
    val estimates: List<Estimate> = emptyList(),
    val invoices: List<Invoice> = emptyList(),
    val payments: List<PaymentRecord> = emptyList(),
    val documents: List<DocumentRecord> = emptyList(),
)

@Serializable
data class EstimateDetail(
    val estimate: Estimate,
    val customer: Customer? = null,
    val property: PropertyRecord? = null,
    val payments: List<PaymentRecord> = emptyList(),
    val documents: List<DocumentRecord> = emptyList(),
    @SerialName("allowed_actions") val allowedActions: List<String> = emptyList(),
)

@Serializable
data class InvoiceDetail(
    val invoice: Invoice,
    val customer: Customer? = null,
    val property: PropertyRecord? = null,
    val payments: List<PaymentRecord> = emptyList(),
    val documents: List<DocumentRecord> = emptyList(),
    @SerialName("allowed_actions") val allowedActions: List<String> = emptyList(),
)


@Serializable
data class CustomerCreateInput(
    @SerialName("first_name") val firstName: String = "",
    @SerialName("last_name") val lastName: String = "",
    val company: String = "",
    val email: String = "",
    val phone: String = "",
    @SerialName("mailing_street") val mailingStreet: String = "",
    @SerialName("mailing_city") val mailingCity: String = "",
    @SerialName("mailing_state") val mailingState: String = "MI",
    @SerialName("mailing_postal_code") val mailingPostalCode: String = "",
    @SerialName("lead_source") val leadSource: String = "Android app",
    @SerialName("initial_note") val initialNote: String = "",
)

@Serializable
data class PropertyCreateInput(
    @SerialName("contact_id") val contactId: String,
    @SerialName("property_name") val propertyName: String = "",
    @SerialName("property_type") val propertyType: String = "",
    @SerialName("service_street") val serviceStreet: String,
    @SerialName("service_city") val serviceCity: String,
    @SerialName("service_state") val serviceState: String = "MI",
    @SerialName("service_postal_code") val servicePostalCode: String = "",
    @SerialName("insurance_company") val insuranceCompany: String = "",
    @SerialName("claim_number") val claimNumber: String = "",
    val notes: String = "",
)

@Serializable
data class EstimateLineInput(
    @SerialName("catalog_item_id") val catalogItemId: String? = null,
    val name: String,
    val description: String = "",
    val category: String = "General Services",
    val unit: String = "each",
    val quantity: Double = 1.0,
    @SerialName("unit_price_cents") val unitPriceCents: Long = 0,
    val taxable: Boolean = false,
    val optional: Boolean = false,
    @SerialName("save_to_catalog") val saveToCatalog: Boolean = false,
)

@Serializable
data class EstimateSectionInput(
    val title: String,
    val description: String = "",
    val lines: List<EstimateLineInput> = emptyList(),
)

@Serializable
data class EstimateCreateInput(
    @SerialName("contact_id") val contactId: String,
    @SerialName("property_id") val propertyId: String,
    @SerialName("estimate_number") val estimateNumber: String = "",
    val title: String,
    @SerialName("project_category") val projectCategory: String = "general-restoration",
    @SerialName("recommended_project_title") val recommendedProjectTitle: String = "",
    @SerialName("project_summary") val projectSummary: String = "",
    @SerialName("estimated_duration") val estimatedDuration: String = "",
    @SerialName("project_outcomes") val projectOutcomes: List<ProjectOutcome> = emptyList(),
    val assumptions: String = "",
    val exclusions: String = "",
    val protections: List<String> = emptyList(),
    @SerialName("optional_upgrades") val optionalUpgrades: List<String> = emptyList(),
    @SerialName("customer_notes") val customerNotes: String = "",
    val terms: String = "",
    @SerialName("expiration_days") val expirationDays: Int = 30,
    @SerialName("deposit_type") val depositType: String = "PERCENT",
    @SerialName("deposit_percent") val depositPercent: Double = 50.0,
    @SerialName("deposit_fixed_cents") val depositFixedCents: Long = 0,
    @SerialName("deposit_due_stage") val depositDueStage: String = "AFTER_AUTHORIZATION",
    val sections: List<EstimateSectionInput>,
)

@Serializable
data class ProjectOutcome(
    val title: String = "",
    val description: String = "",
)

@Serializable
data class ProjectPlanOption(
    val key: String,
    val label: String,
)

@Serializable
data class ProjectPlan(
    val key: String,
    val label: String = "",
    val title: String = "",
    val summary: String = "",
    @SerialName("estimated_duration") val estimatedDuration: String = "",
    val outcomes: List<ProjectOutcome> = emptyList(),
    val assumptions: List<String> = emptyList(),
    val exclusions: List<String> = emptyList(),
    val protections: List<String> = emptyList(),
    val options: List<String> = emptyList(),
)

@Serializable
data class ProjectPlanPage(val items: List<ProjectPlanOption> = emptyList())

@Serializable
data class EstimateActionResponse(
    val estimate: Estimate? = null,
    val invoice: Invoice? = null,
    val document: DocumentRecord? = null,
    val recipient: String? = null,
    @SerialName("signing_url") val signingUrl: String? = null,
    val ok: Boolean? = null,
    @SerialName("deleted_id") val deletedId: String? = null,
)

@Serializable
data class InvoiceActionResponse(
    val invoice: Invoice? = null,
    val recipient: String? = null,
    val ok: Boolean? = null,
    @SerialName("deleted_id") val deletedId: String? = null,
)

@Serializable
data class Employee(
    val id: String,
    val name: String? = null,
    val email: String? = null,
    val role: String? = null,
    val status: String? = null,
)

@Serializable
data class EmployeePage(val items: List<Employee> = emptyList())

@Serializable
data class Appointment(
    val id: String,
    val title: String,
    @SerialName("appointment_type") val appointmentType: String = "JOB",
    val status: String = "SCHEDULED",
    @SerialName("start_at") val startAt: String,
    @SerialName("end_at") val endAt: String,
    @SerialName("contact_id") val contactId: String? = null,
    @SerialName("property_id") val propertyId: String? = null,
    @SerialName("estimate_id") val estimateId: String? = null,
    @SerialName("invoice_id") val invoiceId: String? = null,
    @SerialName("roomflow_job_id") val roomFlowJobId: String? = null,
    @SerialName("assigned_user_ids") val assignedUserIds: List<String> = emptyList(),
    @SerialName("lead_user_id") val leadUserId: String? = null,
    @SerialName("internal_notes") val internalNotes: String? = null,
    @SerialName("customer_notes") val customerNotes: String? = null,
    val location: String? = null,
)

@Serializable
data class CalendarPage(
    val items: List<Appointment> = emptyList(),
    @SerialName("time_zone") val timeZone: String = "America/Detroit",
)

@Serializable
data class AppointmentInput(
    val title: String,
    @SerialName("appointment_type") val appointmentType: String = "JOB",
    val status: String = "SCHEDULED",
    @SerialName("start_at") val startAt: String,
    @SerialName("end_at") val endAt: String,
    @SerialName("contact_id") val contactId: String? = null,
    @SerialName("property_id") val propertyId: String? = null,
    @SerialName("estimate_id") val estimateId: String? = null,
    @SerialName("invoice_id") val invoiceId: String? = null,
    @SerialName("roomflow_job_id") val roomFlowJobId: String? = null,
    @SerialName("assigned_user_ids") val assignedUserIds: List<String> = emptyList(),
    @SerialName("lead_user_id") val leadUserId: String? = null,
    @SerialName("internal_notes") val internalNotes: String = "",
    @SerialName("customer_notes") val customerNotes: String = "",
    val location: String = "",
    @SerialName("override_conflicts") val overrideConflicts: Boolean = false,
)

@Serializable
data class AppointmentResponse(
    val appointment: Appointment,
    @SerialName("conflicts_overridden") val conflictsOverridden: Boolean = false,
)

@Serializable
data class CalendarSubscriptionResponse(
    val url: String,
)

@Serializable
data class TaskRecord(
    val id: String,
    val title: String,
    val description: String? = null,
    val status: String = "OPEN",
    val priority: String = "NORMAL",
    @SerialName("due_at") val dueAt: String? = null,
    @SerialName("assigned_user_id") val assignedUserId: String? = null,
    @SerialName("appointment_id") val appointmentId: String? = null,
    @SerialName("contact_id") val contactId: String? = null,
    @SerialName("property_id") val propertyId: String? = null,
)

@Serializable
data class TaskPage(val items: List<TaskRecord> = emptyList(), val page: Int = 1, @SerialName("page_size") val pageSize: Int = 50, val total: Int = 0, @SerialName("has_more") val hasMore: Boolean = false)

@Serializable
data class TaskInput(
    val title: String, val description: String = "", val status: String = "OPEN", val priority: String = "NORMAL",
    @SerialName("due_at") val dueAt: String? = null, @SerialName("assigned_user_id") val assignedUserId: String? = null,
    @SerialName("appointment_id") val appointmentId: String? = null, @SerialName("contact_id") val contactId: String? = null,
    @SerialName("property_id") val propertyId: String? = null,
)

@Serializable
data class Announcement(
    val id: String, val title: String, val body: String, val severity: String = "INFO",
    @SerialName("expires_at") val expiresAt: String? = null, @SerialName("created_at") val createdAt: String? = null,
)

@Serializable
data class AnnouncementPage(val items: List<Announcement> = emptyList())

@Serializable
data class NotificationRecord(
    val id: String, val title: String, val body: String, val kind: String = "GENERAL", val status: String = "UNREAD",
    @SerialName("reference_id") val referenceId: String? = null, @SerialName("created_at") val createdAt: String? = null,
)

@Serializable
data class NotificationPage(val items: List<NotificationRecord> = emptyList(), val unread: Int = 0)

@Serializable
data class InvoiceCreateInput(
    @SerialName("contact_id") val contactId: String, @SerialName("property_id") val propertyId: String,
    @SerialName("estimate_id") val estimateId: String? = null, @SerialName("invoice_number") val invoiceNumber: String = "",
    val title: String, val terms: String = "Payment is due upon receipt.", @SerialName("customer_notes") val customerNotes: String = "",
    val sections: List<EstimateSectionInput>, @SerialName("allow_partial_payments") val allowPartialPayments: Boolean = true,
    @SerialName("allow_customer_to_save_card") val allowCustomerToSaveCard: Boolean = true,
)

@Serializable
data class PaymentResponse(
    val payment: PaymentRecord,
    val document: JsonElement? = null,
    @SerialName("saved_card") val savedCard: JsonElement? = null,
)

@Serializable
data class PendingCardPayment(
    val targetKind: String,
    val targetId: String,
    val amountCents: Long,
    val saveCard: Boolean = false,
    val authorizationReference: String = "",
    val note: String = "",
)


@Serializable
data class ManualPaymentInput(
    val targetKind: String,
    val targetId: String,
    val amountCents: Long,
    val method: String,
    val reference: String = "",
    val note: String = "",
    val checkDate: String = "",
    val bankName: String = "",
    val checkStatus: String = "RECEIVED",
)
