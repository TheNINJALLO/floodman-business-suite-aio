import SwiftUI

@main
struct FloodmanOperationsApp: App {
    @StateObject private var session = SessionStore()
    var body: some Scene {
        WindowGroup {
            RootView().environmentObject(session).preferredColorScheme(session.preferredColorScheme)
        }
    }
}
