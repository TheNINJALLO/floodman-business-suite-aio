// --- THREE.JS 3D RENDERER ---
let scene, camera, renderer, controls;
let roomMeshes = [];
let showCeilings = false;
const wallThickness = 0.4; // 5 inches in feet

const container3d = document.getElementById('three-container');

function init3D() {
    // 1. Create Scene & Camera
    scene = new THREE.Scene();
    scene.background = new THREE.Color('#0d111a');
    
    // Add Fog for professional depth
    scene.fog = new THREE.FogExp2('#0d111a', 0.015);

    camera = new THREE.PerspectiveCamera(45, container3d.clientWidth / container3d.clientHeight, 0.1, 1000);
    camera.position.set(30, 40, 50);

    // 2. WebGL Renderer
    renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    renderer.setSize(container3d.clientWidth, container3d.clientHeight);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    container3d.appendChild(renderer.domElement);

    // 3. Orbit Controls
    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.maxPolarAngle = Math.PI / 2 - 0.05; // Don't go below floor level

    // 4. Lighting Rig
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
    scene.add(ambientLight);

    const dirLight1 = new THREE.DirectionalLight(0xffffff, 0.8);
    dirLight1.position.set(20, 40, 20);
    dirLight1.castShadow = true;
    dirLight1.shadow.mapSize.width = 2048;
    dirLight1.shadow.mapSize.height = 2048;
    dirLight1.shadow.bias = -0.0001;
    scene.add(dirLight1);

    const dirLight2 = new THREE.DirectionalLight(0x3b82f6, 0.3); // Accent blue fill
    dirLight2.position.set(-20, 20, -20);
    scene.add(dirLight2);

    // 5. Floor Grid Helper
    const gridHelper = new THREE.GridHelper(100, 100, '#1e293b', '#111827');
    gridHelper.position.y = -0.01;
    scene.add(gridHelper);

    // Start render loop
    animate();
}

function animate() {
    requestAnimationFrame(animate);
    if (state.activeView === '3d') {
        controls.update();
        renderer.render(scene, camera);
    }
}

// Resize Three.js container
window.resizeRenderer = function() {
    if (!renderer) return;
    camera.aspect = container3d.clientWidth / container3d.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(container3d.clientWidth, container3d.clientHeight);
};

