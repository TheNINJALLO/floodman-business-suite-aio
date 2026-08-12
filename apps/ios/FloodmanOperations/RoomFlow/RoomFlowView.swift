import SwiftUI
import WebKit

struct RoomFlowJobsView: View {
    @EnvironmentObject private var session: SessionStore
    @State private var jobs: [[String: Any]] = []
    @State private var workspaces: [[String: Any]] = []
    @State private var selectedWorkspaceID = ""
    @State private var selectedJobID: String?
    @State private var showWorkspace = false
    @State private var showImport = false
    @State private var showCreateWorkspace = false
    @State private var busy = false
    @State private var error = ""

    var body: some View {
        List {
            Section("Company workspace") {
                if workspaces.isEmpty {
                    Text("No RoomFlow workspace is available yet.")
                        .foregroundStyle(.secondary)
                } else {
                    Picker("Active company", selection: $selectedWorkspaceID) {
                        ForEach(workspaces.indices, id: \.self) { index in
                            Text((workspaces[index]["name"] as? String) ?? "Floodman")
                                .tag((workspaces[index]["id"] as? String) ?? "")
                        }
                    }
                    .disabled(busy)
                    .onChange(of: selectedWorkspaceID) { oldValue, newValue in
                        guard !newValue.isEmpty, oldValue != newValue else { return }
                        Task { await selectWorkspace(newValue) }
                    }
                }

                Button {
                    showCreateWorkspace = true
                } label: {
                    Label("Create company workspace", systemImage: "building.2.crop.circle")
                }

                Button {
                    showImport = true
                } label: {
                    Label("Import original RoomFlow cloud data", systemImage: "icloud.and.arrow.down")
                }
            }

            if !error.isEmpty {
                Section {
                    Text(error).foregroundStyle(.red)
                }
            }

            Button {
                selectedJobID = nil
                showWorkspace = true
            } label: {
                Label("Start a new RoomFlow job", systemImage: "plus.circle.fill")
            }

            Section("Shared RoomFlow jobs") {
                ForEach(jobs.indices, id: \.self) { index in
                    let job = jobs[index]
                    Button {
                        selectedJobID = job["id"] as? String
                        showWorkspace = true
                    } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            let customerName = String(describing: job["customer_name"] ?? "")
                            let propertyAddress = String(describing: job["property_address"] ?? "")
                            Text((job["job_name"] as? String) ?? (job["name"] as? String) ?? "RoomFlow job")
                                .fontWeight(.bold)
                            Text(verbatim: "\(customerName) • \(propertyAddress)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
        .navigationTitle("Floodman RoomFlow")
        .overlay { if busy { ProgressView("Updating RoomFlow…") } }
        .task { await load() }
        .refreshable { await load() }
        .fullScreenCover(isPresented: $showWorkspace) {
            RoomFlowWebView(jobID: selectedJobID, isPresented: $showWorkspace)
                .environmentObject(session)
        }
        .sheet(isPresented: $showImport) {
            RoomFlowImportView(isPresented: $showImport) {
                Task { await load() }
            }
            .environmentObject(session)
        }
        .sheet(isPresented: $showCreateWorkspace) {
            RoomFlowWorkspaceCreateView(isPresented: $showCreateWorkspace) {
                Task { await load() }
            }
            .environmentObject(session)
        }
    }

    @MainActor
    private func load() async {
        busy = true
        defer { busy = false }
        do {
            let value = try await session.api.json(path: "v1/roomflow/bootstrap") as? [String: Any] ?? [:]
            workspaces = value["workspaces"] as? [[String: Any]] ?? []
            selectedWorkspaceID = value["selected_workspace_id"] as? String ?? ""
            let details = value["jobs"] as? [[String: Any]] ?? []
            jobs = details.compactMap { $0["job"] as? [String: Any] }
            error = ""
        } catch {
            self.error = error.localizedDescription
        }
    }

    @MainActor
    private func selectWorkspace(_ workspaceID: String) async {
        busy = true
        defer { busy = false }
        do {
            _ = try await session.api.json(
                path: "v1/roomflow/workspaces/\(workspaceID)/select",
                method: "POST",
                body: [:]
            )
            error = ""
            await load()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

struct RoomFlowImportView: View {
    @EnvironmentObject private var session: SessionStore
    @Binding var isPresented: Bool
    let onImported: () -> Void
    @State private var email = ""
    @State private var password = ""
    @State private var busy = false
    @State private var error = ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("Use the email and password from the original RoomFlow Supabase login. Floodman uses them for this import only and does not save the password. Repeat imports update stable source records.")
                        .font(.callout)
                    TextField("RoomFlow email", text: $email)
                        .textContentType(.username)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.emailAddress)
                    SecureField("RoomFlow password", text: $password)
                        .textContentType(.password)
                }
                if !error.isEmpty {
                    Section { Text(error).foregroundStyle(.red) }
                }
            }
            .navigationTitle("Import RoomFlow")
            .interactiveDismissDisabled(busy)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { password = ""; isPresented = false }
                        .disabled(busy)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(busy ? "Importing…" : "Import") { Task { await importData() } }
                        .disabled(busy || email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || password.isEmpty)
                }
            }
        }
    }

