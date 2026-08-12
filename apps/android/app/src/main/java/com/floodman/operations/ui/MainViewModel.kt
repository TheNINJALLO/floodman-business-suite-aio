package com.floodman.operations.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.floodman.operations.data.*
import kotlinx.coroutines.launch

class MainViewModel : ViewModel() {
    private val repository = AppGraph.repository

    var signedIn by mutableStateOf(repository.hasSession())
        private set
    var unlocked by mutableStateOf(!repository.hasSession())
        private set
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var notice by mutableStateOf<String?>(null)
        private set

    var config by mutableStateOf<MobileConfig?>(null)
        private set
    var apiBaseUrl by mutableStateOf(repository.apiBaseUrl())
        private set
    var appearanceMode by mutableStateOf(repository.appearanceMode())
        private set
    var dashboard by mutableStateOf<Dashboard?>(null)
        private set
    var customers by mutableStateOf<List<Customer>>(emptyList())
        private set
    var customerDetail by mutableStateOf<CustomerDetail?>(null)
        private set
    var properties by mutableStateOf<List<PropertyRecord>>(emptyList())
        private set
    var estimates by mutableStateOf<List<Estimate>>(emptyList())
        private set
    var estimateDetail by mutableStateOf<EstimateDetail?>(null)
        private set
    var invoices by mutableStateOf<List<Invoice>>(emptyList())
        private set
    var invoiceDetail by mutableStateOf<InvoiceDetail?>(null)
        private set
    var catalog by mutableStateOf<List<CatalogItem>>(emptyList())
        private set
    var roomFlowJobs by mutableStateOf<List<RoomFlowJob>>(emptyList())
        private set
    var timeEntry by mutableStateOf<TimeEntry?>(null)
        private set
    var projectPlans by mutableStateOf<List<ProjectPlanOption>>(emptyList())
        private set
    var employees by mutableStateOf<List<Employee>>(emptyList())
        private set
    var appointments by mutableStateOf<List<Appointment>>(emptyList())
        private set
    var tasks by mutableStateOf<List<TaskRecord>>(emptyList())
        private set
    var announcements by mutableStateOf<List<Announcement>>(emptyList())
        private set
    var notifications by mutableStateOf<List<NotificationRecord>>(emptyList())
        private set
    var documents by mutableStateOf<List<DocumentRecord>>(emptyList())
        private set

    private val requiredServerCapabilities = setOf(
        "estimate.pdf.v1",
        "invoice.pdf.v1",
        "roomflow.bootstrap.v1",
        "roomflow.snapshot.v1",
        "roomflow.supabase-import.v1",
        "roomflow.workspaces.v1",
    )

    private fun requireCompatibleServer(value: MobileConfig) {
        val missing = requiredServerCapabilities - value.capabilities.toSet()
        if (missing.isNotEmpty()) {
            throw IllegalStateException(
                "This Android build requires Floodman server v4.6.3. Install the matching v4.6.3 runtime and launcher, then try again."
            )
        }
    }

    init {
        viewModelScope.launch {
            runCatching {
                val loaded = repository.config()
                requireCompatibleServer(loaded)
                config = loaded
                if (signedIn) refreshHome()
            }.onFailure { error = it.message ?: "Floodman server compatibility check failed." }
        }
    }

    fun unlock() { unlocked = true }
    fun lock() { if (signedIn) unlocked = false }
    fun updateAppearanceMode(value: String) {
        repository.setAppearanceMode(value)
        appearanceMode = value.uppercase()
    }
    fun updateApiBaseUrl(value: String) {
        try {
            repository.setApiBaseUrl(value)
            apiBaseUrl = repository.apiBaseUrl()
            signedIn = false
            unlocked = true
            dashboard = null
            notice = "API address updated. Sign in again."
        } catch (error: Exception) {
            this.error = error.message ?: "The API address is invalid."
        }
    }
    fun dismissError() { error = null }
    fun dismissNotice() { notice = null }

    private fun launch(showBusy: Boolean = true, block: suspend () -> Unit) {
        viewModelScope.launch {
            if (showBusy) busy = true
            error = null
            try { block() } catch (t: Throwable) { error = t.message ?: "Floodman request failed." }
            finally { if (showBusy) busy = false }
        }
    }

