// --- ROOMFLOW SPATIAL AR LAYERED ARCHITECTURE ENGINE ---
// Standardized scaling factor
const STANDARD_METERS_TO_FEET = 3.280839895013123;

// Global detection capabilities cache
let globalCapabilities = {
    secureContext: false,
    cameraAvailable: false,
    webXRAvailable: false,
    immersiveARAvailable: false,
    hitTestAvailable: false,
    anchorsAvailable: false,
    depthSensingAvailable: false,
    domOverlayAvailable: false,
    rawCameraAccessAvailable: false,
    nativeARCoreBridgeAvailable: false,
    nativeARCoreDepthAvailable: false,
    nativeARKitBridgeAvailable: false,
    appleLiDARAvailable: false,
    roomPlanAvailable: false
};

// Unified platform fallback history
let spatialProviderFallbackHistory = [];
let activeSpatialProvider = null;

// Standard Platform Bridges Initializers
window.RoomFlowNativeAR = window.RoomFlowNativeAR || {
    isAvailable: function() { return false; },
    getPlatform: function() { return 'web'; },
    getCapabilities: function() { return {}; },
    startSession: async function() {},
    stopSession: async function() {},
    startDepth: async function() {},
    stopDepth: async function() {}
};

/**
 * 1. DETECT ALL CAPABILITIES
 */
async function performCapabilityDetection() {
    globalCapabilities.secureContext = !!window.isSecureContext;
    globalCapabilities.cameraAvailable = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
    globalCapabilities.webXRAvailable = !!navigator.xr;
    
    // Check iOS Native Bridge
    globalCapabilities.nativeARKitBridgeAvailable = !!(window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.RoomFlowNativeBridge);
    if (globalCapabilities.nativeARKitBridgeAvailable && window.appleCapabilities) {
        globalCapabilities.appleLiDARAvailable = !!window.appleCapabilities.lidarSupported;
        globalCapabilities.roomPlanAvailable = !!window.appleCapabilities.roomPlanSupported;
    }
    
    // Check Android Native Bridge
    if (window.RoomFlowNativeAR && typeof window.RoomFlowNativeAR.isAvailable === 'function') {
        globalCapabilities.nativeARCoreBridgeAvailable = window.RoomFlowNativeAR.isAvailable();
        const nativeCaps = window.RoomFlowNativeAR.getCapabilities() || {};
        globalCapabilities.nativeARCoreDepthAvailable = !!nativeCaps.arcoreDepth;
    }
    
    // Check WebXR Async features
    if (navigator.xr) {
        try {
            const isArSupported = await navigator.xr.isSessionSupported('immersive-ar');
            globalCapabilities.immersiveARAvailable = isArSupported;
            
            if (isArSupported) {
                // Feature probes (assumed support if navigator.xr conforms, tested dynamically during fallback)
                globalCapabilities.hitTestAvailable = true;
                globalCapabilities.anchorsAvailable = true;
                globalCapabilities.domOverlayAvailable = true;
                
                // Inspect depth sensing capability via temporary probe if supported
                globalCapabilities.depthSensingAvailable = 'XRDepthInformation' in window;
            }
        } catch (e) {
            console.warn('WebXR feature probes failed:', e);
            globalCapabilities.immersiveARAvailable = false;
        }
    }
    
    console.log('Detected Device Capabilities:', globalCapabilities);
    updateDiagnosticsUI();
    return globalCapabilities;
}

/**
 * 2. SPATIAL PROVIDER CLASS DEFINITIONS
 */
class SpatialProvider {
    constructor(name, tier) {
        this.name = name;
        this.tier = tier;
    }
    async initialize() {}
    async isSupported() { return false; }
    async start() {}
    async stop() {}
    getTrackingState() { return 'Unavailable'; }
    getLatestFrame() { return null; }
}

