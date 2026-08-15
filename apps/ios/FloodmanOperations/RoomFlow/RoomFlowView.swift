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
            Section("Quick start") {
                Label("Choose the customer", systemImage: "1.circle.fill")
                Label("Choose the service property", systemImage: "2.circle.fill")
                Label("Sketch and add priced services", systemImage: "3.circle.fill")
                Label("Save the draft to Floodman", systemImage: "4.circle.fill")
                Text("Your Floodman sign-in already includes RoomFlow. No separate RoomFlow account is needed.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }

            Section("Company") {
                if workspaces.isEmpty {
                    Text("Floodman is preparing your company workspace.")
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
                DisclosureGroup("More company options") {
                    Button {
                        showCreateWorkspace = true
                    } label: {
                        Label("Create another company", systemImage: "building.2.crop.circle")
                    }

                    Button {
                        showImport = true
                    } label: {
                        Label("Bring in old RoomFlow data", systemImage: "icloud.and.arrow.down")
                    }
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
            ZStack(alignment: .topTrailing) {
                RoomFlowWebView(jobID: selectedJobID, isPresented: $showWorkspace)
                    .environmentObject(session)
                Button {
                    showWorkspace = false
                } label: {
                    Image(systemName: "xmark")
                        .font(.headline)
                        .frame(width: 32, height: 32)
                }
                .buttonStyle(.borderedProminent)
                .clipShape(Circle())
                .padding(.top, 8)
                .padding(.trailing, 8)
                .accessibilityLabel("Close RoomFlow")
            }
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
    @State private var importTask: Task<Void, Never>?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("Use the sign-in from the original RoomFlow cloud account. Floodman uses the password for this request only, clears it immediately, and updates matching source records instead of creating duplicates.")
                        .font(.callout)
                    TextField("Original RoomFlow email", text: $email)
                        .textContentType(.username)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.emailAddress)
                    SecureField("Original RoomFlow password", text: $password)
                        .textContentType(.password)
                }
                if !error.isEmpty {
                    Section { Text(error).foregroundStyle(.red) }
                }
            }
            .navigationTitle("Bring In RoomFlow Data")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { cancel() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(busy ? "Importing…" : "Start Import") {
                        importTask = Task { await importData() }
                    }
                        .disabled(busy || email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || password.isEmpty)
                }
            }
        }
        .onDisappear {
            importTask?.cancel()
            password = ""
        }
    }

    private func cancel() {
        importTask?.cancel()
        password = ""
        isPresented = false
    }

    @MainActor
    private func importData() async {
        busy = true
        error = ""
        defer { busy = false; importTask = nil }
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
        } catch is CancellationError {
            return
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
    @State private var busy = false
    @State private var error = ""
    @State private var createTask: Task<Void, Never>?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("Most teams need only the company Floodman created automatically. Add another only when its customers and jobs must stay separate.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                    TextField("Company name", text: $name)
                        .textContentType(.organizationName)
                }
                Section("Business time") {
                    LabeledContent("Time zone", value: "Eastern Time (Detroit)")
                }
                if !error.isEmpty { Text(error).foregroundStyle(.red) }
            }
            .navigationTitle("Another Company")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { cancel() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(busy ? "Creating…" : "Create") {
                        createTask = Task { await create() }
                    }
                        .disabled(busy || name.trimmingCharacters(in: .whitespacesAndNewlines).count < 2)
                }
            }
        }
        .onDisappear { createTask?.cancel() }
    }

    private func cancel() {
        createTask?.cancel()
        isPresented = false
    }

    @MainActor
    private func create() async {
        busy = true
        error = ""
        defer { busy = false; createTask = nil }
        do {
            _ = try await session.api.json(
                path: "v1/roomflow/workspaces",
                method: "POST",
                body: [
                    "name": name.trimmingCharacters(in: .whitespacesAndNewlines),
                    "timezone": "America/Detroit"
                ]
            )
            isPresented = false
            onCreated()
        } catch is CancellationError {
            return
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
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.userContentController.add(context.coordinator, name: "FloodmanNative")

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        context.coordinator.webView = webView
        context.coordinator.server.start { result in
            DispatchQueue.main.async {
                if case .success(let url) = result {
                    webView.load(URLRequest(url: url))
                } else {
                    webView.loadHTMLString(
                        "<html><meta name=\"viewport\" content=\"width=device-width\"><body style=\"font-family:-apple-system;padding:32px\"><h1>RoomFlow could not start</h1><p>Close this screen and try again.</p></body></html>",
                        baseURL: nil
                    )
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
                let workspaceID = body["workspaceId"] as? String ?? ""
                Task {
                    let path = queryPath("v1/customers", items: [
                        URLQueryItem(name: "q", value: query),
                        URLQueryItem(name: "workspace_id", value: workspaceID),
                        URLQueryItem(name: "page_size", value: "20")
                    ])
                    let result = (try? await parent.session.api.data(path: path)) ?? Data("{\"items\":[]}".utf8)
                    respondItems(function: "receiveCustomers", data: result)
                }
            case "searchProperties":
                let contactID = body["contactId"] as? String ?? ""
                let query = body["query"] as? String ?? ""
                let workspaceID = body["workspaceId"] as? String ?? ""
                Task {
                    let path = queryPath("v1/properties", items: [
                        URLQueryItem(name: "contact_id", value: contactID),
                        URLQueryItem(name: "q", value: query),
                        URLQueryItem(name: "workspace_id", value: workspaceID),
                        URLQueryItem(name: "page_size", value: "20")
                    ])
                    let result = (try? await parent.session.api.data(path: path)) ?? Data("{\"items\":[]}".utf8)
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

        private func queryPath(_ path: String, items: [URLQueryItem]) -> String {
            var components = URLComponents()
            components.path = path
            components.queryItems = items
            return components.string ?? path
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
            decisionHandler(origin.host == "127.0.0.1" ? .grant : .deny)
        }

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            if navigationAction.request.url?.absoluteString == "about:blank" {
                decisionHandler(.allow)
                return
            }
            guard let url = navigationAction.request.url,
                  url.scheme?.lowercased() == "http",
                  url.host == "127.0.0.1" else {
                decisionHandler(.cancel)
                return
            }
            decisionHandler(.allow)
        }
    }
}
