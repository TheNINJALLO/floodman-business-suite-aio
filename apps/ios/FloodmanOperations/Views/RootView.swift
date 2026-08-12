import SwiftUI

struct RootView: View {
    @EnvironmentObject private var session: SessionStore

    var body: some View {
        Group {
            if session.signedIn {
                MainView()
            } else {
                LoginView()
            }
        }
        .alert(
            "Floodman",
            isPresented: Binding(
                get: { !session.error.isEmpty },
                set: { if !$0 { session.error = "" } }
            )
        ) {
            Button("OK", role: .cancel) { session.error = "" }
        } message: {
            Text(session.error)
        }
    }
}

struct LoginView: View {
    @EnvironmentObject private var session: SessionStore
    @State private var email = ""
    @State private var password = ""
    @State private var local = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Label("Floodman Operations", systemImage: "drop.fill")
                        .font(.title.bold())
                    Text("Secure staff access through the encrypted Floodman Mobile API. The Apple app does not require Tailscale.")
                }
                Section("Sign in") {
                    TextField("Email", text: $email)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.emailAddress)
                    SecureField("Password", text: $password)
                    Toggle("Use local Floodman account", isOn: $local)
                    Button("Sign in") {
                        Task { await session.login(email: email, password: password, local: local) }
                    }
                    .disabled(email.isEmpty || password.isEmpty || session.busy)
                }
            }
        }
    }
}

struct MainView: View {
    var body: some View {
        TabView {
            DashboardView()
                .tabItem { Label("Home", systemImage: "house.fill") }
            CalendarListView()
                .tabItem { Label("Calendar", systemImage: "calendar") }
            GenericListView(
                title: "Customers",
                path: "v1/customers",
                primary: ["name", "company", "email"],
                secondary: ["phone", "mailing_street"]
            )
            .tabItem { Label("Customers", systemImage: "person.2.fill") }
            GenericListView(
                title: "Estimates",
                path: "v1/estimates",
                primary: ["estimate_number", "title"],
                secondary: ["status", "total_cents"]
            )
            .tabItem { Label("Estimates", systemImage: "doc.text.fill") }
            MoreView()
                .tabItem { Label("More", systemImage: "ellipsis.circle.fill") }
        }
    }
}

struct DashboardView: View {
    @EnvironmentObject private var session: SessionStore

    var body: some View {
        NavigationStack {
            List {
                Section("Today") {
                    dashboardRow("Customers", session.dashboard["customers"])
                    dashboardRow("Open estimates", session.dashboard["open_estimates"])
                    dashboardRow("Open invoices", session.dashboard["open_invoices"])
                    dashboardRow("Unread notifications", session.dashboard["unread_notifications"])
                }
                Section("Field operations") {
                    NavigationLink("Floodman RoomFlow") { RoomFlowJobsView() }
                    NavigationLink("Jobs and inspections") {
                        GenericListView(
                            title: "Jobs and inspections",
                            path: "v1/calendar",
                            primary: ["title"],
                            secondary: ["appointment_type", "start_at"]
                        )
                    }
                }
            }
            .navigationTitle("Floodman Operations")
            .toolbar {
                Button {
                    Task { await session.refreshDashboard() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
            }
        }
    }

    private func dashboardRow(_ label: String, _ value: Any?) -> some View {
        HStack {
            Text(label)
            Spacer()
            Text(String(describing: value ?? 0)).bold()
        }
    }
}

struct GenericListView: View {
    @EnvironmentObject private var session: SessionStore
    let title: String
    let path: String
    let primary: [String]
    let secondary: [String]
    @State private var items: [[String: Any]] = []

    var body: some View {
        NavigationStack {
            List(items.indices, id: \.self) { index in
                let item = items[index]
                VStack(alignment: .leading, spacing: 4) {
                    Text(first(item, keys: primary) ?? title).bold()
                    if let detail = first(item, keys: secondary) {
                        Text(detail).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            .navigationTitle(title)
            .task { items = await session.page(path) }
            .refreshable { items = await session.page(path) }
        }
    }

    private func first(_ item: [String: Any], keys: [String]) -> String? {
        for key in keys {
            guard let value = item[key] else { continue }
            if key.hasSuffix("_cents"), let number = value as? NSNumber {
                return NumberFormatter.localizedString(
                    from: NSNumber(value: number.doubleValue / 100.0),
                    number: .currency
                )
            }
            let text = String(describing: value)
            if !text.isEmpty { return text }
        }
        return nil
    }
}

struct CalendarListView: View {
    @EnvironmentObject private var session: SessionStore
    @State private var items: [[String: Any]] = []

    var body: some View {
        NavigationStack {
            List(items.indices, id: \.self) { index in
                let item = items[index]
                VStack(alignment: .leading, spacing: 4) {
                    let appointmentType = String(describing: item["appointment_type"] ?? "JOB")
                    let startAt = String(describing: item["start_at"] ?? "")
                    Text(item["title"] as? String ?? "Appointment").bold()
                    Text(verbatim: "\(appointmentType) • \(startAt)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Calendar")
            .task { items = await session.page("v1/calendar") }
            .refreshable { items = await session.page("v1/calendar") }
        }
    }
}

struct MoreView: View {
    @EnvironmentObject private var session: SessionStore

    var body: some View {
        NavigationStack {
            List {
                Section("Operations") {
                    NavigationLink("Floodman RoomFlow") { RoomFlowJobsView() }
                    NavigationLink("Invoices") {
                        GenericListView(title: "Invoices", path: "v1/invoices", primary: ["invoice_number", "title"], secondary: ["status", "balance_cents"])
                    }
                    NavigationLink("Documents") {
                        GenericListView(title: "Documents", path: "v1/documents", primary: ["title", "filename"], secondary: ["kind", "status"])
                    }
                    NavigationLink("Tasks") {
                        GenericListView(title: "Tasks", path: "v1/tasks?assigned_to_me=false", primary: ["title"], secondary: ["status", "due_at"])
                    }
                    NavigationLink("Announcements") {
                        GenericListView(title: "Announcements", path: "v1/announcements", primary: ["title"], secondary: ["message", "created_at"])
                    }
                    NavigationLink("Notifications") {
                        GenericListView(title: "Notifications", path: "v1/notifications", primary: ["title"], secondary: ["message", "created_at"])
                    }
                }
                Section("Appearance") {
                    Picker("Theme", selection: $session.appearanceMode) {
                        Text("System").tag("SYSTEM")
                        Text("Light").tag("LIGHT")
                        Text("Dark").tag("DARK")
                    }
                    .pickerStyle(.segmented)
                }
                Section {
                    Button("Sign out", role: .destructive) {
                        Task { await session.logout() }
                    }
                }
            }
            .navigationTitle("More")
        }
    }
}
