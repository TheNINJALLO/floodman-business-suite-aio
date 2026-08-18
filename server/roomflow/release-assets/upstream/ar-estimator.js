// --- WEBAR CAMERA SPATIAL ESTIMATOR ENGINE ---
const METERS_TO_FEET = 3.280839895013123;

let videoStream = null;
let devicePitch = 45; // Degrees tilt down from horizontal
let deviceYaw = 0;
let manualYaw = 0;
let isUsingManualYaw = false;

// Standardized Spatial Points model:
// Stores raw high-precision metrics in meters
let spatialPoints = []; 
let pinnedPoints = []; // Computed relative layout points (feet) from first pinned point
let activeDistance = 0; // Active estimated distance to aim point (feet)

// Tracking Platform Tier State
let activeTier = 'CAMERA_ESTIMATE';
let appleCapabilities = null;
let webxrSession = null;
let webxrHitTestSource = null;
let webxrRefSpace = null;

// DOM Elements
const videoEl = document.getElementById('ar-video');
const distanceDisplay = document.getElementById('ar-distance');
const segmentDisplay = document.getElementById('ar-segment');
const pinBtn = document.getElementById('btn-ar-pin');
const finishBtn = document.getElementById('btn-ar-finish');
const resetBtn = document.getElementById('btn-ar-reset');
const cameraHeightInput = document.getElementById('ar-camera-height');
const tierBadge = document.getElementById('ar-tier-badge');
const qualityBadge = document.getElementById('ar-quality-badge');

// Create temporary WebGL canvas for WebXR rendering if needed
let xrCanvas = document.getElementById('xr-canvas');
if (!xrCanvas) {
    xrCanvas = document.createElement('canvas');
    xrCanvas.id = 'xr-canvas';
    xrCanvas.className = 'hidden';
    xrCanvas.style.position = 'absolute';
    xrCanvas.style.top = '0';
    xrCanvas.style.left = '0';
    xrCanvas.style.width = '100%';
    xrCanvas.style.height = '100%';
    xrCanvas.style.zIndex = '1';
    if (videoEl && videoEl.parentNode) {
        videoEl.parentNode.insertBefore(xrCanvas, videoEl);
    }
}

// Check Platform capabilities on script load
window.addEventListener('DOMContentLoaded', () => {
    detectSpatialCapabilities();
});

function detectSpatialCapabilities() {
    if (window.RoomFlowSpatial && window.RoomFlowSpatial.spatialManager) {
        window.RoomFlowSpatial.spatialManager.selectBestProvider().then(() => {
            updateARDisplay();
            updateQualityBadgeDisplay();
        });
    }
}

function fallbackToCameraEstimate() {
    activeTier = 'CAMERA_ESTIMATE';
    if (window.RoomFlowSpatial) {
        window.RoomFlowSpatial.globalCapabilities.immersiveARAvailable = false;
        window.RoomFlowSpatial.spatialManager.selectBestProvider().then(() => {
            updateQualityBadgeDisplay();
        });
    } else {
        if (tierBadge) tierBadge.innerText = 'CAMERA ESTIMATE';
        if (qualityBadge) qualityBadge.innerText = 'Orientation Only';
    }
}

function updateQualityBadgeDisplay() {
    if (!qualityBadge) return;
    if (activeTier === 'APPLE_LIDAR') {
        qualityBadge.innerText = 'LiDAR depth active';
    } else if (activeTier === 'APPLE_ARKIT') {
        qualityBadge.innerText = 'ARKit Depth Active';
    } else if (activeTier === 'WEBXR_DEPTH') {
        qualityBadge.innerText = 'WebXR Depth Active';
    } else if (activeTier === 'WEBXR_SPATIAL') {
        qualityBadge.innerText = 'WebXR Hit Test';
    } else if (activeTier === 'ANDROID_NATIVE') {
        qualityBadge.innerText = 'Native ARCore Active';
    } else {
        qualityBadge.innerText = 'Orientation Only';
    }
}

function updateAppleCapabilities(caps) {
    appleCapabilities = caps;
    window.appleCapabilities = caps;
    if (window.RoomFlowSpatial) {
        window.RoomFlowSpatial.globalCapabilities.appleLiDARAvailable = !!caps.lidarSupported;
        window.RoomFlowSpatial.globalCapabilities.roomPlanAvailable = !!caps.roomPlanSupported;
        window.RoomFlowSpatial.spatialManager.selectBestProvider().then(() => {
            updateQualityBadgeDisplay();
        });
    } else {
        if (caps.lidarSupported) {
            activeTier = 'APPLE_LIDAR';
            if (tierBadge) {
                tierBadge.innerText = 'APPLE LiDAR';
                tierBadge.style.background = 'rgba(16, 185, 129, 0.85)'; // Green badge for LiDAR
            }
            if (qualityBadge) qualityBadge.innerText = 'LiDAR depth active';
        } else {
            activeTier = 'APPLE_ARKIT';
            if (tierBadge) {
                tierBadge.innerText = 'APPLE ARKIT';
                tierBadge.style.background = 'rgba(59, 130, 246, 0.85)';
            }
            if (qualityBadge) qualityBadge.innerText = caps.sceneReconstructionSupported ? 'ARKit mesh building' : 'ARKit depth active';
        }
    }
}

