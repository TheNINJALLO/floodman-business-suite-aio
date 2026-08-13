import Foundation
import Network

final class LocalAssetServer {
    private var listener: NWListener?
    private let queue = DispatchQueue(label: "com.floodman.roomflow.server")
    private var completionDelivered = false

    func start(completion: @escaping (Result<URL, Error>) -> Void) {
        stop()
        completionDelivered = false

        do {
            let parameters = NWParameters.tcp
            parameters.allowLocalEndpointReuse = true
            parameters.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: .any)

            let listener = try NWListener(using: parameters, on: .any)
            self.listener = listener

            listener.stateUpdateHandler = { [weak self] state in
                guard let self else { return }
                switch state {
                case .ready:
                    guard !self.completionDelivered, let port = self.listener?.port else { return }
                    self.completionDelivered = true
                    let url = URL(string: "http://127.0.0.1:\(port.rawValue)/index.html?floodman_ios=1")!
                    completion(.success(url))
                case .failed(let error):
                    guard !self.completionDelivered else { return }
                    self.completionDelivered = true
                    completion(.failure(error))
                default:
                    break
                }
            }

            listener.newConnectionHandler = { [weak self] connection in
                self?.serve(connection)
            }
            listener.start(queue: queue)
        } catch {
            completion(.failure(error))
        }
    }

    func stop() {
        listener?.cancel()
        listener = nil
    }

    private func serve(_ connection: NWConnection) {
        connection.start(queue: queue)
        receiveRequest(over: connection, buffer: Data())
    }

    private func receiveRequest(over connection: NWConnection, buffer: Data) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 16_384) { [weak self] data, _, isComplete, error in
            guard let self else {
                connection.cancel()
                return
            }
            var requestData = buffer
            if let data { requestData.append(data) }
            if requestData.count > 65_536 {
                self.send(status: "431 Request Header Fields Too Large", body: Data("Request Too Large".utf8), mime: "text/plain; charset=utf-8", over: connection)
                return
            }
            if requestData.range(of: Data("\r\n\r\n".utf8)) != nil {
                self.handle(requestData, over: connection)
                return
            }
            if isComplete || error != nil {
                connection.cancel()
                return
            }
            self.receiveRequest(over: connection, buffer: requestData)
        }
    }

    private func handle(_ requestData: Data, over connection: NWConnection) {
        guard let request = String(data: requestData, encoding: .utf8) else {
            send(status: "400 Bad Request", body: Data("Bad Request".utf8), mime: "text/plain; charset=utf-8", over: connection)
            return
        }

        let firstLine = request.components(separatedBy: "\r\n").first ?? ""
        let fields = firstLine.split(separator: " ", omittingEmptySubsequences: true)
        guard fields.count >= 2, fields[0] == "GET" else {
            send(status: "405 Method Not Allowed", body: Data("Method Not Allowed".utf8), mime: "text/plain; charset=utf-8", over: connection)
            return
        }
        let target = String(fields[1])
        let rawPath = target.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false).first.map(String.init) ?? "/"
        let decodedPath = rawPath.removingPercentEncoding ?? rawPath
        let relativePath = decodedPath == "/" ? "index.html" : String(decodedPath.drop(while: { $0 == "/" }))

        guard let resourceURL = Bundle.main.resourceURL else {
            send(status: "500 Internal Server Error", body: Data("Missing app resources".utf8), mime: "text/plain; charset=utf-8", over: connection)
            return
        }

        let root = resourceURL.appendingPathComponent("RoomFlow", isDirectory: true).standardizedFileURL
        let file = root.appendingPathComponent(relativePath).standardizedFileURL
        let rootPrefix = root.path.hasSuffix("/") ? root.path : root.path + "/"

        guard file.path.hasPrefix(rootPrefix) else {
            send(status: "403 Forbidden", body: Data("Forbidden".utf8), mime: "text/plain; charset=utf-8", over: connection)
            return
        }

        var isDirectory: ObjCBool = false
        let exists = FileManager.default.fileExists(atPath: file.path, isDirectory: &isDirectory) && !isDirectory.boolValue
        if exists, let body = try? Data(contentsOf: file) {
            send(status: "200 OK", body: body, mime: mime(file.pathExtension), over: connection)
        } else {
            send(status: "404 Not Found", body: Data("Not Found".utf8), mime: "text/plain; charset=utf-8", over: connection)
        }
    }

    private func send(status: String, body: Data, mime: String, over connection: NWConnection) {
        let header = "HTTP/1.1 \(status)\r\nContent-Type: \(mime)\r\nContent-Length: \(body.count)\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nConnection: close\r\n\r\n"
        var response = Data(header.utf8)
        response.append(body)
        connection.send(content: response, completion: .contentProcessed { _ in
            connection.cancel()
        })
    }

    private func mime(_ ext: String) -> String {
        switch ext.lowercased() {
        case "html": return "text/html; charset=utf-8"
        case "js": return "application/javascript; charset=utf-8"
        case "css": return "text/css; charset=utf-8"
        case "json", "map": return "application/json; charset=utf-8"
        case "png": return "image/png"
        case "jpg", "jpeg": return "image/jpeg"
        case "svg": return "image/svg+xml"
        case "webp": return "image/webp"
        case "woff2": return "font/woff2"
        case "wasm": return "application/wasm"
        case "gltf": return "model/gltf+json"
        case "glb": return "model/gltf-binary"
        default: return "application/octet-stream"
        }
    }
}