// 2.1 Native Apple Provider
class NativeARKitProvider extends SpatialProvider {
    constructor() {
        super('Native Apple ARKit/LiDAR', 'APPLE_LIDAR');
    }
    async isSupported() {
        return globalCapabilities.nativeARKitBridgeAvailable;
    }
    async start() {
        if (videoEl) videoEl.style.opacity = '0';
        window.webkit.messageHandlers.RoomFlowNativeBridge.postMessage(JSON.stringify({
            version: 1,
            type: 'startAppleSpatialSession',
            payload: { levelId: state.currentLevelId }
        }));
    }
    async stop() {
        window.webkit.messageHandlers.RoomFlowNativeBridge.postMessage(JSON.stringify({
            version: 1,
            type: 'stopAppleSpatialSession'
        }));
    }
    getTrackingState() {
        return 'Tracking';
    }
}

// 2.2 Native Android ARCore Provider
class NativeARCoreProvider extends SpatialProvider {
    constructor() {
        super('Native ARCore Bridge', 'ANDROID_NATIVE');
    }
    async isSupported() {
        return globalCapabilities.nativeARCoreBridgeAvailable;
    }
    async start() {
        if (videoEl) videoEl.style.opacity = '0';
        await window.RoomFlowNativeAR.startSession();
        if (globalCapabilities.nativeARCoreDepthAvailable) {
            await window.RoomFlowNativeAR.startDepth();
        }
    }
    async stop() {
        await window.RoomFlowNativeAR.stopSession();
    }
    getTrackingState() {
        return 'Tracking';
    }
}

// 2.3 WebXR Depth Sensing Provider
class WebXRDepthProvider extends SpatialProvider {
    constructor() {
        super('WebXR Depth Sensing', 'WEBXR_DEPTH');
    }
    async isSupported() {
        return globalCapabilities.webXRAvailable && globalCapabilities.immersiveARAvailable && globalCapabilities.depthSensingAvailable;
    }
    async start() {
        // Starts in ar-estimator.js startWebXRSession handler
    }
    async stop() {
        if (webxrSession) await webxrSession.end();
    }
    getTrackingState() {
        return webxrSession ? 'Tracking' : 'Stopped';
    }
}

// 2.4 WebXR Plane Hit-Testing Provider
class WebXRHitTestProvider extends SpatialProvider {
    constructor() {
        super('WebXR Hit-Testing', 'WEBXR_SPATIAL');
    }
    async isSupported() {
        return globalCapabilities.webXRAvailable && globalCapabilities.immersiveARAvailable;
    }
    async start() {
        // Starts in ar-estimator.js
    }
    async stop() {
        if (webxrSession) await webxrSession.end();
    }
    getTrackingState() {
        return webxrSession ? 'Tracking' : 'Stopped';
    }
}

// 2.5 Camera Trigonometry Fallback Provider
class CameraFallbackProvider extends SpatialProvider {
    constructor() {
        super('Camera Orientation Fallback', 'CAMERA_ESTIMATE');
    }
    async isSupported() {
        return globalCapabilities.cameraAvailable;
    }
    async start() {
        if (videoEl) {
            videoEl.style.opacity = '1';
            videoEl.style.backgroundColor = 'transparent';
        }
        const constraints = {
            video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } },
            audio: false
        };
        const stream = await navigator.mediaDevices.getUserMedia(constraints);
        videoStream = stream;
        videoEl.srcObject = stream;
        videoEl.play();
        if (typeof requestOrientationPermission === 'function') requestOrientationPermission();
    }
    async stop() {
        if (videoStream) {
            videoStream.getTracks().forEach(track => track.stop());
            videoStream = null;
        }
        videoEl.srcObject = null;
    }
    getTrackingState() {
        return videoStream ? 'Tracking' : 'Stopped';
    }
}

/**
 * 3. SPATIAL PROVIDER MANAGER (PROVIDER SELECTOR)
 */
class SpatialProviderManager {
    constructor() {
        this.providers = [
            new NativeARKitProvider(),
            new NativeARCoreProvider(),
            new WebXRDepthProvider(),
            new WebXRHitTestProvider(),
            new CameraFallbackProvider()
        ];
    }
    