function updateTrackingState(state) {
    if (!qualityBadge) return;
    const states = {
        'Initializing': 'Initializing tracking...',
        'Tracking': activeTier === 'APPLE_LIDAR' ? 'LiDAR depth active' : 'Spatial tracking active',
        'Limited': 'Limited tracking - Move slowly',
        'Lost': 'Tracking lost - Return to scanned area',
        'Relocalizing': 'Relocalizing position...'
    };
    qualityBadge.innerText = states[state] || state;
}

// Native Apple Bridge Message Handlers (callbacks from Swift)
window.RoomFlowNativeBridge = {
    spatialCapabilities: function(payloadStr) {
        try {
            const data = typeof payloadStr === 'string' ? JSON.parse(payloadStr) : payloadStr;
            updateAppleCapabilities(data.payload || data);
        } catch (e) {
            console.error('Error parsing spatialCapabilities:', e);
        }
    },
    trackingStateChanged: function(payloadStr) {
        try {
            const data = typeof payloadStr === 'string' ? JSON.parse(payloadStr) : payloadStr;
            const payload = data.payload || data;
            updateTrackingState(payload.state);
        } catch (e) {
            console.error('Error parsing trackingStateChanged:', e);
        }
    },
    reticlePoseChanged: function(payloadStr) {
        try {
            const data = typeof payloadStr === 'string' ? JSON.parse(payloadStr) : payloadStr;
            const payload = data.payload || data;
            activeDistance = payload.distanceFeet;
            
            // Check if native payload has raw meter coordinates for live aiming segment visualization
            if (payload.xMeters !== undefined && spatialPoints.length > 0) {
                const first = spatialPoints[0];
                const dx = (payload.xMeters - first.xMeters) * METERS_TO_FEET;
                const dy = (payload.zMeters - first.zMeters) * METERS_TO_FEET;
                const segmentDist = Math.sqrt(dx*dx + dy*dy);
                if (segmentDisplay) segmentDisplay.innerText = formatFeetInches(segmentDist);
            }
            if (distanceDisplay) distanceDisplay.innerText = formatFeetInches(activeDistance);
        } catch (e) {
            console.error('Error parsing reticlePoseChanged:', e);
        }
    },
    pointPinned: function(payloadStr) {
        try {
            const data = typeof payloadStr === 'string' ? JSON.parse(payloadStr) : payloadStr;
            const payload = data.payload || data;
            
            // Push standardized coordinate format
            addSpatialPoint({
                id: payload.id || 'pt_' + Date.now(),
                xMeters: payload.xMeters,
                yMeters: payload.yMeters,
                zMeters: payload.zMeters,
                source: payload.source || (activeTier === 'APPLE_LIDAR' ? 'arkit-lidar' : 'arkit'),
                timestamp: payload.timestamp || new Date().toISOString(),
                levelId: state.currentLevelId,
                trackingState: 'Tracking',
                depthValidated: payload.depthValidated !== false
            });
        } catch (e) {
            console.error('Error parsing pointPinned:', e);
        }
    },
    heightMeasured: function(payloadStr) {
        try {
            const data = typeof payloadStr === 'string' ? JSON.parse(payloadStr) : payloadStr;
            const payload = data.payload || data;
            updateHeightMeasurement(payload.heightFeet);
        } catch (e) {
            console.error('Error parsing heightMeasured:', e);
        }
    },
    sessionError: function(payloadStr) {
        alert('Apple Spatial Session Error. Falling back to Camera Estimate.');
        fallbackToCameraEstimate();
    }
};

function addSpatialPoint(pt) {
    spatialPoints.push(pt);
    
    // Convert meters to layout feet coordinate system relative to the first pinned point.
    // In ARKit & WebXR coordinate frames, X is horizontal right, Z is horizontal depth (forward/back).
    const first = spatialPoints[0];
    pinnedPoints = spatialPoints.map(p => ({
        x: (p.xMeters - first.xMeters) * METERS_TO_FEET,
        y: (p.zMeters - first.zMeters) * METERS_TO_FEET
    }));
    
    updateARDisplay();
    triggerSpatialFeedback();
}

