import SwiftUI

@MainActor
final class SessionStore: ObservableObject {
    let api = APIClient()
    @Published var signedIn = false
    @Published var busy = false
    @Published var error = ""
    @AppStorage("appearanceMode") var appearanceMode = "SYSTEM"
    @Published var dashboard: [String: Any] = [:]

    var preferredColorScheme: ColorScheme? { appearanceMode == "DARK" ? .dark : appearanceMode == "LIGHT" ? .light : nil }
    init() { Task { await restoreSession() } }
    private func restoreSession() async {
        guard await api.isSignedIn() else { return }
        do {
            try await api.validateCompatibility()
            signedIn = true
            await refreshDashboard()
        } catch {
            self.error = error.localizedDescription
        }
    }
    func login(email: String, password: String, local: Bool) async { busy=true; defer{busy=false}; do{try await api.login(email:email,password:password,local:local);signedIn=true;await refreshDashboard()}catch{self.error=error.localizedDescription} }
    func logout() async { await api.logout(); signedIn=false; dashboard=[:] }
    func refreshDashboard() async { do{dashboard = try await api.json(path:"v1/dashboard") as? [String:Any] ?? [:]}catch{self.error=error.localizedDescription} }
    func page(_ path: String) async -> [[String: Any]] { do{let value=try await api.json(path:path) as? [String:Any];return value?["items"] as? [[String:Any]] ?? []}catch{self.error=error.localizedDescription;return []} }
}