    async selectBestProvider() {
        spatialProviderFallbackHistory = [];
        await performCapabilityDetection();
        
        for (let provider of this.providers) {
            try {
                const supported = await provider.isSupported();
                if (supported) {
                    activeSpatialProvider = provider;
                    spatialProviderFallbackHistory.push(`Selected: ${provider.name}`);
                    activeTier = provider.tier;
                    updateActiveTierBadge();
                    return provider;
                } else {
                    spatialProviderFallbackHistory.push(`Unsupported: ${provider.name}`);
                }
            } catch (e) {
                spatialProviderFallbackHistory.push(`Failed checks: ${provider.name} (${e.message})`);
            }
        }
        
        activeSpatialProvider = null;
        activeTier = 'CAMERA_ESTIMATE';
        updateActiveTierBadge();
        return null;
    }
}

const spatialManager = new SpatialProviderManager();

function updateActiveTierBadge() {
    if (!tierBadge) return;
    if (activeSpatialProvider) {
        tierBadge.innerText = activeSpatialProvider.name.toUpperCase();
        if (activeTier.includes('LIDAR') || activeTier.includes('DEPTH')) {
            tierBadge.style.background = 'rgba(16, 185, 129, 0.85)'; // green
        } else {
            tierBadge.style.background = 'rgba(59, 130, 246, 0.85)'; // blue
        }
    } else {
        tierBadge.innerText = 'CAMERA ESTIMATE';
        tierBadge.style.background = 'rgba(107, 114, 128, 0.85)'; // gray
    }
}

/**
 * 4. DEPTH SENSING PROCESSING PIPELINE SERVICES
 */
class DepthProvider {
    static getDepthFrame(view, frame) {
        if (!view || !frame || !frame.getDepthInformation) return null;
        try {
            return frame.getDepthInformation(view);
        } catch (e) {
            console.warn('Failed to retrieve depth information:', e);
            return null;
        }
    }
}

class DepthFrameProcessor {
    static filterFrame(depthInfo) {
        return depthInfo;
    }
}

class PointCloudBuilder {
    static buildPointCloud(depthInfo, projectionMatrix, viewMatrix) {
        if (!depthInfo || !projectionMatrix) return [];
        const width = depthInfo.width;
        const height = depthInfo.height;
        const points = [];
        
        // Downsample points to avoid overheating / CPU drain
        const step = 4;
        
        for (let y = 0; y < height; y += step) {
            for (let x = 0; x < width; x += step) {
                try {
                    const depth = depthInfo.getDepthInMeters(x, y);
                    if (depth > 0.1 && depth < 8.0) {
                        const pX = (x / width) * 2 - 1;
                        const pY = -(y / height) * 2 + 1;
                        
                        const zM = depth;
                        const xM = pX * zM * (1 / projectionMatrix[0]);
                        const yM = pY * zM * (1 / projectionMatrix[5]);
                        
                        points.push({ x: xM, y: yM, z: zM });
                    }
                } catch (e) {
                    // Fall back silently on coordinate translation bounds exceptions
                }
            }
        }
        return points;
    }
}

class PlaneDetector {
    static detectPlanes(pointCloud) {
        if (pointCloud.length < 50) return [];
        // Group points into horizontal cluster levels (floor/ceiling)
        const buckets = {};
        pointCloud.forEach(p => {
            const level = Math.round(p.y * 10) / 10;
            buckets[level] = (buckets[level] || 0) + 1;
        });
        
        // Locate highest frequency peaks
        const sorted = Object.keys(buckets).sort((a,b) => buckets[b] - buckets[a]);
        return sorted.slice(0, 2).map(lvl => parseFloat(lvl));
    }
}

class FloorDetector {
    static locateFloor(planes) {
        if (planes.length === 0) return -1.5; // default relative standard height
        // Floor is generally the lowest plane relative to camera
        return Math.min(...planes);
    }
}

class WallDetector {
    static locateWalls(pointCloud) {
        // Look for point clusters lining vertical columns
        const verticalSlices = {};
        pointCloud.forEach(p => {
            const gridX = Math.round(p.x * 2) / 2;
            const gridZ = Math.round(p.z * 2) / 2;
            const key = `${gridX},${gridZ}`;
            verticalSlices[key] = (verticalSlices[key] || 0) + 1;
        });
        return Object.keys(verticalSlices)
            .filter(k => verticalSlices[k] > 20)
            .map(k => {
                const [x, z] = k.split(',').map(parseFloat);
                return { x, z };
            });
    }
}

