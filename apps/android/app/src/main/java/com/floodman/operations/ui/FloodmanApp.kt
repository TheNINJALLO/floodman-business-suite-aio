package com.floodman.operations.ui

import android.content.Context
import android.content.Intent
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.snapshots.SnapshotStateList
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalWindowInfo
import androidx.core.content.FileProvider
import androidx.core.net.toUri
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.floodman.operations.BuildConfig
import com.floodman.operations.data.*
import com.floodman.operations.payments.PaymentCoordinator
import com.floodman.operations.roomflow.RoomFlowActivity
import com.floodman.operations.payments.PaymentEvent
import kotlinx.coroutines.flow.collectLatest
import java.text.NumberFormat
import java.util.Currency
import java.util.UUID
import java.io.File
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private fun money(cents: Long): String = NumberFormat.getCurrencyInstance().apply { currency = Currency.getInstance("USD") }.format(cents / 100.0)
private fun Customer.displayName(): String = name?.takeIf { it.isNotBlank() } ?: listOfNotNull(firstName, lastName).joinToString(" ").ifBlank { company ?: email ?: "Customer" }
private fun PropertyRecord.displayName(): String = propertyName?.takeIf { it.isNotBlank() } ?: name ?: serviceStreet ?: "Service property"

private sealed class Destination(val route: String, val label: String, val icon: androidx.compose.ui.graphics.vector.ImageVector) {
    data object Home : Destination("home", "Home", Icons.Default.Home)
    data object Calendar : Destination("calendar", "Calendar", Icons.Default.CalendarMonth)
    data object Customers : Destination("customers", "Customers", Icons.Default.People)
    data object Estimates : Destination("estimates", "Estimates", Icons.Default.RequestQuote)
    data object More : Destination("more", "More", Icons.Default.MoreHoriz)
}

@Composable
fun FloodmanApp(
    viewModel: MainViewModel,
    requestDeviceUnlock: () -> Unit,
    startCardEntry: () -> Unit,
) {
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(Unit) {
        PaymentCoordinator.events.collectLatest { event ->
            when (event) {
                is PaymentEvent.Success -> {
                    viewModel.paymentCompleted(event.targetKind, event.targetId)
                    snackbar.showSnackbar(event.message)
                }
                is PaymentEvent.Error -> snackbar.showSnackbar(event.message)
                PaymentEvent.Canceled -> snackbar.showSnackbar("Card entry canceled.")
            }
        }
    }
    LaunchedEffect(viewModel.error) { viewModel.error?.let { snackbar.showSnackbar(it); viewModel.dismissError() } }
    LaunchedEffect(viewModel.notice) { viewModel.notice?.let { snackbar.showSnackbar(it); viewModel.dismissNotice() } }

    when {
        !viewModel.signedIn -> LoginScreen(viewModel, snackbar)
        !viewModel.unlocked -> LockedScreen(requestDeviceUnlock, viewModel::logout)
        else -> MainWorkspace(viewModel, snackbar, startCardEntry)
    }
}

@Composable
private fun LoginScreen(viewModel: MainViewModel, snackbar: SnackbarHostState) {
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var localAccount by remember { mutableStateOf(false) }
    Box(Modifier.fillMaxSize().safeDrawingPadding().padding(24.dp), contentAlignment = Alignment.Center) {
        Card(Modifier.widthIn(max = 480.dp)) {
            Column(Modifier.padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Icon(Icons.Default.WaterDrop, contentDescription = null, tint = MaterialTheme.colorScheme.secondary, modifier = Modifier.size(48.dp))
                Text("Floodman Operations", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
                Text("Secure staff access through the encrypted Floodman API at api.oninetwork.com.")
                OutlinedTextField(email, { email = it }, label = { Text("Email") }, modifier = Modifier.fillMaxWidth(), singleLine = true, keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next))
                OutlinedTextField(password, { password = it }, label = { Text("Password") }, modifier = Modifier.fillMaxWidth(), singleLine = true, visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done), keyboardActions = KeyboardActions(onDone = { if (email.isNotBlank() && password.isNotBlank()) viewModel.login(email, password, localAccount) }))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(localAccount, { localAccount = it })
                    Text("Use local Floodman account instead of ERP credentials")
                }
                Button(onClick = { viewModel.login(email, password, localAccount) }, modifier = Modifier.fillMaxWidth(), enabled = !viewModel.busy && email.isNotBlank() && password.isNotBlank()) {
                    if (viewModel.busy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp) else Text("Sign in")
                }
                Text("API: ${viewModel.apiBaseUrl}", style = MaterialTheme.typography.labelSmall)
            }
        }
        SnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter))
    }
}

@Composable
private fun LockedScreen(onUnlock: () -> Unit, onLogout: () -> Unit) {
    Box(Modifier.fillMaxSize().safeDrawingPadding().padding(24.dp), contentAlignment = Alignment.Center) {
        Card {
            Column(Modifier.padding(28.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Icon(Icons.Default.Lock, null, Modifier.size(56.dp))
                Text("Floodman is locked", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Text("Use your fingerprint, face, or device PIN.")
                Button(onClick = onUnlock) { Text("Unlock") }
                TextButton(onClick = onLogout) { Text("Sign out") }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MainWorkspace(viewModel: MainViewModel, snackbar: SnackbarHostState, startCardEntry: () -> Unit) {
    val nav = rememberNavController()
    val density = LocalDensity.current
    val windowInfo = LocalWindowInfo.current
    val wide = with(density) { windowInfo.containerSize.width.toDp() >= 700.dp }
    val destinations = listOf(Destination.Home, Destination.Calendar, Destination.Customers, Destination.Estimates, Destination.More)
    var currentRoute by remember { mutableStateOf(Destination.Home.route) }
    LaunchedEffect(nav) { nav.currentBackStackEntryFlow.collect { currentRoute = it.destination.route.orEmpty() } }
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Floodman Operations") },
                actions = {
                    if (viewModel.busy) CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp)
                    IconButton(onClick = viewModel::refreshHome) { Icon(Icons.Default.Refresh, "Refresh") }
                },
            )
        },
        bottomBar = {
            if (!wide) NavigationBar {
                destinations.forEach { destination ->
                    NavigationBarItem(
                        selected = currentRoute.startsWith(destination.route),
                        onClick = { nav.navigate(destination.route) { launchSingleTop = true; restoreState = true; popUpTo(Destination.Home.route) { saveState = true } } },
                        icon = { Icon(destination.icon, null) },
                        label = { Text(destination.label) },
                    )
                }
            }
        },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        Row(Modifier.fillMaxSize().padding(padding)) {
            if (wide) NavigationRail {
                Spacer(Modifier.height(12.dp))
                destinations.forEach { destination ->
                    NavigationRailItem(
                        selected = currentRoute.startsWith(destination.route),
                        onClick = { nav.navigate(destination.route) { launchSingleTop = true } },
                        icon = { Icon(destination.icon, null) },
                        label = { Text(destination.label) },
                    )
                }
            }
            FloodmanNavHost(nav, viewModel, startCardEntry, Modifier.weight(1f))
        }
    }
}

@Composable
private fun FloodmanNavHost(nav: NavHostController, viewModel: MainViewModel, startCardEntry: () -> Unit, modifier: Modifier = Modifier) {
    NavHost(nav, startDestination = Destination.Home.route, modifier = modifier) {
        composable(Destination.Home.route) { HomeScreen(viewModel, nav) }
        composable(Destination.Calendar.route) { CalendarScreen(viewModel) }
        composable(Destination.Customers.route) { CustomerListScreen(viewModel, nav) }
        composable("customer/{id}") { entry -> CustomerDetailScreen(viewModel, entry.arguments?.getString("id").orEmpty()) }
        composable(Destination.Estimates.route) { EstimateListScreen(viewModel, nav) }
        composable("estimate/{id}") { entry -> EstimateDetailScreen(viewModel, nav, entry.arguments?.getString("id").orEmpty(), startCardEntry) }
        composable("estimate/{id}/edit") { entry -> EditEstimateScreen(viewModel, nav, entry.arguments?.getString("id").orEmpty()) }
        composable("estimate-new") { NewEstimateScreen(viewModel, nav) }
        composable("invoices") { InvoiceListScreen(viewModel, nav) }
        composable("invoice/{id}") { entry -> InvoiceDetailScreen(viewModel, nav, entry.arguments?.getString("id").orEmpty(), startCardEntry) }
        composable("invoice/{id}/edit") { entry -> EditInvoiceScreen(viewModel, nav, entry.arguments?.getString("id").orEmpty()) }
        composable("invoice-new") { NewInvoiceScreen(viewModel, nav) }
        composable(Destination.More.route) { MoreScreen(viewModel, nav) }
        composable("roomflow") { RoomFlowJobsScreen(viewModel) }
        composable("time") { TimeClockScreen(viewModel) }
        composable("tasks") { TasksScreen(viewModel) }
        composable("documents") { DocumentsScreen(viewModel) }
        composable("announcements") { AnnouncementsScreen(viewModel) }
        composable("notifications") { NotificationsScreen(viewModel) }
        composable("settings") { SettingsScreen(viewModel) }
    }
}

@Composable
private fun ScreenContainer(title: String, action: (@Composable RowScope.() -> Unit)? = null, content: @Composable ColumnScope.() -> Unit) {
    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            action?.invoke(this)
        }
        content()
    }
}

@Composable
private fun MetricCard(label: String, value: String, modifier: Modifier = Modifier) {
    Card(modifier) { Column(Modifier.padding(16.dp)) { Text(label, style = MaterialTheme.typography.labelMedium); Text(value, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold) } }
}

@Composable
private fun HomeScreen(viewModel: MainViewModel, nav: NavHostController) {
    LaunchedEffect(Unit) { viewModel.refreshHome() }
    val d = viewModel.dashboard
    ScreenContainer("Operations dashboard") {
        if (d == null) { LinearProgressIndicator(Modifier.fillMaxWidth()); return@ScreenContainer }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            MetricCard("Customers", d.customers.toString(), Modifier.weight(1f))
            MetricCard("Properties", d.properties.toString(), Modifier.weight(1f))
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            MetricCard("Open estimates", d.openEstimates.toString(), Modifier.weight(1f))
            MetricCard("Amount due", money(d.outstandingBalanceCents), Modifier.weight(1f))
        }
        Card { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Quick actions", fontWeight = FontWeight.Bold)
            Button(onClick = { nav.navigate("estimate-new") }, Modifier.fillMaxWidth()) { Icon(Icons.Default.Add, null); Spacer(Modifier.width(8.dp)); Text("Create estimate") }
            OutlinedButton(onClick = { nav.navigate("customers") }, Modifier.fillMaxWidth()) { Text("Find customer") }
            OutlinedButton(onClick = { nav.navigate("roomflow") }, Modifier.fillMaxWidth()) { Text("RoomFlow jobs") }
        } }
        if (d.upcomingAppointments.isNotEmpty()) Card { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Upcoming", fontWeight = FontWeight.Bold)
            d.upcomingAppointments.take(4).forEach { Text("${displayDateTime(it.startAt)} · ${it.title}") }
            TextButton(onClick = { nav.navigate("calendar") }) { Text("Open calendar") }
        } }
        if (d.activeAnnouncements.isNotEmpty()) Card { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Announcements", fontWeight = FontWeight.Bold)
            d.activeAnnouncements.take(3).forEach { Text("${it.title}: ${it.body}") }
        } }
        Card { Column(Modifier.padding(16.dp)) {
            Text("Time clock", fontWeight = FontWeight.Bold)
            Text(if (d.clock == null) "Not clocked in" else "Clocked in: ${d.clock.jobReference.orEmpty()}")
            TextButton(onClick = { nav.navigate("time") }) { Text("Open time clock") }
        } }
    }
}

