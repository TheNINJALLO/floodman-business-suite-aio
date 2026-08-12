import SwiftUI
import WebKit

struct RoomFlowJobsView: View {
    @EnvironmentObject private var session: SessionStore
    @State private var jobs: [[String: Any]] = []
    @State private var selectedJobID: String?
    @State private var showWorkspace = false

    var body: some View {
        List {
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
        .task { jobs = await session.page("v1/roomflow/jobs") }
        .fullScreenCover(isPresented: $showWorkspace) {
            RoomFlowWebView(jobID: selectedJobID, isPresented: $showWorkspace)
                .environmentObject(session)
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
                    let data: Data
                    if let id = currentJobID {
                        data = (try? await parent.session.api.data(path: "v1/roomflow/jobs/\(id)")) ?? Data("null".utf8)
                    } else {
                        data = Data("null".utf8)
                    }
                    respond(function: "receiveContext", data: data)
                }
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