    fun login(email: String, password: String, local: Boolean) = launch {
        val serverConfig = repository.config()
        requireCompatibleServer(serverConfig)
        repository.login(email, password, local)
        signedIn = true
        unlocked = true
        config = serverConfig
        dashboard = repository.dashboard()
    }

    fun logout() = launch {
        repository.logout()
        signedIn = false
        unlocked = true
        dashboard = null
        customers = emptyList()
    }

    fun refreshHome() = launch {
        dashboard = repository.dashboard(); timeEntry = repository.timeStatus()
        runCatching { announcements = repository.announcements().items }
        runCatching { notifications = repository.notifications().items }
    }
    fun loadCustomers(search: String = "") = launch { customers = repository.customers(search).items }
    fun loadCustomer(id: String) = launch { customerDetail = repository.customer(id) }
    fun createCustomer(input: CustomerCreateInput, onCreated: (Customer) -> Unit) = launch {
        val customer = repository.createCustomer(input)
        notice = "Customer ${customer.name ?: customer.company ?: customer.email.orEmpty()} is ready."
        onCreated(customer)
    }
    fun addNote(id: String, text: String, category: String, pinned: Boolean) = launch {
        repository.addNote(id, text, category, pinned)
        customerDetail = repository.customer(id)
        notice = "Customer note saved."
    }
    fun updateTags(id: String, tags: List<String>) = launch {
        repository.updateTags(id, tags)
        customerDetail = repository.customer(id)
        notice = "Customer tags updated."
    }
    fun loadProperties(contactId: String = "", search: String = "") = launch { properties = repository.properties(contactId, search).items }
    fun createProperty(input: PropertyCreateInput, onCreated: (PropertyRecord) -> Unit) = launch {
        val property = repository.createProperty(input)
        notice = "Service property is ready."
        onCreated(property)
    }
    fun loadEstimates(search: String = "", status: String = "") = launch { estimates = repository.estimates(search, status).items }
    fun loadEstimate(id: String) = launch { estimateDetail = repository.estimate(id) }
    fun createEstimate(input: EstimateCreateInput, onCreated: (String) -> Unit) = launch {
        val record = repository.createEstimate(input)
        notice = "Draft estimate ${record.estimateNumber.orEmpty()} created."
        onCreated(record.id)
    }
    fun loadInvoices(search: String = "", status: String = "") = launch { invoices = repository.invoices(search, status).items }
    fun loadInvoice(id: String) = launch { invoiceDetail = repository.invoice(id) }
    fun loadCatalog(search: String = "") = launch(showBusy = false) { catalog = repository.catalog(search).items }
    fun loadRoomFlowJobs(search: String = "") = launch { roomFlowJobs = repository.roomFlowJobs(search).items }
    fun loadRoomFlowJob(id: String, onLoaded: (RoomFlowJobDetail) -> Unit) = launch { onLoaded(repository.roomFlowJob(id)) }
    fun saveRoomFlowJob(id: String?, input: RoomFlowSaveInput, onSaved: (RoomFlowSaveResponse) -> Unit) = launch {
        val response = repository.saveRoomFlowJob(id, input)
        notice = "RoomFlow job, measured layout, and draft estimate synchronized."
        roomFlowJobs = repository.roomFlowJobs().items
        onSaved(response)
    }
    fun clockIn(reference: String, note: String) = launch { timeEntry = repository.clockIn(reference, note); dashboard = repository.dashboard() }
    fun clockOut(note: String) = launch { timeEntry = repository.clockOut(note); dashboard = repository.dashboard() }
    fun recordManualPayment(input: ManualPaymentInput, onComplete: () -> Unit = {}) = launch {
        repository.manualPayment(input)
        notice = "Payment recorded."
        paymentCompleted(input.targetKind, input.targetId)
        onComplete()
    }
    fun paymentCompleted(targetKind: String, targetId: String) {
        notice = "Payment completed."
        if (targetKind == "invoice") loadInvoice(targetId) else loadEstimate(targetId)
        refreshHome()
    }

