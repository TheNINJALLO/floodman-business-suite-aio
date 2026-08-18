import ARKit
import SceneKit
import UIKit
import simd

@available(iOS 17.0, *)
final class ARKitCaptureViewController: UIViewController, ARSessionDelegate {
    private struct HitSample {
        let point: SIMD3<Double>
        let confidence: Double
        let timestamp: TimeInterval
        let meshValidated: Bool
    }

    private let payload: RoomFlowCapturePayload
    private let completion: (Result<[String: Any], Error>) -> Void
    private let sceneView = ARSCNView(frame: .zero)
    private let statusLabel = UILabel()
    private let summaryLabel = UILabel()
    private let finishButton = UIButton(type: .system)
    private var samples: [HitSample] = []
    private var points: [SIMD3<Double>] = []
    private var confidences: [Double] = []
    private var meshValidated: [Bool] = []
    private var markers: [SCNNode] = []
    private var completed = false
    private var lidarAssisted = false
    private let startedAt = Date()

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
        sceneView.translatesAutoresizingMaskIntoConstraints = false
        sceneView.session.delegate = self
        sceneView.automaticallyUpdatesLighting = true
        view.addSubview(sceneView)
        NSLayoutConstraint.activate([
            sceneView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            sceneView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            sceneView.topAnchor.constraint(equalTo: view.topAnchor),
            sceneView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        ])
        installControls()
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(applicationEnteredBackground),
            name: UIApplication.didEnterBackgroundNotification,
            object: nil
        )
    }

    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        let configuration = ARWorldTrackingConfiguration()
        configuration.planeDetection = [.horizontal, .vertical]
        configuration.environmentTexturing = .automatic
        lidarAssisted = ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh)
        if lidarAssisted {
            configuration.sceneReconstruction = .mesh
        }
        sceneView.session.run(configuration, options: [.resetTracking, .removeExistingAnchors])
    }

    override func viewWillDisappear(_ animated: Bool) {
        sceneView.session.pause()
        super.viewWillDisappear(animated)
    }

    deinit { NotificationCenter.default.removeObserver(self) }

    private func installControls() {
        statusLabel.text = "ARKit fallback is active. Aim the center reticle at each floor-level wall corner and hold steady. Verify every measurement afterward; camera frames are never saved."
        statusLabel.textColor = .white
        statusLabel.font = .preferredFont(forTextStyle: .callout)
        statusLabel.numberOfLines = 0
        statusLabel.backgroundColor = UIColor.black.withAlphaComponent(0.74)
        statusLabel.layer.cornerRadius = 12
        statusLabel.layer.masksToBounds = true
        statusLabel.translatesAutoresizingMaskIntoConstraints = false

        let reticle = UIView()
        reticle.translatesAutoresizingMaskIntoConstraints = false
        reticle.layer.borderWidth = 2
        reticle.layer.borderColor = UIColor.systemTeal.cgColor
        reticle.layer.cornerRadius = 13

        summaryLabel.text = "0 corners"
        summaryLabel.textColor = .white
        summaryLabel.backgroundColor = UIColor.black.withAlphaComponent(0.7)
        summaryLabel.textAlignment = .center
        summaryLabel.layer.cornerRadius = 9
        summaryLabel.layer.masksToBounds = true
        summaryLabel.translatesAutoresizingMaskIntoConstraints = false

        let close = button("Close", #selector(confirmCancelCapture))
        let undo = button("Undo", #selector(undoPoint))
        let add = button("Add corner", #selector(addPoint))
        let reset = button("Reset", #selector(resetPoints))
        finishButton.configuration = buttonConfiguration("Finish room", color: .systemGreen)
        finishButton.addTarget(self, action: #selector(finishCapture), for: .touchUpInside)
        finishButton.isEnabled = false
        let row = UIStackView(arrangedSubviews: [close, undo, add, finishButton, reset])
        row.axis = .horizontal
        row.spacing = 6
        row.distribution = .fillEqually
        row.translatesAutoresizingMaskIntoConstraints = false

        view.addSubview(statusLabel)
        view.addSubview(reticle)
        view.addSubview(summaryLabel)
        view.addSubview(row)
        NSLayoutConstraint.activate([
            statusLabel.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 16),
            statusLabel.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -16),
            statusLabel.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 12),
            reticle.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            reticle.centerYAnchor.constraint(equalTo: view.centerYAnchor),
            reticle.widthAnchor.constraint(equalToConstant: 26),
            reticle.heightAnchor.constraint(equalToConstant: 26),
            summaryLabel.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 16),
            summaryLabel.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -16),
            summaryLabel.bottomAnchor.constraint(equalTo: row.topAnchor, constant: -8),
            summaryLabel.heightAnchor.constraint(greaterThanOrEqualToConstant: 38),
            row.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 8),
            row.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -8),
            row.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -10),
            row.heightAnchor.constraint(greaterThanOrEqualToConstant: 52),
        ])
    }

    private func button(_ title: String, _ action: Selector) -> UIButton {
        let value = UIButton(type: .system)
        value.configuration = buttonConfiguration(title, color: UIColor.black.withAlphaComponent(0.78))
        value.addTarget(self, action: action, for: .touchUpInside)
        return value
    }

    private func buttonConfiguration(_ title: String, color: UIColor) -> UIButton.Configuration {
        var configuration = UIButton.Configuration.filled()
        configuration.title = title
        configuration.baseBackgroundColor = color
        configuration.cornerStyle = .medium
        return configuration
    }

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        guard case .normal = frame.camera.trackingState else {
            DispatchQueue.main.async { self.statusLabel.text = "Move slowly while ARKit finds the room surfaces." }
            return
        }
        DispatchQueue.main.async {
            let center = CGPoint(x: self.sceneView.bounds.midX, y: self.sceneView.bounds.midY)
            guard let query = self.sceneView.raycastQuery(from: center, allowing: .estimatedPlane, alignment: .any),
                  let result = self.sceneView.session.raycast(query).first else { return }
            let translation = result.worldTransform.columns.3
            let isMesh = result.anchor is ARMeshAnchor
            self.samples.append(HitSample(
                point: SIMD3<Double>(Double(translation.x), Double(translation.y), Double(translation.z)),
                confidence: isMesh ? 0.9 : (result.anchor is ARPlaneAnchor ? 0.82 : 0.7),
                timestamp: Date().timeIntervalSince1970,
                meshValidated: isMesh
            ))
            let cutoff = Date().timeIntervalSince1970 - 0.9
            self.samples = Array(self.samples.filter { $0.timestamp >= cutoff }.suffix(20))
        }
    }

    @objc private func addPoint() {
        do {
            let hit = try stabilizedHit()
            if let previous = points.last, simd_distance(previous, hit.point) < 0.0762 {
                throw RoomFlowCaptureError.invalid("Move to the next corner; this point is too close to the previous point.")
            }
            if points.contains(where: { simd_distance($0, hit.point) > 91.44 }) {
                throw RoomFlowCaptureError.invalid("This point exceeds the 300 ft room limit. Reset and scan again.")
            }
            if points.count >= 3, let first = points.first, simd_distance(first, hit.point) <= 0.2286 {
                throw RoomFlowCaptureError.invalid("The outline is close enough to finish. Tap Finish room instead of adding the first point again.")
            }
            points.append(hit.point)
            confidences.append(hit.confidence)
            meshValidated.append(hit.meshValidated)
            let sphere = SCNSphere(radius: 0.035)
            sphere.firstMaterial?.diffuse.contents = UIColor.systemTeal
            let node = SCNNode(geometry: sphere)
            node.simdPosition = SIMD3<Float>(Float(hit.point.x), Float(hit.point.y), Float(hit.point.z))
            sceneView.scene.rootNode.addChildNode(node)
            markers.append(node)
            UIImpactFeedbackGenerator(style: .medium).impactOccurred()
            updateSummary("Corner \(points.count) added.")
        } catch {
            statusLabel.text = error.localizedDescription
        }
    }

    private func stabilizedHit() throws -> HitSample {
        let recent = samples.filter { Date().timeIntervalSince1970 - $0.timestamp <= 0.75 && $0.confidence >= 0.6 }
        guard recent.count >= 3 else { throw RoomFlowCaptureError.invalid("Hold steady until at least three reliable AR points are available.") }
        func median(_ values: [Double]) -> Double {
            let sorted = values.sorted()
            let middle = sorted.count / 2
            return sorted.count.isMultiple(of: 2) ? (sorted[middle - 1] + sorted[middle]) / 2 : sorted[middle]
        }
        let point = SIMD3<Double>(median(recent.map { $0.point.x }), median(recent.map { $0.point.y }), median(recent.map { $0.point.z }))
        guard recent.map({ simd_distance($0.point, point) }).max() ?? 1 <= 0.10 else {
            throw RoomFlowCaptureError.invalid("Hold the reticle steady on one corner before adding it.")
        }
        let meshCount = recent.filter(\.meshValidated).count
        let mesh = meshCount >= (recent.count + 1) / 2
        let confidence = min(1, max(0, recent.map(\.confidence).reduce(0, +) / Double(recent.count) + (mesh ? 0.04 : -0.08)))
        return HitSample(point: point, confidence: confidence, timestamp: Date().timeIntervalSince1970, meshValidated: mesh)
    }

    @objc private func undoPoint() {
        guard !points.isEmpty else { return }
        points.removeLast()
        confidences.removeLast()
        meshValidated.removeLast()
        markers.removeLast().removeFromParentNode()
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
        updateSummary("Last corner removed.")
    }

    @objc private func resetPoints() {
        points.removeAll()
        confidences.removeAll()
        meshValidated.removeAll()
        markers.forEach { $0.removeFromParentNode() }
        markers.removeAll()
        samples.removeAll()
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
        updateSummary("Ready to start again.")
    }

    private func updateSummary(_ message: String) {
        summaryLabel.text = "\(points.count) corner\(points.count == 1 ? "" : "s") · \(message)"
        finishButton.isEnabled = points.count >= 3
    }

    @objc private func finishCapture() {
        do {
            let capturePoints = points.indices.map { index in
                RoomFlowCapturePoint(
                    xMeters: points[index].x,
                    zMeters: points[index].z,
                    confidence: confidences[index],
                    depthValidated: meshValidated[index]
                )
            }
            let result = try RoomFlowCaptureResultBuilder.build(
                payload: payload,
                points: capturePoints,
                heightFeet: payload.defaultHeightFeet,
                mode: lidarAssisted ? "apple-arkit-lidar" : "apple-arkit-guided",
                warnings: ["ARKit fallback capture requires manual verification of every wall and opening."],
                startedAt: startedAt
            )
            finish(.success(result))
        } catch {
            statusLabel.text = error.localizedDescription
        }
    }

    @objc private func confirmCancelCapture() {
        guard !points.isEmpty else { finish(.failure(RoomFlowCaptureError.cancelled)); return }
        let alert = UIAlertController(
            title: "Discard this room scan?",
            message: "The captured corners will be cleared. Your existing Floodman job will not change.",
            preferredStyle: .alert
        )
        alert.addAction(UIAlertAction(title: "Keep scanning", style: .cancel))
        alert.addAction(UIAlertAction(title: "Discard scan", style: .destructive) { [weak self] _ in
            self?.finish(.failure(RoomFlowCaptureError.cancelled))
        })
        present(alert, animated: true)
    }

    func session(_ session: ARSession, cameraDidChangeTrackingState camera: ARCamera) {
        let message: String
        switch camera.trackingState {
        case .normal:
            return
        case .notAvailable:
            message = "AR tracking is unavailable. Keep the camera uncovered or enter the room manually."
        case .limited(.relocalizing):
            message = "Floodman is restoring the room position. Return to a previously scanned corner and move slowly."
        case .limited(.excessiveMotion):
            message = "Tracking is limited. Move the device more slowly."
        case .limited(.insufficientFeatures):
            message = "Tracking is limited. Point toward an area with more visible detail."
        case .limited(.initializing):
            message = "Move slowly while ARKit finds the room surfaces."
        @unknown default:
            message = "Tracking is limited. Hold steady and try again."
        }
        DispatchQueue.main.async { self.statusLabel.text = message }
    }

    @objc private func applicationEnteredBackground() {
        guard !completed else { return }
        finish(.failure(RoomFlowCaptureError.interrupted))
    }

    private func finish(_ result: Result<[String: Any], Error>) {
        guard !completed else { return }
        completed = true
        sceneView.session.pause()
        completion(result)
    }
}