@Composable
private fun SearchField(value: String, onValueChange: (String) -> Unit, onSearch: () -> Unit, placeholder: String) {
    OutlinedTextField(
        value, onValueChange,
        modifier = Modifier.fillMaxWidth(), singleLine = true,
        placeholder = { Text(placeholder) }, leadingIcon = { Icon(Icons.Default.Search, null) },
        trailingIcon = { IconButton(onClick = onSearch) { Icon(Icons.AutoMirrored.Filled.ArrowForward, "Search") } },
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
        keyboardActions = KeyboardActions(onSearch = { onSearch() }),
    )
}

@Composable
private fun CustomerListScreen(viewModel: MainViewModel, nav: NavHostController) {
    var query by remember { mutableStateOf("") }
    LaunchedEffect(Unit) { viewModel.loadCustomers() }
    ScreenContainer("Customers") {
        SearchField(query, { query = it }, { viewModel.loadCustomers(query) }, "Name, phone, email, address, or tag")
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(viewModel.customers, key = { it.id }) { customer ->
                Card(onClick = { nav.navigate("customer/${customer.id}") }, modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp)) {
                        Text(customer.displayName(), fontWeight = FontWeight.Bold)
                        Text(listOfNotNull(customer.company, customer.email, customer.phone ?: customer.mobilePhone).filter { it.isNotBlank() }.joinToString(" · "))
                        if (customer.tags.isNotEmpty()) Text(customer.tags.joinToString(" • "), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.secondary)
                    }
                }
            }
        }
    }
}

@Composable
private fun CustomerDetailScreen(viewModel: MainViewModel, id: String) {
    var note by remember { mutableStateOf("") }
    var tagText by remember { mutableStateOf("") }
    LaunchedEffect(id) { viewModel.loadCustomer(id) }
    val detail = viewModel.customerDetail
    ScreenContainer("Customer file") {
        if (detail == null || detail.customer.id != id) { LinearProgressIndicator(Modifier.fillMaxWidth()); return@ScreenContainer }
        val c = detail.customer
        Card { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(c.displayName(), style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            Text(c.email.orEmpty()); Text(c.phone ?: c.mobilePhone.orEmpty())
            Text(listOfNotNull(c.mailingStreet ?: c.address, c.mailingCity, c.mailingState, c.mailingPostalCode).filter { it.isNotBlank() }.joinToString(", "))
            if (c.tags.isNotEmpty()) Text("Tags: ${c.tags.joinToString(", ")}")
        } }
        Text("Service properties", fontWeight = FontWeight.Bold)
        detail.properties.forEach { p -> Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(12.dp)) { Text(p.displayName(), fontWeight = FontWeight.Bold); Text(listOfNotNull(p.serviceStreet, p.serviceCity, p.serviceState, p.servicePostalCode).joinToString(", ")) } } }
        Text("Add note", fontWeight = FontWeight.Bold)
        OutlinedTextField(note, { note = it }, Modifier.fillMaxWidth(), minLines = 3, label = { Text("Customer note") })
        Button(onClick = { if (note.isNotBlank()) { viewModel.addNote(id, note, "GENERAL", false); note = "" } }, enabled = note.isNotBlank()) { Text("Save note") }
        Text("Update tags", fontWeight = FontWeight.Bold)
        OutlinedTextField(tagText, { tagText = it }, Modifier.fillMaxWidth(), label = { Text("Comma-separated tags") }, placeholder = { Text(c.tags.joinToString(", ")) })
        OutlinedButton(onClick = { viewModel.updateTags(id, tagText.split(',').map(String::trim).filter(String::isNotBlank)) }) { Text("Save tags") }
        Text("Recent notes", fontWeight = FontWeight.Bold)
        detail.notes.take(20).forEach { n -> Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(12.dp)) { Text(n.category ?: "NOTE", style = MaterialTheme.typography.labelSmall); Text(n.text ?: n.note.orEmpty()); Text(n.createdAt.orEmpty(), style = MaterialTheme.typography.labelSmall) } } }
    }
}

@Composable
private fun EstimateListScreen(viewModel: MainViewModel, nav: NavHostController) {
    var query by remember { mutableStateOf("") }
    LaunchedEffect(Unit) { viewModel.loadEstimates() }
    ScreenContainer("Estimates", action = { FilledTonalButton(onClick = { nav.navigate("estimate-new") }) { Icon(Icons.Default.Add, null); Text(" New") } }) {
        SearchField(query, { query = it }, { viewModel.loadEstimates(query) }, "Estimate number, customer, or title")
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(viewModel.estimates, key = { it.id }) { estimate ->
                Card(onClick = { nav.navigate("estimate/${estimate.id}") }, Modifier.fillMaxWidth()) {
                    Row(Modifier.padding(16.dp).fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) { Text(estimate.estimateNumber ?: "Estimate", fontWeight = FontWeight.Bold); Text(estimate.title.orEmpty()); Text(estimate.status.orEmpty(), style = MaterialTheme.typography.labelMedium) }
                        Text(money(estimate.totalCents), fontWeight = FontWeight.Bold)
                    }
                }
            }
        }
    }
}

@Composable
private fun EstimateDetailScreen(viewModel: MainViewModel, nav: NavHostController, id: String, startCardEntry: () -> Unit) {
    val context = LocalContext.current
    LaunchedEffect(id) { viewModel.loadEstimate(id) }
    val detail = viewModel.estimateDetail
    var showPayment by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    ScreenContainer("Estimate") {
        if (detail == null || detail.estimate.id != id) { LinearProgressIndicator(Modifier.fillMaxWidth()); return@ScreenContainer }
        val e = detail.estimate
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            DocumentHeader(e.estimateNumber ?: "Estimate", e.title.orEmpty(), e.status.orEmpty(), e.totalCents)
            DetailPair("Customer", detail.customer?.displayName().orEmpty(), "Service property", detail.property?.displayName().orEmpty())
            Card { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                Text(e.recommendedProjectTitle ?: e.title.orEmpty(), fontWeight = FontWeight.Bold)
                Text(e.projectSummary.orEmpty())
                Text("Duration: ${e.estimatedDuration.orEmpty()}")
                Text("Deposit: ${money(e.depositCents)} · Due ${money(e.depositBalanceCents)}")
            } }
            ScopeView(e.sections, e.lineItems)
            Card { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Estimate actions", fontWeight = FontWeight.Bold)
                if ("edit" in detail.allowedActions) OutlinedButton(onClick = { nav.navigate("estimate/$id/edit") }, Modifier.fillMaxWidth()) { Icon(Icons.Default.Edit, null); Text(" Edit estimate") }
                Button(onClick = { viewModel.loadEstimatePdf(id) { bytes -> openPdf(context, bytes, "${e.estimateNumber ?: "estimate"}.pdf") } }, Modifier.fillMaxWidth()) { Icon(Icons.Default.PictureAsPdf, null); Text(" View Floodman PDF") }
                if ("send" in detail.allowedActions || "resend" in detail.allowedActions) Button(onClick = { viewModel.estimateAction(id, if (e.status == "DRAFT") "send" else "resend") }, Modifier.fillMaxWidth()) { Icon(Icons.AutoMirrored.Filled.Send, null); Text(if (e.status == "DRAFT") " Send estimate" else " Resend estimate") }
                if ("send_work_authorization" in detail.allowedActions) OutlinedButton(onClick = { viewModel.estimateAction(id, "send_work_authorization") { response -> response.signingUrl?.let { openUrl(context, it) } } }, Modifier.fillMaxWidth()) { Text("Send Work Authorization") }
                if ("mark_accepted" in detail.allowedActions) OutlinedButton(onClick = { viewModel.estimateAction(id, "mark_accepted") }, Modifier.fillMaxWidth()) { Text("Mark accepted") }
                if ("activate_deposit" in detail.allowedActions) OutlinedButton(onClick = { viewModel.estimateAction(id, "activate_deposit") }, Modifier.fillMaxWidth()) { Text("Activate deposit payment") }
                if ("take_payment" in detail.allowedActions && e.depositBalanceCents > 0) Button(onClick = { showPayment = true }, Modifier.fillMaxWidth()) { Text("Take deposit ${money(e.depositBalanceCents)}") }
                OutlinedButton(onClick = {
                    viewModel.estimateAction(id, "ensure_public") { response -> response.estimate?.publicUrl?.let { openUrl(context, it) } }
                }, Modifier.fillMaxWidth()) { Text("Open customer estimate") }
                if ("open_payment_link" in detail.allowedActions) OutlinedButton(onClick = {
                    viewModel.estimateAction(id, "ensure_public") { response -> response.estimate?.publicPayUrl?.let { openUrl(context, it) } }
                }, Modifier.fillMaxWidth()) { Text("Open customer payment page") }
                if ("convert_to_invoice" in detail.allowedActions) Button(onClick = { viewModel.estimateAction(id, "convert_to_invoice") { response -> response.invoice?.let { nav.navigate("invoice/${it.id}") } } }, Modifier.fillMaxWidth(), colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.tertiary)) { Text("Convert to invoice") }
                if ("delete" in detail.allowedActions) TextButton(onClick = { confirmDelete = true }, Modifier.fillMaxWidth(), colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error)) { Text("Delete estimate") }
            } }
            if (detail.documents.isNotEmpty()) Card { Column(Modifier.padding(16.dp)) { Text("Documents", fontWeight = FontWeight.Bold); detail.documents.forEach { Text("${it.kind.orEmpty()} · ${it.status.orEmpty()}") } } }
        }
        if (showPayment) PaymentDialog(viewModel, "estimate", e.id, e.depositBalanceCents, startCardEntry) { showPayment = false }
        if (confirmDelete) AlertDialog(onDismissRequest = { confirmDelete = false }, title = { Text("Delete estimate?") }, text = { Text("Only eligible unconverted estimates can be deleted.") }, confirmButton = { Button(onClick = { confirmDelete = false; viewModel.estimateAction(id, "delete") { nav.navigate("estimates") { popUpTo("estimates") { inclusive = true } } } }, colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)) { Text("Delete") } }, dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("Cancel") } })
    }
}

@Composable
private fun InvoiceListScreen(viewModel: MainViewModel, nav: NavHostController) {
    var query by remember { mutableStateOf("") }
    LaunchedEffect(Unit) { viewModel.loadInvoices() }
    ScreenContainer("Invoices", action = { FilledTonalButton(onClick = { nav.navigate("invoice-new") }) { Icon(Icons.Default.Add, null); Text(" New") } }) {
        SearchField(query, { query = it }, { viewModel.loadInvoices(query) }, "Invoice number, customer, or title")
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(viewModel.invoices, key = { it.id }) { invoice ->
                Card(onClick = { nav.navigate("invoice/${invoice.id}") }, Modifier.fillMaxWidth()) {
                    Row(Modifier.padding(16.dp).fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) { Text(invoice.invoiceNumber ?: "Invoice", fontWeight = FontWeight.Bold); Text(invoice.status.orEmpty()); Text("Paid ${money(invoice.paidCents)}") }
                        Text(money(invoice.balanceCents), fontWeight = FontWeight.Bold)
                    }
                }
            }
        }
    }
}