    @MainActor
    private func importData() async {
        busy = true
        error = ""
        defer { busy = false }
        let suppliedPassword = password
        password = ""
        do {
            _ = try await session.api.json(
                path: "v1/roomflow/import/supabase",
                method: "POST",
                body: ["email": email.trimmingCharacters(in: .whitespacesAndNewlines), "password": suppliedPassword]
            )
            isPresented = false
            onImported()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

struct RoomFlowWorkspaceCreateView: View {
    @EnvironmentObject private var session: SessionStore
    @Binding var isPresented: Bool
    let onCreated: () -> Void
    @State private var name = ""
    @State private var timezone = "America/Detroit"
    @State private var busy = false
    @State private var error = ""

    var body: some View {
        NavigationStack {
            Form {
                TextField("Company or workspace name", text: $name)
                TextField("Business time zone", text: $timezone)
                    .textInputAutocapitalization(.never)
                if !error.isEmpty { Text(error).foregroundStyle(.red) }
            }
            .navigationTitle("New workspace")
            .interactiveDismissDisabled(busy)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { isPresented = false }.disabled(busy)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(busy ? "Creating…" : "Create") { Task { await create() } }
                        .disabled(busy || name.trimmingCharacters(in: .whitespacesAndNewlines).count < 2)
                }
            }
        }
    }

    @MainActor
    private func create() async {
        busy = true
        error = ""
        defer { busy = false }
        do {
            _ = try await session.api.json(
                path: "v1/roomflow/workspaces",
                method: "POST",
                body: [
                    "name": name.trimmingCharacters(in: .whitespacesAndNewlines),
                    "timezone": timezone.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "America/Detroit" : timezone
                ]
            )
            isPresented = false
            onCreated()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

struct RoomFlowWebView: UIViewRepresentable {
    @EnvironmentObject private var session: SessionStore
    let jobID: String?
    @Binding var isPresented: Bool

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = true
        configuration.userContentController.add(context.coordinator, name: "FloodmanNative")

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        context.coordinator.webView = webView
        context.coordinator.server.start { result in
            DispatchQueue.main.async {
                if case .success(let url) = result {
                    webView.load(URLRequest(url: url))
                }
            }
        }
        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    static func dismantleUIView(_ uiView: WKWebView, coordinator: Coordinator) {
        uiView.configuration.userContentController.removeScriptMessageHandler(forName: "FloodmanNative")
        coordinator.server.stop()
    }

    final class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate, WKUIDelegate {
        let parent: RoomFlowWebView
        let server = LocalAssetServer()
        weak var webView: WKWebView?
        private var currentJobID: String?

        init(_ parent: RoomFlowWebView) {
            self.parent = parent
            self.currentJobID = parent.jobID
        }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard let body = message.body as? [String: Any], let type = body["type"] as? String else { return }
            switch type {
            case "ready":
                Task {
                    do {
                        let bootstrap = try await parent.session.api.data(path: "v1/roomflow/bootstrap")
                        respond(function: "receiveBootstrap", data: bootstrap)
                    } catch {
                        respondString(function: "bootstrapFailed", text: error.localizedDescription)
                    }
                    let data: Data
                    if let id = currentJobID {
                        data = (try? await parent.session.api.data(path: "v1/roomflow/jobs/\(id)")) ?? Data("null".utf8)
                    } else {
                        data = Data("null".utf8)
                    }
                    respond(function: "receiveContext", data: data)
                }
            case "selectJob":
                currentJobID = (body["id"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            case "save":
                guard let payload = body["payload"] else { return }
                Task {
                    do {
                        let data = try JSONSerialization.data(withJSONObject: payload)
                        let path = currentJobID.map { "v1/roomflow/jobs/\($0)" } ?? "v1/roomflow/jobs"
                        let result = try await parent.session.api.data(
                            path: path,
                            method: currentJobID == nil ? "POST" : "PUT",
                            bodyData: data
                        )
                        if let object = try? JSONSerialization.jsonObject(with: result) as? [String: Any],
                           let job = object["job"] as? [String: Any],
                           let savedID = job["id"] as? String {
                            currentJobID = savedID
                        }
                        respond(function: "saveCompleted", data: result)
                    } catch {
                        respondString(function: "saveFailed", text: error.localizedDescription)
                    }
                }
            case "searchCustomers":
                let query = body["query"] as? String ?? ""
                Task {
                    let escaped = query.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
                    let result = (try? await parent.session.api.data(path: "v1/customers?q=\(escaped)&page_size=20")) ?? Data("{\"items\":[]}".utf8)
                    respondItems(function: "receiveCustomers", data: result)
                }
            case "searchProperties":
                let contactID = body["contactId"] as? String ?? ""
                let query = body["query"] as? String ?? ""
                Task {
                    let escaped = query.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
                    let result = (try? await parent.session.api.data(path: "v1/properties?contact_id=\(contactID)&q=\(escaped)&page_size=20")) ?? Data("{\"items\":[]}".utf8)
                    respondItems(function: "receiveProperties", data: result)
                }
            case "close":
                DispatchQueue.main.async { self.parent.isPresented = false }
            default:
                break
            }
        }

        private func quoted(_ text: String) -> String {
            let data = try? JSONEncoder().encode(text)
            return data.flatMap { String(data: $0, encoding: .utf8) } ?? "\"\""
        }

        private func respond(function: String, data: Data) {
            let text = String(data: data, encoding: .utf8) ?? "null"
            DispatchQueue.main.async {
                self.webView?.evaluateJavaScript("window.FloodmanRoomFlow?.\(function)(\(self.quoted(text)));", completionHandler: nil)
            }
        }

        private func respondString(function: String, text: String) {
            DispatchQueue.main.async {
                self.webView?.evaluateJavaScript("window.FloodmanRoomFlow?.\(function)(\(self.quoted(text)));", completionHandler: nil)
            }
        }

        private func respondItems(function: String, data: Data) {
            let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            let items = object?["items"] ?? []
            let output = (try? JSONSerialization.data(withJSONObject: items)).flatMap { String(data: $0, encoding: .utf8) } ?? "[]"
            respondString(function: function, text: output)
        }

        @available(iOS 15.0, *)
        func webView(
            _ webView: WKWebView,
            requestMediaCapturePermissionFor origin: WKSecurityOrigin,
            initiatedByFrame frame: WKFrameInfo,
            type: WKMediaCaptureType,
            decisionHandler: @escaping (WKPermissionDecision) -> Void
        ) {
            decisionHandler(.grant)
        }
    }
}
