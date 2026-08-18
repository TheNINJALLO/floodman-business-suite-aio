import RoomPlan
import UIKit
import simd

@available(iOS 17.0, *)
final class RoomPlanCaptureViewController: UIViewController, RoomCaptureViewDelegate {
    private let payload: RoomFlowCapturePayload
    private let completion: (Result<[String: Any], Error>) -> Void
    private let captureView = RoomCaptureView(frame: .zero)
    private let statusLabel = UILabel()
    private let startedAt = Date()
    private var started = false
    private var completed = false

    init(payload: RoomFlowCapturePayload, completion: @escaping (Result<[String: Any], Error>) -> Void) {
        self.payload = payload
        self.completion = completion
        super.init(nibName: nil, bundle: nil)
        modalPresentationStyle = .fullScreen
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError("init(coder:) is unavailable") }

    override func viewDidLoad() {
        super.viewDidLoad()
        captureView.translatesAutoresizingMaskIntoConstraints = false
        captureView.delegate = self
        captureView.isModelEnabled = true
        view.addSubview(captureView)
        NSLayoutConstraint.activate([
            captureView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            captureView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            captureView.topAnchor.constraint(equalTo: view.topAnchor),
            captureView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        ])
        installControls()
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(applicationEnteredBackground),
            name: UIApplication.didEnterBackgroundNotification,
            object: nil
        )
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        guard !started else { return }
        started = true
        let configuration = RoomCaptureSession.Configuration()
        captureView.captureSession.run(configuration: configuration)
    }

    override func viewWillDisappear(_ animated: Bool) {
        if started && !completed { captureView.captureSession.stop() }
        super.viewWillDisappear(animated)
    }

    deinit { NotificationCenter.default.removeObserver(self) }

    private func installControls() {
        let close = button("Close", action: #selector(confirmCancelCapture))
        let finish = button("Finish room", action: #selector(finishCapture))
        finish.backgroundColor = UIColor.systemGreen.withAlphaComponent(0.94)
        statusLabel.text = "LiDAR RoomPlan is active. Walk slowly and show every wall, corner, door, and window. Camera/depth frames are never saved."
        statusLabel.textColor = .white
        statusLabel.font = .preferredFont(forTextStyle: .callout)
        statusLabel.numberOfLines = 0
        statusLabel.backgroundColor = UIColor.black.withAlphaComponent(0.72)
        statusLabel.layer.cornerRadius = 12
        statusLabel.layer.masksToBounds = true
        statusLabel.translatesAutoresizingMaskIntoConstraints = false
        let row = UIStackView(arrangedSubviews: [close, finish])
        row.axis = .horizontal
        row.spacing = 12
        row.distribution = .fillEqually
        row.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(statusLabel)
        view.addSubview(row)
        NSLayoutConstraint.activate([
            statusLabel.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 16),
            statusLabel.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -16),
            statusLabel.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 12),
            row.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 16),
            row.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -16),
            row.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -12),
            row.heightAnchor.constraint(greaterThanOrEqualToConstant: 52),
        ])
    }

    private func button(_ title: String, action: Selector) -> UIButton {
        var configuration = UIButton.Configuration.filled()
        configuration.title = title
        configuration.baseBackgroundColor = UIColor.black.withAlphaComponent(0.78)
        configuration.cornerStyle = .large
        let value = UIButton(configuration: configuration)
        value.addTarget(self, action: action, for: .touchUpInside)
        return value
    }

    @objc private func finishCapture() {
        guard !completed else { return }
        statusLabel.text = "Processing the measured room…"
        captureView.captureSession.stop()
    }

    @objc private func confirmCancelCapture() {
        let alert = UIAlertController(
            title: "Discard this room scan?",
            message: "The unfinished RoomPlan scan will be cleared. Your existing Floodman job will not change.",
            preferredStyle: .alert
        )
        alert.addAction(UIAlertAction(title: "Keep scanning", style: .cancel))
        alert.addAction(UIAlertAction(title: "Discard scan", style: .destructive) { [weak self] _ in self?.cancelCapture() })
        present(alert, animated: true)
    }

    private func cancelCapture() {
        captureView.captureSession.stop()
        finish(.failure(RoomFlowCaptureError.cancelled))
    }

    @objc private func applicationEnteredBackground() {
        guard started, !completed else { return }
        captureView.captureSession.stop()
        finish(.failure(RoomFlowCaptureError.interrupted))
    }

    func captureView(shouldPresent roomDataForProcessing: CapturedRoomData, error: Error?) -> Bool {
        if let error {
            finish(.failure(error))
            return false
        }
        return !completed
    }

    func captureView(didPresent processedResult: CapturedRoom, error: Error?) {
        if let error {
            finish(.failure(error))
            return
        }
        do {
            let result = try RoomPlanCaptureConverter.convert(room: processedResult, payload: payload, startedAt: startedAt)
            finish(.success(result))
        } catch {
            finish(.failure(error))
        }
    }

    private func finish(_ result: Result<[String: Any], Error>) {
        guard !completed else { return }
        completed = true
        completion(result)
    }
}