@Composable
private fun InvoiceDetailScreen(viewModel: MainViewModel, nav: NavHostController, id: String, startCardEntry: () -> Unit) {
    val context = LocalContext.current
    LaunchedEffect(id) { viewModel.loadInvoice(id) }
    val detail = viewModel.invoiceDetail
    var showPayment by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    ScreenContainer("Invoice") {
        if (detail == null || detail.invoice.id != id) { LinearProgressIndicator(Modifier.fillMaxWidth()); return@ScreenContainer }
        val i = detail.invoice
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            DocumentHeader(i.invoiceNumber ?: "Invoice", i.title.orEmpty(), i.status.orEmpty(), i.balanceCents)
            DetailPair("Customer", detail.customer?.displayName().orEmpty(), "Service property", detail.property?.displayName().orEmpty())
            ScopeView(i.sections, i.lineItems)
            Card { Column(Modifier.padding(16.dp)) { Text("Payment history", fontWeight = FontWeight.Bold); if (detail.payments.isEmpty()) Text("No payments recorded.") else detail.payments.forEach { Text("${it.method.orEmpty()} · ${money(it.amountCents)} · ${it.paymentDate.orEmpty()}") } } }
            Card { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Invoice actions", fontWeight = FontWeight.Bold)
                if ("edit" in detail.allowedActions) OutlinedButton(onClick = { nav.navigate("invoice/$id/edit") }, Modifier.fillMaxWidth()) { Text("Edit invoice") }
                Button(onClick = { viewModel.loadInvoicePdf(id) { bytes -> openPdf(context, bytes, "${i.invoiceNumber ?: "invoice"}.pdf") } }, Modifier.fillMaxWidth()) { Icon(Icons.Default.PictureAsPdf, null); Text(" View Floodman PDF") }
                if ("send" in detail.allowedActions || "resend" in detail.allowedActions) Button(onClick = { viewModel.invoiceAction(id, if (i.status == "DRAFT") "send" else "resend") }, Modifier.fillMaxWidth()) { Icon(Icons.AutoMirrored.Filled.Send, null); Text(if (i.status == "DRAFT") " Send invoice" else " Resend invoice") }
                if ("take_payment" in detail.allowedActions && i.balanceCents > 0) Button(onClick = { showPayment = true }, Modifier.fillMaxWidth()) { Text("Take payment ${money(i.balanceCents)}") }
                OutlinedButton(onClick = { viewModel.invoiceAction(id, "ensure_public") { response -> response.invoice?.publicUrl?.let { openUrl(context, it) } } }, Modifier.fillMaxWidth()) { Text("Open customer invoice") }
                if ("open_payment_link" in detail.allowedActions) OutlinedButton(onClick = { viewModel.invoiceAction(id, "ensure_public") { response -> response.invoice?.publicPayUrl?.let { openUrl(context, it) } } }, Modifier.fillMaxWidth()) { Text("Open customer payment page") }
                if ("void" in detail.allowedActions) OutlinedButton(onClick = { viewModel.invoiceAction(id, "void") }, Modifier.fillMaxWidth(), colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error)) { Text("Void invoice") }
                if ("delete" in detail.allowedActions) TextButton(onClick = { confirmDelete = true }, Modifier.fillMaxWidth(), colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error)) { Text("Delete draft") }
            } }
        }
        if (showPayment) PaymentDialog(viewModel, "invoice", i.id, i.balanceCents, startCardEntry) { showPayment = false }
        if (confirmDelete) AlertDialog(onDismissRequest = { confirmDelete = false }, title = { Text("Delete invoice draft?") }, text = { Text("Only unpaid drafts can be deleted.") }, confirmButton = { Button(onClick = { confirmDelete = false; viewModel.invoiceAction(id, "delete") { nav.navigate("invoices") { popUpTo("invoices") { inclusive = true } } } }, colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)) { Text("Delete") } }, dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("Cancel") } })
    }
}

@Composable
private fun NewInvoiceScreen(viewModel: MainViewModel, nav: NavHostController) = InvoiceWorkspaceScreen(viewModel, nav, null)

@Composable
private fun EditInvoiceScreen(viewModel: MainViewModel, nav: NavHostController, invoiceId: String) = InvoiceWorkspaceScreen(viewModel, nav, invoiceId)

@Composable
private fun InvoiceWorkspaceScreen(viewModel: MainViewModel, nav: NavHostController, invoiceId: String?) {
    val editing = invoiceId != null
    var initialized by remember(invoiceId) { mutableStateOf(false) }
    var customerQuery by remember { mutableStateOf("") }
    var selectedCustomer by remember { mutableStateOf<Customer?>(null) }
    var propertyQuery by remember { mutableStateOf("") }
    var selectedProperty by remember { mutableStateOf<PropertyRecord?>(null) }
    var invoiceNumber by remember { mutableStateOf("") }
    var title by remember { mutableStateOf("") }
    var terms by remember { mutableStateOf("Payment is due upon receipt.") }
    var notes by remember { mutableStateOf("") }
    var catalogQuery by remember { mutableStateOf("") }
    var selectedSectionIndex by remember { mutableIntStateOf(0) }
    var showCustom by remember { mutableStateOf(false) }
    val sections = remember(invoiceId) { mutableStateListOf<SectionDraft>() }
    LaunchedEffect(invoiceId) { if (invoiceId != null) viewModel.loadInvoice(invoiceId) else viewModel.loadCustomers() }
    LaunchedEffect(viewModel.invoiceDetail, invoiceId) {
        val detail = viewModel.invoiceDetail
        if (!initialized && invoiceId != null && detail?.invoice?.id == invoiceId) {
            val i = detail.invoice
            selectedCustomer = detail.customer; selectedProperty = detail.property
            invoiceNumber = i.invoiceNumber.orEmpty()
            title = i.title.orEmpty(); terms = i.terms.orEmpty(); notes = i.customerNotes.orEmpty()
            sections.clear(); sections.addAll(i.sections.sortedBy { it.sortOrder }.map { section ->
                SectionDraft(section.id ?: UUID.randomUUID().toString(), section.title, section.description, i.lineItems.filter { it.sectionId == section.id || (it.sectionId == null && it.sectionName == section.title) }.map { line ->
                    LineDraft(line.id ?: UUID.randomUUID().toString(), line.catalogItemId, line.name, line.description, line.category, line.unit, line.quantity.toString(), "%.2f".format(line.unitPriceCents / 100.0), line.taxable)
                })
            }.ifEmpty { listOf(SectionDraft(title = "Completed Scope")) })
            initialized = true
        }
    }
    LaunchedEffect(Unit) { if (!editing && sections.isEmpty()) sections.add(SectionDraft(title = "Completed Scope")) }
    ScreenContainer(if (editing) "Edit invoice" else "Create invoice") {
        if (editing && !initialized) { LinearProgressIndicator(Modifier.fillMaxWidth()); return@ScreenContainer }
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (editing) DetailPair("Customer", selectedCustomer?.displayName().orEmpty(), "Service property", selectedProperty?.displayName().orEmpty()) else {
                Text("Customer and property", fontWeight = FontWeight.Bold)
                SearchField(customerQuery, { customerQuery = it }, { viewModel.loadCustomers(customerQuery) }, "Search customer")
                selectedCustomer?.let { AssistChip(onClick = {}, label = { Text(it.displayName()) }) }
                if (selectedCustomer == null) viewModel.customers.take(8).forEach { c -> TextButton(onClick = { selectedCustomer = c; selectedProperty = null; viewModel.loadProperties(c.id) }, Modifier.fillMaxWidth()) { Text(c.displayName()) } }
                SearchField(propertyQuery, { propertyQuery = it }, { selectedCustomer?.let { viewModel.loadProperties(it.id, propertyQuery) } }, "Search property")
                selectedProperty?.let { AssistChip(onClick = {}, label = { Text(it.displayName()) }) }
                if (selectedCustomer != null && selectedProperty == null) viewModel.properties.take(8).forEach { prop -> TextButton(onClick = { selectedProperty = prop }, Modifier.fillMaxWidth()) { Text(prop.displayName()) } }
            }
            OutlinedTextField(invoiceNumber, { invoiceNumber = it }, Modifier.fillMaxWidth(), label = { Text("Invoice number (blank = automatic)") })
            OutlinedTextField(title, { title = it }, Modifier.fillMaxWidth(), label = { Text("Invoice title") })
            OutlinedTextField(notes, { notes = it }, Modifier.fillMaxWidth(), minLines = 2, label = { Text("Customer-facing notes") })
            OutlinedTextField(terms, { terms = it }, Modifier.fillMaxWidth(), minLines = 2, label = { Text("Terms") })
            Text("Headers and line items", fontWeight = FontWeight.Bold)
            sections.forEachIndexed { index, section ->
                Card { Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Header ${index + 1}", Modifier.weight(1f), fontWeight = FontWeight.Bold)
                        IconButton(onClick = { if (index > 0) { val moved = sections.removeAt(index); sections.add(index-1,moved) } }, enabled = index > 0) { Icon(Icons.Default.ArrowUpward, null) }
                        IconButton(onClick = { if (index < sections.lastIndex) { val moved = sections.removeAt(index); sections.add(index+1,moved) } }, enabled = index < sections.lastIndex) { Icon(Icons.Default.ArrowDownward, null) }
                        IconButton(onClick = { if (sections.size > 1) sections.removeAt(index) }, enabled = sections.size > 1) { Icon(Icons.Default.Delete, null) }
                    }
                    OutlinedTextField(section.title, { section.title = it }, Modifier.fillMaxWidth(), label = { Text("Header name") })
                    OutlinedTextField(section.description, { section.description = it }, Modifier.fillMaxWidth(), label = { Text("Header description") })
                    section.lines.forEachIndexed { lineIndex, line ->
                        Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) { Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Row { Text("Line ${lineIndex + 1}", Modifier.weight(1f), fontWeight = FontWeight.Bold); IconButton(onClick = { section.lines.removeAt(lineIndex) }) { Icon(Icons.Default.Delete, null) } }
                            OutlinedTextField(line.name, { line.name = it }, Modifier.fillMaxWidth(), label = { Text("Item") })
                            OutlinedTextField(line.description, { line.description = it }, Modifier.fillMaxWidth(), label = { Text("Description") })
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                OutlinedTextField(line.quantity, { line.quantity = it }, Modifier.weight(1f), label = { Text("Qty") })
                                OutlinedTextField(line.unit, { line.unit = it }, Modifier.weight(1f), label = { Text("Unit") })
                                OutlinedTextField(line.unitPrice, { line.unitPrice = it }, Modifier.weight(1f), label = { Text("Price") })
                            }
                        } }
                    }
                    FilledTonalButton(onClick = { selectedSectionIndex = index; viewModel.loadCatalog(catalogQuery) }) { Text("Add catalog item") }
                } }
            }
            OutlinedButton(onClick = { sections.add(SectionDraft(title = "New header")); selectedSectionIndex = sections.lastIndex }, Modifier.fillMaxWidth()) { Text("Add header") }
            SearchField(catalogQuery, { catalogQuery = it }, { viewModel.loadCatalog(catalogQuery) }, "Search line-item catalog")
            viewModel.catalog.take(12).forEach { item -> TextButton(onClick = { (sections.getOrNull(selectedSectionIndex) ?: sections.first()).lines.add(LineDraft(catalogItemId=item.id,name=item.name,description=item.description.orEmpty(),category=item.category?:"General Services",unit=item.unit?:"each",unitPrice="%.2f".format(item.unitPriceCents/100.0))) }, Modifier.fillMaxWidth()) { Text("${item.name} · ${money(item.unitPriceCents)}") } }
            OutlinedButton(onClick = { showCustom = true }, Modifier.fillMaxWidth()) { Text("Add custom item") }
            Button(onClick = {
                val customer = selectedCustomer ?: return@Button; val prop = selectedProperty ?: return@Button
                val input = InvoiceCreateInput(contactId=customer.id, propertyId=prop.id, invoiceNumber=invoiceNumber.trim(), title=title.trim(), terms=terms.trim(), customerNotes=notes.trim(), sections=sections.toInputs())
                if (invoiceId == null) viewModel.createInvoice(input) { id -> nav.navigate("invoice/$id") { popUpTo("invoice-new") { inclusive = true } } }
                else viewModel.updateInvoice(invoiceId, input) { nav.popBackStack() }
            }, Modifier.fillMaxWidth(), enabled = selectedCustomer != null && selectedProperty != null && title.isNotBlank() && sections.any { it.lines.isNotEmpty() }) { Text(if (editing) "Save invoice changes" else "Save draft invoice") }
        }
        if (showCustom) CustomLineDialog(onDismiss = { showCustom = false }) { line -> sections.getOrNull(selectedSectionIndex)?.lines?.add(line); showCustom = false }
    }
}