function triggerSpatialFeedback() {
    // 1. Haptic vibration feedback
    if (typeof navigator !== 'undefined' && typeof navigator.vibrate === 'function') {
        navigator.vibrate(80);
    }
    
    // 2. Audible feedback (beep) if not muted
    if (typeof state !== 'undefined' && !state.arMuteAudio) {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            
            osc.frequency.setValueAtTime(880, ctx.currentTime);
            gain.gain.setValueAtTime(0.04, ctx.currentTime);
            
            osc.start();
            osc.stop(ctx.currentTime + 0.08);
        } catch (e) {
            console.warn("Audio Context playback blocked or unsupported:", e);
        }
    }
}

function updateHeightMeasurement(heightFeet) {
    const selectedRoom = state.rooms.find(r => r.id === state.selectedRoomId);
    if (selectedRoom) {
        selectedRoom.h = Math.max(4, Math.round(heightFeet));
        updateGlobalStats();
        if (window.sync3D) window.sync3D();
        alert(`Measured Ceiling Height: ${heightFeet.toFixed(1)} ft. Applied to ${selectedRoom.name}.`);
    } else {
        alert(`Measured Ceiling Height: ${heightFeet.toFixed(1)} ft. Select a room to apply this height.`);
    }
}

// Request Camera access / Initialize active mode session
window.startCamera = function(skipSplash) {
    spatialPoints = [];
    pinnedPoints = [];
    updateARDisplay();

    // Show the splash screen first to comply with browser user-gesture requirements
    const arSplash = document.getElementById('ar-splash');
    if (arSplash && !skipSplash) {
        arSplash.style.display = 'flex';
        
        // Update title and description dynamically
        const splashTitle = document.getElementById('ar-splash-title');
        const splashDesc = document.getElementById('ar-splash-desc');
        
        if (activeTier === 'APPLE_LIDAR') {
            if (splashTitle) splashTitle.innerText = "Apple LiDAR Scanner";
            if (splashDesc) splashDesc.innerText = "Utilizes iPhone/iPad Pro LiDAR depth sensors for sub-inch spatial room blueprint estimation.";
        } else if (activeTier === 'APPLE_ARKIT') {
            if (splashTitle) splashTitle.innerText = "Apple Spatial AR Scanner";
            if (splashDesc) splashDesc.innerText = "Uses native ARKit world tracking to map rooms and boundaries in real-time.";
        } else if (activeTier === 'WEBXR_SPATIAL') {
            if (splashTitle) splashTitle.innerText = "Spatial AR Scanner (WebXR)";
            if (splashDesc) splashDesc.innerText = "Requires camera and spatial tracking permissions to detect surfaces and pin corners.";
        } else {
            if (splashTitle) splashTitle.innerText = "Camera Estimator";
            if (splashDesc) splashDesc.innerText = "Standard browser orientation fallback. Input device holding height and aim at floor corners.";
        }
    } else {
        if (arSplash) arSplash.style.display = 'none';
        initializeScannerSession();
    }
};

// Bind initialization button click (acts as the mandatory user gesture!)
document.getElementById('btn-ar-start-session').addEventListener('click', () => {
    const arSplash = document.getElementById('ar-splash');
    if (arSplash) arSplash.style.display = 'none';
    
    // Request device orientation permission synchronously on click (mandatory for iOS Safari)
    if (typeof DeviceOrientationEvent !== 'undefined' && 
        typeof DeviceOrientationEvent.requestPermission === 'function') {
        DeviceOrientationEvent.requestPermission()
            .then(permissionState => {
                if (permissionState === 'granted') {
                    window.addEventListener('deviceorientation', handleOrientation);
                }
            })
            .catch(console.error);
    } else {
        window.addEventListener('deviceorientation', handleOrientation);
    }

    // Request device motion permission synchronously on click (mandatory for iOS Safari)
    if (typeof DeviceMotionEvent !== 'undefined' && 
        typeof DeviceMotionEvent.requestPermission === 'function') {
        DeviceMotionEvent.requestPermission()
            .then(permissionState => {
                if (permissionState === 'granted') {
                    window.addEventListener('devicemotion', handleMotion);
                }
            })
            .catch(console.error);
    } else {
        window.addEventListener('devicemotion', handleMotion);
    }
    
    initializeScannerSession();
});