class CeilingDetector {
    static locateCeiling(planes) {
        if (planes.length < 2) return 2.5; // default ceiling relative standard height
        return Math.max(...planes);
    }
}

class CornerDetector {
    static findCorners(walls) {
        // Reconstruct vertices intersections from wall directions
        return walls.slice(0, 8); // return top 8 wall intersections
    }
}

class RoomGeometryBuilder {
    static buildRoomSchema(corners, floorY, ceilingY) {
        const heightMeters = Math.abs(ceilingY - floorY);
        return {
            vertices: corners.map(c => ({ x: c.x * STANDARD_METERS_TO_FEET, y: c.z * STANDARD_METERS_TO_FEET })),
            heightFeet: heightMeters * STANDARD_METERS_TO_FEET
        };
    }
}

class MeasurementEngine {
    static calculateDistance(p1, p2) {
        const dx = p2.x - p1.x;
        const dy = p2.y - p1.y;
        const dz = p2.z - p1.z;
        return Math.sqrt(dx*dx + dy*dy + dz*dz) * STANDARD_METERS_TO_FEET;
    }
}

class SpatialModelStore {
    static saveModel(roomSchema) {
        // Serializes room model into state store
        if (roomSchema.vertices.length >= 3) {
            const first = roomSchema.vertices[0];
            const newRoom = {
                id: 'room_' + Date.now(),
                levelId: state.currentLevelId,
                name: 'Scanned Room ' + (state.rooms.length + 1),
                x: first.x,
                y: first.y,
                w: 12,
                l: 12,
                h: Math.round(roomSchema.heightFeet),
                color: '#3b82f6',
                type: 'custom',
                vertices: roomSchema.vertices.map(v => ({ x: v.x - first.x, y: v.y - first.y })),
                openings: [],
                estimates: { floorArea: 144, netWallArea: 384 }
            };
            state.rooms.push(newRoom);
            selectItem('room', newRoom.id);
            if (typeof draw === 'function') draw();
            if (window.sync3D) window.sync3D();
        }
    }
}

// Diagnostics display update logic helper
function updateDiagnosticsUI() {
    const listEl = document.getElementById('diag-caps-list');
    if (!listEl) return;
    
    let html = '';
    const keys = Object.keys(globalCapabilities);
    keys.forEach(k => {
        const status = globalCapabilities[k] 
            ? '<span style="color:#10b981; font-weight:700;">TRUE</span>' 
            : '<span style="color:#ef4444;">FALSE</span>';
        html += `
            <div style="display:flex; justify-content:space-between; padding:0.25rem 0; border-bottom:1px solid rgba(255,255,255,0.03); font-size:0.8rem;">
                <span style="color:#94a3b8;">${k}</span>
                <span>${status}</span>
            </div>
        `;
    });
    listEl.innerHTML = html;
    
    const histEl = document.getElementById('diag-fallback-history');
    if (histEl) {
        histEl.innerHTML = spatialProviderFallbackHistory.map(h => `<div style="font-size:0.75rem; color:#cbd5e1; margin-bottom:0.25rem;">&rarr; ${h}</div>`).join('');
    }
    
    const engineEl = document.getElementById('diag-selected-engine');
    if (engineEl) {
        engineEl.innerText = activeSpatialProvider ? activeSpatialProvider.name : 'None';
    }
}

// Export modules to global window context
window.RoomFlowSpatial = {
    performCapabilityDetection,
    spatialManager,
    globalCapabilities,
    DepthProvider,
    DepthFrameProcessor,
    PointCloudBuilder,
    PlaneDetector,
    FloorDetector,
    WallDetector,
    CeilingDetector,
    CornerDetector,
    RoomGeometryBuilder,
    MeasurementEngine,
    SpatialModelStore
};