@Composable
private fun DocumentHeader(number: String, title: String, status: String, amountCents: Long) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primary)) {
        Row(Modifier.padding(20.dp).fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) { Text(number, color = MaterialTheme.colorScheme.onPrimary, fontWeight = FontWeight.Bold); Text(title, color = MaterialTheme.colorScheme.onPrimary); Text(status, color = MaterialTheme.colorScheme.secondary) }
            Text(money(amountCents), color = MaterialTheme.colorScheme.onPrimary, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
private fun DetailPair(leftLabel: String, left: String, rightLabel: String, right: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Card(Modifier.weight(1f)) { Column(Modifier.padding(12.dp)) { Text(leftLabel, style = MaterialTheme.typography.labelSmall); Text(left, fontWeight = FontWeight.Bold) } }
        Card(Modifier.weight(1f)) { Column(Modifier.padding(12.dp)) { Text(rightLabel, style = MaterialTheme.typography.labelSmall); Text(right, fontWeight = FontWeight.Bold) } }
    }
}

@Composable
private fun ScopeView(sections: List<EstimateSectionModel>, lines: List<EstimateLineModel>) {
    Text("Scope and pricing", fontWeight = FontWeight.Bold)
    sections.sortedBy { it.sortOrder }.forEach { section ->
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(section.title, fontWeight = FontWeight.Bold)
                if (section.description.isNotBlank()) Text(section.description, style = MaterialTheme.typography.bodySmall)
                lines.filter { it.sectionId == section.id || (it.sectionId == null && it.sectionName == section.title) }.forEach { line ->
                    Row(Modifier.fillMaxWidth()) { Column(Modifier.weight(1f)) { Text(line.name); Text("${line.quantity} ${line.unit}", style = MaterialTheme.typography.labelSmall) }; Text(money(if (line.lineTotalCents > 0) line.lineTotalCents else (line.quantity * line.unitPriceCents).toLong())) }
                }
                HorizontalDivider()
                Row(Modifier.fillMaxWidth()) { Text("Section subtotal", Modifier.weight(1f), fontWeight = FontWeight.Bold); Text(money(section.subtotalCents), fontWeight = FontWeight.Bold) }
            }
        }
    }
}

private class LineDraft(
    val id: String = UUID.randomUUID().toString(),
    catalogItemId: String? = null,
    name: String = "",
    description: String = "",
    category: String = "General Services",
    unit: String = "each",
    quantity: String = "1",
    unitPrice: String = "0.00",
    taxable: Boolean = false,
    saveToCatalog: Boolean = false,
) {
    var catalogItemId by mutableStateOf(catalogItemId)
    var name by mutableStateOf(name)
    var description by mutableStateOf(description)
    var category by mutableStateOf(category)
    var unit by mutableStateOf(unit)
    var quantity by mutableStateOf(quantity)
    var unitPrice by mutableStateOf(unitPrice)
    var taxable by mutableStateOf(taxable)
    var saveToCatalog by mutableStateOf(saveToCatalog)
}
private class SectionDraft(
    val id: String = UUID.randomUUID().toString(),
    title: String = "Scope of Work",
    description: String = "",
    lines: List<LineDraft> = emptyList(),
) {
    var title by mutableStateOf(title)
    var description by mutableStateOf(description)
    val lines: SnapshotStateList<LineDraft> = mutableStateListOf<LineDraft>().also { it.addAll(lines) }
}

private fun List<SectionDraft>.toInputs(): List<EstimateSectionInput> =
    filter { it.title.isNotBlank() }.map { section ->
        EstimateSectionInput(
            title = section.title.trim(),
            description = section.description.trim(),
            lines = section.lines.filter { it.name.isNotBlank() }.map { line ->
                EstimateLineInput(
                    catalogItemId = line.catalogItemId, name = line.name.trim(), description = line.description.trim(),
                    category = line.category, unit = line.unit, quantity = line.quantity.toDoubleOrNull() ?: 1.0,
                    unitPriceCents = ((line.unitPrice.toDoubleOrNull() ?: 0.0) * 100).toLong(), taxable = line.taxable,
                    optional = false, saveToCatalog = line.saveToCatalog,
                )
            },
        )
    }

private fun estimateSections(estimate: Estimate): List<SectionDraft> = estimate.sections.sortedBy { it.sortOrder }.map { section ->
    SectionDraft(
        id = section.id ?: UUID.randomUUID().toString(),
        title = section.title, description = section.description,
        lines = estimate.lineItems.filter { it.sectionId == section.id || (it.sectionId == null && it.sectionName == section.title) }.map { line ->
            LineDraft(
                id = line.id ?: UUID.randomUUID().toString(), catalogItemId = line.catalogItemId, name = line.name, description = line.description,
                category = line.category, unit = line.unit, quantity = line.quantity.toString(),
                unitPrice = "%.2f".format(line.unitPriceCents / 100.0), taxable = line.taxable,
            )
        },
    )
}.ifEmpty { listOf(SectionDraft()) }

@Composable
private fun NewEstimateScreen(viewModel: MainViewModel, nav: NavHostController) =
    EstimateWorkspaceScreen(viewModel, nav, null)

@Composable
private fun EditEstimateScreen(viewModel: MainViewModel, nav: NavHostController, estimateId: String) =
    EstimateWorkspaceScreen(viewModel, nav, estimateId)