function initializeScannerSession() {
    if (activeTier === 'APPLE_LIDAR' || activeTier === 'APPLE_ARKIT') {
        // Hide standard video element as iOS shell renders camera overlay natively
        if (videoEl) videoEl.style.opacity = '0';
        
        window.webkit.messageHandlers.RoomFlowNativeBridge.postMessage(JSON.stringify({
            version: 1,
            type: 'startAppleSpatialSession',
            payload: {
                levelId: state.currentLevelId
            }
        }));
    } else if (activeTier === 'WEBXR_SPATIAL' || activeTier === 'WEBXR_DEPTH') {
        startWebXRSession();
    } else {
        // TIER C: Camera orientation estimate fallback
        if (videoEl) {
            videoEl.style.opacity = '1';
            videoEl.style.backgroundColor = 'transparent';
        }
        
        const constraints = {
            video: {
                facingMode: 'environment',
                width: { ideal: 1280 },
                height: { ideal: 720 }
            },
            audio: false
        };

        navigator.mediaDevices.getUserMedia(constraints)
            .then(stream => {
                videoStream = stream;
                videoEl.srcObject = stream;
                videoEl.play();
                requestOrientationPermission();
            })
            .catch(err => {
                console.error('Camera access failed:', err);
                alert('Unable to access camera. Showing simulation overlay.');
                videoEl.style.backgroundColor = '#1e293b';
            });
    }
}

// Stop Active AR Session
window.stopCamera = function() {
    const arSplash = document.getElementById('ar-splash');
    if (arSplash) arSplash.style.display = 'flex';

    if (activeTier === 'APPLE_LIDAR' || activeTier === 'APPLE_ARKIT') {
        window.webkit.messageHandlers.RoomFlowNativeBridge.postMessage(JSON.stringify({
            version: 1,
            type: 'stopAppleSpatialSession'
        }));
    } else if (webxrSession) {
        webxrSession.end();
    } else {
        if (videoStream) {
            videoStream.getTracks().forEach(track => track.stop());
            videoStream = null;
        }
        videoEl.srcObject = null;
    }
};

// // Android WebXR spatial session initializer
function startWebXRSession() {
    if (videoEl) videoEl.style.opacity = '0';
    if (xrCanvas) xrCanvas.classList.remove('hidden');
    
    // Progressive session option attempts to gracefully handle lack of permissions or features
    const attempts = [
        {
            requiredFeatures: ['local'],
            optionalFeatures: ['local-floor', 'hit-test', 'anchors', 'depth-sensing', 'dom-overlay'],
            depthSensing: {
                usagePreference: ['cpu-optimized', 'gpu-optimized'],
                dataFormatPreference: ['float32', 'luminance-alpha']
            },
            domOverlay: { root: document.body }
        },
        {
            requiredFeatures: ['local'],
            optionalFeatures: ['local-floor', 'hit-test', 'anchors', 'dom-overlay'],
            domOverlay: { root: document.body }
        },
        {
            requiredFeatures: ['local'],
            optionalFeatures: ['local-floor', 'hit-test', 'dom-overlay'],
            domOverlay: { root: document.body }
        },
        {
            requiredFeatures: ['local'],
            optionalFeatures: ['dom-overlay'],
            domOverlay: { root: document.body }
        },
        {
            requiredFeatures: ['local']
        }
    ];

    let attemptIndex = 0;

    function tryNextSession() {
        if (attemptIndex >= attempts.length) {
            console.error('All progressive WebXR session attempts failed.');
            alert('Immersive WebXR AR sessions are unavailable in the current browser.');
            fallbackToCameraEstimate();
            window.startCamera(true);
            return;
        }

        const options = attempts[attemptIndex];
        const attemptLabel = `Attempt ${attemptIndex + 1}: req=[${options.requiredFeatures.join(',')}], opt=[${(options.optionalFeatures || []).join(',')}]`;
        console.log(`Requesting WebXR Session - ${attemptLabel}`);
        
        if (window.RoomFlowSpatial) {
            window.RoomFlowSpatial.spatialManager.providers[2].name = `WebXR (${attemptLabel})`;
            window.RoomFlowSpatial.spatialManager.providers[3].name = `WebXR (${attemptLabel})`;
        }

        navigator.xr.requestSession('immersive-ar', options)
            .then(session => {
                console.log(`WebXR Session successfully created: ${attemptLabel}`);
                if (window.RoomFlowSpatial) {
                    window.RoomFlowSpatial.spatialManager.providers[2].name = 'WebXR Depth Sensing';
                    window.RoomFlowSpatial.spatialManager.providers[3].name = 'WebXR Hit-Testing';
                    window.RoomFlowSpatial.spatialManager.selectBestProvider();
                }
                initializeWebXRSession(session);
            })
            .catch(err => {
                console.warn(`WebXR configuration failed: ${attemptLabel} - Error: ${err.message}`);
                attemptIndex++;
                tryNextSession();
            });
    }

    tryNextSession();
}