// Rebuild the 3D meshes based on state
window.sync3D = function() {
    if (!scene) {
        init3D();
    }

    // Clear old meshes
    roomMeshes.forEach(mesh => scene.remove(mesh));
    roomMeshes = [];

    // Build floor, ceiling and joist planes for each room
    state.rooms.forEach(room => {
        const roomGroup = new THREE.Group();
        const level = state.levels.find(l => l.id === room.levelId) || { elevation: 0 };
        const elevation = level.elevation || 0;
        roomGroup.position.set(room.x, elevation, room.y); // Canvas Y maps to 3D Z

        if (room.type === 'staircase') {
            const stepCount = room.steps || 12;
            const riser = room.h / stepCount;
            const orient = room.stairOrientation || 'N';
            const slope = room.stairDirection || 'up';
            
            const stepMat = new THREE.MeshStandardMaterial({
                color: room.color,
                roughness: 0.75,
                metalness: 0.1
            });
            
            const isHorizontal = (orient === 'N' || orient === 'S');
            
            for (let i = 0; i < stepCount; i++) {
                let stepHeight;
                if (slope === 'up') {
                    stepHeight = (i + 1) * riser;
                } else {
                    stepHeight = (stepCount - i) * riser;
                }
                
                let stepGeo, stepMesh;
                
                if (isHorizontal) {
                    const tread = room.l / stepCount;
                    stepGeo = new THREE.BoxGeometry(room.w, stepHeight, tread);
                    stepMesh = new THREE.Mesh(stepGeo, stepMat);
                    
                    const stepZ = (orient === 'S') ? (i * tread + tread / 2) : ((stepCount - 1 - i) * tread + tread / 2);
                    stepMesh.position.set(room.w / 2, stepHeight / 2, stepZ);
                } else {
                    const tread = room.w / stepCount;
                    stepGeo = new THREE.BoxGeometry(tread, stepHeight, room.l);
                    stepMesh = new THREE.Mesh(stepGeo, stepMat);
                    
                    const stepX = (orient === 'E') ? (i * tread + tread / 2) : ((stepCount - 1 - i) * tread + tread / 2);
                    stepMesh.position.set(stepX, stepHeight / 2, room.l / 2);
                }
                
                stepMesh.castShadow = true;
                stepMesh.receiveShadow = true;
                roomGroup.add(stepMesh);
            }
        } else if (room.type === 'custom' && room.vertices && room.vertices.length >= 3) {
            // 1. Draw floor plane using Shape Geometry
            const shape = new THREE.Shape();
            shape.moveTo(room.vertices[0].x, room.vertices[0].y);
            for (let i = 1; i < room.vertices.length; i++) {
                shape.lineTo(room.vertices[i].x, room.vertices[i].y);
            }
            shape.closePath();
            
            const floorGeo = new THREE.ShapeGeometry(shape);
            const floorMat = new THREE.MeshStandardMaterial({
                color: room.color,
                roughness: 0.8,
                metalness: 0.1,
                side: THREE.DoubleSide
            });
            const floorMesh = new THREE.Mesh(floorGeo, floorMat);
            floorMesh.rotation.x = -Math.PI / 2;
            floorMesh.receiveShadow = true;
            roomGroup.add(floorMesh);

            // 2. Ceiling Plane (if visible)
            if (showCeilings) {
                const ceilMesh = floorMesh.clone();
                ceilMesh.position.y = room.h;
                roomGroup.add(ceilMesh);
            }
        } else {
            // 1. Floor Plane
            const floorGeo = new THREE.PlaneGeometry(room.w, room.l);
            const floorMat = new THREE.MeshStandardMaterial({
                color: room.color,
                roughness: 0.8,
                metalness: 0.1,
                side: THREE.DoubleSide
            });
            const floorMesh = new THREE.Mesh(floorGeo, floorMat);
            floorMesh.rotation.x = -Math.PI / 2;
            floorMesh.position.set(room.w / 2, 0, room.l / 2);
            floorMesh.receiveShadow = true;
            roomGroup.add(floorMesh);

            // 2. Ceiling Plane (if visible)
            if (showCeilings) {
                const ceilMesh = floorMesh.clone();
                ceilMesh.position.y = room.h;
                roomGroup.add(ceilMesh);
            }
        }

        // --- Render Floor Joists if set ---
        if (room.joists && room.joists !== 'none') {
            const joistMat = new THREE.MeshStandardMaterial({
                color: '#854d0e', // Wood brown
                roughness: 0.8,
                metalness: 0.1
            });
            const spacing = 1.333; // 16 inches spacing
            const jThick = 0.15;   // 2 inches wide
            const jHeight = 0.65;  // 8 inches deep
            
            if (room.type === 'custom' && room.vertices) {
                // Find bounding box
                let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
                room.vertices.forEach(v => {
                    if (v.x < minX) minX = v.x;
                    if (v.x > maxX) maxX = v.x;
                    if (v.y < minY) minY = v.y;
                    if (v.y > maxY) maxY = v.y;
                });
                
                if (room.joists === 'ns') {
                    for (let x = Math.ceil(minX / spacing) * spacing; x < maxX; x += spacing) {
                        const len = maxY - minY;
                        const joistGeo = new THREE.BoxGeometry(jThick, jHeight, len);
                        const joistMesh = new THREE.Mesh(joistGeo, joistMat);
                        joistMesh.position.set(x, room.h - jHeight/2, minY + len/2);
                        joistMesh.castShadow = true;
                        joistMesh.receiveShadow = true;
                        roomGroup.add(joistMesh);
                    }
                } else {
                    for (let y = Math.ceil(minY / spacing) * spacing; y < maxY; y += spacing) {
                        const len = maxX - minX;
                        const joistGeo = new THREE.BoxGeometry(len, jHeight, jThick);
                        const joistMesh = new THREE.Mesh(joistGeo, joistMat);
                        joistMesh.position.set(minX + len/2, room.h - jHeight/2, y);
                        joistMesh.castShadow = true;
                        joistMesh.receiveShadow = true;
                        roomGroup.add(joistMesh);
                    }
                }
            } else {
                // Rectangular / staircase rooms
                if (room.joists === 'ns') {
                    for (let x = spacing; x < room.w; x += spacing) {
                        const joistGeo = new THREE.BoxGeometry(jThick, jHeight, room.l);
                        const joistMesh = new THREE.Mesh(joistGeo, joistMat);
                        joistMesh.position.set(x, room.h - jHeight/2, room.l / 2);
                        joistMesh.castShadow = true;
                        joistMesh.receiveShadow = true;
                        roomGroup.add(joistMesh);
                    }
                } else {
                    for (let y = spacing; y < room.l; y += spacing) {
                        const joistGeo = new THREE.BoxGeometry(room.w, jHeight, jThick);
                        const joistMesh = new THREE.Mesh(joistGeo, joistMat);
                        joistMesh.position.set(room.w / 2, room.h - jHeight/2, y);
                        joistMesh.castShadow = true;
                        joistMesh.receiveShadow = true;
                        roomGroup.add(joistMesh);
                    }
                }
            }
        }

        // --- Render 3D pink XPS insulation foam boards on exterior walls ---
        if (room.foamBoard) {
            const segments = getRoomSegments(room);
            const foamMat = new THREE.MeshStandardMaterial({
                color: '#f472b6', // Owens Corning pink XPS board
                roughness: 0.95,
                metalness: 0.05
            });
            const fThick = 0.16; // 2 inches
            
            segments.forEach(seg => {
                const mx = (seg.x1 + seg.x2) / 2;
                const my = (seg.y1 + seg.y2) / 2;
                
                // Check if exterior wall
                let isShared = false;
                for (let i = 0; i < state.rooms.length; i++) {
                    const other = state.rooms[i];
                    if (other.id === room.id || other.levelId !== room.levelId) continue;
                    
                    const otherSegs = getRoomSegments(other);
                    for (let j = 0; j < otherSegs.length; j++) {
                        const oSeg = otherSegs[j];
                        const dist = getDistanceToSegment(mx, my, oSeg.x1, oSeg.y1, oSeg.x2, oSeg.y2);
                        if (dist < 0.25) {
                            isShared = true;
                            break;
                        }
                    }
                    if (isShared) break;
                }
                
                if (!isShared) {
                    const len = Math.sqrt((seg.x2 - seg.x1)**2 + (seg.y2 - seg.y1)**2);
                    if (len < 0.05) return;
                    
                    const geometry = new THREE.BoxGeometry(len, room.h, fThick);
                    const mesh = new THREE.Mesh(geometry, foamMat);
                    
                    const dx = seg.x2 - seg.x1;
                    const dy = seg.y2 - seg.y1;
                    const nx = -dy / len;
                    const ny = dx / len;
                    
                    // Outward normal check
                    const testDist = 0.5;
                    const testX = mx + nx * testDist;
                    const testY = my + ny * testDist;
                    const inRoom = getRoomAt(testX, testY, room.levelId);
                    
                    const mul = (inRoom && inRoom.id === room.id) ? 1 : -1;
                    const offsetDist = wallThickness / 2 + 0.08;
                    
                    mesh.position.set(
                        mx + nx * offsetDist * mul,
                        elevation + room.h / 2,
                        my + ny * offsetDist * mul
                    );
                    
                    const angle = Math.atan2(dy, dx);
                    mesh.rotation.y = -angle;
                    
                    mesh.castShadow = true;
                    mesh.receiveShadow = true;
                    
                    scene.add(mesh);
                    roomMeshes.push(mesh);
                }
            });
        }

        // --- Render 3D NB1 Cementitious Coating ---
        if (room.nb1Height && room.nb1Height !== 'none') {
            const segments = getRoomSegments(room);
            const nb1Mat = new THREE.MeshStandardMaterial({
                color: '#94a3b8', // Cement grey
                roughness: 0.95,
                metalness: 0.05
            });
            const coatingH = room.nb1Height === '2ft' ? 2.0 : (room.nb1Height === '4ft' ? 4.0 : room.h);
            const nb1Thick = 0.015; // 0.18 inches thick layer
            
            segments.forEach(seg => {
                const len = Math.sqrt((seg.x2 - seg.x1)**2 + (seg.y2 - seg.y1)**2);
                if (len < 0.05) return;
                
                const geometry = new THREE.BoxGeometry(len, coatingH, nb1Thick);
                const mesh = new THREE.Mesh(geometry, nb1Mat);
                
                const dx = seg.x2 - seg.x1;
                const dy = seg.y2 - seg.y1;
                const nx = -dy / len;
                const ny = dx / len;
                
                const mx = (seg.x1 + seg.x2) / 2;
                const my = (seg.y1 + seg.y2) / 2;
                const testDist = 0.5;
                const testX = mx + nx * testDist;
                const testY = my + ny * testDist;
                const inRoom = getRoomAt(testX, testY, room.levelId);
                
                const mul = (inRoom && inRoom.id === room.id) ? 1 : -1;
                const offsetDist = wallThickness / 2 - 0.01;
                
                mesh.position.set(
                    mx + nx * offsetDist * mul,
                    elevation + coatingH / 2,
                    my + ny * offsetDist * mul
                );
                
                const angle = Math.atan2(dy, dx);
                mesh.rotation.y = -angle;
                
                mesh.castShadow = true;
                mesh.receiveShadow = true;
                
                scene.add(mesh);
                roomMeshes.push(mesh);
            });
        }

        // --- Render 3D Drywall ---
        if (room.drywallHeight && room.drywallHeight !== 'none') {
            const segments = getRoomSegments(room);
            const dwMat = new THREE.MeshStandardMaterial({
                color: '#f8fafc', // Clean off-white drywall
                roughness: 0.95,
                metalness: 0.02
            });
            const coatingH = room.drywallHeight === '2ft' ? 2.0 : (room.drywallHeight === '4ft' ? 4.0 : room.h);
            const dwThick = 0.04; // 1/2 inch drywall panel
            
            segments.forEach(seg => {
                const len = Math.sqrt((seg.x2 - seg.x1)**2 + (seg.y2 - seg.y1)**2);
                if (len < 0.05) return;
                
                const geometry = new THREE.BoxGeometry(len, coatingH, dwThick);
                const mesh = new THREE.Mesh(geometry, dwMat);
                
                const dx = seg.x2 - seg.x1;
                const dy = seg.y2 - seg.y1;
                const nx = -dy / len;
                const ny = dx / len;
                
                const mx = (seg.x1 + seg.x2) / 2;
                const my = (seg.y1 + seg.y2) / 2;
                const testDist = 0.5;
                const testX = mx + nx * testDist;
                const testY = my + ny * testDist;
                const inRoom = getRoomAt(testX, testY, room.levelId);
                
                const mul = (inRoom && inRoom.id === room.id) ? 1 : -1;
                const offsetDist = wallThickness / 2 - 0.02;
                
                mesh.position.set(
                    mx + nx * offsetDist * mul,
                    elevation + coatingH / 2,
                    my + ny * offsetDist * mul
                );
                
                const angle = Math.atan2(dy, dx);
                mesh.rotation.y = -angle;
                
                mesh.castShadow = true;
                mesh.receiveShadow = true;
                
                scene.add(mesh);
                roomMeshes.push(mesh);
            });
        }

        // --- Render 3D Carbon Fiber Wall Reinforcements ---
        if (room.carbonStraps > 0) {
            const segments = getRoomSegments(room);
            const cfMat = new THREE.MeshStandardMaterial({
                color: '#1e293b', // Woven Carbon Look
                roughness: 0.6,
                metalness: 0.7
            });
            const sWidth = 0.5;  // 6 inches wide strap
            const sThick = 0.015; // 0.18 inch profile
            
            if (room.carbonFiberScope === 'specific' && Array.isArray(room.customCarbonStraps) && room.customCarbonStraps.length > 0) {
                // Render specific custom positions
                room.customCarbonStraps.forEach(strap => {
                    const seg = segments.find(s => s.wall === strap.wall);
                    if (!seg) return;
                    
                    const dx = seg.x2 - seg.x1;
                    const dy = seg.y2 - seg.y1;
                    const len = Math.sqrt(dx*dx + dy*dy);
                    if (len < 0.05) return;
                    
                    const px = seg.x1 + dx * strap.ratio;
                    const py = seg.y1 + dy * strap.ratio;
                    
                    const nx = -dy / len;
                    const ny = dx / len;
                    const testDist = 0.5;
                    const testX = px + nx * testDist;
                    const testY = py + ny * testDist;
                    const inRoom = getRoomAt(testX, testY, room.levelId);
                    const mul = (inRoom && inRoom.id === room.id) ? 1 : -1;
                    const offsetDist = wallThickness / 2 - 0.005;
                    
                    const geometry = new THREE.BoxGeometry(sWidth, room.h, sThick);
                    const mesh = new THREE.Mesh(geometry, cfMat);
                    
                    mesh.position.set(
                        px + nx * offsetDist * mul,
                        elevation + room.h / 2,
                        py + ny * offsetDist * mul
                    );
                    
                    const angle = Math.atan2(dy, dx);
                    mesh.rotation.y = -angle;
                    mesh.castShadow = true;
                    
                    scene.add(mesh);
                    roomMeshes.push(mesh);
                });
            } else {
                // Automatic Even Spacing Mode
                let drawSegments = segments;
                if (room.carbonFiberScope === 'specific' && Array.isArray(room.carbonFiberWalls)) {
                    drawSegments = segments.filter(seg => room.carbonFiberWalls.includes(seg.wall));
                }
                
                let totalPerim = 0;
                const segData = [];
                drawSegments.forEach(seg => {
                    const dx = seg.x2 - seg.x1;
                    const dy = seg.y2 - seg.y1;
                    const len = Math.sqrt(dx*dx + dy*dy);
                    if (len > 0.05) {
                        totalPerim += len;
                        segData.push({ seg, len, dx, dy });
                    }
                });
                
                if (totalPerim > 0 && segData.length > 0) {
                    const N = room.carbonStraps;
                    const spacing = totalPerim / N;
                    
                    let currentDist = spacing / 2;
                    let currentSegIdx = 0;
                    let accumulatedDist = 0;
                    
                    for (let i = 0; i < N; i++) {
                        while (currentSegIdx < segData.length && accumulatedDist + segData[currentSegIdx].len < currentDist) {
                            accumulatedDist += segData[currentSegIdx].len;
                            currentSegIdx++;
                        }
                        if (currentSegIdx >= segData.length) break;
                        
                        const s = segData[currentSegIdx];
                        const distInSeg = currentDist - accumulatedDist;
                        const ratio = distInSeg / s.len;
                        
                        const px = s.seg.x1 + s.dx * ratio;
                        const py = s.seg.y1 + s.dy * ratio;
                        
                        const len = s.len;
                        const nx = -s.dy / len;
                        const ny = s.dx / len;
                        const testDist = 0.5;
                        const testX = px + nx * testDist;
                        const testY = py + ny * testDist;
                        const inRoom = getRoomAt(testX, testY, room.levelId);
                        const mul = (inRoom && inRoom.id === room.id) ? 1 : -1;
                        const offsetDist = wallThickness / 2 - 0.005;
                        
                        const geometry = new THREE.BoxGeometry(sWidth, room.h, sThick);
                        const mesh = new THREE.Mesh(geometry, cfMat);
                        
                        mesh.position.set(
                            px + nx * offsetDist * mul,
                            elevation + room.h / 2,
                            py + ny * offsetDist * mul
                        );
                        
                        const angle = Math.atan2(s.dy, s.dx);
                        mesh.rotation.y = -angle;
                        mesh.castShadow = true;
                        
                        scene.add(mesh);
                        roomMeshes.push(mesh);
                        
                        currentDist += spacing;
                    }
                }
            }
        }

        scene.add(roomGroup);
        roomMeshes.push(roomGroup);
    });

    // Build logical building walls in 3D
    const wallMat = new THREE.MeshStandardMaterial({
        color: '#e2e8f0',
        roughness: 0.9,
        metalness: 0.05
    });

    (state.walls || []).forEach(w => {
        const wallGroup = new THREE.Group();
        const level = state.levels.find(l => l.id === w.levelId) || { elevation: 0 };
        const elevation = level.elevation || 0;
        wallGroup.position.set(0, elevation, 0);

        // Map openings from first-class doors & windows
        const openings = [];
        (state.doors || []).forEach(d => {
            if (d.hostWallId === w.id) {
                openings.push({
                    type: 'door',
                    w: d.w || 3.0,
                    h: d.h || 6.8,
                    offset: d.offset
                });
            }
        });
        (state.windows || []).forEach(win => {
            if (win.hostWallId === w.id) {
                openings.push({
                    type: 'window',
                    w: win.w || 3.0,
                    h: win.h || 4.0,
                    offset: win.offset,
                    sillHeight: win.sillHeight || 3.0
                });
            }
        });

        build3DWall(w.x1, w.y1, w.x2, w.y2, w.height || 8, openings, wallGroup, wallMat);
        
        scene.add(wallGroup);
        roomMeshes.push(wallGroup);
    });

    // --- UTILITIES & PIPING 3D RENDERING ---
    // 1. Render Sump Pumps
    state.sumpPumps.forEach(sp => {
        const spLevelId = sp.levelId || 'basement';
        const level = state.levels.find(l => l.id === spLevelId) || { elevation: 0, height: 8 };
        const elevation = level.elevation || 0;
        const room = getRoomAt(sp.x, sp.y, spLevelId);
        const roomH = room ? room.h : (level.height || 8);
        
        const sumpGroup = new THREE.Group();
        sumpGroup.position.set(sp.x, elevation, sp.y);
        
        // Sump lid
        const lidGeo = new THREE.CylinderGeometry(0.8, 0.8, 0.05, 16);
        const lidMat = new THREE.MeshStandardMaterial({ color: '#1e293b', roughness: 0.6 });
        const lidMesh = new THREE.Mesh(lidGeo, lidMat);
        lidMesh.position.y = 0.025;
        lidMesh.receiveShadow = true;
        sumpGroup.add(lidMesh);
        
        // Pump motor block representation
        const motorGeo = new THREE.BoxGeometry(0.3, 0.4, 0.3);
        const motorMat = new THREE.MeshStandardMaterial({ color: '#0f172a', metalness: 0.6, roughness: 0.3 });
        const motorMesh = new THREE.Mesh(motorGeo, motorMat);
        motorMesh.position.set(0.1, 0.2, 0.1);
        motorMesh.castShadow = true;
        sumpGroup.add(motorMesh);
        
        // Vertical PVC riser
        const pipeH = roomH - 0.2;
        const pipeGeo = new THREE.CylinderGeometry(0.08, 0.08, pipeH, 8);
        const pipeMat = new THREE.MeshStandardMaterial({ color: '#f8fafc', roughness: 0.5 });
        const pipeMesh = new THREE.Mesh(pipeGeo, pipeMat);
        pipeMesh.position.set(-0.2, pipeH / 2, -0.2);
        pipeMesh.castShadow = true;
        pipeMesh.receiveShadow = true;
        sumpGroup.add(pipeMesh);
        
        scene.add(sumpGroup);
        roomMeshes.push(sumpGroup);
    });

    // 2. Render Discharge Lines (thick green on the floor)
    state.dischargeLines.forEach(dl => {
        const level = state.levels.find(l => l.id === dl.levelId) || { elevation: 0 };
        const elevation = level.elevation || 0;
        build3DPipe(dl.x1, elevation + 0.1, dl.y1, dl.x2, elevation + 0.1, dl.y2, 0.12, '#10b981', scene);
    });

    // 3. Render Interior Plumbing (white PVC run overhead)
    state.interiorPipes.forEach(ip => {
        const ipLevelId = ip.levelId || 'basement';
        const level = state.levels.find(l => l.id === ipLevelId) || { elevation: 0, height: 8 };
        const elevation = level.elevation || 0;
        
        // Find room containing start point
        const containingRoom = getRoomAt(ip.x1, ip.y1, ipLevelId);
        const roomH = containingRoom ? containingRoom.h : (level.height || 8);
        
        // Route horizontal run at overhead ceiling height (room height - 0.5ft)
        const pipeY = elevation + (roomH - 0.5);
        build3DPipe(ip.x1, pipeY, ip.y1, ip.x2, pipeY, ip.y2, 0.08, '#f8fafc', scene);
    });

    // 4. Render Stanchions (support posts)
    state.stanchions.forEach(st => {
        const stLevelId = st.levelId || 'basement';
        const level = state.levels.find(l => l.id === stLevelId) || { elevation: 0, height: 8 };
        const elevation = level.elevation || 0;
        const room = getRoomAt(st.x, st.y, stLevelId);
        const roomH = room ? room.h : (level.height || 8);
        
        // Check if stanchion is underneath any support beam on this level
        let isUnderBeam = false;
        const bHeight = 0.9;
        for (let i = 0; i < state.mainBeams.length; i++) {
            const bm = state.mainBeams[i];
            if (bm.levelId !== stLevelId) continue;
            const dist = getDistanceToSegment(st.x, st.y, bm.x1, bm.y1, bm.x2, bm.y2);
            if (dist < 0.5) {
                isUnderBeam = true;
                break;
            }
        }
        
        const postH = isUnderBeam ? Math.max(0.5, roomH - bHeight) : roomH;
        
        let geometry;
        let material;
        
        if (st.type === 'brick') {
            geometry = new THREE.BoxGeometry(1.0, postH, 1.0);
            material = new THREE.MeshStandardMaterial({
                color: '#c2410c', // brick red/orange
                roughness: 0.95,
                metalness: 0.05
            });
        } else if (st.type === 'square') {
            geometry = new THREE.BoxGeometry(0.8, postH, 0.8);
            material = new THREE.MeshStandardMaterial({ 
                color: '#b91c1c', // red-oxide steel look
                metalness: 0.6, 
                roughness: 0.3 
            });
        } else { // round
            geometry = new THREE.CylinderGeometry(0.4, 0.4, postH, 16);
            material = new THREE.MeshStandardMaterial({ 
                color: '#b91c1c', // red-oxide lally column
                metalness: 0.6, 
                roughness: 0.3 
            });
        }
        
        const mesh = new THREE.Mesh(geometry, material);
        mesh.position.set(st.x, elevation + postH / 2, st.y);
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        
        scene.add(mesh);
        roomMeshes.push(mesh);
    });

    // 4b. Render Dehumidifiers
    if (state.dehumidifiers) {
        state.dehumidifiers.forEach(dehum => {
            const dehumLevelId = dehum.levelId || 'basement';
            if (dehumLevelId !== state.currentLevelId) return;
            const level = state.levels.find(l => l.id === dehumLevelId) || { elevation: 0, height: 8 };
            const elevation = level.elevation || 0;
            
            const dehumGeo = new THREE.BoxGeometry(1.0, 0.8, 1.2);
            const dehumMat = new THREE.MeshStandardMaterial({ color: '#9333ea', roughness: 0.5, metalness: 0.1 });
            const dehumMesh = new THREE.Mesh(dehumGeo, dehumMat);
            
            dehumMesh.position.set(dehum.x, elevation + 0.4, dehum.y);
            dehumMesh.castShadow = true;
            dehumMesh.receiveShadow = true;
            
            scene.add(dehumMesh);
            roomMeshes.push(dehumMesh);
        });
    }

    // Render Floor Hatches (Access ports)
    state.floorHatches.forEach(h => {
        const hLevelId = h.levelId || 'basement';
        const level = state.levels.find(l => l.id === hLevelId) || { elevation: 0, height: 8 };
        const elevation = level.elevation || 0;
        const room = getRoomAt(h.x, h.y, hLevelId);
        const roomH = room ? room.h : (level.height || 8);
        
        const yPos = h.target === 'ceiling' ? (elevation + roomH - 0.02) : (elevation + 0.02);
        
        const hatchGroup = new THREE.Group();
        hatchGroup.position.set(h.x, yPos, h.y);
        
        // Frame border
        const frameGeo = new THREE.BoxGeometry(h.w, 0.04, h.l);
        const frameMat = new THREE.MeshStandardMaterial({
            color: '#1e293b',
            roughness: 0.5,
            metalness: 0.8
        });
        const frameMesh = new THREE.Mesh(frameGeo, frameMat);
        hatchGroup.add(frameMesh);
        
        // Lid panel
        const lidGeo = new THREE.BoxGeometry(h.w - 0.2, 0.06, h.l - 0.2);
        const lidMat = new THREE.MeshStandardMaterial({
            color: '#475569',
            roughness: 0.6,
            metalness: 0.7
        });
        const lidMesh = new THREE.Mesh(lidGeo, lidMat);
        lidMesh.position.y = 0.01;
        hatchGroup.add(lidMesh);
        
        // Tiny latch handle
        const handleGeo = new THREE.BoxGeometry(0.3, 0.02, 0.1);
        const handleMat = new THREE.MeshStandardMaterial({
            color: '#ec4899',
            roughness: 0.2
        });
        const handleMesh = new THREE.Mesh(handleGeo, handleMat);
        handleMesh.position.set(h.w / 2 - 0.4, 0.05, 0);
        hatchGroup.add(handleMesh);
        
        scene.add(hatchGroup);
        roomMeshes.push(hatchGroup);
    });

    // 5. Render Support Beams (timber wood or steel girders)
    state.mainBeams.forEach(bm => {
        const bmLevelId = bm.levelId || 'basement';
        const level = state.levels.find(l => l.id === bmLevelId) || { elevation: 0, height: 8 };
        const elevation = level.elevation || 0;
        const room = getRoomAt(bm.x1, bm.y1, bmLevelId);
        const roomH = room ? room.h : (level.height || 8);
        
        const len = Math.sqrt((bm.x2 - bm.x1)**2 + (bm.y2 - bm.y1)**2);
        if (len < 0.01) return;
        
        const bWidth = 0.6; // 7 inches wide
        const bHeight = 0.9; // 11 inches deep
        const geometry = new THREE.BoxGeometry(len, bHeight, bWidth);
        
        const material = bm.type === 'steel'
            ? new THREE.MeshStandardMaterial({ color: '#334155', metalness: 0.8, roughness: 0.2 })
            : new THREE.MeshStandardMaterial({ color: '#78350f', roughness: 0.9, metalness: 0.1 });
            
        const mesh = new THREE.Mesh(geometry, material);
        
        // Position midpoint
        const mx = (bm.x1 + bm.x2) / 2;
        const my = (bm.y1 + bm.y2) / 2;
        const pipeY = elevation + roomH - bHeight / 2;
        mesh.position.set(mx, pipeY, my);
        
        // Rotate Y to align along endpoints
        const angle = Math.atan2(bm.y2 - bm.y1, bm.x2 - bm.x1);
        mesh.rotation.y = -angle;
        
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        
        scene.add(mesh);
        roomMeshes.push(mesh);
    });

    // Auto-adjust camera focus point
    if (state.rooms.length > 0) {
        // Calculate bounding box of all rooms
        let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
        state.rooms.forEach(r => {
            minX = Math.min(minX, r.x);
            maxX = Math.max(maxX, r.x + r.w);
            minZ = Math.min(minZ, r.y);
            maxZ = Math.max(maxZ, r.y + r.l);
        });
        const center = new THREE.Vector3((minX + maxX) / 2, 2, (minZ + maxZ) / 2);
        controls.target.copy(center);
    }
};

