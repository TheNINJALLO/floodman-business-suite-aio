import Foundation
import CryptoKit
import UIKit

actor APIClient {
    private let keychain = KeychainStore()
    private var baseURL: URL
    private let decoder = JSONDecoder()

    init() {
        let configured = Bundle.main.object(forInfoDictionaryKey: "FLOODMAN_API_BASE_URL") as? String
        baseURL = URL(string: configured?.isEmpty == false ? configured! : "https://floodman-operations.tail274417.ts.net/mobile-api/")!
    }

    func apiURL() -> String { baseURL.absoluteString }
    func isSignedIn() -> Bool { keychain.get("accessToken") != nil && keychain.get("refreshToken") != nil }

    func login(email: String, password: String, local: Bool) async throws {
        let deviceID: String
        if let savedDeviceID = keychain.get("deviceID") {
            deviceID = savedDeviceID
        } else {
            deviceID = UUID().uuidString
            keychain.set(deviceID, for: "deviceID")
        }
        let deviceName = await MainActor.run { UIDevice.current.name }
        let body: [String: Any] = ["email":email,"password":password,"auth_source":local ? "local" : "platform","device_id":deviceID,"device_name":deviceName,"platform":"ios","app_version":"0.1.0-alpha02"]
        let data = try await raw(path: "v1/auth/login", method: "POST", body: body, authorized: false, retry: false)
        let value = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
        guard let access = value["access_token"] as? String, let refresh = value["refresh_token"] as? String, let secret = value["device_secret"] as? String else { throw APIError.message("Floodman login response was incomplete.") }
        keychain.set(access, for: "accessToken"); keychain.set(refresh, for: "refreshToken"); keychain.set(secret, for: "deviceSecret")
        if let device = value["device"] as? [String: Any], let id = device["id"] as? String { keychain.set(id, for: "deviceID") }
    }

    func logout() async {
        _ = try? await raw(path: "v1/auth/logout", method: "POST", body: ["refresh_token":keychain.get("refreshToken") ?? ""], authorized: true, retry: false)
        for key in ["accessToken","refreshToken","deviceSecret"] { keychain.delete(key) }
    }

    func json(path: String, method: String = "GET", body: Any? = nil) async throws -> Any {
        let data = try await raw(path: path, method: method, body: body, authorized: true, retry: true)
        return try JSONSerialization.jsonObject(with: data)
    }

    func data(path: String, method: String = "GET", bodyData: Data? = nil) async throws -> Data {
        try await raw(path: path, method: method, bodyData: bodyData, authorized: true, retry: true)
    }

    private func raw(path: String, method: String, body: Any? = nil, bodyData: Data? = nil, authorized: Bool, retry: Bool) async throws -> Data {
        let url = URL(string: path, relativeTo: baseURL)!
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 180
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let bodyData { request.httpBody = bodyData; request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        else if let body { request.httpBody = try JSONSerialization.data(withJSONObject: body); request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        if authorized, let token = keychain.get("accessToken") { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        let (data, response) = try await URLSession.shared.data(for: request)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        if code == 401 && authorized && retry { try await refresh(); return try await raw(path: path, method: method, body: body, bodyData: bodyData, authorized: true, retry: false) }
        guard (200..<300).contains(code) else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw APIError.message(detail ?? "Floodman request failed (\(code)).")
        }
        return data
    }

    private func refresh() async throws {
        guard let refresh = keychain.get("refreshToken"), let deviceID = keychain.get("deviceID"), let secretText = keychain.get("deviceSecret") else { throw APIError.message("Sign in again.") }
        let timestamp = Int(Date().timeIntervalSince1970), nonce = UUID().uuidString
        let tokenHash = SHA256.hash(data: Data(refresh.utf8)).map { String(format:"%02x",$0) }.joined()
        let canonical = "\(deviceID).\(timestamp).\(nonce).\(tokenHash)"
        let secret = Data(base64URLEncoded: secretText) ?? Data()
        let signature = HMAC<SHA256>.authenticationCode(for: Data(canonical.utf8), using: SymmetricKey(data: secret))
        let proof = Data(signature).base64URLEncodedString()
        let data = try await raw(path: "v1/auth/refresh", method: "POST", body: ["refresh_token":refresh,"device_id":deviceID,"timestamp":timestamp,"nonce":nonce,"proof":proof], authorized: false, retry: false)
        let value = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
        guard let access = value["access_token"] as? String, let next = value["refresh_token"] as? String else { throw APIError.message("Session refresh failed.") }
        keychain.set(access, for: "accessToken"); keychain.set(next, for: "refreshToken")
    }
}

enum APIError: Error, LocalizedError { case message(String); var errorDescription: String? { if case .message(let text)=self{return text};return "Floodman request failed." } }

extension Data {
    init?(base64URLEncoded value: String) { var s=value.replacingOccurrences(of:"-",with:"+").replacingOccurrences(of:"_",with:"/"); s += String(repeating:"=",count:(4-s.count%4)%4); self.init(base64Encoded:s) }
    func base64URLEncodedString() -> String { base64EncodedString().replacingOccurrences(of:"+",with:"-").replacingOccurrences(of:"/",with:"_").replacingOccurrences(of:"=",with:"") }
}
