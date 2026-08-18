import Foundation

private struct PendingRoomFlowCaptureOperation: Codable {
    let jobID: String
    let workspaceID: String
    let operation: Data
    let operationID: String
    let queuedAt: Date
}

actor RoomFlowCaptureOutbox {
    private let fileURL: URL
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    init(fileManager: FileManager = .default) {
        let support = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? fileManager.temporaryDirectory
        let directory = support.appendingPathComponent("FloodmanOperations/Offline", isDirectory: true)
        try? fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        fileURL = directory.appendingPathComponent("roomflow-capture-outbox-v2.json")
        encoder.dateEncodingStrategy = .iso8601
        decoder.dateDecodingStrategy = .iso8601
    }

    func enqueue(jobID: String, workspaceID: String, operation: [String: Any]) throws {
        guard let operationID = operation["operationId"] as? String, !operationID.isEmpty else {
            throw RoomFlowCaptureError.invalid("Capture operationId is required.")
        }
        let data = try JSONSerialization.data(withJSONObject: operation)
        guard data.count <= 256 * 1024 else {
            throw RoomFlowCaptureError.invalid("A room change cannot exceed 256 KB.")
        }
        var values = try load()
        if !values.contains(where: { $0.operationID == operationID }) {
            values.append(PendingRoomFlowCaptureOperation(
                jobID: jobID,
                workspaceID: workspaceID,
                operation: data,
                operationID: operationID,
                queuedAt: Date()
            ))
        }
        try save(Array(values.suffix(200)))
    }

    func flush(jobID: String, api: APIClient) async throws -> [String: Any] {
        let values = try load()
        let pending = values.filter { $0.jobID == jobID }
        guard !pending.isEmpty else { return ["complete": true, "results": []] }
        let operations = try pending.map { entry -> Any in
            try JSONSerialization.jsonObject(with: entry.operation)
        }
        let body = try JSONSerialization.data(withJSONObject: ["operations": operations])
        let responseData = try await api.data(
            path: "v1/roomflow/jobs/\(pathComponent(jobID))/capture/operations",
            method: "POST",
            bodyData: body
        )
        let response = try JSONSerialization.jsonObject(with: responseData) as? [String: Any] ?? [:]
        let results = response["results"] as? [[String: Any]] ?? []
        let succeeded = Set(results.compactMap { result -> String? in
            guard result["ok"] as? Bool == true else { return nil }
            return result["operationId"] as? String
        })
        if !succeeded.isEmpty {
            try save(values.filter { !succeeded.contains($0.operationID) })
        }
        return response
    }

    func count(jobID: String) throws -> Int {
        try load().filter { $0.jobID == jobID }.count
    }

    private func load() throws -> [PendingRoomFlowCaptureOperation] {
        guard FileManager.default.fileExists(atPath: fileURL.path) else { return [] }
        return try decoder.decode([PendingRoomFlowCaptureOperation].self, from: Data(contentsOf: fileURL))
    }

    private func save(_ values: [PendingRoomFlowCaptureOperation]) throws {
        let data = try encoder.encode(values)
        try data.write(to: fileURL, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    }

    private func pathComponent(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? value
    }
}