    fun loadProjectPlans() = launch(showBusy = false) { projectPlans = repository.projectPlans().items }
    fun projectPlan(category: String, onLoaded: (ProjectPlan) -> Unit) = launch(showBusy = false) { onLoaded(repository.projectPlan(category)) }
    fun updateEstimate(id: String, input: EstimateCreateInput, onUpdated: () -> Unit = {}) = launch {
        repository.updateEstimate(id, input)
        estimateDetail = repository.estimate(id)
        notice = "Estimate updated."
        onUpdated()
    }
    fun estimateAction(id: String, action: String, onComplete: (EstimateActionResponse) -> Unit = {}) = launch {
        val response = repository.estimateAction(id, action)
        response.estimate?.let { estimateDetail = repository.estimate(it.id) }
        response.invoice?.let { invoices = repository.invoices().items }
        notice = when (action) {
            "send", "resend" -> "Estimate sent."
            "send_work_authorization" -> "Work Authorization sent."
            "mark_accepted" -> "Estimate marked accepted."
            "activate_deposit" -> "Deposit payment activated."
            "convert_to_invoice" -> "Invoice created."
            "delete" -> "Estimate deleted."
            else -> "Estimate updated."
        }
        onComplete(response)
        refreshHome()
    }
    fun loadEstimatePdf(id: String, onLoaded: (ByteArray) -> Unit) = launch { onLoaded(repository.estimatePdf(id)) }
    fun createInvoice(input: InvoiceCreateInput, onCreated: (String) -> Unit) = launch {
        val value = repository.createInvoice(input)
        notice = "Draft invoice ${value.invoiceNumber.orEmpty()} created."
        onCreated(value.id)
    }
    fun updateInvoice(id: String, input: InvoiceCreateInput, onUpdated: () -> Unit = {}) = launch {
        repository.updateInvoice(id, input)
        invoiceDetail = repository.invoice(id)
        notice = "Invoice updated."
        onUpdated()
    }
    fun invoiceAction(id: String, action: String, onComplete: (InvoiceActionResponse) -> Unit = {}) = launch {
        val response = repository.invoiceAction(id, action)
        response.invoice?.let { invoiceDetail = repository.invoice(it.id) }
        notice = when (action) {
            "send", "resend" -> "Invoice sent."
            "void" -> "Invoice voided."
            "delete" -> "Invoice deleted."
            else -> "Invoice updated."
        }
        onComplete(response)
        refreshHome()
    }
    fun loadInvoicePdf(id: String, onLoaded: (ByteArray) -> Unit) = launch { onLoaded(repository.invoicePdf(id)) }
    fun loadEmployees(search: String = "") = launch(showBusy = false) { employees = repository.employees(search).items }
    fun loadCalendar(start: String = "", end: String = "", employeeId: String = "") = launch { appointments = repository.calendar(start, end, employeeId).items }
    fun createAppointment(input: AppointmentInput, onCreated: () -> Unit = {}) = launch {
        repository.createAppointment(input)
        notice = "Appointment booked."
        appointments = repository.calendar().items
        onCreated()
    }
    fun updateAppointment(id: String, input: AppointmentInput, onUpdated: () -> Unit = {}) = launch {
        repository.updateAppointment(id, input)
        notice = "Appointment updated."
        appointments = repository.calendar().items
        onUpdated()
    }
    fun deleteAppointment(id: String) = launch {
        repository.deleteAppointment(id)
        appointments = repository.calendar().items
        notice = "Appointment removed."
    }
    fun createCalendarSubscription(onCreated: (String) -> Unit) = launch {
        val response = repository.createCalendarSubscription()
        notice = "Private calendar subscription created."
        onCreated(response.url)
    }
    fun loadTasks(assignedToMe: Boolean = false) = launch { tasks = repository.tasks(assignedToMe).items }
    fun createTask(input: TaskInput, onCreated: () -> Unit = {}) = launch {
        repository.createTask(input); tasks = repository.tasks(false).items; notice = "Task saved."; onCreated()
    }
    fun updateTask(id: String, input: TaskInput) = launch {
        repository.updateTask(id, input); tasks = repository.tasks(false).items; notice = "Task updated."
    }
    fun loadAnnouncements() = launch { announcements = repository.announcements().items }
    fun loadNotifications() = launch { notifications = repository.notifications().items }
    fun markNotificationRead(id: String) = launch { repository.markNotificationRead(id); notifications = repository.notifications().items }

    fun loadDocuments(contactId: String = "", propertyId: String = "") = launch { documents = repository.documents(contactId, propertyId).items }
    fun loadDocumentBytes(id: String, signed: Boolean = false, onLoaded: (ByteArray) -> Unit) = launch { onLoaded(repository.documentBytes(id, signed)) }

}