function initializeWebXRSession(session) {
    webxrSession = session;
    
    // Configure WebGL compatibility
    const gl = xrCanvas.getContext('webgl', { xrCompatible: true });
    session.updateRenderState({
        baseLayer: new XRWebGLLayer(session, gl)
    });
    
    // Request viewer space first to correctly bind requestHitTestSource
    session.requestReferenceSpace('viewer')
        .then(viewerSpace => {
            if (session.requestHitTestSource) {
                return session.requestHitTestSource({ space: viewerSpace });
            }
            return null;
        })
        .catch(err => {
            console.warn('Hit test source registration failed:', err);
            return null;
        })
        .then(hitTestSource => {
            webxrHitTestSource = hitTestSource;
            
            // Request tracking reference space ('local-floor' or 'local')
            return session.requestReferenceSpace('local-floor')
                .catch(() => session.requestReferenceSpace('local'));
        })
        .then(refSpace => {
            webxrRefSpace = refSpace;
            session.requestAnimationFrame(onXRFrame);
        })
        .catch(err => {
            console.error('WebXR tracking init failed:', err);
            session.requestAnimationFrame(onXRFrame);
        });
        
    session.addEventListener('end', () => {
        webxrSession = null;
        webxrHitTestSource = null;
        webxrRefSpace = null;
        if (xrCanvas) xrCanvas.classList.add('hidden');
        if (videoEl) videoEl.style.opacity = '1';
        fallbackToCameraEstimate();
    });
}

function onXRFrame(time, frame) {
    if (!webxrSession) return;
    
    webxrSession.requestAnimationFrame(onXRFrame);
    
    const pose = frame.getViewerPose(webxrRefSpace);
    if (!pose) return;

    // --- Dynamic Depth-Sensing Feature Extract ---
    if (window.RoomFlowSpatial && pose.views) {
        pose.views.forEach(view => {
            const depthInfo = window.RoomFlowSpatial.DepthProvider.getDepthFrame(view, frame);
            if (depthInfo) {
                const filtered = window.RoomFlowSpatial.DepthFrameProcessor.filterFrame(depthInfo);
                const cloud = window.RoomFlowSpatial.PointCloudBuilder.buildPointCloud(filtered, view.projectionMatrix, view.transform.matrix);
                
                // If point cloud has valid data, perform plane fits
                if (cloud.length > 50) {
                    const planes = window.RoomFlowSpatial.PlaneDetector.detectPlanes(cloud);
                    const floorY = window.RoomFlowSpatial.FloorDetector.locateFloor(planes);
                    const ceilingY = window.RoomFlowSpatial.CeilingDetector.locateCeiling(planes);
                    
                    // Display current depth stats in quality badge
                    if (qualityBadge) {
                        qualityBadge.innerText = `Depth Active: ${cloud.length} pts`;
                    }
                    
                    // Complement hit-test with depth-based active distance estimation if hit-test is delayed
                    if (!webxrHitTestSource && cloud.length > 0) {
                        // Use center pixel depth as active aim distance
                        const midIndex = Math.floor(filtered.width / 2) * filtered.width + Math.floor(filtered.height / 2);
                        let midDepth = filtered.rawValueType === 'float32' ? filtered.rawValue[midIndex] : filtered.rawValue[midIndex * 2] / 255.0;
                        if (midDepth > 0.1 && midDepth < 8.0) {
                            activeDistance = midDepth * STANDARD_METERS_TO_FEET;
                            distanceDisplay.innerText = formatFeetInches(activeDistance);
                        }
                    }
                }
            }
        });
    }
    
    if (!webxrHitTestSource) {
        if (devicePitch !== undefined) {
            const camHeightFeet = parseFloat(cameraHeightInput.value) / 12;
            const thetaDeg = 90 - devicePitch;
            const thetaRad = (thetaDeg * Math.PI) / 180;
            activeDistance = camHeightFeet * Math.tan(thetaRad);
            if (distanceDisplay) distanceDisplay.innerText = formatFeetInches(activeDistance) + " (Est.)";
        }
        return;
    }
    
    const hitTestResults = frame.getHitTestResults(webxrHitTestSource);
    if (hitTestResults.length > 0) {
        const hit = hitTestResults[0];
        const hitPose = hit.getPose(webxrRefSpace);
        
        if (hitPose) {
            // Compute real spatial distance in meters from viewer position to hit point
            const camPos = pose.transform.position;
            const hitPos = hitPose.transform.position;
            const dx = hitPos.x - camPos.x;
            const dy = hitPos.y - camPos.y;
            const dz = hitPos.z - camPos.z;
            
            // Standardize coordinates
            activeXRHitPoint = {
                xMeters: hitPos.x,
                yMeters: hitPos.y,
                zMeters: hitPos.z
            };
            
            activeDistance = Math.sqrt(dx*dx + dy*dy + dz*dz) * METERS_TO_FEET;
            distanceDisplay.innerText = formatFeetInches(activeDistance);
            
            // Update active aiming segment display
            if (spatialPoints.length > 0) {
                const first = spatialPoints[0];
                const segX = (hitPos.x - first.xMeters) * METERS_TO_FEET;
                const segZ = (hitPos.z - first.zMeters) * METERS_TO_FEET;
                const segmentDist = Math.sqrt(segX*segX + segZ*segZ);
                segmentDisplay.innerText = formatFeetInches(segmentDist);
            }
            if (qualityBadge && (!window.RoomFlowSpatial || !window.RoomFlowSpatial.globalCapabilities.depthSensingAvailable)) {
                qualityBadge.innerText = 'Spatial tracking active';
            }
        }
    } else {
        activeXRHitPoint = null;
        if (devicePitch !== undefined) {
            const camHeightFeet = parseFloat(cameraHeightInput.value) / 12;
            const thetaDeg = 90 - devicePitch;
            const thetaRad = (thetaDeg * Math.PI) / 180;
            activeDistance = camHeightFeet * Math.tan(thetaRad);
            if (distanceDisplay) distanceDisplay.innerText = formatFeetInches(activeDistance) + " (Est.)";
        }
        if (qualityBadge && (!window.RoomFlowSpatial || !window.RoomFlowSpatial.globalCapabilities.depthSensingAvailable)) {
            qualityBadge.innerText = 'Scan surface...';
        }
    }
}

