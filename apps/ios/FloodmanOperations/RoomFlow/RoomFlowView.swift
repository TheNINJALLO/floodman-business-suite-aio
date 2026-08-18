import ARKit
import AVFoundation
import Foundation
import RoomPlan
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
        configuration.userContentController.add(context.coordinator, name: "RoomFlowCaptureV2")

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
        uiView.configuration.userContentController.removeScriptMessageHandler(forName: "RoomFlowCaptureV2")
        coordinator.server.stop()
    }

    final class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate, WKUIDelegate {
        let parent: RoomFlowWebView
        let server = LocalAssetServer()
        weak var webView: WKWebView?
        private var currentJobID: String?
        private var currentWorkspaceID = ""
        private var pendingCaptureRequestID: String?
        private weak var captureController: UIViewController?
        private let captureOutbox = RoomFlowCaptureOutbox()
        private let captureRequestLock = NSLock()
        private var captureRequests: [String: (sessionID: String, type: String)] = [:]

        init(_ parent: RoomFlowWebView) {
            self.parent = parent
            self.currentJobID = parent.jobID
        }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            if message.name == "RoomFlowCaptureV2" {
                handleCaptureEnvelope(message.body)
                return
            }
            guard let body = message.body as? [String: Any], let type = body["type"] as? String else { return }
            switch type {
            case "ready":
                Task {
                    do {
                        let bootstrap = try await parent.session.api.data(path: "v1/roomflow/bootstrap")
                        if let value = try? JSONSerialization.jsonObject(with: bootstrap) as? [String: Any] {
                            let active = value["active_workspace"] as? [String: Any]
                            currentWorkspaceID = (active?["id"] as? String) ?? (value["selected_workspace_id"] as? String) ?? ""
                        }
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

        private func handleCaptureEnvelope(_ message: Any) {
            guard let envelope = message as? [String: Any],
                  let requestID = envelope["requestId"] as? String,
                  !requestID.isEmpty,
                  let sessionID = envelope["sessionId"] as? String,
                  !sessionID.isEmpty,
                  let type = envelope["type"] as? String,
                  !type.isEmpty else { return }
            captureRequestLock.lock()
            captureRequests[requestID] = (sessionID, type)
            captureRequestLock.unlock()
            guard JSONSerialization.isValidJSONObject(envelope),
                  let encoded = try? JSONSerialization.data(withJSONObject: envelope),
                  encoded.count <= 256 * 1024 else {
                respondCaptureError(requestID: requestID, code: "CAPTURE_PAYLOAD_TOO_LARGE", message: "The room capture message cannot exceed 256 KB.")
                return
            }
            guard (envelope["version"] as? NSNumber)?.intValue == 2 else {
                respondCaptureError(requestID: requestID, code: "UNSUPPORTED_BRIDGE_VERSION", message: "This Floodman build supports RoomFlow Capture bridge version 2.")
                return
            }
            let payload = envelope["payload"] as? [String: Any] ?? [:]
            switch type {
            case "capabilitiesRequested":
                let roomPlan = RoomCaptureSession.isSupported
                let arKit = ARWorldTrackingConfiguration.isSupported
                var modes = ["manual"]
                if arKit {
                    modes.insert(ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh) ? "apple-arkit-lidar" : "apple-arkit-guided", at: 0)
                }
                if roomPlan { modes.insert("apple-roomplan", at: 0) }
                respondCapture(requestID: requestID, result: [
                    "supported": roomPlan || arKit,
                    "modes": modes,
                    "preferredMode": roomPlan ? "apple-roomplan" : (arKit ? (ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh) ? "apple-arkit-lidar" : "apple-arkit-guided") : "manual"),
                    "depthSupported": roomPlan,
                    "provider": roomPlan ? "apple-roomplan" : "apple-arkit",
                    "reason": roomPlan || arKit ? NSNull() : "Room scanning is unavailable on this device. Manual room entry remains available.",
                ])
            case "roomCaptureStarted":
                startNativeCapture(requestID: requestID, value: payload)
            case "captureRoomsRequested":
                listCaptureRooms(requestID: requestID, value: payload)
            case "captureOperationQueued":
                saveCaptureOperation(requestID: requestID, value: payload)
            case "captureOutboxReplayRequested":
                replayCaptureOutbox(requestID: requestID, value: payload)
            case "roomCaptureCancelled":
                if let activeRequestID = pendingCaptureRequestID {
                    pendingCaptureRequestID = nil
                    captureController?.dismiss(animated: true)
                    respondCaptureError(requestID: activeRequestID, code: "CAPTURE_CANCELLED", message: RoomFlowCaptureError.cancelled.localizedDescription)
                }
                respondCapture(requestID: requestID, result: ["cancelled": true])
            default:
                respondCaptureError(requestID: requestID, code: "UNSUPPORTED_MESSAGE_TYPE", message: "This Floodman build does not support \(type).")
            }
        }

        private func startNativeCapture(requestID: String, value: [String: Any]) {
            let payload: RoomFlowCapturePayload
            do { payload = try RoomFlowCapturePayload(value) }
            catch { respondCaptureError(requestID: requestID, error: error); return }
            guard validCaptureScope(requestID: requestID, jobID: payload.jobID, workspaceID: payload.workspaceID) else { return }
            guard pendingCaptureRequestID == nil else {
                respondCaptureError(requestID: requestID, code: "CAPTURE_BUSY", message: "Finish or close the current room scan first.")
                return
            }
            Task { @MainActor in
                let cameraAllowed: Bool
                switch AVCaptureDevice.authorizationStatus(for: .video) {
                case .authorized: cameraAllowed = true
                case .notDetermined: cameraAllowed = await AVCaptureDevice.requestAccess(for: .video)
                default: cameraAllowed = false
                }
                guard cameraAllowed else {
                    respondCaptureError(requestID: requestID, code: "CAMERA_PERMISSION_DENIED", message: "Camera permission is required for room scanning. You can still enter the room manually.")
                    return
                }
                presentCaptureController(requestID: requestID, payload: payload)
            }
        }

        @MainActor
        private func presentCaptureController(requestID: String, payload: RoomFlowCapturePayload) {
            guard let presenter = topViewController() else {
                respondCaptureError(requestID: requestID, code: "CAPTURE_UNAVAILABLE", message: "Floodman could not open the room scanner. Enter the room manually.")
                return
            }
            pendingCaptureRequestID = requestID
            weak var presentedController: UIViewController?
            let completion: (Result<[String: Any], Error>) -> Void = { [weak self] outcome in
                DispatchQueue.main.async {
                    presentedController?.dismiss(animated: true)
                    self?.completeNativeCapture(requestID: requestID, outcome: outcome)
                }
            }
            let controller: UIViewController
            if payload.requestedMode.hasPrefix("apple-arkit") && ARWorldTrackingConfiguration.isSupported {
                controller = ARKitCaptureViewController(payload: payload, completion: completion)
            } else if RoomCaptureSession.isSupported {
                controller = RoomPlanCaptureViewController(payload: payload, completion: completion)
            } else if ARWorldTrackingConfiguration.isSupported {
                controller = ARKitCaptureViewController(payload: payload, completion: completion)
            } else {
                pendingCaptureRequestID = nil
                respondCaptureError(requestID: requestID, code: "CAPTURE_UNSUPPORTED", message: "This device does not support RoomPlan or ARKit room scanning. Enter the room manually.")
                return
            }
            presentedController = controller
            captureController = controller
            presenter.present(controller, animated: true)
        }

        @MainActor
        private func completeNativeCapture(requestID: String, outcome: Result<[String: Any], Error>) {
            guard pendingCaptureRequestID == requestID else { return }
            pendingCaptureRequestID = nil
            captureController = nil
            switch outcome {
            case .success(let room): respondCapture(requestID: requestID, result: room)
            case .failure(let error): respondCaptureError(requestID: requestID, error: error)
            }
        }

        private func listCaptureRooms(requestID: String, value: [String: Any]) {
            let jobID = (value["jobId"] as? String) ?? ""
            let workspaceID = (value["workspaceId"] as? String) ?? ""
            guard validCaptureScope(requestID: requestID, jobID: jobID, workspaceID: workspaceID) else { return }
            Task {
                _ = try? await captureOutbox.flush(jobID: jobID, api: parent.session.api)
                do {
                    let data = try await parent.session.api.data(path: "v1/roomflow/jobs/\(pathComponent(jobID))/capture/rooms")
                    let result = try JSONSerialization.jsonObject(with: data)
                    respondCapture(requestID: requestID, result: result)
                } catch {
                    respondCaptureError(requestID: requestID, code: "CAPTURE_LOAD_FAILED", message: error.localizedDescription)
                }
            }
        }

        private func saveCaptureOperation(requestID: String, value: [String: Any]) {
            let jobID = (value["jobId"] as? String) ?? ""
            let workspaceID = (value["workspaceId"] as? String) ?? ""
            guard validCaptureScope(requestID: requestID, jobID: jobID, workspaceID: workspaceID) else { return }
            guard let operation = value["operation"] as? [String: Any] else {
                respondCaptureError(requestID: requestID, code: "INVALID_CAPTURE", message: "The room change is missing its operation payload.")
                return
            }
            Task {
                do {
                    try await captureOutbox.enqueue(jobID: jobID, workspaceID: workspaceID, operation: operation)
                } catch {
                    respondCaptureError(requestID: requestID, error: error)
                    return
                }
                do {
                    let response = try await captureOutbox.flush(jobID: jobID, api: parent.session.api)
                    let results = response["results"] as? [[String: Any]] ?? []
                    let operationID = operation["operationId"] as? String
                    let result = results.first { ($0["operationId"] as? String) == operationID } ?? results.last
                    if let result, result["ok"] as? Bool == true {
                        respondCapture(requestID: requestID, result: result)
                    } else {
                        respondCaptureError(
                            requestID: requestID,
                            code: result?["code"] as? String ?? "CAPTURE_SAVE_FAILED",
                            message: result?["message"] as? String ?? "The room could not be saved. It remains queued on this device."
                        )
                    }
                } catch {
                    let revision = (operation["expectedRevision"] as? NSNumber)?.intValue ?? 0
                    respondCapture(requestID: requestID, result: [
                        "queued": true,
                        "operationId": operation["operationId"] ?? NSNull(),
                        "revision": revision + 1,
                        "room": operation["room"] ?? NSNull(),
                    ])
                }
            }
        }

        private func replayCaptureOutbox(requestID: String, value: [String: Any]) {
            let jobID = (value["jobId"] as? String) ?? ""
            let workspaceID = (value["workspaceId"] as? String) ?? ""
            guard validCaptureScope(requestID: requestID, jobID: jobID, workspaceID: workspaceID) else { return }
            Task {
                do {
                    let result = try await captureOutbox.flush(jobID: jobID, api: parent.session.api)
                    respondCapture(requestID: requestID, result: result)
                } catch {
                    respondCaptureError(requestID: requestID, code: "OFFLINE", message: "Room changes remain safely queued on this device.")
                }
            }
        }

        private func validCaptureScope(requestID: String, jobID: String, workspaceID: String) -> Bool {
            guard !jobID.isEmpty, currentJobID == nil || currentJobID == jobID else {
                respondCaptureError(requestID: requestID, code: "JOB_SCOPE_MISMATCH", message: "The room request does not match the open Floodman job.")
                return false
            }
            guard workspaceID.isEmpty || currentWorkspaceID.isEmpty || currentWorkspaceID == workspaceID else {
                respondCaptureError(requestID: requestID, code: "WORKSPACE_SCOPE_MISMATCH", message: "The room request does not match the selected Floodman company.")
                return false
            }
            return true
        }

        private func topViewController() -> UIViewController? {
            var controller = webView?.window?.rootViewController
            while let presented = controller?.presentedViewController { controller = presented }
            return controller
        }

        private func pathComponent(_ value: String) -> String {
            value.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? value
        }

        private func respondCapture(requestID: String, result: Any) {
            guard let context = takeCaptureRequest(requestID) else { return }
            let envelope: [String: Any] = [
                "version": 2,
                "sessionId": context.sessionID,
                "type": captureResponseType(context.type, failed: false),
                "requestId": requestID,
                "ok": true,
                "payload": result,
            ]
            guard let data = try? JSONSerialization.data(withJSONObject: envelope),
                  let text = String(data: data, encoding: .utf8) else { return }
            DispatchQueue.main.async {
                self.webView?.evaluateJavaScript("window.RoomFlowCaptureBridgeV2?.receive(\(text));", completionHandler: nil)
            }
        }

        private func respondCaptureError(requestID: String, error: Error) {
            let code = (error as? RoomFlowCaptureError)?.code ?? "CAPTURE_FAILED"
            respondCaptureError(requestID: requestID, code: code, message: error.localizedDescription)
        }

        private func respondCaptureError(requestID: String, code: String, message: String) {
            guard let context = takeCaptureRequest(requestID) else { return }
            let envelope: [String: Any] = [
                "version": 2,
                "sessionId": context.sessionID,
                "type": code == "CAPTURE_CANCELLED" ? "sessionCancelled" : captureResponseType(context.type, failed: true),
                "requestId": requestID,
                "ok": false,
                "error": ["code": code, "message": message],
            ]
            guard let data = try? JSONSerialization.data(withJSONObject: envelope),
                  let text = String(data: data, encoding: .utf8) else { return }
            DispatchQueue.main.async {
                self.webView?.evaluateJavaScript("window.RoomFlowCaptureBridgeV2?.receive(\(text));", completionHandler: nil)
            }
        }

        private func takeCaptureRequest(_ requestID: String) -> (sessionID: String, type: String)? {
            captureRequestLock.lock()
            defer { captureRequestLock.unlock() }
            return captureRequests.removeValue(forKey: requestID)
        }

        private func captureResponseType(_ requestType: String, failed: Bool) -> String {
            switch requestType {
            case "capabilitiesRequested": return "capabilitiesReported"
            case "roomCaptureStarted": return failed ? "sessionFailed" : "roomCaptureCompleted"
            case "roomCaptureCancelled": return "sessionCancelled"
            case "captureRoomsRequested": return failed ? "captureRoomsFailed" : "captureRoomsReported"
            case "captureOperationQueued": return failed ? "captureOperationFailed" : "captureOperationSaved"
            case "captureOutboxReplayRequested": return failed ? "captureOutboxReplayFailed" : "captureOutboxReplayed"
            default: return failed ? "sessionFailed" : "sessionCompleted"
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