@Composable
private fun EstimateWorkspaceScreen(viewModel: MainViewModel, nav: NavHostController, estimateId: String?) {
    val editing = estimateId != null
    var initialized by remember(estimateId) { mutableStateOf(false) }
    var customerQuery by remember { mutableStateOf("") }
    var selectedCustomer by remember { mutableStateOf<Customer?>(null) }
    var propertyQuery by remember { mutableStateOf("") }
    var selectedProperty by remember { mutableStateOf<PropertyRecord?>(null) }
    var estimateNumber by remember { mutableStateOf("") }
    var title by remember { mutableStateOf("") }
    var projectCategory by remember { mutableStateOf("general-restoration") }
    var recommendedTitle by remember { mutableStateOf("") }
    var summary by remember { mutableStateOf("") }
    var duration by remember { mutableStateOf("") }
    var outcomes by remember { mutableStateOf<List<ProjectOutcome>>(emptyList()) }
    var assumptions by remember { mutableStateOf("") }
    var exclusions by remember { mutableStateOf("") }
    var protections by remember { mutableStateOf<List<String>>(emptyList()) }
    var upgrades by remember { mutableStateOf<List<String>>(emptyList()) }
    var customerNotes by remember { mutableStateOf("") }
    var terms by remember { mutableStateOf("") }
    var depositType by remember { mutableStateOf("PERCENT") }
    var depositPercent by remember { mutableStateOf("50") }
    var depositFixed by remember { mutableStateOf("0.00") }
    var depositStage by remember { mutableStateOf("AFTER_AUTHORIZATION") }
    var catalogQuery by remember { mutableStateOf("") }
    var selectedSectionIndex by remember { mutableIntStateOf(0) }
    var showCustom by remember { mutableStateOf(false) }
    var showNewCustomer by remember { mutableStateOf(false) }
    var showNewProperty by remember { mutableStateOf(false) }
    var categoryMenu by remember { mutableStateOf(false) }
    val sections = remember(estimateId) { mutableStateListOf<SectionDraft>() }
    val scroll = rememberScrollState()

    LaunchedEffect(estimateId) {
        viewModel.loadProjectPlans()
        if (estimateId != null) viewModel.loadEstimate(estimateId) else viewModel.loadCustomers()
    }
    LaunchedEffect(viewModel.estimateDetail, estimateId) {
        val detail = viewModel.estimateDetail
        if (!initialized && estimateId != null && detail?.estimate?.id == estimateId) {
            val e = detail.estimate
            selectedCustomer = detail.customer
            selectedProperty = detail.property
            estimateNumber = e.estimateNumber.orEmpty()
            title = e.title.orEmpty()
            projectCategory = e.projectCategory ?: "general-restoration"
            recommendedTitle = e.recommendedProjectTitle.orEmpty()
            summary = e.projectSummary.orEmpty()
            duration = e.estimatedDuration.orEmpty()
            outcomes = e.projectOutcomes
            assumptions = e.assumptions.orEmpty()
            exclusions = e.exclusions.orEmpty()
            protections = e.protections
            upgrades = e.optionalUpgrades
            customerNotes = e.customerNotes.orEmpty()
            terms = e.terms.orEmpty()
            depositType = e.depositType
            depositPercent = e.depositPercent.toString()
            depositFixed = "%.2f".format(e.depositFixedCents / 100.0)
            depositStage = e.depositDueStage
            sections.clear(); sections.addAll(estimateSections(e))
            initialized = true
        }
    }
    LaunchedEffect(Unit) { if (!editing && sections.isEmpty()) sections.add(SectionDraft(title = "Scope of Work")) }

    fun applyPlan(plan: ProjectPlan) {
        projectCategory = plan.key
        recommendedTitle = plan.title
        if (title.isBlank()) title = plan.title
        summary = plan.summary
        duration = plan.estimatedDuration
        outcomes = plan.outcomes
        assumptions = plan.assumptions.joinToString("\n") { "- $it" }
        exclusions = plan.exclusions.joinToString("\n") { "- $it" }
        protections = plan.protections
        upgrades = plan.options
    }

    ScreenContainer(if (editing) "Edit estimate" else "Create estimate") {
        if (editing && !initialized) { LinearProgressIndicator(Modifier.fillMaxWidth()); return@ScreenContainer }
        Column(Modifier.fillMaxSize().verticalScroll(scroll), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("1. Customer and property", fontWeight = FontWeight.Bold)
            if (editing) {
                DetailPair("Customer", selectedCustomer?.displayName().orEmpty(), "Service property", selectedProperty?.displayName().orEmpty())
            } else {
                SearchField(customerQuery, { customerQuery = it }, { viewModel.loadCustomers(customerQuery) }, "Search customer")
                selectedCustomer?.let { AssistChip(onClick = {}, label = { Text(it.displayName()) }, leadingIcon = { Icon(Icons.Default.Check, null) }) }
                if (selectedCustomer == null) viewModel.customers.take(8).forEach { c ->
                    TextButton(onClick = { selectedCustomer = c; selectedProperty = null; viewModel.loadProperties(c.id) }, Modifier.fillMaxWidth()) { Text(c.displayName()) }
                }
                OutlinedButton(onClick = { showNewCustomer = true }, Modifier.fillMaxWidth()) { Icon(Icons.Default.PersonAdd, null); Text(" Create new customer") }
                SearchField(propertyQuery, { propertyQuery = it }, { selectedCustomer?.let { viewModel.loadProperties(it.id, propertyQuery) } }, "Search this customer's properties")
                selectedProperty?.let { AssistChip(onClick = {}, label = { Text(it.displayName()) }, leadingIcon = { Icon(Icons.Default.Check, null) }) }
                if (selectedCustomer != null && selectedProperty == null) viewModel.properties.take(8).forEach { prop ->
                    TextButton(onClick = { selectedProperty = prop }, Modifier.fillMaxWidth()) { Text("${prop.displayName()} · ${prop.serviceStreet.orEmpty()}") }
                }
                OutlinedButton(onClick = { if (selectedCustomer != null) showNewProperty = true }, Modifier.fillMaxWidth(), enabled = selectedCustomer != null) { Icon(Icons.Default.Add, null); Text(" Create new property") }
            }

            Text("2. Recommended project plan", fontWeight = FontWeight.Bold)
            Box {
                OutlinedButton(onClick = { categoryMenu = true }, Modifier.fillMaxWidth()) {
                    Text(viewModel.projectPlans.firstOrNull { it.key == projectCategory }?.label ?: projectCategory.replace('-', ' ').replaceFirstChar(Char::uppercase), Modifier.weight(1f))
                    Icon(Icons.Default.ArrowDropDown, null)
                }
                DropdownMenu(categoryMenu, { categoryMenu = false }) {
                    viewModel.projectPlans.forEach { option -> DropdownMenuItem(text = { Text(option.label) }, onClick = {
                        categoryMenu = false
                        viewModel.projectPlan(option.key, ::applyPlan)
                    }) }
                }
            }
            OutlinedTextField(recommendedTitle, { recommendedTitle = it }, Modifier.fillMaxWidth(), label = { Text("Recommended project title") })
            OutlinedTextField(estimateNumber, { estimateNumber = it }, Modifier.fillMaxWidth(), label = { Text("Estimate number (blank = automatic)") })
            OutlinedTextField(title, { title = it }, Modifier.fillMaxWidth(), label = { Text("Estimate title") })
            OutlinedTextField(summary, { summary = it }, Modifier.fillMaxWidth(), minLines = 3, label = { Text("Recommended project summary") })
            OutlinedTextField(duration, { duration = it }, Modifier.fillMaxWidth(), label = { Text("Estimated duration") })
            if (outcomes.isNotEmpty()) Card { Column(Modifier.padding(12.dp)) { Text("What this plan accomplishes", fontWeight = FontWeight.Bold); outcomes.forEach { Text("• ${it.title}: ${it.description}") } } }
            OutlinedTextField(assumptions, { assumptions = it }, Modifier.fillMaxWidth(), minLines = 3, label = { Text("Project assumptions") })
            OutlinedTextField(exclusions, { exclusions = it }, Modifier.fillMaxWidth(), minLines = 3, label = { Text("Not included unless listed") })
            OutlinedTextField(customerNotes, { customerNotes = it }, Modifier.fillMaxWidth(), minLines = 2, label = { Text("Customer-facing notes") })
            OutlinedTextField(terms, { terms = it }, Modifier.fillMaxWidth(), minLines = 2, label = { Text("Terms") })

            Text("3. Deposit plan", fontWeight = FontWeight.Bold)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf("NONE", "PERCENT", "FIXED").forEach { choice -> FilterChip(selected = depositType == choice, onClick = { depositType = choice }, label = { Text(choice.lowercase().replaceFirstChar(Char::uppercase)) }) }
            }
            if (depositType == "PERCENT") OutlinedTextField(depositPercent, { depositPercent = it }, Modifier.fillMaxWidth(), label = { Text("Deposit percentage") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
            if (depositType == "FIXED") OutlinedTextField(depositFixed, { depositFixed = it }, Modifier.fillMaxWidth(), label = { Text("Fixed deposit amount") }, prefix = { Text("$") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                FilterChip(selected = depositStage == "AFTER_AUTHORIZATION", onClick = { depositStage = "AFTER_AUTHORIZATION" }, label = { Text("After authorization") })
                FilterChip(selected = depositStage == "IMMEDIATELY", onClick = { depositStage = "IMMEDIATELY" }, label = { Text("When sent") })
            }

            Text("4. Headers and line items", fontWeight = FontWeight.Bold)
            sections.forEachIndexed { index, section ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text("Header ${index + 1}", Modifier.weight(1f), fontWeight = FontWeight.Bold)
                            IconButton(onClick = { if (index > 0) { val moved = sections.removeAt(index); sections.add(index - 1, moved) } }, enabled = index > 0) { Icon(Icons.Default.ArrowUpward, "Move up") }
                            IconButton(onClick = { if (index < sections.lastIndex) { val moved = sections.removeAt(index); sections.add(index + 1, moved) } }, enabled = index < sections.lastIndex) { Icon(Icons.Default.ArrowDownward, "Move down") }
                            IconButton(onClick = { if (sections.size > 1) sections.removeAt(index) }, enabled = sections.size > 1) { Icon(Icons.Default.Delete, "Remove header") }
                        }
                        OutlinedTextField(section.title, { section.title = it }, Modifier.fillMaxWidth(), label = { Text("Header name") })
                        OutlinedTextField(section.description, { section.description = it }, Modifier.fillMaxWidth(), minLines = 2, label = { Text("Header description") })
                        section.lines.forEachIndexed { lineIndex, line ->
                            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                                Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                    Row(verticalAlignment = Alignment.CenterVertically) { Text("Line ${lineIndex + 1}", Modifier.weight(1f), fontWeight = FontWeight.Bold); IconButton(onClick = { section.lines.removeAt(lineIndex) }) { Icon(Icons.Default.Delete, "Remove line") } }
                                    OutlinedTextField(line.name, { line.name = it }, Modifier.fillMaxWidth(), label = { Text("Line item") })
                                    OutlinedTextField(line.description, { line.description = it }, Modifier.fillMaxWidth(), minLines = 2, label = { Text("Description") })
                                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                        OutlinedTextField(line.quantity, { line.quantity = it }, Modifier.weight(1f), label = { Text("Qty") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
                                        OutlinedTextField(line.unit, { line.unit = it }, Modifier.weight(1f), label = { Text("Unit") })
                                        OutlinedTextField(line.unitPrice, { line.unitPrice = it }, Modifier.weight(1f), label = { Text("Price") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
                                    }
                                    Row(verticalAlignment = Alignment.CenterVertically) { Checkbox(line.taxable, { line.taxable = it }); Text("Taxable") }
                                }
                            }
                        }
                        FilledTonalButton(onClick = { selectedSectionIndex = index; viewModel.loadCatalog(catalogQuery) }) { Text("Add catalog item to this header") }
                    }
                }
            }
            OutlinedButton(onClick = { sections.add(SectionDraft(title = "New header")); selectedSectionIndex = sections.lastIndex }, Modifier.fillMaxWidth()) { Icon(Icons.Default.Add, null); Text(" Add header") }
            SearchField(catalogQuery, { catalogQuery = it }, { viewModel.loadCatalog(catalogQuery) }, "Search reusable line-item catalog")
            viewModel.catalog.take(12).forEach { item -> TextButton(onClick = {
                val section = sections.getOrNull(selectedSectionIndex) ?: sections.first()
                section.lines.add(LineDraft(catalogItemId = item.id, name = item.name, description = item.description.orEmpty(), category = item.category ?: "General Services", unit = item.unit ?: "each", unitPrice = "%.2f".format(item.unitPriceCents / 100.0)))
            }, Modifier.fillMaxWidth()) { Text("${item.name} · ${money(item.unitPriceCents)}") } }
            OutlinedButton(onClick = { showCustom = true }, Modifier.fillMaxWidth()) { Text("Add custom line and save to catalog") }

            Button(onClick = {
                val customer = selectedCustomer ?: return@Button
                val prop = selectedProperty ?: return@Button
                val input = EstimateCreateInput(
                    contactId = customer.id, propertyId = prop.id, estimateNumber = estimateNumber.trim(), title = title.trim(), projectCategory = projectCategory,
                    recommendedProjectTitle = recommendedTitle.trim(), projectSummary = summary.trim(), estimatedDuration = duration.trim(),
                    projectOutcomes = outcomes, assumptions = assumptions.trim(), exclusions = exclusions.trim(), protections = protections,
                    optionalUpgrades = upgrades, customerNotes = customerNotes.trim(), terms = terms.trim(), depositType = depositType,
                    depositPercent = depositPercent.toDoubleOrNull() ?: 50.0, depositFixedCents = ((depositFixed.toDoubleOrNull() ?: 0.0) * 100).toLong(),
                    depositDueStage = depositStage, sections = sections.toInputs(),
                )
                if (estimateId == null) viewModel.createEstimate(input) { id -> nav.navigate("estimate/$id") { popUpTo("estimate-new") { inclusive = true } } }
                else viewModel.updateEstimate(estimateId, input) { nav.popBackStack() }
            }, Modifier.fillMaxWidth(), enabled = selectedCustomer != null && selectedProperty != null && title.isNotBlank() && sections.any { it.lines.isNotEmpty() }) { Text(if (editing) "Save estimate changes" else "Save draft estimate") }
        }
        if (showCustom) CustomLineDialog(onDismiss = { showCustom = false }) { line -> sections.getOrNull(selectedSectionIndex)?.lines?.add(line); showCustom = false }
        if (showNewCustomer) CreateCustomerDialog(onDismiss = { showNewCustomer = false }) { input -> viewModel.createCustomer(input) { created -> selectedCustomer = created; selectedProperty = null; customerQuery = created.displayName(); viewModel.loadProperties(created.id); showNewCustomer = false } }
        if (showNewProperty) selectedCustomer?.let { customer -> CreatePropertyDialog(customer, onDismiss = { showNewProperty = false }) { input -> viewModel.createProperty(input) { created -> selectedProperty = created; propertyQuery = created.displayName(); showNewProperty = false } } }
    }
}

@Composable
private fun CustomLineDialog(onDismiss: () -> Unit, onSave: (LineDraft) -> Unit) {
    var name by remember { mutableStateOf("") }; var description by remember { mutableStateOf("") }; var quantity by remember { mutableStateOf("1") }; var unit by remember { mutableStateOf("each") }; var price by remember { mutableStateOf("0.00") }
    AlertDialog(onDismissRequest = onDismiss, title = { Text("Custom line item") }, text = { Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedTextField(name, { name = it }, label = { Text("Name") }); OutlinedTextField(description, { description = it }, label = { Text("Description") }); OutlinedTextField(quantity, { quantity = it }, label = { Text("Quantity") }); OutlinedTextField(unit, { unit = it }, label = { Text("Unit") }); OutlinedTextField(price, { price = it }, label = { Text("Unit price") })
    } }, confirmButton = { Button(onClick = { onSave(LineDraft(name = name, description = description, quantity = quantity, unit = unit, unitPrice = price, saveToCatalog = true)) }, enabled = name.isNotBlank()) { Text("Add & save") } }, dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } })
}