let activeXRHitPoint = null;

// Orientation permissions and trackers (Tier C fallback)
function requestOrientationPermission() {
    if (typeof DeviceOrientationEvent === 'undefined' || 
        typeof DeviceOrientationEvent.requestPermission !== 'function') {
        window.addEventListener('deviceorientation', handleOrientation);
    }
    if (typeof DeviceMotionEvent === 'undefined' || 
        typeof DeviceMotionEvent.requestPermission !== 'function') {
        window.addEventListener('devicemotion', handleMotion);
    }
}

let smoothAx = 0;
let smoothAy = 9.8;
let smoothAz = 0;
const alpha = 0.12;

function handleMotion(e) {
    const acc = e.accelerationIncludingGravity;
    if (!acc) return;
    
    const rawX = acc.x || 0;
    const rawY = acc.y || 0;
    const rawZ = acc.z || 0;
    
    // Low pass filter
    smoothAx = smoothAx + alpha * (rawX - smoothAx);
    smoothAy = smoothAy + alpha * (rawY - smoothAy);
    smoothAz = smoothAz + alpha * (rawZ - smoothAz);
    
    const g = Math.sqrt(smoothAx * smoothAx + smoothAy * smoothAy + smoothAz * smoothAz);
    if (g > 0.1) {
        // Y-axis alignment with gravity
        const cosTheta = Math.abs(smoothAy) / g;
        const thetaRad = Math.acos(Math.max(-1.0, Math.min(1.0, cosTheta)));
        const thetaDeg = (thetaRad * 180) / Math.PI;
        
        if (thetaDeg >= 5 && thetaDeg <= 80) {
            devicePitch = thetaDeg;
            if (activeTier === 'CAMERA_ESTIMATE') {
                calculateDistance();
            }
        }
    }
}

function handleOrientation(e) {
    // Only fall back to orientation angles if device motion / accelerometer is not triggering updates
    if (smoothAx === 0 && smoothAy === 9.8) {
        let beta = e.beta || 90;
        beta = Math.max(15, Math.min(85, beta));
        devicePitch = 90 - beta;
        if (activeTier === 'CAMERA_ESTIMATE') {
            calculateDistance();
        }
    }
}

function calculateDistance() {
    // Trigonometry distance calculation (Tier C)
    const camHeightFeet = parseFloat(cameraHeightInput.value) / 12;
    const thetaRad = (devicePitch * Math.PI) / 180;
    activeDistance = camHeightFeet * Math.tan(thetaRad);
    updateARDisplay();
}

function formatFeetInches(feetVal) {
    const totalInches = Math.round(feetVal * 12);
    const feet = Math.floor(totalInches / 12);
    const inches = totalInches % 12;
    return `${feet}' ${inches}"`;
}