/**
 * Builds a wall segmenting it around openings (doors/windows)
 */
function build3DWall(x1, z1, x2, z2, height, openings, group, material) {
    const wallLength = Math.sqrt((x2 - x1) ** 2 + (z2 - z1) ** 2);
    const angle = Math.atan2(z2 - z1, x2 - x1);

    // Create a local sub-group for the wall
    const wallGroup = new THREE.Group();
    wallGroup.position.set(x1, 0, z1);
    wallGroup.rotation.y = -angle; // Rotate wall alignment

    // Sort openings by offset along the wall
    openings.sort((a, b) => a.offset - b.offset);

    let currentOffset = 0;

    openings.forEach(op => {
        const startOp = op.offset - op.w / 2;
        const endOp = op.offset + op.w / 2;

        // 1. Solid wall segment before opening
        if (startOp > currentOffset) {
            const segW = startOp - currentOffset;
            const segGeo = new THREE.BoxGeometry(segW, height, wallThickness);
            const segMesh = new THREE.Mesh(segGeo, material);
            segMesh.position.set(currentOffset + segW / 2, height / 2, 0);
            segMesh.castShadow = true;
            segMesh.receiveShadow = true;
            wallGroup.add(segMesh);
        }

        // 2. Vertical slices above/below the opening, and the door/window visual models
        if (op.type === 'door' || op.type === 'crawl_door') {
            // Door opening: Only wall segment above the lintel (header)
            const headerH = height - op.h;
            if (headerH > 0) {
                const headerGeo = new THREE.BoxGeometry(op.w, headerH, wallThickness);
                const headerMesh = new THREE.Mesh(headerGeo, material);
                headerMesh.position.set(op.offset, op.h + headerH / 2, 0);
                headerMesh.castShadow = true;
                headerMesh.receiveShadow = true;
                wallGroup.add(headerMesh);
            }

            // Draw visual door frame
            const frameColor = op.type === 'crawl_door' ? '#475569' : '#57534e';
            const frameMat = new THREE.MeshStandardMaterial({ color: frameColor, roughness: 0.6 });
            
            // Left jamb
            const leftJambGeo = new THREE.BoxGeometry(0.15, op.h, wallThickness + 0.02);
            const leftJamb = new THREE.Mesh(leftJambGeo, frameMat);
            leftJamb.position.set(op.offset - op.w / 2 + 0.075, op.h / 2, 0);
            wallGroup.add(leftJamb);

            // Right jamb
            const rightJambGeo = new THREE.BoxGeometry(0.15, op.h, wallThickness + 0.02);
            const rightJamb = new THREE.Mesh(rightJambGeo, frameMat);
            rightJamb.position.set(op.offset + op.w / 2 - 0.075, op.h / 2, 0);
            wallGroup.add(rightJamb);

            // Head jamb (top frame)
            const headJambGeo = new THREE.BoxGeometry(op.w, 0.15, wallThickness + 0.02);
            const headJamb = new THREE.Mesh(headJambGeo, frameMat);
            headJamb.position.set(op.offset, op.h - 0.075, 0);
            wallGroup.add(headJamb);

            // Door panel group for hinge rotation (hinge pivot at left jamb)
            const doorPanelGroup = new THREE.Group();
            doorPanelGroup.position.set(op.offset - op.w / 2 + 0.15, 0, 0);
            
            const doorPanelW = op.w - 0.3;
            const doorPanelH = op.h - 0.15;
            const doorPanelGeo = new THREE.BoxGeometry(doorPanelW, doorPanelH, 0.1);
            const doorPanelColor = op.type === 'crawl_door' ? '#64748b' : '#b45309';
            const doorPanelMat = new THREE.MeshStandardMaterial({ color: doorPanelColor, roughness: 0.7 });
            const doorPanelMesh = new THREE.Mesh(doorPanelGeo, doorPanelMat);
            doorPanelMesh.position.set(doorPanelW / 2, doorPanelH / 2, 0);
            doorPanelMesh.castShadow = true;
            doorPanelGroup.add(doorPanelMesh);
            
            // Rotate door slightly open (45 degrees inwards)
            doorPanelGroup.rotation.y = Math.PI / 4; 
            wallGroup.add(doorPanelGroup);

        } else if (op.type === 'window') {
            // Window opening: Wall segment below sill, and wall segment above lintel
            const sillH = 3.0; // standard sill height: 3ft
            const headerH = height - (sillH + op.h);

            // Sill (bottom part)
            if (sillH > 0) {
                const sillGeo = new THREE.BoxGeometry(op.w, sillH, wallThickness);
                const sillMesh = new THREE.Mesh(sillGeo, material);
                sillMesh.position.set(op.offset, sillH / 2, 0);
                sillMesh.castShadow = true;
                sillMesh.receiveShadow = true;
                wallGroup.add(sillMesh);
            }

            // Lintel (top part)
            if (headerH > 0) {
                const headerGeo = new THREE.BoxGeometry(op.w, headerH, wallThickness);
                const headerMesh = new THREE.Mesh(headerGeo, material);
                headerMesh.position.set(op.offset, sillH + op.h + headerH / 2, 0);
                headerMesh.castShadow = true;
                headerMesh.receiveShadow = true;
                wallGroup.add(headerMesh);
            }

            // Draw visual window frame & glass
            const frameMat = new THREE.MeshStandardMaterial({ color: '#f1f5f9', roughness: 0.5 });
            const borderSize = 0.1;
            
            // Top frame border
            const fTop = new THREE.Mesh(new THREE.BoxGeometry(op.w, borderSize, wallThickness + 0.02), frameMat);
            fTop.position.set(op.offset, sillH + op.h - borderSize/2, 0);
            wallGroup.add(fTop);

            // Bottom frame border
            const fBot = new THREE.Mesh(new THREE.BoxGeometry(op.w, borderSize, wallThickness + 0.02), frameMat);
            fBot.position.set(op.offset, sillH + borderSize/2, 0);
            wallGroup.add(fBot);

            // Left frame border
            const fLeft = new THREE.Mesh(new THREE.BoxGeometry(borderSize, op.h - borderSize*2, wallThickness + 0.02), frameMat);
            fLeft.position.set(op.offset - op.w/2 + borderSize/2, sillH + op.h/2, 0);
            wallGroup.add(fLeft);

            // Right frame border
            const fRight = new THREE.Mesh(new THREE.BoxGeometry(borderSize, op.h - borderSize*2, wallThickness + 0.02), frameMat);
            fRight.position.set(op.offset + op.w/2 - borderSize/2, sillH + op.h/2, 0);
            wallGroup.add(fRight);

            // Transparent glass panel
            const glassW = op.w - borderSize * 2;
            const glassH = op.h - borderSize * 2;
            const glassGeo = new THREE.BoxGeometry(glassW, glassH, 0.03);
            const glassMat = new THREE.MeshStandardMaterial({
                color: '#bae6fd',
                transparent: true,
                opacity: 0.35,
                roughness: 0.1,
                metalness: 0.9
            });
            const glassMesh = new THREE.Mesh(glassGeo, glassMat);
            glassMesh.position.set(op.offset, sillH + op.h / 2, 0);
            wallGroup.add(glassMesh);
        }

        currentOffset = endOp;
    });

    // 3. Final solid segment after the last opening
    if (wallLength > currentOffset) {
        const segW = wallLength - currentOffset;
        const segGeo = new THREE.BoxGeometry(segW, height, wallThickness);
        const segMesh = new THREE.Mesh(segGeo, material);
        segMesh.position.set(currentOffset + segW / 2, height / 2, 0);
        segMesh.castShadow = true;
        segMesh.receiveShadow = true;
        wallGroup.add(segMesh);
    }

    group.add(wallGroup);
}