@Composable
private fun CreateCustomerDialog(onDismiss: () -> Unit, onCreate: (CustomerCreateInput) -> Unit) {
    var first by remember { mutableStateOf("") }
    var last by remember { mutableStateOf("") }
    var company by remember { mutableStateOf("") }
    var email by remember { mutableStateOf("") }
    var phone by remember { mutableStateOf("") }
    var street by remember { mutableStateOf("") }
    var city by remember { mutableStateOf("") }
    var state by remember { mutableStateOf("MI") }
    var postal by remember { mutableStateOf("") }
    var note by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("New customer") },
        text = {
            Column(
                Modifier.heightIn(max = 560.dp).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedTextField(first, { first = it }, Modifier.fillMaxWidth(), label = { Text("First name") })
                OutlinedTextField(last, { last = it }, Modifier.fillMaxWidth(), label = { Text("Last name") })
                OutlinedTextField(company, { company = it }, Modifier.fillMaxWidth(), label = { Text("Company, optional") })
                OutlinedTextField(email, { email = it }, Modifier.fillMaxWidth(), label = { Text("Email") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email))
                OutlinedTextField(phone, { phone = it }, Modifier.fillMaxWidth(), label = { Text("Phone") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone))
                OutlinedTextField(street, { street = it }, Modifier.fillMaxWidth(), label = { Text("Mailing street") })
                OutlinedTextField(city, { city = it }, Modifier.fillMaxWidth(), label = { Text("Mailing city") })
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(state, { state = it }, Modifier.weight(1f), label = { Text("State") })
                    OutlinedTextField(postal, { postal = it }, Modifier.weight(1f), label = { Text("ZIP") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
                }
                OutlinedTextField(note, { note = it }, Modifier.fillMaxWidth(), minLines = 2, label = { Text("Initial note") })
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    onCreate(
                        CustomerCreateInput(
                            firstName = first.trim(), lastName = last.trim(), company = company.trim(),
                            email = email.trim(), phone = phone.trim(), mailingStreet = street.trim(),
                            mailingCity = city.trim(), mailingState = state.trim().ifBlank { "MI" },
                            mailingPostalCode = postal.trim(), initialNote = note.trim(),
                        )
                    )
                },
                enabled = first.isNotBlank() || last.isNotBlank() || company.isNotBlank(),
            ) { Text("Create customer") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun CreatePropertyDialog(customer: Customer, onDismiss: () -> Unit, onCreate: (PropertyCreateInput) -> Unit) {
    var name by remember { mutableStateOf("") }
    var type by remember { mutableStateOf("") }
    var street by remember { mutableStateOf("") }
    var city by remember { mutableStateOf("") }
    var state by remember { mutableStateOf("MI") }
    var postal by remember { mutableStateOf("") }
    var insurer by remember { mutableStateOf("") }
    var claim by remember { mutableStateOf("") }
    var notes by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("New service property") },
        text = {
            Column(
                Modifier.heightIn(max = 560.dp).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text("Customer: ${customer.displayName()}", fontWeight = FontWeight.Bold)
                OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(), label = { Text("Property name, optional") })
                OutlinedTextField(type, { type = it }, Modifier.fillMaxWidth(), label = { Text("Property type") })
                OutlinedTextField(street, { street = it }, Modifier.fillMaxWidth(), label = { Text("Service street") })
                OutlinedTextField(city, { city = it }, Modifier.fillMaxWidth(), label = { Text("Service city") })
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(state, { state = it }, Modifier.weight(1f), label = { Text("State") })
                    OutlinedTextField(postal, { postal = it }, Modifier.weight(1f), label = { Text("ZIP") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
                }
                OutlinedTextField(insurer, { insurer = it }, Modifier.fillMaxWidth(), label = { Text("Insurance company, optional") })
                OutlinedTextField(claim, { claim = it }, Modifier.fillMaxWidth(), label = { Text("Claim number, optional") })
                OutlinedTextField(notes, { notes = it }, Modifier.fillMaxWidth(), minLines = 2, label = { Text("Property or job notes") })
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    onCreate(
                        PropertyCreateInput(
                            contactId = customer.id, propertyName = name.trim(), propertyType = type.trim(),
                            serviceStreet = street.trim(), serviceCity = city.trim(),
                            serviceState = state.trim().ifBlank { "MI" }, servicePostalCode = postal.trim(),
                            insuranceCompany = insurer.trim(), claimNumber = claim.trim(), notes = notes.trim(),
                        )
                    )
                },
                enabled = street.isNotBlank() && city.isNotBlank(),
            ) { Text("Create property") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun PaymentDialog(
    viewModel: MainViewModel,
    targetKind: String,
    targetId: String,
    maximumCents: Long,
    startCardEntry: () -> Unit,
    onDismiss: () -> Unit,
) {
    val methods = listOf(
        "CARD_BY_PHONE" to "Card by phone",
        "CASH" to "Cash",
        "CHECK" to "Check",
        "ACH" to "Bank transfer / ACH",
        "EXTERNAL_CARD" to "Card processed elsewhere",
        "OTHER" to "Other",
    )
    var amount by remember { mutableStateOf("%.2f".format(maximumCents / 100.0)) }
    var method by remember { mutableStateOf(methods.first()) }
    var menuOpen by remember { mutableStateOf(false) }
    var reference by remember { mutableStateOf("") }
    var note by remember { mutableStateOf("") }
    var checkDate by remember { mutableStateOf("") }
    var bankName by remember { mutableStateOf("") }
    var checkStatus by remember { mutableStateOf("RECEIVED") }
    var saveCard by remember { mutableStateOf(false) }
    var authorization by remember { mutableStateOf("") }
    val cents = ((amount.toDoubleOrNull() ?: 0.0) * 100).toLong()
    val validAmount = cents in 1..maximumCents
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (targetKind == "estimate") "Take deposit" else "Take payment") },
        text = {
            Column(
                Modifier.heightIn(max = 580.dp).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Text("Balance available: ${money(maximumCents)}")
                OutlinedTextField(
                    amount, { amount = it }, Modifier.fillMaxWidth(),
                    label = { Text("Amount") }, prefix = { Text("$") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    isError = cents > maximumCents,
                )
                Box {
                    OutlinedButton(onClick = { menuOpen = true }, Modifier.fillMaxWidth()) {
                        Text(method.second, Modifier.weight(1f))
                        Icon(Icons.Default.ArrowDropDown, null)
                    }
                    DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                        methods.forEach { choice ->
                            DropdownMenuItem(text = { Text(choice.second) }, onClick = { method = choice; menuOpen = false })
                        }
                    }
                }
                if (method.first == "CARD_BY_PHONE") {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(saveCard, { saveCard = it })
                        Text("Save payment method for future separately authorized charges")
                    }
                    if (saveCard) {
                        OutlinedTextField(
                            authorization, { authorization = it }, Modifier.fillMaxWidth(),
                            label = { Text("Authorization reference") },
                            supportingText = { Text("Example: signed authorization, written email, or recorded customer request") },
                        )
                    }
                } else {
                    OutlinedTextField(reference, { reference = it }, Modifier.fillMaxWidth(), label = { Text(if (method.first == "CHECK") "Check number" else "Reference") })
                    if (method.first == "CHECK") {
                        OutlinedTextField(checkDate, { checkDate = it }, Modifier.fillMaxWidth(), label = { Text("Check date (YYYY-MM-DD)") })
                        OutlinedTextField(bankName, { bankName = it }, Modifier.fillMaxWidth(), label = { Text("Bank, optional") })
                        val statuses = listOf("RECEIVED", "DEPOSITED", "CLEARED", "RETURNED")
                        Text("Check status", style = MaterialTheme.typography.labelMedium)
                        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                            statuses.forEach { status ->
                                FilterChip(selected = checkStatus == status, onClick = { checkStatus = status }, label = { Text(status.lowercase().replaceFirstChar(Char::uppercase)) })
                            }
                        }
                    }
                }
                OutlinedTextField(note, { note = it }, Modifier.fillMaxWidth(), minLines = 2, label = { Text("Payment note") })
                Text(
                    "Floodman never stores a full card number or card security code. Card entry is handled by the secure processor SDK.",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    if (method.first == "CARD_BY_PHONE") {
                        PaymentCoordinator.prepare(
                            PendingCardPayment(
                                targetKind = targetKind, targetId = targetId, amountCents = cents,
                                saveCard = saveCard, authorizationReference = authorization.trim(), note = note.trim(),
                            )
                        )
                        onDismiss()
                        startCardEntry()
                    } else {
                        viewModel.recordManualPayment(
                            ManualPaymentInput(
                                targetKind = targetKind, targetId = targetId, amountCents = cents,
                                method = method.first, reference = reference.trim(), note = note.trim(),
                                checkDate = checkDate.trim(), bankName = bankName.trim(), checkStatus = checkStatus,
                            ),
                            onComplete = onDismiss,
                        )
                    }
                },
                enabled = validAmount && (method.first != "CARD_BY_PHONE" || !saveCard || authorization.isNotBlank()),
            ) { Text(if (method.first == "CARD_BY_PHONE") "Enter card" else "Record payment") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun RoomFlowJobsScreen(viewModel: MainViewModel) {
    var query by remember { mutableStateOf("") }
    val context = LocalContext.current
    LaunchedEffect(Unit) { viewModel.loadRoomFlowJobs() }
    ScreenContainer("Floodman RoomFlow") {
        Card { Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Four-step field workflow", fontWeight = FontWeight.Bold)
            Text("1. Choose the customer  •  2. Choose the service property")
            Text("3. Sketch and add priced services  •  4. Save the draft")
            Text("Your Floodman sign-in and company workspace are already connected. No separate RoomFlow account is needed.", style = MaterialTheme.typography.bodySmall)
        } }
        Button(onClick = { context.startActivity(RoomFlowActivity.intent(context)) }, Modifier.fillMaxWidth()) {
            Icon(Icons.Default.Add, null); Spacer(Modifier.width(8.dp)); Text("Start a new RoomFlow job")
        }
        SearchField(query, { query = it }, { viewModel.loadRoomFlowJobs(query) }, "Customer, property, job, or estimate")
        Card { Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Text("Complete field-estimating workspace", fontWeight = FontWeight.Bold)
            Text("The app includes the full RoomFlow engine: guided workflow, 2D sketch, custom shapes, camera/AR measurement tools, 3D review, scope, materials, costing, proposal tools, and actual-layout synchronization.")
        } }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(viewModel.roomFlowJobs, key = { it.id }) { job ->
                Card(Modifier.fillMaxWidth().clickable { context.startActivity(RoomFlowActivity.intent(context, job.id)) }) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                        Text(job.jobName ?: job.name ?: "RoomFlow job", fontWeight = FontWeight.Bold)
                        Text(job.customerName.orEmpty())
                        Text(job.propertyAddress.orEmpty())
                        Text(listOfNotNull(job.status, job.estimateNumber).filter { it.isNotBlank() }.joinToString(" · "), style = MaterialTheme.typography.labelMedium)
                        Text("Open full RoomFlow workspace", color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.SemiBold)
                    }
                }
            }
        }
    }
}