function updateARDisplay() {
    if (distanceDisplay) distanceDisplay.innerText = formatFeetInches(activeDistance);
    
    if (pinnedPoints.length > 0) {
        let currentPos;
        if (activeTier === 'WEBXR_SPATIAL' && activeXRHitPoint) {
            const first = spatialPoints[0];
            currentPos = {
                x: (activeXRHitPoint.xMeters - first.xMeters) * METERS_TO_FEET,
                y: (activeXRHitPoint.zMeters - first.zMeters) * METERS_TO_FEET
            };
        } else {
            currentPos = getTargetCoordinates();
        }
        
        const lastPoint = pinnedPoints[pinnedPoints.length - 1];
        const dx = currentPos.x - lastPoint.x;
        const dy = currentPos.y - lastPoint.y;
        const segmentDist = Math.sqrt(dx*dx + dy*dy);
        if (segmentDisplay) segmentDisplay.innerText = formatFeetInches(segmentDist);
        if (finishBtn) finishBtn.disabled = pinnedPoints.length < 3;
    } else {
        if (segmentDisplay) segmentDisplay.innerText = "0' 0\"";
        if (finishBtn) finishBtn.disabled = true;
    }

    const angleEl = document.getElementById('ar-angle');
    if (angleEl) {
        angleEl.innerText = `${Math.round(deviceYaw)}°${isUsingManualYaw ? ' (M)' : ''}`;
    }
}

function getTargetCoordinates() {
    const angleRad = (deviceYaw * Math.PI) / 180;
    return {
        x: activeDistance * Math.cos(angleRad),
        y: activeDistance * Math.sin(angleRad)
    };
}

window.addEventListener('deviceorientation', (e) => {
    if (e.alpha !== null && !isUsingManualYaw) {
        deviceYaw = e.alpha;
        updateARDisplay();
    }
});

// Swipe to adjust manual yaw on camera overlay
let touchStartX = 0;
if (videoEl) {
    videoEl.addEventListener('touchstart', (e) => {
        touchStartX = e.touches[0].clientX;
    }, { passive: true });

    videoEl.addEventListener('touchmove', (e) => {
        if (activeTier !== 'CAMERA_ESTIMATE') return;
        if (e.touches.length === 1) {
            const touchX = e.touches[0].clientX;
            const deltaX = touchX - touchStartX;
            touchStartX = touchX;
            
            isUsingManualYaw = true;
            manualYaw = (deviceYaw - deltaX * 0.5) % 360;
            if (manualYaw < 0) manualYaw += 360;
            deviceYaw = manualYaw;
            
            calculateDistance();
        }
    }, { passive: true });
}

// Mouse simulated controls for local desktop development tests
document.addEventListener('mousemove', (e) => {
    if (!videoStream && state.activeView === 'ar' && activeTier === 'CAMERA_ESTIMATE') {
        const percentX = e.clientX / window.innerWidth;
        const percentY = e.clientY / window.innerHeight;
        
        devicePitch = 15 + percentY * 60;
        deviceYaw = percentX * 360;
        
        calculateDistance();
    }
});

// Button Click Event Listeners
pinBtn.addEventListener('click', () => {
    if (activeTier === 'APPLE_LIDAR' || activeTier === 'APPLE_ARKIT') {
        // Send pin command to Apple native session
        window.webkit.messageHandlers.RoomFlowNativeBridge.postMessage(JSON.stringify({
            version: 1,
            type: 'pinPoint'
        }));
    } else if (activeTier === 'WEBXR_SPATIAL') {
        if (activeXRHitPoint) {
            addSpatialPoint({
                id: 'xr_' + Date.now(),
                xMeters: activeXRHitPoint.xMeters,
                yMeters: activeXRHitPoint.yMeters,
                zMeters: activeXRHitPoint.zMeters,
                source: 'webxr',
                timestamp: new Date().toISOString(),
                levelId: state.currentLevelId,
                trackingState: 'Tracking',
                depthValidated: true
            });
        } else {
            alert('Cannot pin corner: Pointing at invalid surface.');
        }
    } else {
        // TIER C orientation fallback coords
        const coords = getTargetCoordinates();
        const firstPoint = spatialPoints[0];
        
        // Convert feet layout points back to canonical meters structure
        const metersPt = {
            id: 'cam_' + Date.now(),
            xMeters: firstPoint ? (firstPoint.xMeters + coords.x / METERS_TO_FEET) : (coords.x / METERS_TO_FEET),
            yMeters: 0,
            zMeters: firstPoint ? (firstPoint.zMeters + coords.y / METERS_TO_FEET) : (coords.y / METERS_TO_FEET),
            source: 'camera',
            timestamp: new Date().toISOString(),
            levelId: state.currentLevelId,
            trackingState: 'Tracking',
            depthValidated: false
        };
        addSpatialPoint(metersPt);
    }
    
    // Action visual feedback animation
    const originalBg = pinBtn.style.backgroundColor;
    pinBtn.style.backgroundColor = '#10b981';
    setTimeout(() => { pinBtn.style.backgroundColor = originalBg; }, 150);
});