// Helper: Builds cylindrical pipe in 3D between two coordinate points
function build3DPipe(x1, y1, z1, x2, y2, z2, radius, color, sceneGroup) {
    const point1 = new THREE.Vector3(x1, y1, z1);
    const point2 = new THREE.Vector3(x2, y2, z2);
    const direction = new THREE.Vector3().subVectors(point2, point1);
    const length = direction.length();
    if (length < 0.01) return;
    
    const geometry = new THREE.CylinderGeometry(radius, radius, length, 8);
    const material = new THREE.MeshStandardMaterial({ 
        color: color, 
        roughness: 0.4,
        metalness: 0.1 
    });
    const mesh = new THREE.Mesh(geometry, material);
    
    mesh.position.copy(point1).add(direction.clone().multiplyScalar(0.5));
    
    const up = new THREE.Vector3(0, 1, 0);
    direction.normalize();
    mesh.quaternion.setFromUnitVectors(up, direction);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    
    sceneGroup.add(mesh);
    roomMeshes.push(mesh);
}



// 3D Specific UI Controls
document.getElementById('btn-3d-roof').addEventListener('click', (e) => {
    showCeilings = !showCeilings;
    e.currentTarget.classList.toggle('active', showCeilings);
    window.sync3D();
});

window.get3DScreenshot = function() {
    // Force initialize scene if not already initialized
    if (!scene) {
        init3D();
    }
    
    // Force a sync3D to build/update the meshes to the latest state of the project
    window.sync3D();
    
    if (!renderer || !scene || !camera) return null;
    
    // Save original settings
    const origBg = scene.background;
    const origFog = scene.fog;
    const origCamPos = camera.position.clone();
    const origTarget = controls ? controls.target.clone() : new THREE.Vector3();
    
    // Save original size/aspect
    const originalWidth = renderer.domElement.width;
    const originalHeight = renderer.domElement.height;
    const originalAspect = camera.aspect;
    
    // Check if container is hidden/collapsed
    const targetW = container3d.clientWidth || 800;
    const targetH = container3d.clientHeight || 600;
    
    // Set rendering size to ensure a valid canvas size
    renderer.setSize(targetW, targetH, false);
    camera.aspect = targetW / targetH;
    camera.updateProjectionMatrix();
    
    // Temporarily swap to white print background and clear fog
    scene.background = new THREE.Color('#ffffff');
    scene.fog = null;
    
    // Auto-focus camera on structure tightly
    const box = new THREE.Box3();
    let hasObjects = false;
    roomMeshes.forEach(mesh => {
        box.expandByObject(mesh);
        hasObjects = true;
    });
    
    if (hasObjects && controls) {
        const size = new THREE.Vector3();
        box.getSize(size);
        const center = new THREE.Vector3();
        box.getCenter(center);
        
        controls.target.copy(center);
        
        const maxDim = Math.max(size.x, size.y, size.z);
        const fov = camera.fov * (Math.PI / 180);
        
        // Zoom closer: 1.02 padding fills the screen tightly!
        let cameraZ = Math.abs(maxDim / 2 / Math.tan(fov / 2)) * 1.02;
        cameraZ = Math.max(10, cameraZ);
        
        // Steeped top-down aerial view (62 degrees) to see inside rooms clearly without shrinking size
        camera.position.set(
            center.x + cameraZ * 0.35,
            center.y + cameraZ * 1.1,
            center.z + cameraZ * 0.45
        );
        
        camera.lookAt(center);
        controls.update();
    }
    
    // Render and capture
    renderer.render(scene, camera);
    const dataUrl = renderer.domElement.toDataURL('image/png');
    
    // Restore settings
    scene.background = origBg;
    scene.fog = origFog;
    camera.position.copy(origCamPos);
    if (controls) {
        controls.target.copy(origTarget);
        controls.update();
    }
    
    // Restore renderer size
    const restoreW = container3d.clientWidth;
    const restoreH = container3d.clientHeight;
    if (restoreW > 0 && restoreH > 0) {
        renderer.setSize(restoreW, restoreH);
        camera.aspect = restoreW / restoreH;
    } else {
        renderer.setSize(originalWidth, originalHeight, false);
        camera.aspect = originalAspect;
    }
    camera.updateProjectionMatrix();
    
    // Render normal view once
    if (restoreW > 0 && restoreH > 0 && state.activeView === '3d') {
        renderer.render(scene, camera);
    }
    
    return dataUrl;
};

// Programmatic 3D Zoom Function
window.zoom3D = function(zoomIn) {
    if (!camera || !controls) return;
    const factor = zoomIn ? 0.85 : 1.15; // Zoom in scales down camera distance
    const target = controls.target;
    
    camera.position.x = target.x + (camera.position.x - target.x) * factor;
    camera.position.y = target.y + (camera.position.y - target.y) * factor;
    camera.position.z = target.z + (camera.position.z - target.z) * factor;
    controls.update();
};

// Bind 3D zoom buttons
document.getElementById('btn-3d-zoom-in').addEventListener('click', () => {
    window.zoom3D(true);
});
document.getElementById('btn-3d-zoom-out').addEventListener('click', () => {
    window.zoom3D(false);
});