@Composable
private fun TimeClockScreen(viewModel: MainViewModel) {
    var jobReference by remember { mutableStateOf("") }
    var note by remember { mutableStateOf("") }
    LaunchedEffect(Unit) { viewModel.refreshHome() }
    ScreenContainer("Time clock") {
        val entry = viewModel.timeEntry
        Card {
            Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(if (entry == null) "Not clocked in" else "Clocked in", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                entry?.let {
                    Text("Job: ${it.jobReference.orEmpty()}")
                    Text("Started: ${it.clockIn.orEmpty()}")
                    if (!it.note.isNullOrBlank()) Text(it.note)
                }
            }
        }
        if (entry == null) {
            OutlinedTextField(jobReference, { jobReference = it }, Modifier.fillMaxWidth(), label = { Text("Job or property reference") })
            OutlinedTextField(note, { note = it }, Modifier.fillMaxWidth(), minLines = 2, label = { Text("Start note") })
            Button(onClick = { viewModel.clockIn(jobReference.trim(), note.trim()) }, Modifier.fillMaxWidth()) { Icon(Icons.Default.PlayArrow, null); Text(" Clock in") }
        } else {
            OutlinedTextField(note, { note = it }, Modifier.fillMaxWidth(), minLines = 2, label = { Text("Completion note") })
            Button(onClick = { viewModel.clockOut(note.trim()) }, Modifier.fillMaxWidth(), colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)) { Icon(Icons.Default.Stop, null); Text(" Clock out") }
        }
    }
}

private fun displayDateTime(value: String): String = runCatching {
    OffsetDateTime.parse(value).atZoneSameInstant(ZoneId.of("America/Detroit")).format(DateTimeFormatter.ofPattern("EEE, MMM d · h:mm a"))
}.getOrDefault(value)

@Composable
private fun CalendarScreen(viewModel: MainViewModel) {
    var showCreate by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<Appointment?>(null) }
    var employeeFilter by remember { mutableStateOf("") }
    LaunchedEffect(Unit) {
        viewModel.loadCalendar()
        viewModel.loadEmployees()
        viewModel.loadCustomers()
    }
    ScreenContainer(
        "Calendar",
        action = {
            FilledTonalButton(onClick = { showCreate = true }) {
                Icon(Icons.Default.Add, null)
                Text(" Book")
            }
        },
    ) {
        if (viewModel.employees.isNotEmpty()) {
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                FilterChip(
                    selected = employeeFilter.isBlank(),
                    onClick = { employeeFilter = ""; viewModel.loadCalendar() },
                    label = { Text("Everyone") },
                )
                viewModel.employees.forEach { employee ->
                    FilterChip(
                        selected = employeeFilter == employee.id,
                        onClick = { employeeFilter = employee.id; viewModel.loadCalendar(employeeId = employee.id) },
                        label = { Text(employee.name ?: employee.email ?: "Employee") },
                    )
                }
            }
        }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(viewModel.appointments, key = { it.id }) { appointment ->
                Card(onClick = { editing = appointment }, modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Row {
                            Text(appointment.title, Modifier.weight(1f), fontWeight = FontWeight.Bold)
                            Text(appointment.status.replace('_', ' '), style = MaterialTheme.typography.labelMedium)
                        }
                        Text("${appointment.appointmentType.replace('_', ' ')} · ${displayDateTime(appointment.startAt)}")
                        if (!appointment.location.isNullOrBlank()) Text(appointment.location)
                        val names = appointment.assignedUserIds.mapNotNull { id -> viewModel.employees.firstOrNull { it.id == id }?.name }
                        if (names.isNotEmpty()) Text("Assigned: ${names.joinToString()}", style = MaterialTheme.typography.bodySmall)
                        Text("Tap to edit", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.secondary)
                    }
                }
            }
        }
        if (showCreate) {
            AppointmentDialog(
                viewModel = viewModel,
                appointment = null,
                onDismiss = { showCreate = false },
                onDelete = null,
                onSave = { input -> viewModel.createAppointment(input) { showCreate = false } },
            )
        }
        editing?.let { appointment ->
            AppointmentDialog(
                viewModel = viewModel,
                appointment = appointment,
                onDismiss = { editing = null },
                onDelete = { viewModel.deleteAppointment(appointment.id); editing = null },
                onSave = { input -> viewModel.updateAppointment(appointment.id, input) { editing = null } },
            )
        }
    }
}

private fun localAppointmentDate(value: String): LocalDateTime = runCatching {
    OffsetDateTime.parse(value).atZoneSameInstant(ZoneId.of("America/Detroit")).toLocalDateTime()
}.getOrElse { LocalDateTime.now().plusDays(1).withHour(9).withMinute(0).withSecond(0).withNano(0) }

@Composable
private fun AppointmentDialog(
    viewModel: MainViewModel,
    appointment: Appointment?,
    onDismiss: () -> Unit,
    onDelete: (() -> Unit)?,
    onSave: (AppointmentInput) -> Unit,
) {
    val initialStart = remember(appointment?.id) { appointment?.let { localAppointmentDate(it.startAt) } ?: LocalDateTime.now().plusDays(1).withHour(9).withMinute(0).withSecond(0).withNano(0) }
    val initialEnd = remember(appointment?.id) { appointment?.let { localAppointmentDate(it.endAt) } ?: initialStart.plusHours(2) }
    var title by remember(appointment?.id) { mutableStateOf(appointment?.title.orEmpty()) }
    var type by remember(appointment?.id) { mutableStateOf(appointment?.appointmentType ?: "JOB") }
    var status by remember(appointment?.id) { mutableStateOf(appointment?.status ?: "SCHEDULED") }
    var date by remember(appointment?.id) { mutableStateOf(initialStart.format(DateTimeFormatter.ISO_LOCAL_DATE)) }
    var startTime by remember(appointment?.id) { mutableStateOf(initialStart.format(DateTimeFormatter.ofPattern("HH:mm"))) }
    var endTime by remember(appointment?.id) { mutableStateOf(initialEnd.format(DateTimeFormatter.ofPattern("HH:mm"))) }
    var customerQuery by remember { mutableStateOf("") }
    var selectedCustomer by remember(appointment?.id) { mutableStateOf<Customer?>(null) }
    var selectedProperty by remember(appointment?.id) { mutableStateOf<PropertyRecord?>(null) }
    var location by remember(appointment?.id) { mutableStateOf(appointment?.location.orEmpty()) }
    var internalNotes by remember(appointment?.id) { mutableStateOf(appointment?.internalNotes.orEmpty()) }
    var customerNotes by remember(appointment?.id) { mutableStateOf(appointment?.customerNotes.orEmpty()) }
    var overrideConflicts by remember { mutableStateOf(false) }
    var validationError by remember { mutableStateOf<String?>(null) }
    val assigned = remember(appointment?.id) { mutableStateListOf<String>().also { it.addAll(appointment?.assignedUserIds.orEmpty()) } }
    var lead by remember(appointment?.id) { mutableStateOf(appointment?.leadUserId) }

    LaunchedEffect(appointment?.contactId, viewModel.customers) {
        if (selectedCustomer == null && !appointment?.contactId.isNullOrBlank()) {
            selectedCustomer = viewModel.customers.firstOrNull { it.id == appointment.contactId }
            selectedCustomer?.let { viewModel.loadProperties(it.id) }
        }
    }
    LaunchedEffect(appointment?.propertyId, viewModel.properties) {
        if (selectedProperty == null && !appointment?.propertyId.isNullOrBlank()) {
            selectedProperty = viewModel.properties.firstOrNull { it.id == appointment.propertyId }
        }
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (appointment == null) "Book job or inspection" else "Edit appointment") },
        text = {
            Column(Modifier.heightIn(max = 640.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                validationError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                OutlinedTextField(title, { title = it }, Modifier.fillMaxWidth(), label = { Text("Title") })
                Text("Type", fontWeight = FontWeight.Bold)
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    listOf("JOB", "INSPECTION", "ESTIMATE_APPOINTMENT", "FOLLOW_UP", "DELIVERY", "TRAINING", "MEETING").forEach { value ->
                        FilterChip(
                            selected = type == value,
                            onClick = { type = value },
                            label = { Text(value.replace('_', ' ').lowercase().replaceFirstChar(Char::uppercase)) },
                        )
                    }
                }
                Text("Status", fontWeight = FontWeight.Bold)
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    listOf("SCHEDULED", "CONFIRMED", "EN_ROUTE", "IN_PROGRESS", "COMPLETED", "CANCELED", "NO_SHOW").forEach { value ->
                        FilterChip(
                            selected = status == value,
                            onClick = { status = value },
                            label = { Text(value.replace('_', ' ').lowercase().replaceFirstChar(Char::uppercase)) },
                        )
                    }
                }
                OutlinedTextField(date, { date = it }, Modifier.fillMaxWidth(), label = { Text("Date (YYYY-MM-DD)") })
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(startTime, { startTime = it }, Modifier.weight(1f), label = { Text("Start (HH:MM)") })
                    OutlinedTextField(endTime, { endTime = it }, Modifier.weight(1f), label = { Text("End (HH:MM)") })
                }
                SearchField(customerQuery, { customerQuery = it }, { viewModel.loadCustomers(customerQuery) }, "Search customer")
                selectedCustomer?.let { customer ->
                    AssistChip(onClick = { selectedCustomer = null; selectedProperty = null }, label = { Text(customer.displayName()) }, trailingIcon = { Icon(Icons.Default.Close, null) })
                }
                if (selectedCustomer == null) {
                    viewModel.customers.take(6).forEach { customer ->
                        TextButton(
                            onClick = { selectedCustomer = customer; selectedProperty = null; viewModel.loadProperties(customer.id) },
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text(customer.displayName()) }
                    }
                }
                selectedCustomer?.let {
                    Text("Service property", fontWeight = FontWeight.Bold)
                    viewModel.properties.take(8).forEach { prop ->
                        FilterChip(
                            selected = selectedProperty?.id == prop.id,
                            onClick = {
                                selectedProperty = prop
                                location = listOfNotNull(prop.serviceStreet, prop.serviceCity, prop.serviceState, prop.servicePostalCode).filter { value -> value.isNotBlank() }.joinToString(", ")
                            },
                            label = { Text(prop.displayName()) },
                        )
                    }
                }
                OutlinedTextField(location, { location = it }, Modifier.fillMaxWidth(), label = { Text("Location") })
                Text("Assign employees", fontWeight = FontWeight.Bold)
                viewModel.employees.forEach { employee ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(
                            checked = employee.id in assigned,
                            onCheckedChange = { checked -> if (checked) { if (employee.id !in assigned) assigned.add(employee.id) } else assigned.remove(employee.id) },
                        )
                        Column(Modifier.weight(1f)) {
                            Text(employee.name ?: employee.email.orEmpty())
                            Text(employee.role.orEmpty(), style = MaterialTheme.typography.labelSmall)
                        }
                        RadioButton(selected = lead == employee.id, onClick = { lead = employee.id; if (employee.id !in assigned) assigned.add(employee.id) })
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(overrideConflicts, { overrideConflicts = it })
                    Text("Allow authorized conflict override")
                }
                OutlinedTextField(internalNotes, { internalNotes = it }, Modifier.fillMaxWidth(), minLines = 2, label = { Text("Internal notes") })
                OutlinedTextField(customerNotes, { customerNotes = it }, Modifier.fillMaxWidth(), minLines = 2, label = { Text("Customer notes") })
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    val parsed = runCatching {
                        val zone = ZoneId.of("America/Detroit")
                        val start = LocalDateTime.parse("${date}T${startTime}").atZone(zone).toOffsetDateTime().toString()
                        val end = LocalDateTime.parse("${date}T${endTime}").atZone(zone).toOffsetDateTime().toString()
                        require(OffsetDateTime.parse(end).isAfter(OffsetDateTime.parse(start))) { "End time must be after start time." }
                        AppointmentInput(
                            title = title.trim(), appointmentType = type, status = status, startAt = start, endAt = end,
                            contactId = selectedCustomer?.id, propertyId = selectedProperty?.id,
                            assignedUserIds = assigned.toList(), leadUserId = lead,
                            internalNotes = internalNotes.trim(), customerNotes = customerNotes.trim(),
                            location = location.trim(), overrideConflicts = overrideConflicts,
                        )
                    }
                    parsed.onSuccess { validationError = null; onSave(it) }
                        .onFailure { validationError = it.message ?: "Enter valid appointment dates and times." }
                },
                enabled = title.isNotBlank() && date.isNotBlank() && startTime.isNotBlank() && endTime.isNotBlank(),
            ) { Text(if (appointment == null) "Book appointment" else "Save changes") }
        },
        dismissButton = {
            Row {
                onDelete?.let { delete -> TextButton(onClick = delete, colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error)) { Text("Delete") } }
                TextButton(onClick = onDismiss) { Text("Cancel") }
            }
        },
    )
}