@available(iOS 17.0, *)
private enum RoomPlanCaptureConverter {
    static func convert(room: CapturedRoom, payload: RoomFlowCapturePayload, startedAt: Date) throws -> [String: Any] {
        let outline = try outline(from: room.walls)
        let heights = room.walls.map { Double($0.dimensions.y) }.filter { $0 > 0.2 }.sorted()
        let heightFeet = (heights.isEmpty ? payload.defaultHeightFeet / roomFlowFeetPerMeter : heights[heights.count / 2]) * roomFlowFeetPerMeter
        var openings: [[String: Any]] = []
        for surface in room.doors { if let value = opening(surface, type: "door", room: room, outline: outline) { openings.append(value) } }
        for surface in room.windows { if let value = opening(surface, type: "window", room: room, outline: outline) { openings.append(value) } }
        for surface in room.openings { if let value = opening(surface, type: "open-wall", room: room, outline: outline) { openings.append(value) } }
        return try RoomFlowCaptureResultBuilder.build(
            payload: payload,
            points: outline.points,
            heightFeet: heightFeet,
            mode: "apple-roomplan",
            openings: openings,
            warnings: [],
            startedAt: startedAt
        )
    }

    private static func outline(from walls: [CapturedRoom.Surface]) throws -> RoomFlowMeasuredOutline {
        let measured = walls.compactMap { wall -> RoomFlowMeasuredWall? in
            let center = SIMD2<Float>(wall.transform.columns.3.x, wall.transform.columns.3.z)
            var axis = SIMD2<Float>(wall.transform.columns.0.x, wall.transform.columns.0.z)
            guard wall.dimensions.x >= 0.075, simd_length(axis) > 0.001 else { return nil }
            axis = simd_normalize(axis)
            return RoomFlowMeasuredWall(
                id: wall.identifier,
                center: center,
                axis: axis,
                lengthMeters: wall.dimensions.x,
                confidence: confidenceValue(wall.confidence)
            )
        }
        return try RoomFlowMeasuredOutlineBuilder.build(walls: measured)
    }

    private static func opening(
        _ surface: CapturedRoom.Surface,
        type: String,
        room: CapturedRoom,
        outline: RoomFlowMeasuredOutline
    ) -> [String: Any]? {
        guard let parentID = surface.parentIdentifier,
              let segment = outline.wallSegments[parentID],
              segment < outline.points.count else { return nil }
        let first = outline.points[segment]
        let second = outline.points[(segment + 1) % outline.points.count]
        let wallVector = SIMD2<Double>(second.xMeters - first.xMeters, second.zMeters - first.zMeters)
        let lengthSquared = simd_length_squared(wallVector)
        guard lengthSquared > 0.000001 else { return nil }
        let center = SIMD2<Double>(Double(surface.transform.columns.3.x), Double(surface.transform.columns.3.z))
        let start = SIMD2<Double>(first.xMeters, first.zMeters)
        let offsetMeters = max(0, min(1, simd_dot(center - start, wallVector) / lengthSquared)) * sqrt(lengthSquared)
        let parentWall = room.walls.first { $0.identifier == parentID }
        let wallBottom = parentWall.map { Double($0.transform.columns.3.y - $0.dimensions.y / 2) } ?? 0
        let openingBottom = Double(surface.transform.columns.3.y - surface.dimensions.y / 2)
        return [
            "id": surface.identifier.uuidString,
            "type": type,
            "wallSegmentIndex": segment,
            "offset": offsetMeters * roomFlowFeetPerMeter,
            "width": Double(surface.dimensions.x) * roomFlowFeetPerMeter,
            "height": Double(surface.dimensions.y) * roomFlowFeetPerMeter,
            "sillHeight": max(0, openingBottom - wallBottom) * roomFlowFeetPerMeter,
            "confidence": confidenceValue(surface.confidence),
            "source": "apple-roomplan",
        ]
    }

    private static func confidenceValue(_ value: CapturedRoom.Confidence) -> Double {
        switch value {
        case .high: return 0.97
        case .medium: return 0.82
        case .low: return 0.62
        @unknown default: return 0.6
        }
    }
}