const captureBtn = document.getElementById('btn-ar-capture');
captureBtn.addEventListener('click', () => {
    if (activeDistance > 0.1) {
        if (!state.capturedMeasurements) {
            state.capturedMeasurements = [];
        }
        state.capturedMeasurements.push(activeDistance);
        
        const originalBg = captureBtn.style.backgroundColor;
        captureBtn.style.backgroundColor = '#10b981';
        setTimeout(() => { captureBtn.style.backgroundColor = originalBg; }, 150);
        
        updateARDisplay();
        updateARCapturesOverlay();
        if (window.updateMeasurementsSidebar) window.updateMeasurementsSidebar();
        triggerSpatialFeedback();
    } else {
        alert('Aim at a layout target point first.');
    }
});

// Bind audio toggle button in overlay
const audioToggleBtn = document.getElementById('btn-ar-audio-toggle');
if (audioToggleBtn) {
    audioToggleBtn.addEventListener('click', () => {
        state.arMuteAudio = !state.arMuteAudio;
        const icon = audioToggleBtn.querySelector('i');
        const span = audioToggleBtn.querySelector('span');
        if (state.arMuteAudio) {
            audioToggleBtn.style.opacity = '0.6';
            if (span) span.innerText = 'Muted';
        } else {
            audioToggleBtn.style.opacity = '1';
            if (span) span.innerText = 'Audio';
        }
    });
}

function updateARCapturesOverlay() {
    const listEl = document.getElementById('ar-captures-list');
    if (!listEl) return;
    
    if (!state.capturedMeasurements || state.capturedMeasurements.length === 0) {
        listEl.innerHTML = `<span class="empty-pills">No captures yet</span>`;
        return;
    }
    
    let html = '';
    state.capturedMeasurements.forEach(val => {
        html += `<span class="ar-capture-pill">${val.toFixed(1)} ft</span>`;
    });
    listEl.innerHTML = html;
}
window.updateARCapturesOverlay = updateARCapturesOverlay;

resetBtn.addEventListener('click', () => {
    if (activeTier === 'APPLE_LIDAR' || activeTier === 'APPLE_ARKIT') {
        window.webkit.messageHandlers.RoomFlowNativeBridge.postMessage(JSON.stringify({
            version: 1,
            type: 'resetScan'
        }));
    }
    
    spatialPoints = [];
    pinnedPoints = [];
    state.capturedMeasurements = [];
    
    updateARDisplay();
    updateARCapturesOverlay();
    if (window.updateMeasurementsSidebar) window.updateMeasurementsSidebar();
});

finishBtn.addEventListener('click', () => {
    if (pinnedPoints.length < 3) return;

    if (activeTier === 'APPLE_LIDAR' || activeTier === 'APPLE_ARKIT') {
        window.webkit.messageHandlers.RoomFlowNativeBridge.postMessage(JSON.stringify({
            version: 1,
            type: 'finishRoomScan'
        }));
    }

    // Normalized room polygon builder
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    pinnedPoints.forEach(p => {
        minX = Math.min(minX, p.x);
        maxX = Math.max(maxX, p.x);
        minY = Math.min(minY, p.y);
        maxY = Math.max(maxY, p.y);
    });

    const roomW = snap(maxX - minX);
    const roomL = snap(maxY - minY);

    if (roomW >= 2 && roomL >= 2) {
        const centerX = snap(toWorldX(canvas.width / 2) - roomW / 2);
        const centerY = snap(toWorldY(canvas.height / 2) - roomL / 2);

        // Convert coordinates from relative scan space to local room coordinate origin space.
        // We preserve full irregular polygon geometries as vertices relative to the bounding box top-left.
        const relativeVertices = pinnedPoints.map(p => ({
            x: snap(p.x - minX),
            y: snap(p.y - minY)
        }));

        // Preserve acquisition tracking source
        const finalSource = spatialPoints.length > 0 ? spatialPoints[0].source : 'camera';

        const newRoom = {
            id: 'r_' + Date.now(),
            levelId: state.currentLevelId,
            name: `AR ${finalSource === 'arkit-lidar' ? 'LiDAR' : 'Spatial'} Room`,
            type: 'custom',
            x: centerX,
            y: centerY,
            w: roomW,
            l: roomL,
            h: 8,
            color: '#ec4899',
            openings: [],
            vertices: relativeVertices,
            foamBoard: false,
            carbonStraps: 0,
            floorPerimeterStrap: false,
            nb1Height: 'none',
            scanMetadata: {
                source: finalSource,
                pointCount: spatialPoints.length,
                timestamp: new Date().toISOString()
            }
        };

        state.rooms.push(newRoom);
        selectRoom(newRoom.id);
        
        // Return back to 2D Blueprint grid layout view
        switchView('2d');
        updateGlobalStats();
        if (window.sync3D) window.sync3D();
        
        // End camera and tracking sessions
        window.stopCamera();
    } else {
        alert('Scanned corner layout footprint is too small.');
    }
});