@Composable
private fun TasksScreen(viewModel: MainViewModel) {
    var showCreate by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { viewModel.loadTasks(false); viewModel.loadEmployees() }
    ScreenContainer("Tasks", action={FilledTonalButton(onClick={showCreate=true}){Icon(Icons.Default.Add,null);Text(" New")}}) {
        LazyColumn(verticalArrangement=Arrangement.spacedBy(8.dp)) { items(viewModel.tasks,key={it.id}) { task -> Card { Column(Modifier.padding(16.dp)) { Row{Text(task.title,Modifier.weight(1f),fontWeight=FontWeight.Bold);Text(task.status)};Text(task.description.orEmpty());Text("Priority: ${task.priority} · Due: ${task.dueAt.orEmpty()}",style=MaterialTheme.typography.labelSmall); if(task.status!="COMPLETED") TextButton(onClick={viewModel.updateTask(task.id,TaskInput(task.title,task.description.orEmpty(),"COMPLETED",task.priority,task.dueAt,task.assignedUserId,task.appointmentId,task.contactId,task.propertyId))}){Text("Mark complete")} } } } }
        if(showCreate) TaskDialog(viewModel,{showCreate=false}){input->viewModel.createTask(input){showCreate=false}}
    }
}

@Composable
private fun TaskDialog(viewModel: MainViewModel,onDismiss:()->Unit,onSave:(TaskInput)->Unit){
    var title by remember{mutableStateOf("")};var description by remember{mutableStateOf("")};var due by remember{mutableStateOf("")};var assignee by remember{mutableStateOf<String?>(null)}
    AlertDialog(onDismissRequest=onDismiss,title={Text("New task")},text={Column(verticalArrangement=Arrangement.spacedBy(8.dp)){OutlinedTextField(title,{title=it},Modifier.fillMaxWidth(),label={Text("Title")});OutlinedTextField(description,{description=it},Modifier.fillMaxWidth(),minLines=3,label={Text("Description")});OutlinedTextField(due,{due=it},Modifier.fillMaxWidth(),label={Text("Due ISO date/time, optional")});viewModel.employees.forEach{e->FilterChip(assignee==e.id,{assignee=e.id},{Text(e.name?:e.email.orEmpty())})}}},confirmButton={Button(onClick={onSave(TaskInput(title=title.trim(),description=description.trim(),dueAt=due.trim().ifBlank{null},assignedUserId=assignee))},enabled=title.isNotBlank()){Text("Save")}},dismissButton={TextButton(onClick=onDismiss){Text("Cancel")}})
}

@Composable
private fun DocumentsScreen(viewModel: MainViewModel) {
    val context = LocalContext.current
    LaunchedEffect(Unit) { viewModel.loadDocuments() }
    ScreenContainer("Documents") {
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(viewModel.documents, key = { it.id }) { doc ->
                Card {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(doc.title ?: doc.filename ?: "Document", fontWeight = FontWeight.Bold)
                        Text("${doc.kind.orEmpty()} · ${doc.status.orEmpty()}")
                        Text(doc.completedAt.orEmpty(), style = MaterialTheme.typography.labelSmall)
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedButton(onClick = {
                                viewModel.loadDocumentBytes(doc.id, signed = false) { bytes ->
                                    openFile(context, bytes, doc.filename ?: "floodman-document", doc.mimeType ?: "application/octet-stream")
                                }
                            }) { Text("Open") }
                            if (!doc.signedDownloadUrl.isNullOrBlank() || doc.status.equals("COMPLETED", true) || doc.status.equals("SIGNED", true)) {
                                Button(onClick = {
                                    viewModel.loadDocumentBytes(doc.id, signed = true) { bytes ->
                                        openFile(context, bytes, "signed-${doc.filename ?: "floodman-document.pdf"}", doc.mimeType ?: "application/pdf")
                                    }
                                }) { Text("Open signed") }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun AnnouncementsScreen(viewModel: MainViewModel){
    LaunchedEffect(Unit){viewModel.loadAnnouncements()}
    ScreenContainer("Announcements") { LazyColumn(verticalArrangement=Arrangement.spacedBy(8.dp)){items(viewModel.announcements,key={it.id}){item->Card{Column(Modifier.padding(16.dp)){Text(item.title,fontWeight=FontWeight.Bold);Text(item.body);Text(item.severity,style=MaterialTheme.typography.labelSmall)}}}} }
}

@Composable
private fun NotificationsScreen(viewModel: MainViewModel){
    LaunchedEffect(Unit){viewModel.loadNotifications()}
    ScreenContainer("Notifications") { LazyColumn(verticalArrangement=Arrangement.spacedBy(8.dp)){items(viewModel.notifications,key={it.id}){item->Card(onClick={viewModel.markNotificationRead(item.id)}){Column(Modifier.padding(16.dp)){Row{Text(item.title,Modifier.weight(1f),fontWeight=FontWeight.Bold);Text(item.status)};Text(item.body);Text(item.createdAt.orEmpty(),style=MaterialTheme.typography.labelSmall)}}}} }
}

@Composable
private fun MoreScreen(viewModel: MainViewModel, nav: NavHostController) {
    ScreenContainer("More") {
        val entries = listOf(
            Triple("Billing", "Invoices, balances, and payments", "invoices"),
            Triple("Jobs and inspections", "Scheduled work and inspection assignments", "calendar"),
            Triple("Tasks", "Assigned and company work items", "tasks"),
            Triple("Documents", "Customer documents and signed files", "documents"),
            Triple("Announcements", "Company-wide updates", "announcements"),
            Triple("Notifications", "Appointments, assignments, and workflow alerts", "notifications"),
            Triple("RoomFlow jobs", "Shared field-estimating jobs and mappings", "roomflow"),
            Triple("Time clock", "Clock into and out of assigned work", "time"),
            Triple("App settings", "Appearance, calendar, connection, and device security", "settings"),
        )
        entries.forEach { (title, description, route) ->
            Card(onClick = { nav.navigate(route) }, Modifier.fillMaxWidth()) {
                Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) { Text(title, fontWeight = FontWeight.Bold); Text(description, style = MaterialTheme.typography.bodySmall) }
                    Icon(Icons.Default.ChevronRight, null)
                }
            }
        }
        Card {
            Column(Modifier.padding(16.dp)) {
                Text("Floodman native operations", fontWeight = FontWeight.Bold)
                Text("Customers, properties, estimates, invoices, payments, schedules, employees, tasks, documents, announcements, notifications, RoomFlow jobs, and time tracking use the encrypted Mobile API.")
            }
        }
    }
}

@Composable
private fun SettingsScreen(viewModel: MainViewModel) {
    val context = LocalContext.current
    val config = viewModel.config
    var apiUrl by remember(viewModel.apiBaseUrl) { mutableStateOf(viewModel.apiBaseUrl) }
    var showAdvancedConnection by remember { mutableStateOf(false) }
    ScreenContainer("App settings") {
        Card {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Your Floodman connection", fontWeight = FontWeight.Bold)
                Text("Company: ${config?.company ?: "Floodman"}")
                Text("Business time: Eastern Time (Detroit)")
                Text("Status: Secure mobile connection")
                Text("Android ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})", style = MaterialTheme.typography.bodySmall)
            }
        }
        Card {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Calendar subscription", fontWeight = FontWeight.Bold)
                Text("Create a private read-only feed for Outlook, Apple Calendar, or Google Calendar.", style = MaterialTheme.typography.bodySmall)
                OutlinedButton(
                    onClick = { viewModel.createCalendarSubscription { url -> openUrl(context, url) } },
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Create and open calendar feed") }
            }
        }
        OutlinedButton(onClick = { showAdvancedConnection = !showAdvancedConnection }, Modifier.fillMaxWidth()) {
            Text(if (showAdvancedConnection) "Hide installer connection setting" else "Installer: change server connection")
        }
        if (showAdvancedConnection) {
            Card {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Mobile API address", fontWeight = FontWeight.Bold)
                    Text("Do not change this during normal use. A new address signs this device out so it can verify the new server.", style = MaterialTheme.typography.bodySmall)
                    OutlinedTextField(apiUrl, { apiUrl = it }, Modifier.fillMaxWidth(), label = { Text("Secure HTTPS address ending in /mobile-api") }, singleLine = true)
                    OutlinedButton(onClick = { viewModel.updateApiBaseUrl(apiUrl) }, Modifier.fillMaxWidth(), enabled = apiUrl.trim() != viewModel.apiBaseUrl) { Text("Save new address and sign out") }
                }
            }
        }
        Card {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Appearance", fontWeight = FontWeight.Bold)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("SYSTEM", "LIGHT", "DARK").forEach { choice ->
                        FilterChip(selected = viewModel.appearanceMode == choice, onClick = { viewModel.updateAppearanceMode(choice) }, label = { Text(choice.lowercase().replaceFirstChar(Char::uppercase)) })
                    }
                }
            }
        }
        Card {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Security", fontWeight = FontWeight.Bold)
                Text("Cleartext HTTP is disabled. Session secrets are encrypted with Android Keystore. Refresh requests are signed by this registered device.")
                Text("The Floodman web workspace remains separate from this app and is protected by the company HTTPS access policy.")
            }
        }
        Button(onClick = viewModel::logout, Modifier.fillMaxWidth(), colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)) { Text("Sign out and remove this device session") }
    }
}

private fun openUrl(context: Context, url: String) {
    if (url.isBlank()) return
    runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, url.toUri()).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
}

private fun openPdf(context: Context, bytes: ByteArray, filename: String) =
    openFile(context, bytes, filename, "application/pdf")

private fun openFile(context: Context, bytes: ByteArray, filename: String, mimeType: String) {
    if (bytes.isEmpty()) return
    runCatching {
        val safeName = filename.replace(Regex("[^A-Za-z0-9._-]"), "-")
        val folder = File(context.cacheDir, "shared-files").apply { mkdirs() }
        val file = File(folder, safeName).apply { writeBytes(bytes) }
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
        context.startActivity(Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, mimeType.ifBlank { "application/octet-stream" })
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        })
    }
}
