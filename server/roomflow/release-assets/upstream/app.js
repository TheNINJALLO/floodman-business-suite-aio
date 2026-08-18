// --- STATE DEFINITIONS ---
const state = {
    rooms: [],
    sumpPumps: [],
    dehumidifiers: [],
    dischargeLines: [],
    floorHatches: [],
    capturedMeasurements: [],
    selectedRoomId: null,
    selectedSumpPumpId: null,
    selectedDehumidifierId: null,
    selectedDischargeLineId: null,
    selectedFloorHatchId: null,
    activeView: 'checklist', // 'checklist', '2d', '3d', 'ar'
    scale: 15,        // Pixels per foot
    offsetX: 0,       // Canvas pan offset X
    offsetY: 0,       // Canvas pan offset Y
    isDraggingCanvas: false,
    dragStartX: 0,
    dragStartY: 0,
    draggedRoomId: null,
    draggedHandle: null, // 'w', 'e', 'n', 's', 'nw', 'ne', 'se', 'sw' or 'move'
    draggedSumpPumpId: null,
    draggedDehumidifierId: null,
    draggedFloorHatchId: null,
    draggedDischargeHandle: null, // { id, point: 'p1' | 'p2' | 'move' }
    draggedOpening: null,        // { roomId, openingId }
    draggedVertex: null,         // { roomId, vertexIndex }
    drawMode: null,              // 'custom' or null
    sketchVertices: [],          // temporary drawing vertices
    sketchRedoVertices: [],      // temporary redo drawing vertices
    lastMouseWorldX: 0,          // live mouse positions for line previews
    lastMouseWorldY: 0,
    pendingPlacement: null,      // { kind, type } for tap-to-place and drag/drop tools
    undoStack: [],
    redoStack: [],
    levels: [
        { id: 'crawlspace', name: 'Crawl Space', height: 4, elevation: 0 },
        { id: 'basement', name: 'Basement', height: 8, elevation: 0 },
        { id: 'main', name: 'Main Floor', height: 9, elevation: 8 },
        { id: 'second', name: '2nd Floor', height: 8, elevation: 17 },
        { id: 'attic', name: 'Attic', height: 8, elevation: 25 }
    ],
    currentLevelId: 'basement',
    interiorPipes: [],
    selectedInteriorPipeId: null,
    draggedInteriorPipeHandle: null, // { id, point: 'p1' | 'p2' | 'move' }
    stanchions: [],
    selectedStanchionId: null,
    draggedStanchionId: null,
    mainBeams: [],
    selectedMainBeamId: null,
    draggedMainBeamHandle: null, // { id, point: 'p1' | 'p2' | 'move' }
    snapGridSize: 0.5,   // Snap to nearest 0.5 foot (6 inches)
    showGrid: true,
    initialMouseOffset: {},
    
    // Coordinated building structure schema elements
    walls: [],
    roomConnections: [],
    doors: [],
    windows: [],
    openings: [],
    stairs: [],
    createdTimestamp: Date.now(),
    updatedTimestamp: Date.now(),
    revisionNumber: 1,
    syncState: 'synchronized'
};

// Integration modules load as separate classic scripts and need the same
// application state object for organization, session, and capability checks.
window.state = state;

// Initialize default costing state
initDefaultCosting(state);

// Preset dimensions (in feet)
const PRESETS = {
    living: { name: 'Living Room', w: 16, l: 20, h: 8, color: '#3b82f6' },
    bedroom: { name: 'Bedroom', w: 12, l: 14, h: 8, color: '#8b5cf6' },
    kitchen: { name: 'Kitchen', w: 12, l: 12, h: 8, color: '#10b981' },
    bathroom: { name: 'Bathroom', w: 8, l: 8, h: 8, color: '#f59e0b' },
    hallway: { name: 'Hallway', w: 4, l: 16, h: 8, color: '#6b7280' },
    closet: { name: 'Closet', w: 4, l: 6, h: 8, color: '#10b981' },
    staircase: { name: 'Staircase', w: 3.5, l: 12, h: 8, color: '#f43f5e', steps: 12 },
    custom: { name: 'Custom Room', w: 10, l: 10, h: 8, color: '#ec4899' }
};

// Canvas Setup
const canvas = document.getElementById('sketch-canvas');
const ctx = canvas.getContext('2d');
const container = document.getElementById('canvas-container');

// Keep the compact CAD customer fields synchronized with the guided job
// record so every document reads the same source of truth.
[
    ['customer-name', 'customerName'],
    ['customer-address', 'customerAddress']
].forEach(([elementId, key]) => {
    const input = document.getElementById(elementId);
    if (!input) return;
    input.addEventListener('input', () => {
        initDefaultCosting(state);
        state.costing[key] = input.value;
        if (typeof window.triggerAutosave === 'function') window.triggerAutosave();
    });
});

// Resize Canvas
function resizeCanvas() {
    canvas.width = container.clientWidth;
    canvas.height = container.clientHeight;
    draw();
}

// Coordinate Conversions
function toCanvasX(worldX) {
    return (worldX * state.scale) + state.offsetX + (canvas.width / 2);
}

function toCanvasY(worldY) {
    return (worldY * state.scale) + state.offsetY + (canvas.height / 2);
}

function toWorldX(canvasX) {
    return (canvasX - state.offsetX - (canvas.width / 2)) / state.scale;
}

function toWorldY(canvasY) {
    return (canvasY - state.offsetY - (canvas.height / 2)) / state.scale;
}

// Helper: Checks which room a world coordinate is in (supports custom polygons)
function getRoomAt(x, y, levelId) {
    return state.rooms.find(room => {
        if (room.levelId !== levelId) return false;
        if (room.type === 'custom' && room.vertices) {
            let inside = false;
            for (let i = 0, j = room.vertices.length - 1; i < room.vertices.length; j = i++) {
                const xi = room.x + room.vertices[i].x, yi = room.y + room.vertices[i].y;
                const xj = room.x + room.vertices[j].x, yj = room.y + room.vertices[j].y;
                const intersect = ((yi > y) !== (yj > y))
                    && (x < (xj - xi) * (y - yi) / (yj - yi) + xi);
                if (intersect) inside = !inside;
            }
            return inside;
        } else {
            return x >= room.x && x <= room.x + room.w && y >= room.y && y <= room.y + room.l;
        }
    });
}

// Print-safe color selector helper
function c(darkColor, printColor) {
    return state.isPrintingMode ? printColor : darkColor;
}

// Snap value to nearest grid size
function snap(val) {
    return Math.round(val / state.snapGridSize) * state.snapGridSize;
}

// Generate unique ID
function generateId() {
    return 'id_' + Math.random().toString(36).substr(2, 9);
}

// Add Room Function
function addRoom(type, placement = null) {
    if (typeof saveHistoryState === 'function') saveHistoryState();
    const preset = PRESETS[type];
    const newRoom = {
        id: generateId(),
        levelId: state.currentLevelId,
        name: preset.name,
        type: type,
        w: preset.w,
        l: preset.l,
        h: preset.h,
        x: snap((placement ? placement.x : toWorldX(canvas.width / 2)) - preset.w / 2),
        y: snap((placement ? placement.y : toWorldY(canvas.height / 2)) - preset.l / 2),
        color: preset.color,
        openings: [],
        foamBoard: false,
        foamBondPockets: false,
        carbonStraps: 0,
        carbonFiberScope: 'full',
        carbonFiberWalls: [],
        customCarbonStraps: [],
        floorPerimeterStrap: false,
        nb1Height: 'none',
        drywallHeight: 'none'
    };
    if (preset.steps) {
        newRoom.steps = preset.steps;
        newRoom.stairOrientation = 'N';
        newRoom.stairDirection = 'up';
    }
    state.rooms.push(newRoom);
    selectItem('room', newRoom.id);
    draw();
    updateGlobalStats();
    
    if (window.sync3D) window.sync3D();
}

function centerOnRoom(room) {
    state.offsetX = -(room.x + room.w / 2) * state.scale;
    state.offsetY = -(room.y + room.l / 2) * state.scale;
}

// Add Sump Pump
function addSumpPump(placement = null) {
    if (typeof saveHistoryState === 'function') saveHistoryState();
    const newPump = {
        id: generateId(),
        levelId: state.currentLevelId,
        name: `Sump Pump ${state.sumpPumps.length + 1}`,
        x: snap(placement ? placement.x : toWorldX(canvas.width / 2)),
        y: snap(placement ? placement.y : toWorldY(canvas.height / 2))
    };
    state.sumpPumps.push(newPump);
    selectItem('sump', newPump.id);
    draw();
    updateGlobalStats();
}

// Add Dehumidifier
function addDehumidifier(placement = null) {
    if (typeof saveHistoryState === 'function') saveHistoryState();
    const newDehum = {
        id: generateId(),
        levelId: state.currentLevelId,
        name: `Dehumidifier ${state.dehumidifiers.length + 1}`,
        x: snap(placement ? placement.x : toWorldX(canvas.width / 2)),
        y: snap(placement ? placement.y : toWorldY(canvas.height / 2))
    };
    state.dehumidifiers.push(newDehum);
    selectItem('dehumidifier', newDehum.id);
    draw();
    updateGlobalStats();
}

// Add Discharge Line
function addDischargeLine(placement = null) {
    if (typeof saveHistoryState === 'function') saveHistoryState();
    const cx = snap(placement ? placement.x : toWorldX(canvas.width / 2));
    const cy = snap(placement ? placement.y : toWorldY(canvas.height / 2));
    const newLine = {
        id: generateId(),
        levelId: state.currentLevelId,
        label: `Discharge Line ${state.dischargeLines.length + 1}`,
        x1: cx - 3,
        y1: cy,
        x2: cx + 3,
        y2: cy,
        length: 6.0
    };
    state.dischargeLines.push(newLine);
    selectItem('discharge', newLine.id);
    draw();
    updateGlobalStats();
}
// Add Interior Pipe
function addInteriorPipe(placement = null) {
    if (typeof saveHistoryState === 'function') saveHistoryState();
    const cx = snap(placement ? placement.x : toWorldX(canvas.width / 2));
    const cy = snap(placement ? placement.y : toWorldY(canvas.height / 2));
    const newPipe = {
        id: generateId(),
        levelId: state.currentLevelId,
        label: `Interior Pipe ${state.interiorPipes.length + 1}`,
        x1: cx - 2,
        y1: cy,
        x2: cx + 2,
        y2: cy,
        length: 4.0
    };
    state.interiorPipes.push(newPipe);
    selectItem('interiorPipe', newPipe.id);
    draw();
    updateGlobalStats();
}

// Add Stanchion
function addStanchion(placement = null) {
    if (typeof saveHistoryState === 'function') saveHistoryState();
    const cx = snap(placement ? placement.x : toWorldX(canvas.width / 2));
    const cy = snap(placement ? placement.y : toWorldY(canvas.height / 2));
    const newStanchion = {
        id: generateId(),
        levelId: state.currentLevelId,
        name: `Stanchion ${state.stanchions.length + 1}`,
        x: cx,
        y: cy,
        type: 'round' // 'round' or 'square'
    };
    state.stanchions.push(newStanchion);
    selectItem('stanchion', newStanchion.id);
    draw();
    updateGlobalStats();
}

// Add Support Beam
function addSupportBeam(placement = null) {
    if (typeof saveHistoryState === 'function') saveHistoryState();
    const cx = snap(placement ? placement.x : toWorldX(canvas.width / 2));
    const cy = snap(placement ? placement.y : toWorldY(canvas.height / 2));
    const newBeam = {
        id: generateId(),
        levelId: state.currentLevelId,
        label: `Support Beam ${state.mainBeams.length + 1}`,
        x1: cx - 3,
        y1: cy,
        x2: cx + 3,
        y2: cy,
        length: 6.0,
        type: 'timber' // 'timber' or 'steel'
    };
    state.mainBeams.push(newBeam);
    selectItem('beam', newBeam.id);
    draw();
    updateGlobalStats();
}



function updateToolboxReinforcementLabels(room) {
    const strapLabel = document.getElementById('btn-add-strap-label');
    const perimLabel = document.getElementById('btn-add-perimeter-strap-label');
    const nb1Label = document.getElementById('btn-add-nb1-label');
    const drywallLabel = document.getElementById('btn-add-drywall-label');
    
    if (room) {
        const straps = room.carbonStraps || 0;
        const hasPerim = !!room.floorPerimeterStrap;
        const nb1Val = room.nb1Height || 'none';
        const nb1HeightLabels = { 'none': 'None', '2ft': '2 ft', '4ft': '4 ft', 'full': 'Full' };
        const drywallVal = room.drywallHeight || 'none';
        const drywallHeightLabels = { 'none': 'None', '1ft': '1 ft', '2ft': '2 ft', '4ft': '4 ft', '6ft': '6 ft', 'full': 'Full' };
        
        if (strapLabel) strapLabel.innerText = `Vertical Strap (${straps})`;
        if (perimLabel) perimLabel.innerText = `Perimeter: ${hasPerim ? 'ON' : 'OFF'}`;
        if (nb1Label) nb1Label.innerText = `NB1: ${nb1HeightLabels[nb1Val]}`;
        if (drywallLabel) drywallLabel.innerText = `Drywall: ${drywallHeightLabels[drywallVal]}`;
    } else {
        if (strapLabel) strapLabel.innerText = 'Vertical Strap (+1)';
        if (perimLabel) perimLabel.innerText = 'Floor Perimeter';
        if (nb1Label) nb1Label.innerText = 'NB1 Coating (Cycle)';
        if (drywallLabel) drywallLabel.innerText = 'Drywall Cut (Cycle)';
    }
}

// Selection Manager
function selectItem(type, id) {
    state.selectedRoomId = (type === 'room') ? id : null;
    state.selectedSumpPumpId = (type === 'sump') ? id : null;
    state.selectedDehumidifierId = (type === 'dehumidifier') ? id : null;
    state.selectedDischargeLineId = (type === 'discharge') ? id : null;
    state.selectedInteriorPipeId = (type === 'interiorPipe') ? id : null;
    state.selectedStanchionId = (type === 'stanchion') ? id : null;
    state.selectedMainBeamId = (type === 'beam') ? id : null;
    state.selectedFloorHatchId = (type === 'floorHatch') ? id : null;
    
    const roomFields = document.getElementById('room-edit-fields');
    const sumpFields = document.getElementById('sump-edit-fields');
    const dehumidifierFields = document.getElementById('dehumidifier-edit-fields');
    const dischargeFields = document.getElementById('discharge-edit-fields');
    const interiorPipeFields = document.getElementById('interior-pipe-edit-fields');
    const stanchionFields = document.getElementById('stanchion-edit-fields');
    const beamFields = document.getElementById('beam-edit-fields');
    const floorHatchFields = document.getElementById('floor-hatch-edit-fields');
    const noSel = document.getElementById('no-selection-msg');
    
    const btnAddDoor = document.getElementById('btn-add-door');
    const btnAddWindow = document.getElementById('btn-add-window');
    const btnAddCrawlDoor = document.getElementById('btn-add-crawl-door');
    const btnAddHatch = document.getElementById('btn-add-hatch');
    const btnAddStrap = document.getElementById('btn-add-strap');
    const btnAddPerim = document.getElementById('btn-add-perimeter-strap');
    const btnAddNb1 = document.getElementById('btn-add-nb1');
    const btnAddDrywall = document.getElementById('btn-add-drywall');
    
    // Hide all
    roomFields.classList.add('hidden');
    sumpFields.classList.add('hidden');
    if (dehumidifierFields) dehumidifierFields.classList.add('hidden');
    dischargeFields.classList.add('hidden');
    if (interiorPipeFields) interiorPipeFields.classList.add('hidden');
    if (stanchionFields) stanchionFields.classList.add('hidden');
    if (beamFields) beamFields.classList.add('hidden');
    if (floorHatchFields) floorHatchFields.classList.add('hidden');
    noSel.classList.remove('hidden');
    btnAddDoor.disabled = true;
    btnAddWindow.disabled = true;
    if (btnAddCrawlDoor) btnAddCrawlDoor.disabled = true;
    if (btnAddHatch) btnAddHatch.disabled = true;
    if (btnAddStrap) btnAddStrap.disabled = true;
    if (btnAddPerim) btnAddPerim.disabled = true;
    if (btnAddNb1) btnAddNb1.disabled = true;
    if (btnAddDrywall) btnAddDrywall.disabled = true;
    updateToolboxReinforcementLabels(null);
    
    if (type === 'room' && id) {
        const room = state.rooms.find(r => r.id === id);
        if (room) {
            noSel.classList.add('hidden');
            roomFields.classList.remove('hidden');
            btnAddDoor.disabled = false;
            btnAddWindow.disabled = false;
            if (btnAddCrawlDoor) btnAddCrawlDoor.disabled = false;
            if (btnAddHatch) btnAddHatch.disabled = false;
            
            document.getElementById('room-name-input').value = room.name;
            document.getElementById('room-h-input').value = room.h;
            
            const joistSelect = document.getElementById('room-joists-select');
            if (joistSelect) joistSelect.value = room.joists || 'none';

            const foamCheckbox = document.getElementById('room-foam-board-checkbox');
            if (foamCheckbox) foamCheckbox.checked = !!room.foamBoard;

            const pocketsCheckbox = document.getElementById('room-foam-bond-pockets-checkbox');
            if (pocketsCheckbox) pocketsCheckbox.checked = !!room.foamBondPockets;

            const strapsInput = document.getElementById('room-carbon-straps-input');
            if (strapsInput) strapsInput.value = room.carbonStraps || 0;

            const scopeSelect = document.getElementById('room-carbon-scope-select');
            if (scopeSelect) scopeSelect.value = room.carbonFiberScope || 'full';
            if (typeof renderCarbonWallsCheckboxes === 'function') {
                renderCarbonWallsCheckboxes(room);
            }

            const floorStrapCheckbox = document.getElementById('room-floor-perimeter-strap-checkbox');
            if (floorStrapCheckbox) floorStrapCheckbox.checked = !!room.floorPerimeterStrap;

            const nb1Select = document.getElementById('room-nb1-select');
            if (nb1Select) nb1Select.value = room.nb1Height || 'none';
            
            const drywallSelect = document.getElementById('room-drywall-select');
            if (drywallSelect) drywallSelect.value = room.drywallHeight || 'none';
            renderDrywallWallCheckboxes(room);

            const removeInsulationCheckbox = document.getElementById('room-remove-insulation-checkbox');
            if (removeInsulationCheckbox) removeInsulationCheckbox.checked = !!room.removeInsulation;

            const blowInsulationCheckbox = document.getElementById('room-blow-insulation-checkbox');
            if (blowInsulationCheckbox) blowInsulationCheckbox.checked = !!room.blowInInsulation;
            
            const rectInputs = document.getElementById('room-rect-inputs');
            const customInputs = document.getElementById('room-custom-walls-inputs');
            
            customInputs.classList.remove('hidden');
            const container = document.getElementById('custom-walls-list-container');
            container.innerHTML = '';
            
            if (room.type === 'custom' && room.vertices && room.vertices.length >= 3) {
                rectInputs.classList.add('hidden');
                for (let i = 0; i < room.vertices.length; i++) {
                    const v1 = room.vertices[i];
                    const v2 = room.vertices[(i + 1) % room.vertices.length];
                    const dx = v2.x - v1.x;
                    const dy = v2.y - v1.y;
                    const currentLength = Math.sqrt(dx*dx + dy*dy);
                    
                    const div = document.createElement('div');
                    div.style.display = 'flex';
                    div.style.justifyContent = 'space-between';
                    div.style.alignItems = 'center';
                    div.style.marginBottom = '0.3rem';
                    div.style.padding = '0.2rem 0.5rem';
                    div.style.background = 'rgba(255,255,255,0.02)';
                    div.style.border = '1px solid var(--border-color)';
                    div.style.borderRadius = '6px';
                    div.innerHTML = `
                        <span style="font-size:0.75rem; color:var(--text-muted); font-weight:500;">Wall ${i + 1}</span>
                        <input type="number" step="0.5" min="0.5" value="${currentLength.toFixed(1)}" 
                            style="width: 75px; padding: 0.15rem 0.35rem; font-family: var(--font-mono); font-weight:600; font-size: 0.75rem; background:rgba(0,0,0,0.3); border:1px solid var(--border-color); border-radius:4px; color:var(--accent-teal); text-align:right;"
                            onchange="changeCustomWallLength('${room.id}', ${i}, this.value)">
                    `;
                    container.appendChild(div);
                }
            } else {
                rectInputs.classList.remove('hidden');
                document.getElementById('room-w-input').value = room.w;
                document.getElementById('room-l-input').value = room.l;
                
                const walls = [
                    { name: 'Wall 1 (North)', key: 'n', val: room.w },
                    { name: 'Wall 2 (East)', key: 'e', val: room.l },
                    { name: 'Wall 3 (South)', key: 's', val: room.w },
                    { name: 'Wall 4 (West)', key: 'w', val: room.l }
                ];
                
                walls.forEach(w => {
                    const div = document.createElement('div');
                    div.style.display = 'flex';
                    div.style.justifyContent = 'space-between';
                    div.style.alignItems = 'center';
                    div.style.marginBottom = '0.3rem';
                    div.style.padding = '0.2rem 0.5rem';
                    div.style.background = 'rgba(255,255,255,0.02)';
                    div.style.border = '1px solid var(--border-color)';
                    div.style.borderRadius = '6px';
                    div.innerHTML = `
                        <span style="font-size:0.75rem; color:var(--text-muted); font-weight:500;">${w.name}</span>
                        <input type="number" step="0.5" min="0.5" value="${w.val.toFixed(1)}" 
                            style="width: 75px; padding: 0.15rem 0.35rem; font-family: var(--font-mono); font-weight:600; font-size: 0.75rem; background:rgba(0,0,0,0.3); border:1px solid var(--border-color); border-radius:4px; color:var(--accent-teal); text-align:right;"
                            onchange="changeRectWallLength('${room.id}', '${w.key}', this.value)">
                    `;
                    container.appendChild(div);
                });
            }
            
            const stepsGroup = document.getElementById('room-steps-group');
            const stairProperties = document.getElementById('room-staircase-properties');
            if (room.type === 'staircase') {
                stepsGroup.classList.remove('hidden');
                stairProperties.classList.remove('hidden');
                document.getElementById('room-steps-input').value = room.steps || 12;
                
                if (!room.stairOrientation) room.stairOrientation = 'N';
                if (!room.stairDirection) room.stairDirection = 'up';
                
                document.getElementById('stair-orientation-select').value = room.stairOrientation;
                document.getElementById('stair-direction-select').value = room.stairDirection;
            } else {
                stepsGroup.classList.add('hidden');
                stairProperties.classList.add('hidden');
            }
            
            btnAddDoor.disabled = false;
            btnAddWindow.disabled = false;
            if (btnAddStrap) btnAddStrap.disabled = false;
            if (btnAddPerim) btnAddPerim.disabled = false;
            if (btnAddNb1) btnAddNb1.disabled = false;
            if (btnAddDrywall) btnAddDrywall.disabled = false;
            updateToolboxReinforcementLabels(room);
            updateRoomEstimates(room);
        }
    } else if (type === 'sump' && id) {
        const sump = state.sumpPumps.find(p => p.id === id);
        if (sump) {
            noSel.classList.add('hidden');
            sumpFields.classList.remove('hidden');
            document.getElementById('sump-name-input').value = sump.name;
        }
    } else if (type === 'dehumidifier' && id) {
        const dehum = state.dehumidifiers.find(p => p.id === id);
        if (dehum && dehumidifierFields) {
            noSel.classList.add('hidden');
            dehumidifierFields.classList.remove('hidden');
            document.getElementById('dehumidifier-name-input').value = dehum.name;
        }
    } else if (type === 'discharge' && id) {
        const dl = state.dischargeLines.find(l => l.id === id);
        if (dl) {
            noSel.classList.add('hidden');
            dischargeFields.classList.remove('hidden');
            document.getElementById('discharge-label-input').value = dl.label;
            document.getElementById('discharge-len-input').value = dl.length.toFixed(1);
        }
    } else if (type === 'interiorPipe' && id) {
        const ip = state.interiorPipes.find(l => l.id === id);
        const interiorPipeFields = document.getElementById('interior-pipe-edit-fields');
        if (ip && interiorPipeFields) {
            noSel.classList.add('hidden');
            interiorPipeFields.classList.remove('hidden');
            document.getElementById('interior-pipe-label-input').value = ip.label;
            document.getElementById('interior-pipe-len-input').value = ip.length.toFixed(1);
        }
    } else if (type === 'stanchion' && id) {
        const st = state.stanchions.find(p => p.id === id);
        const stanchionFields = document.getElementById('stanchion-edit-fields');
        if (st && stanchionFields) {
            noSel.classList.add('hidden');
            stanchionFields.classList.remove('hidden');
            document.getElementById('stanchion-name-input').value = st.name;
            document.getElementById('stanchion-type-select').value = st.type || 'round';
        }
    } else if (type === 'beam' && id) {
        const bm = state.mainBeams.find(l => l.id === id);
        const beamFields = document.getElementById('beam-edit-fields');
        if (bm && beamFields) {
            noSel.classList.add('hidden');
            beamFields.classList.remove('hidden');
            document.getElementById('beam-label-input').value = bm.label;
            document.getElementById('beam-type-select').value = bm.type || 'timber';
            document.getElementById('beam-len-input').value = bm.length.toFixed(1);
        }
    } else if (type === 'floorHatch' && id) {
        const h = state.floorHatches.find(p => p.id === id);
        const floorHatchFields = document.getElementById('floor-hatch-edit-fields');
        if (h && floorHatchFields) {
            noSel.classList.add('hidden');
            floorHatchFields.classList.remove('hidden');
            document.getElementById('floor-hatch-name-input').value = h.name;
            document.getElementById('floor-hatch-width-input').value = h.w;
            document.getElementById('floor-hatch-length-input').value = h.l;
            document.getElementById('floor-hatch-target-select').value = h.target || 'floor';
        }
    }
    
    // Toggle estimator panel visibility
    const estList = document.getElementById('estimations-list');
    const noEstMsg = document.getElementById('no-estimates-msg');
    if (type === 'room' && id) {
        estList.classList.remove('hidden');
        noEstMsg.classList.add('hidden');
    } else {
        estList.classList.add('hidden');
        noEstMsg.classList.remove('hidden');
    }

    // Keep the mobile canvas available after selection so rooms and vertices
    // can be dragged immediately. The explicit Details button opens the editor.
    const mobileDetailsButton = document.getElementById('mobile-toggle-details');
    if (mobileDetailsButton) mobileDetailsButton.classList.toggle('has-selection', !!(type && id));
    
    draw();
}

// Fallback mapper
function selectRoom(id) {
    selectItem('room', id);
}

// Add Openings (Doors/Windows)
function addOpening(type) {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (!room) return;
    if (typeof saveHistoryState === 'function') saveHistoryState();

    let bestWall;
    let maxOffset;

    if (room.type === 'custom' && room.vertices && room.vertices.length >= 3) {
        // Custom room: Find the wall segment (index) with the fewest openings
        const wallCounts = {};
        for (let i = 0; i < room.vertices.length; i++) {
            wallCounts[i] = 0;
        }
        room.openings.forEach(op => {
            const idx = parseInt(op.wall);
            if (!isNaN(idx) && idx in wallCounts) {
                wallCounts[idx]++;
            }
        });
        
        let minCount = Infinity;
        let selectedIdx = 0;
        for (let i = 0; i < room.vertices.length; i++) {
            if (wallCounts[i] < minCount) {
                minCount = wallCounts[i];
                selectedIdx = i;
            }
        }
        bestWall = selectedIdx.toString();
        
        const v1 = room.vertices[selectedIdx];
        const v2 = room.vertices[(selectedIdx + 1) % room.vertices.length];
        const dx = v2.x - v1.x;
        const dy = v2.y - v1.y;
        maxOffset = Math.sqrt(dx*dx + dy*dy);
    } else {
        const walls = ['n', 'e', 's', 'w'];
        const wallCounts = { n: 0, e: 0, s: 0, w: 0 };
        room.openings.forEach(op => wallCounts[op.wall]++);
        bestWall = walls.reduce((a, b) => wallCounts[a] <= wallCounts[b] ? a : b);
        maxOffset = (bestWall === 'n' || bestWall === 's') ? room.w : room.l;
    }

    const width = type === 'door' ? 3.0 : (type === 'crawl_door' ? 3.0 : 4.0);
    const height = type === 'door' ? 6.8 : (type === 'crawl_door' ? 2.0 : 4.0);
    const offset = snap(maxOffset / 2);

    room.openings.push({
        id: generateId(),
        type: type,
        wall: bestWall,
        offset: offset,
        w: width,
        h: height
    });

    updateRoomEstimates(room);
    draw();
    if (window.sync3D) window.sync3D();
}

// Remove Opening
function removeOpening(openingId) {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (!room) return;
    if (typeof saveHistoryState === 'function') saveHistoryState();

    room.openings = room.openings.filter(op => op.id !== openingId);
    updateRoomEstimates(room);
    draw();
    if (window.sync3D) window.sync3D();
}

// Update Opening inline values
window.updateOpening = function(roomId, openingId, property, value) {
    const room = state.rooms.find(r => r.id === roomId);
    if (!room) return;
    const op = room.openings.find(o => o.id === openingId);
    if (!op) return;
    if (typeof saveHistoryState === 'function') saveHistoryState();
    
    if (property === 'wall') {
        op.wall = value;
        const maxOffset = (value === 'n' || value === 's') ? room.w : room.l;
        op.offset = snap(maxOffset / 2);
    } else if (property === 'offset') {
        const maxOffset = (op.wall === 'n' || op.wall === 's') ? room.w : room.l;
        op.offset = Math.min(maxOffset - op.w/2, Math.max(op.w/2, snap(parseFloat(value))));
    } else if (property === 'w') {
        op.w = Math.max(0.5, parseFloat(value));
    } else if (property === 'h') {
        op.h = Math.max(0.5, parseFloat(value));
    }
    
    updateRoomEstimates(room);
    draw();
    if (window.sync3D) window.sync3D();
};

function getPolygonArea(vertices) {
    if (!vertices || vertices.length < 3) return 0;
    let area = 0;
    for (let i = 0; i < vertices.length; i++) {
        const v1 = vertices[i];
        const v2 = vertices[(i + 1) % vertices.length];
        area += v1.x * v2.y - v2.x * v1.y;
    }
    return Math.abs(area / 2);
}

function getPolygonPerimeter(vertices) {
    if (!vertices || vertices.length < 2) return 0;
    let perimeter = 0;
    for (let i = 0; i < vertices.length; i++) {
        const v1 = vertices[i];
        const v2 = vertices[(i + 1) % vertices.length];
        const dx = v2.x - v1.x;
        const dy = v2.y - v1.y;
        perimeter += Math.sqrt(dx*dx + dy*dy);
    }
    return perimeter;
}

// Calculate Estimates
function updateRoomEstimates(room) {
    let floorArea, perimeter;
    if (room.type === 'custom' && room.vertices && room.vertices.length >= 3) {
        floorArea = getPolygonArea(room.vertices);
        perimeter = getPolygonPerimeter(room.vertices);
    } else {
        floorArea = room.w * room.l;
        perimeter = 2 * (room.w + room.l);
    }
    const ceilingArea = floorArea;
    const volume = room.type === 'staircase' ? 0.5 * floorArea * room.h : floorArea * room.h;
    
    // Gross Wall Area
    let grossWallArea;
    if (room.type === 'staircase') {
        grossWallArea = (room.l * room.h) + (room.w * room.h);
    } else {
        grossWallArea = perimeter * room.h;
    }
    
    // Deductions
    let totalDeductions = 0;
    const deductionsUl = document.getElementById('deductions-ul');
    deductionsUl.innerHTML = '';

    room.openings.forEach(op => {
        const area = op.w * op.h;
        totalDeductions += area;

        const li = document.createElement('li');
        li.className = 'opening-edit-card';
        li.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.4rem;">
                <span style="font-weight:600; color:var(--text-primary); font-size:0.75rem;">${op.type.toUpperCase()}</span>
                <button onclick="removeOpening('${op.id}')" style="background:none; border:none; color:var(--text-muted); cursor:pointer;" title="Delete"><i data-lucide="trash-2" style="width:14px; height:14px;"></i></button>
            </div>
            <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap: 0.25rem;">
                <div>
                    <label>Wall</label>
                    <select onchange="updateOpening('${room.id}', '${op.id}', 'wall', this.value)">
                        ${room.type === 'custom' && room.vertices
                            ? room.vertices.map((v, i) => `<option value="${i}" ${op.wall === i.toString() ? 'selected' : ''}>Wall ${i+1}</option>`).join('')
                            : `
                                <option value="n" ${op.wall === 'n' ? 'selected' : ''}>N</option>
                                <option value="e" ${op.wall === 'e' ? 'selected' : ''}>E</option>
                                <option value="s" ${op.wall === 's' ? 'selected' : ''}>S</option>
                                <option value="w" ${op.wall === 'w' ? 'selected' : ''}>W</option>
                            `
                        }
                    </select>
                </div>
                <div>
                    <label>Offset</label>
                    <input type="number" step="0.5" value="${op.offset}" oninput="updateOpening('${room.id}', '${op.id}', 'offset', this.value)">
                </div>
                <div>
                    <label>Width</label>
                    <input type="number" step="0.5" value="${op.w}" oninput="updateOpening('${room.id}', '${op.id}', 'w', this.value)">
                </div>
                <div>
                    <label>Height</label>
                    <input type="number" step="0.5" value="${op.h}" oninput="updateOpening('${room.id}', '${op.id}', 'h', this.value)">
                </div>
            </div>
        `;
        deductionsUl.appendChild(li);
    });
    lucide.createIcons();

    const netWallArea = Math.max(0, grossWallArea - totalDeductions);

    // Update UI
    document.getElementById('metric-floor-area').innerText = `${floorArea.toFixed(1)} sq ft`;
    document.getElementById('metric-wall-area').innerText = `${netWallArea.toFixed(1)} sq ft (${grossWallArea.toFixed(1)} gross)`;
    document.getElementById('metric-ceiling-area').innerText = `${ceilingArea.toFixed(1)} sq ft`;
    document.getElementById('metric-perimeter').innerText = `${perimeter.toFixed(1)} ft`;
    document.getElementById('metric-volume').innerText = `${volume.toFixed(1)} cu ft`;

    const bondPocketRow = document.getElementById('metric-bond-pockets-row');
    const bondPocketCans = document.getElementById('metric-bond-pockets-cans');
    
    if (room.foamBondPockets && room.joists && room.joists !== 'none') {
        const segments = getRoomSegments(room);
        let wallLen = 0;
        segments.forEach(seg => {
            const dx = seg.x2 - seg.x1;
            const dy = seg.y2 - seg.y1;
            if (room.joists === 'ns') {
                wallLen += Math.abs(dx);
            } else if (room.joists === 'ew') {
                wallLen += Math.abs(dy);
            }
        });
        const roomBF = wallLen * 1.5;
        const cans = Math.ceil(roomBF / 20);
        
        if (bondPocketRow) bondPocketRow.style.display = 'flex';
        if (bondPocketCans) bondPocketCans.innerText = `${cans} cans (${roomBF.toFixed(1)} BF)`;
    } else {
        if (bondPocketRow) bondPocketRow.style.display = 'none';
    }

    updateGlobalStats();
}

// Helper to calculate the exterior wall perimeter of a room (excluding shared/touching walls on the same floor)
function getRoomExteriorPerimeter(room) {
    let extPerimeter = 0;
    const segments = getRoomSegments(room);
    
    segments.forEach(seg => {
        const mx = (seg.x1 + seg.x2) / 2;
        const my = (seg.y1 + seg.y2) / 2;
        
        let isShared = false;
        // Check other rooms
        for (let i = 0; i < state.rooms.length; i++) {
            const other = state.rooms[i];
            if (other.id === room.id || other.levelId !== room.levelId) continue;
            
            const otherSegs = getRoomSegments(other);
            for (let j = 0; j < otherSegs.length; j++) {
                const oSeg = otherSegs[j];
                const dist = getDistanceToSegment(mx, my, oSeg.x1, oSeg.y1, oSeg.x2, oSeg.y2);
                if (dist < 0.25) { // within 3 inches
                    isShared = true;
                    break;
                }
            }
            if (isShared) break;
        }
        
        if (!isShared) {
            extPerimeter += Math.sqrt((seg.x2 - seg.x1)**2 + (seg.y2 - seg.y1)**2);
        }
    });
    
    return extPerimeter;
}

// Automatically space straps: start 2ft from corners, then space roughly 5ft apart
function autoSpaceCarbonStraps(room) {
    room.customCarbonStraps = [];
    const segments = getRoomSegments(room);
    
    segments.forEach(seg => {
        // Only place on walls included in carbonFiberWalls if scope is 'specific'
        if (room.carbonFiberScope === 'specific' && Array.isArray(room.carbonFiberWalls)) {
            if (!room.carbonFiberWalls.includes(seg.wall)) return;
        }
        
        const dx = seg.x2 - seg.x1;
        const dy = seg.y2 - seg.y1;
        const len = Math.sqrt(dx*dx + dy*dy);
        
        if (len < 4.0) {
            // Short wall: place 1 strap at the center if length is at least 1.5 ft
            if (len >= 1.5) {
                room.customCarbonStraps.push({
                    id: 'strap_' + Math.random().toString(36).substr(2, 9),
                    wall: seg.wall,
                    offset: 0.5
                });
            }
        } else {
            // Standard wall: start 2ft from each corner, space roughly 5ft
            const availableLen = len - 4.0;
            const intervals = Math.round(availableLen / 5.0);
            const count = intervals + 1;
            
            if (count === 1) {
                room.customCarbonStraps.push({
                    id: 'strap_' + Math.random().toString(36).substr(2, 9),
                    wall: seg.wall,
                    offset: 0.5
                });
            } else {
                const spacing = availableLen / (count - 1);
                for (let i = 0; i < count; i++) {
                    const distFromStart = 2.0 + i * spacing;
                    const ratio = distFromStart / len;
                    room.customCarbonStraps.push({
                        id: 'strap_' + Math.random().toString(36).substr(2, 9),
                        wall: seg.wall,
                        offset: Math.max(0.01, Math.min(0.99, ratio))
                    });
                }
            }
        }
    });
    
    room.carbonStraps = room.customCarbonStraps.length;
}

// Initialize or synchronize manual custom straps to match count
function initializeCustomStraps(room) {
    if (!room.customCarbonStraps) room.customCarbonStraps = [];
    const count = room.carbonStraps || 0;
    if (room.customCarbonStraps.length === count) return;
    
    const segments = getRoomSegments(room);
    if (segments.length === 0) return;
    
    if (room.customCarbonStraps.length < count) {
        const needed = count - room.customCarbonStraps.length;
        for (let i = 0; i < needed; i++) {
            const segIdx = (room.customCarbonStraps.length) % segments.length;
            const seg = segments[segIdx];
            // Space offset ratios safely
            const sameSegCount = room.customCarbonStraps.filter(s => s.wall === seg.wall).length;
            const offset = Math.max(0.1, Math.min(0.9, 0.2 + (sameSegCount * 0.2) % 0.6));
            room.customCarbonStraps.push({
                id: 'strap_' + Math.random().toString(36).substr(2, 9),
                wall: seg.wall,
                offset: offset
            });
        }
    } else if (room.customCarbonStraps.length > count) {
        room.customCarbonStraps = room.customCarbonStraps.slice(0, count);
    }
}

// Helper to get all wall segments of a room
function getRoomSegments(room) {
    const segs = [];
    if (room.type === 'custom' && room.vertices && room.vertices.length >= 3) {
        const originX = Number(room.x) || 0;
        const originY = Number(room.y) || 0;
        for (let i = 0; i < room.vertices.length; i++) {
            const v1 = room.vertices[i];
            const v2 = room.vertices[(i + 1) % room.vertices.length];
            segs.push({
                x1: originX + v1.x,
                y1: originY + v1.y,
                x2: originX + v2.x,
                y2: originY + v2.y,
                wall: i.toString()
            });
        }
    } else {
        const x = Number(room.x) || 0;
        const y = Number(room.y) || 0;
        const w = Number(room.w) || 0;
        const l = Number(room.l) || 0;
        segs.push({ x1: x, y1: y, x2: x + w, y2: y, wall: 'n' }); // North
        segs.push({ x1: x + w, y1: y, x2: x + w, y2: y + l, wall: 'e' }); // East
        segs.push({ x1: x, y1: y + l, x2: x + w, y2: y + l, wall: 's' }); // South
        segs.push({ x1: x, y1: y, x2: x, y2: y + l, wall: 'w' }); // West
    }
    return segs;
}

function getWallDisplayName(room, wallKey) {
    const cardinal = { n: 'North wall', e: 'East wall', s: 'South wall', w: 'West wall' };
    return cardinal[wallKey] || `Wall ${parseInt(wallKey, 10) + 1}`;
}

function getSelectedDrywallSegments(room) {
    const segments = getRoomSegments(room);
    if (!Array.isArray(room.drywallWalls)) return segments;
    return segments.filter(segment => room.drywallWalls.includes(String(segment.wall)));
}

function renderDrywallWallCheckboxes(room) {
    const container = document.getElementById('room-drywall-walls-checkboxes');
    const editor = document.getElementById('room-drywall-wall-scope');
    if (!container || !editor || !room) return;

    const segments = getRoomSegments(room);
    const selectedKeys = Array.isArray(room.drywallWalls)
        ? room.drywallWalls.map(String)
        : segments.map(segment => String(segment.wall));
    const disabled = !room.drywallHeight || room.drywallHeight === 'none';
    editor.classList.toggle('is-disabled', disabled);
    container.innerHTML = segments.map(segment => {
        const key = String(segment.wall);
        const length = Math.hypot(segment.x2 - segment.x1, segment.y2 - segment.y1);
        return `
            <label class="wall-scope-option">
                <input type="checkbox" ${selectedKeys.includes(key) ? 'checked' : ''} ${disabled ? 'disabled' : ''} onchange="toggleRoomDrywallWall('${room.id}','${key}',this.checked)">
                <span class="wall-color-key"></span>
                <strong>${getWallDisplayName(room, key)}</strong>
                <small>${length.toFixed(1)} ft</small>
            </label>
        `;
    }).join('');
}

window.toggleRoomDrywallWall = function(roomId, wallKey, checked) {
    const room = state.rooms.find(item => item.id === roomId);
    if (!room) return;
    if (typeof saveHistoryState === 'function') saveHistoryState();
    const allKeys = getRoomSegments(room).map(segment => String(segment.wall));
    const selected = Array.isArray(room.drywallWalls) ? [...room.drywallWalls].map(String) : [...allKeys];
    if (checked && !selected.includes(String(wallKey))) selected.push(String(wallKey));
    if (!checked) {
        const index = selected.indexOf(String(wallKey));
        if (index >= 0) selected.splice(index, 1);
    }
    room.drywallWalls = selected;
    renderDrywallWallCheckboxes(room);
    updateRoomEstimates(room);
    updateGlobalStats();
    draw();
    if (typeof window.triggerAutosave === 'function') window.triggerAutosave();
};

window.setAllRoomDrywallWalls = function(checked, roomId = state.selectedRoomId) {
    const room = state.rooms.find(item => item.id === roomId);
    if (!room) return;
    if (typeof saveHistoryState === 'function') saveHistoryState();
    room.drywallWalls = checked ? getRoomSegments(room).map(segment => String(segment.wall)) : [];
    renderDrywallWallCheckboxes(room);
    updateRoomEstimates(room);
    updateGlobalStats();
    draw();
    if (typeof window.renderGuidedStep === 'function' && state.currentStep === 4) window.renderGuidedStep();
    if (typeof window.triggerAutosave === 'function') window.triggerAutosave();
};

function drawDrywallWallScopes(room) {
    if (!room.drywallHeight || room.drywallHeight === 'none') return;
    const segments = getSelectedDrywallSegments(room);
    if (!segments.length) return;

    ctx.save();
    ctx.strokeStyle = state.isPrintingMode ? '#dc2626' : '#fb7185';
    ctx.fillStyle = state.isPrintingMode ? '#991b1b' : '#fecdd3';
    ctx.lineWidth = state.isPrintingMode ? 4 : 6;
    ctx.setLineDash([10, 6]);
    ctx.lineCap = 'round';
    ctx.font = `700 10px var(--font-sans)`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';

    segments.forEach(segment => {
        const x1 = toCanvasX(segment.x1);
        const y1 = toCanvasY(segment.y1);
        const x2 = toCanvasX(segment.x2);
        const y2 = toCanvasY(segment.y2);
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
        ctx.setLineDash([]);
        const worldDx = segment.x2 - segment.x1;
        const worldDy = segment.y2 - segment.y1;
        const worldLength = Math.hypot(worldDx, worldDy) || 1;
        const normalX = -worldDy / worldLength;
        const normalY = worldDx / worldLength;
        const midWorldX = (segment.x1 + segment.x2) / 2;
        const midWorldY = (segment.y1 + segment.y2) / 2;
        const insideCandidate = getRoomAt(midWorldX + normalX * 0.4, midWorldY + normalY * 0.4, room.levelId);
        const direction = insideCandidate && insideCandidate.id === room.id ? 1 : -1;
        const mx = (x1 + x2) / 2 + normalX * direction * 18;
        const my = (y1 + y2) / 2 + normalY * direction * 18;
        const label = room.drywallHeight === 'full' ? 'CUT FULL WALL' : `CUT ${room.drywallHeight.toUpperCase()}`;
        const labelWidth = ctx.measureText(label).width + 10;
        ctx.fillStyle = state.isPrintingMode ? 'rgba(255,255,255,0.9)' : 'rgba(15,23,42,0.88)';
        ctx.fillRect(mx - labelWidth / 2, my - 14, labelWidth, 16);
        ctx.fillStyle = state.isPrintingMode ? '#991b1b' : '#fecdd3';
        ctx.fillText(label, mx, my);
        ctx.setLineDash([10, 6]);
    });
    ctx.restore();
}

// Helper to estimate total PVC sticks and elbow fittings based on pipeline geometry
function estimatePlumbingMaterials() {
    let totalFootage = 0;
    let totalDrainTile = 0;
    let elbow90 = 0;
    let elbow45 = 0;
    
    let sumpCount = state.sumpPumps.length;
    let bushing3to2 = sumpCount * 1;
    let tee3x3x2 = sumpCount * 1;
    let elbow3in90 = sumpCount * 1;
    let screwAdapter1_5 = sumpCount * 2;
    let checkValve2 = sumpCount * 2;
    let yFitting2 = sumpCount * 1;
    
    // Add sump pump specific 2" elbows and 45s:
    // - 2 x 2" 90s from package
    // - 1 x 2" 90 where pvc goes up out of the sump
    // - 1 x 2" 45 from package
    elbow90 += sumpCount * 3;
    elbow45 += sumpCount * 1;
    
    // 1. Calculate PVC and Drain Tile footage
    state.dischargeLines.forEach(dl => { totalDrainTile += dl.length; });
    state.interiorPipes.forEach(ip => { totalFootage += ip.length; });
    state.sumpPumps.forEach(sp => {
        const spLevelId = sp.levelId || 'basement';
        const level = state.levels.find(l => l.id === spLevelId) || { height: 8 };
        const room = getRoomAt(sp.x, sp.y, spLevelId);
        const roomH = room ? room.h : (level.height || 8);
        totalFootage += (roomH - 0.2);
        
        // 1 x 90-degree elbow for riser top to horizontal run connection
        elbow90 += 1;
    });
    
    // 2. Identify pipe-to-pipe connections (only for PVC interior pipes)
    const pipes = [];
    state.interiorPipes.forEach(ip => {
        pipes.push({ x1: ip.x1, y1: ip.y1, x2: ip.x2, y2: ip.y2, levelId: ip.levelId || 'basement' });
    });
    
    const connectedPairs = new Set();
    
    for (let i = 0; i < pipes.length; i++) {
        for (let j = i + 1; j < pipes.length; j++) {
            const pA = pipes[i];
            const pB = pipes[j];
            if (pA.levelId !== pB.levelId) continue;
            
            let connected = false;
            let ax, ay, bx, by;
            
            if (Math.sqrt((pA.x1 - pB.x1)**2 + (pA.y1 - pB.y1)**2) < 0.25) {
                connected = true;
                ax = pA.x2 - pA.x1; ay = pA.y2 - pA.y1;
                bx = pB.x2 - pB.x1; by = pB.y2 - pB.y1;
            }
            else if (Math.sqrt((pA.x1 - pB.x2)**2 + (pA.y1 - pB.y2)**2) < 0.25) {
                connected = true;
                ax = pA.x2 - pA.x1; ay = pA.y2 - pA.y1;
                bx = pB.x1 - pB.x2; by = pB.y1 - pB.y2;
            }
            else if (Math.sqrt((pA.x2 - pB.x1)**2 + (pA.y2 - pB.y1)**2) < 0.25) {
                connected = true;
                ax = pA.x1 - pA.x2; ay = pA.y1 - pA.y2;
                bx = pB.x2 - pB.x1; by = pB.y2 - pB.y1;
            }
            else if (Math.sqrt((pA.x2 - pB.x2)**2 + (pA.y2 - pB.y2)**2) < 0.25) {
                connected = true;
                ax = pA.x1 - pA.x2; ay = pA.y1 - pA.y2;
                bx = pB.x1 - pB.x2; by = pB.y1 - pB.y2;
            }
            
            if (connected) {
                const key = `${i}_${j}`;
                if (!connectedPairs.has(key)) {
                    connectedPairs.add(key);
                    
                    const dot = ax * bx + ay * by;
                    const lenA = Math.sqrt(ax*ax + ay*ay);
                    const lenB = Math.sqrt(bx*bx + by*by);
                    if (lenA > 0.01 && lenB > 0.01) {
                        const cosTheta = Math.max(-1, Math.min(1, dot / (lenA * lenB)));
                        const rad = Math.acos(cosTheta);
                        const deg = rad * 180 / Math.PI;
                        const deflection = Math.abs(180 - deg);
                        
                        if (Math.abs(deflection - 90) <= 25) {
                            elbow90 += 1;
                        } else if (Math.abs(deflection - 45) <= 20) {
                            elbow45 += 1;
                        }
                    }
                }
            }
        }
    }
    
    const sticks = Math.ceil(totalFootage / 10);
    return {
        sticks,
        elbow90,
        elbow45,
        drainTile: totalDrainTile,
        bushing3to2,
        tee3x3x2,
        elbow3in90,
        screwAdapter1_5,
        checkValve2,
        yFitting2
    };
}

function updateGlobalStats() {
    const q = calculateProjectQuantities(state);
    
    document.getElementById('total-rooms-count').innerText = q.totalRooms;
    document.getElementById('total-floor-area').innerText = `${q.totalFloorArea.toFixed(1)} sq ft`;
    document.getElementById('total-wall-area').innerText = `${q.totalWallArea.toFixed(1)} sq ft`;
    
    let totalSumpCount = state.sumpPumps.length;
    let totalDischargeLen = 0;
    state.dischargeLines.forEach(dl => { totalDischargeLen += dl.length; });
    let totalInteriorPipeLen = 0;
    state.interiorPipes.forEach(ip => { totalInteriorPipeLen += ip.length; });
    
    document.getElementById('total-sumps-count').innerText = totalSumpCount;
    document.getElementById('total-discharge-length').innerText = `${totalDischargeLen.toFixed(1)} ft`;
    const intPipeText = document.getElementById('total-interior-pipe-length');
    if (intPipeText) intPipeText.innerText = `${q.totalInteriorPipeLen !== undefined ? q.totalInteriorPipeLen.toFixed(1) : totalInteriorPipeLen.toFixed(1)} ft`;
    
    const xpsText = document.getElementById('total-foam-sheets');
    if (xpsText) xpsText.innerText = `${Math.ceil(q.totalXpsSheets)} sheets`;
    
    const sticksText = document.getElementById('total-pvc-sticks');
    if (sticksText) sticksText.innerText = `${q.plumbingEst.sticks} sticks`;
    
    const elbows90Text = document.getElementById('total-pvc-90s');
    if (elbows90Text) elbows90Text.innerText = q.plumbingEst.elbow90;
    
    const elbows45Text = document.getElementById('total-pvc-45s');
    if (elbows45Text) elbows45Text.innerText = q.plumbingEst.elbow45;
    
    const tileText = document.getElementById('total-drain-tile');
    if (tileText) tileText.innerText = `${q.plumbingEst.drainTile.toFixed(1)} ft`;
    
    const sumpFittingsGroup = document.getElementById('sump-fittings-group');
    if (sumpFittingsGroup) {
        if (state.sumpPumps.length > 0) {
            sumpFittingsGroup.classList.remove('hidden');
            const bText = document.getElementById('total-bushing-3-2');
            const tText = document.getElementById('total-tee-3-3-2');
            const e3Text = document.getElementById('total-elbow-3-90');
            const sText = document.getElementById('total-screw-adapter');
            const cText = document.getElementById('total-check-valve');
            const yText = document.getElementById('total-y-fitting');
            
            if (bText) bText.innerText = q.plumbingEst.bushing3to2;
            if (tText) tText.innerText = q.plumbingEst.tee3x3x2;
            if (e3Text) e3Text.innerText = q.plumbingEst.elbow3in90;
            if (sText) sText.innerText = q.plumbingEst.screwAdapter1_5;
            if (cText) cText.innerText = q.plumbingEst.checkValve2;
            if (yText) yText.innerText = q.plumbingEst.yFitting2;
        } else {
            sumpFittingsGroup.classList.add('hidden');
        }
    }
    
    const linerText = document.getElementById('total-barrier-liner');
    if (linerText) linerText.innerText = `${q.totalLinerArea.toFixed(0)} sq ft`;
    
    const carbonText = document.getElementById('total-carbon-fiber');
    if (carbonText) carbonText.innerText = `${q.totalCarbonFiberLen.toFixed(1)} ft`;
    
    const nb1Text = document.getElementById('total-nb1-bags');
    if (nb1Text) {
        const sqFtPerBag = (state.costing && state.costing.settings && state.costing.settings.nb1SqFtPerBag) || 8;
        const nb1Bags = Math.ceil(q.totalNb1Area / sqFtPerBag);
        nb1Text.innerText = `${nb1Bags} bags (${q.totalNb1Area.toFixed(0)} sq ft)`;
    }
    
    const drywallText = document.getElementById('total-drywall-cut');
    if (drywallText) {
        drywallText.innerText = `${q.totalDrywallCutArea.toFixed(0)} sq ft`;
    }

    const insRemoveText = document.getElementById('total-insulation-remove');
    if (insRemoveText) {
        insRemoveText.innerText = `${(q.totalInsulationRemoveArea || 0).toFixed(0)} sq ft`;
    }

    const insBlowText = document.getElementById('total-insulation-blow');
    if (insBlowText) {
        insBlowText.innerText = `${(q.totalInsulationBlowArea || 0).toFixed(0)} sq ft`;
    }
    
    const foamCansText = document.getElementById('total-bond-pockets-cans');
    if (foamCansText) foamCansText.innerText = `${q.totalSprayFoamCans} cans`;
}

// Delete Selected Items
function deleteSelectedRoom() {
    if (!state.selectedRoomId) return;
    if (typeof saveHistoryState === 'function') saveHistoryState();
    state.rooms = state.rooms.filter(r => r.id !== state.selectedRoomId);
    selectItem(null);
    draw();
    updateGlobalStats();
    if (window.sync3D) window.sync3D();
}

function deleteSelectedSump() {
    if (!state.selectedSumpPumpId) return;
    if (typeof saveHistoryState === 'function') saveHistoryState();
    state.sumpPumps = state.sumpPumps.filter(p => p.id !== state.selectedSumpPumpId);
    selectItem(null);
    draw();
    updateGlobalStats();
}

function deleteSelectedDehumidifier() {
    if (!state.selectedDehumidifierId) return;
    if (typeof saveHistoryState === 'function') saveHistoryState();
    state.dehumidifiers = state.dehumidifiers.filter(p => p.id !== state.selectedDehumidifierId);
    selectItem(null);
    draw();
    updateGlobalStats();
}

function deleteSelectedDischarge() {
    if (!state.selectedDischargeLineId) return;
    if (typeof saveHistoryState === 'function') saveHistoryState();
    state.dischargeLines = state.dischargeLines.filter(l => l.id !== state.selectedDischargeLineId);
    selectItem(null);
    draw();
    updateGlobalStats();
}

function deleteSelectedInteriorPipe() {
    if (!state.selectedInteriorPipeId) return;
    if (typeof saveHistoryState === 'function') saveHistoryState();
    state.interiorPipes = state.interiorPipes.filter(p => p.id !== state.selectedInteriorPipeId);
    selectItem(null);
    draw();
    updateGlobalStats();
    if (window.sync3D) window.sync3D();
}

function deleteSelectedStanchion() {
    if (!state.selectedStanchionId) return;
    if (typeof saveHistoryState === 'function') saveHistoryState();
    state.stanchions = state.stanchions.filter(p => p.id !== state.selectedStanchionId);
    selectItem(null);
    draw();
    updateGlobalStats();
    if (window.sync3D) window.sync3D();
}

function deleteSelectedMainBeam() {
    if (!state.selectedMainBeamId) return;
    if (typeof saveHistoryState === 'function') saveHistoryState();
    state.mainBeams = state.mainBeams.filter(l => l.id !== state.selectedMainBeamId);
    selectItem(null);
    draw();
    updateGlobalStats();
    if (window.sync3D) window.sync3D();
}

// Helper: Distance from point to segment
function getDistanceToSegment(px, py, x1, y1, x2, y2) {
    const l2 = (x2 - x1)**2 + (y2 - y1)**2;
    if (l2 === 0) return Math.sqrt((px - x1)**2 + (py - y1)**2);
    let t = ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / l2;
    t = Math.max(0, Math.min(1, t));
    const projX = x1 + t * (x2 - x1);
    const projY = y1 + t * (y2 - y1);
    return Math.sqrt((px - projX)**2 + (py - projY)**2);
}

// --- DRAWING ENGINE ---
function drawLogicalWallsAndOpenings() {
    const levelId = state.currentLevelId;
    const walls = (state.walls || []).filter(w => w.levelId === levelId);
    
    // Draw solid walls
    walls.forEach(w => {
        const x1 = toCanvasX(w.x1);
        const y1 = toCanvasY(w.y1);
        const x2 = toCanvasX(w.x2);
        const y2 = toCanvasY(w.y2);
        
        ctx.save();
        ctx.strokeStyle = w.type === 'exterior' ? '#334155' : '#64748b';
        ctx.lineWidth = w.type === 'exterior' ? 6 : 3.5;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
        ctx.restore();
    });

    // Draw doors
    (state.doors || []).forEach(d => {
        if (d.levelId !== levelId) return;
        const wall = walls.find(w => w.id === d.hostWallId);
        if (!wall) return;

        const dx = wall.x2 - wall.x1;
        const dy = wall.y2 - wall.y1;
        const wallLen = Math.sqrt(dx*dx + dy*dy) || 1;
        const ux = dx / wallLen;
        const uy = dy / wallLen;

        const doorX = wall.x1 + ux * d.offset;
        const doorY = wall.y1 + uy * d.offset;

        const px = -uy;
        const py = ux;

        const cx = toCanvasX(doorX);
        const cy = toCanvasY(doorY);
        const ws = d.w * state.scale;

        ctx.save();
        // Clear host wall segment under door
        ctx.strokeStyle = '#0f172a'; // Match background color to cut wall opening
        ctx.lineWidth = 8;
        ctx.beginPath();
        ctx.moveTo(cx - ux * ws/2, cy - uy * ws/2);
        ctx.lineTo(cx + ux * ws/2, cy + uy * ws/2);
        ctx.stroke();

        // Draw door swing arc
        ctx.strokeStyle = 'rgba(16, 185, 129, 0.45)';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(cx, cy, ws, 0, Math.PI / 2);
        ctx.stroke();

        // Draw door panel line
        ctx.strokeStyle = '#10b981';
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(cx + px * ws, cy + py * ws);
        ctx.stroke();
        
        ctx.restore();
    });

    // Draw windows
    (state.windows || []).forEach(w => {
        if (w.levelId !== levelId) return;
        const wall = walls.find(wa => wa.id === w.hostWallId);
        if (!wall) return;

        const dx = wall.x2 - wall.x1;
        const dy = wall.y2 - wall.y1;
        const wallLen = Math.sqrt(dx*dx + dy*dy) || 1;
        const ux = dx / wallLen;
        const uy = dy / wallLen;

        const winX = wall.x1 + ux * w.offset;
        const winY = wall.y1 + uy * w.offset;

        const cx = toCanvasX(winX);
        const cy = toCanvasY(winY);
        const ws = w.w * state.scale;

        ctx.save();
        // Draw window frame
        ctx.fillStyle = '#3b82f6';
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(cx, cy, 5, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.restore();
    });
}

function draw(isPrinting = false) {
    state.isPrintingMode = isPrinting;
    
    // Auto compile walls
    if (typeof window.rebuildLogicalLayout === 'function') {
        window.rebuildLogicalLayout();
    }

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    if (isPrinting) {
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
    }
    
    if (state.showGrid && !isPrinting) {
        drawGrid();
    }
    
    if (!isPrinting && state.draggedRoomId && state.draggedHandle === 'move') {
        drawSnappingGuidelines();
    }

    // 1. Draw rooms
    state.rooms.forEach(room => {
        if (!room.levelId || room.levelId === state.currentLevelId) {
            drawRoom(room);
        }
    });

    // 2. Draw logical building walls & openings
    drawLogicalWallsAndOpenings();

    // 3. Draw per-wall work overlays last so field scope stays visible above
    // logical walls and openings in both the editor and printed blueprint.
    state.rooms.forEach(room => {
        if (!room.levelId || room.levelId === state.currentLevelId) drawDrywallWallScopes(room);
    });

    // Draw committed segments of current custom drawing in progress
    if (state.drawMode === 'custom' && state.sketchVertices.length > 0) {
        ctx.strokeStyle = '#a855f7'; // Purple sketch lines
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.moveTo(toCanvasX(state.sketchVertices[0].x), toCanvasY(state.sketchVertices[0].y));
        for (let i = 1; i < state.sketchVertices.length; i++) {
            ctx.lineTo(toCanvasX(state.sketchVertices[i].x), toCanvasY(state.sketchVertices[i].y));
        }
        ctx.stroke();

        // Draw live preview segment from last vertex to current mouse position
        const lastV = state.sketchVertices[state.sketchVertices.length - 1];
        const previewX = toCanvasX(state.lastMouseWorldX);
        const previewY = toCanvasY(state.lastMouseWorldY);

        ctx.strokeStyle = 'rgba(168, 85, 247, 0.5)'; // Dashed preview line
        ctx.setLineDash([5, 5]);
        ctx.beginPath();
        ctx.moveTo(toCanvasX(lastV.x), toCanvasY(lastV.y));
        ctx.lineTo(previewX, previewY);
        ctx.stroke();
        ctx.setLineDash([]);

        // Show live length and angle next to preview segment
        const dx = state.lastMouseWorldX - lastV.x;
        const dy = state.lastMouseWorldY - lastV.y;
        const liveDist = Math.sqrt(dx*dx + dy*dy);
        let liveAngle = Math.round(Math.atan2(dy, dx) * 180 / Math.PI);
        if (liveAngle < 0) liveAngle += 360;

        ctx.fillStyle = '#a855f7';
        ctx.font = '600 10px var(--font-mono)';
        ctx.fillText(` ${liveDist.toFixed(1)} ft @ ${liveAngle}°`, previewX + 10, previewY - 5);

        // Draw vertex nodes
        state.sketchVertices.forEach(v => {
            ctx.fillStyle = '#a855f7';
            ctx.strokeStyle = '#ffffff';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.arc(toCanvasX(v.x), toCanvasY(v.y), 4, 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();
        });
    }

    // 2. Draw discharge lines
    state.dischargeLines.forEach(dl => {
        if (dl.levelId && dl.levelId !== state.currentLevelId) return;
        const x1 = toCanvasX(dl.x1);
        const y1 = toCanvasY(dl.y1);
        const x2 = toCanvasX(dl.x2);
        const y2 = toCanvasY(dl.y2);
        const isSelected = dl.id === state.selectedDischargeLineId;
        
        ctx.strokeStyle = isSelected ? varColor('--accent-teal') : '#3b82f6';
        ctx.lineWidth = isSelected ? 4 : 2.5;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
        
        // Dashed inner plumbing look
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
        ctx.setLineDash([]);
        
        // Draw endpoints if selected
        if (isSelected) {
            ctx.fillStyle = varColor('--accent-teal');
            ctx.strokeStyle = '#ffffff';
            ctx.lineWidth = 1.5;
            ctx.fillRect(x1 - 5, y1 - 5, 10, 10);
            ctx.strokeRect(x1 - 5, y1 - 5, 10, 10);
            ctx.fillRect(x2 - 5, y2 - 5, 10, 10);
            ctx.strokeRect(x2 - 5, y2 - 5, 10, 10);
        }
        
        // Draw length label
        const mx = (x1 + x2) / 2;
        const my = (y1 + y2) / 2;
        const angle = Math.atan2(y2 - y1, x2 - x1);
        
        ctx.save();
        ctx.translate(mx, my);
        let textAngle = angle;
        if (textAngle > Math.PI / 2 || textAngle < -Math.PI / 2) {
            textAngle += Math.PI;
        }
        ctx.rotate(textAngle);
        
        const label = `${dl.label}: ${dl.length.toFixed(1)} ft`;
        ctx.font = '600 10px var(--font-mono)';
        const textWidth = ctx.measureText(label).width;
        ctx.fillStyle = 'rgba(10, 13, 20, 0.8)';
        ctx.fillRect(-textWidth/2 - 4, -14, textWidth + 8, 14);
        
        ctx.fillStyle = isSelected ? varColor('--accent-teal') : '#ffffff';
        ctx.textAlign = 'center';
        ctx.fillText(label, 0, -4);
        ctx.restore();
    });

    // Draw interior pipes
    state.interiorPipes.forEach(ip => {
        if (ip.levelId && ip.levelId !== state.currentLevelId) return;
        const x1 = toCanvasX(ip.x1);
        const y1 = toCanvasY(ip.y1);
        const x2 = toCanvasX(ip.x2);
        const y2 = toCanvasY(ip.y2);
        const isSelected = ip.id === state.selectedInteriorPipeId;
        
        ctx.strokeStyle = isSelected ? varColor('--accent-teal') : '#64748b';
        ctx.lineWidth = isSelected ? 4 : 2.5;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
        
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 1.2;
        ctx.setLineDash([5, 4]);
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
        ctx.setLineDash([]);
        
        // Draw endpoints if selected
        if (isSelected) {
            ctx.fillStyle = varColor('--accent-teal');
            ctx.strokeStyle = '#ffffff';
            ctx.lineWidth = 1.5;
            ctx.fillRect(x1 - 5, y1 - 5, 10, 10);
            ctx.strokeRect(x1 - 5, y1 - 5, 10, 10);
            ctx.fillRect(x2 - 5, y2 - 5, 10, 10);
            ctx.strokeRect(x2 - 5, y2 - 5, 10, 10);
        }
        
        // Length label
        const mx = (x1 + x2) / 2;
        const my = (y1 + y2) / 2;
        const angle = Math.atan2(y2 - y1, x2 - x1);
        
        ctx.save();
        ctx.translate(mx, my);
        let textAngle = angle;
        if (textAngle > Math.PI / 2 || textAngle < -Math.PI / 2) {
            textAngle += Math.PI;
        }
        ctx.rotate(textAngle);
        
        const label = `${ip.label}: ${ip.length.toFixed(1)} ft`;
        ctx.font = '600 10px var(--font-mono)';
        const textWidth = ctx.measureText(label).width;
        ctx.fillStyle = 'rgba(10, 13, 20, 0.8)';
        ctx.fillRect(-textWidth/2 - 4, -14, textWidth + 8, 14);
        
        ctx.fillStyle = isSelected ? varColor('--accent-teal') : '#cbd5e1';
        ctx.textAlign = 'center';
        ctx.fillText(label, 0, -4);
        ctx.restore();
    });

    // 3. Draw sump pumps
    state.sumpPumps.forEach(sp => {
        if (sp.levelId && sp.levelId !== state.currentLevelId) return;
        const cx = toCanvasX(sp.x);
        const cy = toCanvasY(sp.y);
        const isSelected = sp.id === state.selectedSumpPumpId;
        const radius = 13;
        
        // Outer glow
        if (isSelected) {
            ctx.shadowColor = varColor('--accent-teal');
            ctx.shadowBlur = 10;
        }
        
        // Outer ring
        ctx.fillStyle = c('rgba(16, 22, 35, 0.9)', '#e2e8f0');
        ctx.strokeStyle = isSelected ? varColor('--accent-teal') : '#f59e0b';
        ctx.lineWidth = isSelected ? 3 : 2;
        ctx.beginPath();
        ctx.arc(cx, cy, radius, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        
        // Reset shadow
        ctx.shadowBlur = 0;
        
        // Inner dotted ring
        ctx.strokeStyle = c('rgba(255, 255, 255, 0.3)', 'rgba(0, 0, 0, 0.3)');
        ctx.lineWidth = 1;
        ctx.setLineDash([2, 2]);
        ctx.beginPath();
        ctx.arc(cx, cy, radius - 4, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
        
        // Label
        ctx.fillStyle = c('#ffffff', '#0f172a');
        ctx.font = '700 8px var(--font-sans)';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('SP', cx, cy);
        
        // Floating label
        ctx.fillStyle = isSelected ? varColor('--accent-teal') : c(varColor('--text-muted'), '#475569');
        ctx.font = '600 9px var(--font-sans)';
        ctx.fillText(sp.name, cx, cy - radius - 6);
    });

    // 3b. Draw Dehumidifiers
    if (state.dehumidifiers) {
        state.dehumidifiers.forEach(dehum => {
            if (dehum.levelId && dehum.levelId !== state.currentLevelId) return;
            const cx = toCanvasX(dehum.x);
            const cy = toCanvasY(dehum.y);
            const isSelected = dehum.id === state.selectedDehumidifierId;
            const width = 1.0 * state.scale;  // 1ft wide
            const height = 1.2 * state.scale; // 1.2ft long
            
            // Outer glow on select
            if (isSelected) {
                ctx.shadowColor = varColor('--accent-teal');
                ctx.shadowBlur = 10;
            }
            
            // Dehum box
            ctx.fillStyle = isSelected ? 'rgba(147, 51, 234, 0.2)' : 'rgba(147, 51, 234, 0.75)';
            ctx.strokeStyle = isSelected ? varColor('--accent-teal') : '#c084fc';
            ctx.lineWidth = isSelected ? 3 : 2;
            
            ctx.beginPath();
            ctx.rect(cx - width/2, cy - height/2, width, height);
            ctx.fill();
            ctx.stroke();
            
            // Reset shadow
            ctx.shadowBlur = 0;
            
            // Text tag inside
            ctx.fillStyle = '#ffffff';
            ctx.font = '700 8px var(--font-sans)';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText('DH', cx, cy);
            
            // Floating label
            ctx.fillStyle = isSelected ? varColor('--accent-teal') : c(varColor('--text-muted'), '#475569');
            ctx.font = '600 9px var(--font-sans)';
            ctx.fillText(dehum.name, cx, cy - height/2 - 6);
        });
    }

    // Draw Stanchions
    state.stanchions.forEach(st => {
        if (st.levelId && st.levelId !== state.currentLevelId) return;
        const cx = toCanvasX(st.x);
        const cy = toCanvasY(st.y);
        const isSelected = st.id === state.selectedStanchionId;
        const radius = 0.5 * state.scale; // 1ft diameter
        
        if (st.type === 'brick') {
            ctx.fillStyle = isSelected ? 'rgba(194, 65, 12, 0.2)' : '#c2410c';
            ctx.strokeStyle = isSelected ? varColor('--accent-teal') : '#ea580c';
        } else {
            ctx.fillStyle = isSelected ? 'rgba(20, 184, 166, 0.2)' : '#475569';
            ctx.strokeStyle = isSelected ? varColor('--accent-teal') : '#94a3b8';
        }
        ctx.lineWidth = isSelected ? 3 : 2;
        
        ctx.beginPath();
        if (st.type === 'square' || st.type === 'brick') {
            ctx.rect(cx - radius, cy - radius, radius * 2, radius * 2);
        } else {
            ctx.arc(cx, cy, radius, 0, Math.PI * 2);
        }
        ctx.fill();
        ctx.stroke();
        
        // Internal Crosshair X
        ctx.strokeStyle = isSelected ? varColor('--accent-teal') : c('rgba(255, 255, 255, 0.4)', 'rgba(0, 0, 0, 0.4)');
        ctx.lineWidth = 1;
        ctx.beginPath();
        if (st.type === 'square' || st.type === 'brick') {
            ctx.moveTo(cx - radius + 2, cy - radius + 2);
            ctx.lineTo(cx + radius - 2, cy + radius - 2);
            ctx.moveTo(cx + radius - 2, cy - radius + 2);
            ctx.lineTo(cx - radius + 2, cy + radius - 2);
        } else {
            const offset = radius * 0.707;
            ctx.moveTo(cx - offset, cy - offset);
            ctx.lineTo(cx + offset, cy + offset);
            ctx.moveTo(cx + offset, cy - offset);
            ctx.lineTo(cx - offset, cy + offset);
        }
        ctx.stroke();
        
        // Floating label
        ctx.fillStyle = isSelected ? varColor('--accent-teal') : c(varColor('--text-muted'), '#475569');
        ctx.font = '600 9px var(--font-sans)';
        ctx.textAlign = 'center';
        ctx.fillText(st.name, cx, cy - radius - 6);
    });

    // Draw Floor Hatches
    state.floorHatches.forEach(h => {
        if (h.levelId && h.levelId !== state.currentLevelId) return;
        const cx = toCanvasX(h.x);
        const cy = toCanvasY(h.y);
        const isSelected = h.id === state.selectedFloorHatchId;
        const wPix = h.w * state.scale;
        const lPix = h.l * state.scale;
        
        ctx.fillStyle = isSelected ? 'rgba(236, 72, 153, 0.2)' : 'rgba(30, 41, 59, 0.6)';
        ctx.strokeStyle = isSelected ? varColor('--accent-teal') : '#ec4899';
        ctx.lineWidth = isSelected ? 3 : 2;
        
        ctx.beginPath();
        ctx.rect(cx - wPix / 2, cy - lPix / 2, wPix, lPix);
        ctx.fill();
        ctx.stroke();
        
        // Crossed lines for hatch designation
        ctx.strokeStyle = isSelected ? varColor('--accent-teal') : 'rgba(236, 72, 153, 0.4)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(cx - wPix / 2, cy - lPix / 2);
        ctx.lineTo(cx + wPix / 2, cy + lPix / 2);
        ctx.moveTo(cx + wPix / 2, cy - lPix / 2);
        ctx.lineTo(cx - wPix / 2, cy + lPix / 2);
        ctx.stroke();
        
        ctx.fillStyle = isSelected ? varColor('--accent-teal') : '#ec4899';
        ctx.font = '600 8px var(--font-mono)';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        const labelText = (h.target === 'ceiling' ? 'CEILING HATCH' : 'FLOOR HATCH');
        ctx.fillText(labelText, cx, cy);
        
        ctx.fillStyle = isSelected ? varColor('--accent-teal') : c(varColor('--text-muted'), '#475569');
        ctx.font = '600 9px var(--font-sans)';
        ctx.textBaseline = 'alphabetic';
        ctx.fillText(h.name, cx, cy - lPix / 2 - 6);
    });

    // Draw Support Beams
    state.mainBeams.forEach(bm => {
        if (bm.levelId && bm.levelId !== state.currentLevelId) return;
        const x1 = toCanvasX(bm.x1);
        const y1 = toCanvasY(bm.y1);
        const x2 = toCanvasX(bm.x2);
        const y2 = toCanvasY(bm.y2);
        const isSelected = bm.id === state.selectedMainBeamId;
        
        const color = bm.type === 'steel' ? '#475569' : '#b45309';
        ctx.strokeStyle = isSelected ? varColor('--accent-teal') : color;
        ctx.lineWidth = isSelected ? 8 : 6;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
        
        ctx.strokeStyle = bm.type === 'steel' ? '#94a3b8' : '#d97706';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
        
        // Draw endpoints if selected
        if (isSelected) {
            ctx.fillStyle = varColor('--accent-teal');
            ctx.strokeStyle = '#ffffff';
            ctx.lineWidth = 1.5;
            ctx.fillRect(x1 - 5, y1 - 5, 10, 10);
            ctx.strokeRect(x1 - 5, y1 - 5, 10, 10);
            ctx.fillRect(x2 - 5, y2 - 5, 10, 10);
            ctx.strokeRect(x2 - 5, y2 - 5, 10, 10);
        }
        
        // Label
        const mx = (x1 + x2) / 2;
        const my = (y1 + y2) / 2;
        const angle = Math.atan2(y2 - y1, x2 - x1);
        
        ctx.save();
        ctx.translate(mx, my);
        let textAngle = angle;
        if (textAngle > Math.PI / 2 || textAngle < -Math.PI / 2) {
            textAngle += Math.PI;
        }
        ctx.rotate(textAngle);
        
        const label = `${bm.label}: ${bm.length.toFixed(1)} ft`;
        ctx.font = '600 10px var(--font-mono)';
        const textWidth = ctx.measureText(label).width;
        ctx.fillStyle = c('rgba(10, 13, 20, 0.8)', '#ffffff');
        ctx.fillRect(-textWidth/2 - 4, -14, textWidth + 8, 14);
        
        ctx.fillStyle = isSelected ? varColor('--accent-teal') : c('#ffffff', '#0f172a');
        ctx.textAlign = 'center';
        ctx.fillText(label, 0, -4);
        ctx.restore();
    });
}

function drawGrid() {
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.03)';
    ctx.lineWidth = 1;
    
    const startX = toWorldX(0);
    const endX = toWorldX(canvas.width);
    const startY = toWorldY(0);
    const endY = toWorldY(canvas.height);
    const gridStep = 1;
    
    for (let x = Math.floor(startX); x <= Math.ceil(endX); x += gridStep) {
        ctx.beginPath();
        ctx.strokeStyle = x % 5 === 0 ? 'rgba(255, 255, 255, 0.08)' : 'rgba(255, 255, 255, 0.03)';
        ctx.moveTo(toCanvasX(x), 0);
        ctx.lineTo(toCanvasX(x), canvas.height);
        ctx.stroke();
    }
    
    for (let y = Math.floor(startY); y <= Math.ceil(endY); y += gridStep) {
        ctx.beginPath();
        ctx.strokeStyle = y % 5 === 0 ? 'rgba(255, 255, 255, 0.08)' : 'rgba(255, 255, 255, 0.03)';
        ctx.moveTo(0, toCanvasY(y));
        ctx.lineTo(canvas.width, toCanvasY(y));
        ctx.stroke();
    }
}

// Helper to render floor joists grid inside rooms
function drawJoists(room) {
    if (!room.joists || room.joists === 'none') return;
    
    ctx.save();
    
    // Set clip path to room bounds
    ctx.beginPath();
    if (room.type === 'custom' && room.vertices && room.vertices.length >= 3) {
        ctx.moveTo(toCanvasX(room.x + room.vertices[0].x), toCanvasY(room.y + room.vertices[0].y));
        for (let i = 1; i < room.vertices.length; i++) {
            ctx.lineTo(toCanvasX(room.x + room.vertices[i].x), toCanvasY(room.y + room.vertices[i].y));
        }
    } else {
        const rx = toCanvasX(room.x);
        const ry = toCanvasY(room.y);
        const rw = room.w * state.scale;
        const rl = room.l * state.scale;
        ctx.rect(rx, ry, rw, rl);
    }
    ctx.clip();
    
    // Draw parallel joist lines
    ctx.strokeStyle = c('rgba(255, 255, 255, 0.08)', 'rgba(0, 0, 0, 0.15)');
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    
    let minX = room.x, maxX = room.x + (room.w || 0);
    let minY = room.y, maxY = room.y + (room.l || 0);
    if (room.type === 'custom' && room.vertices) {
        minX = Infinity; maxX = -Infinity;
        minY = Infinity; maxY = -Infinity;
        room.vertices.forEach(v => {
            const wx = room.x + v.x;
            const wy = room.y + v.y;
            if (wx < minX) minX = wx;
            if (wx > maxX) maxX = wx;
            if (wy < minY) minY = wy;
            if (wy > maxY) maxY = wy;
        });
    }
    
    const spacing = 1.333; // 16 inches spacing
    
    if (room.joists === 'ns') {
        for (let x = Math.ceil(minX / spacing) * spacing; x < maxX; x += spacing) {
            const cx = toCanvasX(x);
            ctx.beginPath();
            ctx.moveTo(cx, toCanvasY(minY));
            ctx.lineTo(cx, toCanvasY(maxY));
            ctx.stroke();
        }
    } else if (room.joists === 'ew') {
        for (let y = Math.ceil(minY / spacing) * spacing; y < maxY; y += spacing) {
            const cy = toCanvasY(y);
            ctx.beginPath();
            ctx.moveTo(toCanvasX(minX), cy);
            ctx.lineTo(toCanvasX(maxX), cy);
            ctx.stroke();
        }
    }
    
    ctx.restore();
}

function drawRoom(room) {
    const rx = toCanvasX(room.x);
    const ry = toCanvasY(room.y);
    const rw = room.w * state.scale;
    const rl = room.l * state.scale;
    const isSelected = room.id === state.selectedRoomId;

    // Draw 2D XPS Foam Board insulation lines on exterior walls
    if (room.foamBoard) {
        const segments = getRoomSegments(room);
        ctx.save();
        ctx.strokeStyle = '#f472b6'; // Owens Corning Pink
        ctx.lineWidth = 5; // Thick insulation line
        segments.forEach(seg => {
            const mx = (seg.x1 + seg.x2) / 2;
            const my = (seg.y1 + seg.y2) / 2;
            
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
                const dx = seg.x2 - seg.x1;
                const dy = seg.y2 - seg.y1;
                const len = Math.sqrt(dx*dx + dy*dy);
                if (len > 0.05) {
                    const nx = -dy / len;
                    const ny = dx / len;
                    const testDist = 0.5;
                    const testX = mx + nx * testDist;
                    const testY = my + ny * testDist;
                    const inRoom = getRoomAt(testX, testY, room.levelId);
                    
                    const mul = (inRoom && inRoom.id === room.id) ? 1 : -1;
                    const offsetDist = 0.15; // Offset inside room in feet
                    const ox = nx * offsetDist * mul;
                    const oy = ny * offsetDist * mul;
                    
                    ctx.beginPath();
                    ctx.moveTo(toCanvasX(seg.x1 + ox), toCanvasY(seg.y1 + oy));
                    ctx.lineTo(toCanvasX(seg.x2 + ox), toCanvasY(seg.y2 + oy));
                    ctx.stroke();
                }
            }
        });
        ctx.restore();
    }

    // Draw 2D Floor Perimeter Carbon Fiber Strap
    if (room.floorPerimeterStrap) {
        const segments = getRoomSegments(room);
        ctx.save();
        ctx.strokeStyle = '#38bdf8'; // Sky blue to match sidebar totals
        ctx.lineWidth = 2.5;
        segments.forEach(seg => {
            const dx = seg.x2 - seg.x1;
            const dy = seg.y2 - seg.y1;
            const len = Math.sqrt(dx*dx + dy*dy);
            if (len > 0.05) {
                const nx = -dy / len;
                const ny = dx / len;
                const testDist = 0.5;
                const mx = (seg.x1 + seg.x2) / 2;
                const my = (seg.y1 + seg.y2) / 2;
                const testX = mx + nx * testDist;
                const testY = my + ny * testDist;
                const inRoom = getRoomAt(testX, testY, room.levelId);
                
                const mul = (inRoom && inRoom.id === room.id) ? 1 : -1;
                const offsetDist = 0.1; // Offset slightly inside
                const ox = nx * offsetDist * mul;
                const oy = ny * offsetDist * mul;
                
                ctx.beginPath();
                ctx.moveTo(toCanvasX(seg.x1 + ox), toCanvasY(seg.y1 + oy));
                ctx.lineTo(toCanvasX(seg.x2 + ox), toCanvasY(seg.y2 + oy));
                ctx.stroke();
            }
        });
        ctx.restore();
    }

    // Draw 2D Carbon Fiber Straps (Vertical tick marks)
    if (room.carbonStraps > 0) {
        const segments = getRoomSegments(room);
        
        if (room.carbonFiberScope === 'specific' && room.customCarbonStraps && room.customCarbonStraps.length > 0) {
            // Manual Custom Placed Straps
            ctx.save();
            ctx.strokeStyle = '#0f172a'; // Deep charcoal/black
            ctx.lineWidth = 3;
            
            room.customCarbonStraps.forEach(strap => {
                const seg = segments.find(s => s.wall === strap.wall);
                if (!seg) return;
                
                const dx = seg.x2 - seg.x1;
                const dy = seg.y2 - seg.y1;
                const len = Math.sqrt(dx*dx + dy*dy);
                if (len < 0.05) return;
                
                const px = seg.x1 + dx * strap.offset;
                const py = seg.y1 + dy * strap.offset;
                
                const nx = -dy / len;
                const ny = dx / len;
                const testDist = 0.5;
                const testX = px + nx * testDist;
                const testY = py + ny * testDist;
                const inRoom = getRoomAt(testX, testY, room.levelId);
                const mul = (inRoom && inRoom.id === room.id) ? 1 : -1;
                
                const tickLen = 0.45;
                const ox = nx * mul;
                const oy = ny * mul;
                
                // Draw strap tick mark
                ctx.beginPath();
                ctx.moveTo(toCanvasX(px), toCanvasY(py));
                ctx.lineTo(toCanvasX(px + ox * tickLen), toCanvasY(py + oy * tickLen));
                ctx.stroke();
                
                // If this is the selected room, draw a small draggable grab handle at the end of the tick mark!
                if (state.selectedRoomId === room.id) {
                    ctx.save();
                    ctx.fillStyle = '#2dd4bf'; // Teal active grab handle
                    ctx.strokeStyle = '#0f172a';
                    ctx.lineWidth = 1.5;
                    ctx.beginPath();
                    const hx = toCanvasX(px + ox * tickLen * 0.5);
                    const hy = toCanvasY(py + oy * tickLen * 0.5);
                    ctx.arc(hx, hy, 5, 0, 2 * Math.PI);
                    ctx.fill();
                    ctx.stroke();
                    ctx.restore();
                }
            });
            ctx.restore();
        } else {
            // Automatic Even Spacing (Scope is 'full' or no custom straps array yet)
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
                
                ctx.save();
                ctx.strokeStyle = '#0f172a'; // Deep charcoal/black
                ctx.lineWidth = 3;
                
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
                    
                    const nx = -s.dy / s.len;
                    const ny = s.dx / s.len;
                    const testDist = 0.5;
                    const testX = px + nx * testDist;
                    const testY = py + ny * testDist;
                    const inRoom = getRoomAt(testX, testY, room.levelId);
                    const mul = (inRoom && inRoom.id === room.id) ? 1 : -1;
                    
                    const tickLen = 0.35;
                    const ox = nx * mul;
                    const oy = ny * mul;
                    
                    ctx.beginPath();
                    ctx.moveTo(toCanvasX(px), toCanvasY(py));
                    ctx.lineTo(toCanvasX(px + ox * tickLen), toCanvasY(py + oy * tickLen));
                    ctx.stroke();
                    
                    currentDist += spacing;
                }
                ctx.restore();
            }
        }
    }

    if (room.type === 'custom' && room.vertices && room.vertices.length >= 3) {
        // --- Render Custom Polygon Room ---
        ctx.fillStyle = room.color + '15';
        ctx.beginPath();
        ctx.moveTo(toCanvasX(room.x + room.vertices[0].x), toCanvasY(room.y + room.vertices[0].y));
        for (let i = 1; i < room.vertices.length; i++) {
            ctx.lineTo(toCanvasX(room.x + room.vertices[i].x), toCanvasY(room.y + room.vertices[i].y));
        }
        ctx.closePath();
        ctx.fill();
        drawJoists(room);

        ctx.strokeStyle = isSelected ? varColor('--accent-teal') : c('rgba(255, 255, 255, 0.3)', '#1e293b');
        ctx.lineWidth = isSelected ? 3 : 1.5;
        ctx.stroke();

        // Calculate Average center for Room Name Label
        let sumX = 0, sumY = 0;
        room.vertices.forEach(v => { sumX += v.x; sumY += v.y; });
        const avgX = room.x + sumX / room.vertices.length;
        const avgY = room.y + sumY / room.vertices.length;

        ctx.fillStyle = isSelected ? c('#ffffff', '#0f172a') : c(varColor('--text-muted'), '#475569');
        ctx.font = `600 13px var(--font-sans)`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(room.name, toCanvasX(avgX), toCanvasY(avgY));

        // Draw wall segment lengths
        ctx.fillStyle = c('rgba(255, 255, 255, 0.6)', '#334155');
        ctx.font = `500 9px var(--font-mono)`;
        for (let i = 0; i < room.vertices.length; i++) {
            const v1 = room.vertices[i];
            const v2 = room.vertices[(i + 1) % room.vertices.length];
            const mx = room.x + (v1.x + v2.x) / 2;
            const my = room.y + (v1.y + v2.y) / 2;
            const dx = v2.x - v1.x;
            const dy = v2.y - v1.y;
            const wallLength = Math.sqrt(dx*dx + dy*dy);

            ctx.save();
            ctx.translate(toCanvasX(mx), toCanvasY(my));
            let textAng = Math.atan2(dy, dx);
            if (textAng > Math.PI / 2 || textAng < -Math.PI / 2) textAng += Math.PI;
            ctx.rotate(textAng);
            ctx.fillText(`${wallLength.toFixed(1)} ft`, 0, -6);
            ctx.restore();
        }

        // Draw openings
        room.openings.forEach(op => {
            drawOpeningOnWall(room, op);
        });

        // Draw vertex edit handles
        if (isSelected) {
            room.vertices.forEach((v, idx) => {
                const vx = toCanvasX(room.x + v.x);
                const vy = toCanvasY(room.y + v.y);
                ctx.fillStyle = '#a855f7';
                ctx.strokeStyle = '#ffffff';
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.arc(vx, vy, 6, 0, Math.PI * 2);
                ctx.fill();
                ctx.stroke();
            });
        }
        return;
    }

    // Room Body Fill
    ctx.fillStyle = room.color + '15';
    ctx.fillRect(rx, ry, rw, rl);
    drawJoists(room);
    // Draw staircase steps
    if (room.type === 'staircase') {
        const stepCount = room.steps || 12;
        const orient = room.stairOrientation || 'N';
        const dirText = (room.stairDirection || 'up') === 'down' ? 'DN' : 'UP';
        
        ctx.strokeStyle = c('rgba(255, 255, 255, 0.15)', 'rgba(0, 0, 0, 0.25)');
        ctx.lineWidth = 1;
        
        if (orient === 'N' || orient === 'S') {
            // Steps are horizontal
            const stepSize = rl / stepCount;
            for (let i = 1; i < stepCount; i++) {
                ctx.beginPath();
                ctx.moveTo(rx, ry + i * stepSize);
                ctx.lineTo(rx + rw, ry + i * stepSize);
                ctx.stroke();
            }
        } else {
            // Steps are vertical
            const stepSize = rw / stepCount;
            for (let i = 1; i < stepCount; i++) {
                ctx.beginPath();
                ctx.moveTo(rx + i * stepSize, ry);
                ctx.lineTo(rx + i * stepSize, ry + rl);
                ctx.stroke();
            }
        }
        
        // Draw directional climb arrow
        ctx.strokeStyle = varColor('--accent-teal') || '#00ffd1';
        ctx.lineWidth = 2;
        ctx.fillStyle = varColor('--accent-teal') || '#00ffd1';
        
        let startX, startY, endX, endY, head1X, head1Y, head2X, head2Y, textX, textY;
        
        if (orient === 'N') {
            startX = rx + rw / 2; startY = ry + rl * 0.8;
            endX = rx + rw / 2; endY = ry + rl * 0.2;
            head1X = endX - 5; head1Y = endY + 8;
            head2X = endX + 5; head2Y = endY + 8;
            textX = endX; textY = endY - 10;
        } else if (orient === 'S') {
            startX = rx + rw / 2; startY = ry + rl * 0.2;
            endX = rx + rw / 2; endY = ry + rl * 0.8;
            head1X = endX - 5; head1Y = endY - 8;
            head2X = endX + 5; head2Y = endY - 8;
            textX = endX; textY = endY + 12;
        } else if (orient === 'E') {
            startX = rx + rw * 0.2; startY = ry + rl / 2;
            endX = rx + rw * 0.8; endY = ry + rl / 2;
            head1X = endX - 8; head1Y = endY - 5;
            head2X = endX - 8; head2Y = endY + 5;
            textX = endX + 12; textY = endY;
        } else { // 'W'
            startX = rx + rw * 0.8; startY = ry + rl / 2;
            endX = rx + rw * 0.2; endY = ry + rl / 2;
            head1X = endX + 8; head1Y = endY - 5;
            head2X = endX + 8; head2Y = endY + 5;
            textX = endX - 12; textY = endY;
        }
        
        ctx.beginPath();
        ctx.moveTo(startX, startY);
        ctx.lineTo(endX, endY);
        ctx.stroke();
        
        ctx.beginPath();
        ctx.moveTo(head1X, head1Y);
        ctx.lineTo(endX, endY);
        ctx.lineTo(head2X, head2Y);
        ctx.stroke();
        
        ctx.font = '600 9px var(--font-sans)';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(dirText, textX, textY);
    }

    // Room Outline
    ctx.strokeStyle = isSelected ? varColor('--accent-teal') : c('rgba(255, 255, 255, 0.3)', '#1e293b');
    ctx.lineWidth = isSelected ? 3 : 1.5;
    ctx.strokeRect(rx, ry, rw, rl);

    // Label
    ctx.fillStyle = isSelected ? c('#ffffff', '#0f172a') : c(varColor('--text-muted'), '#475569');
    ctx.font = `600 13px var(--font-sans)`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(room.name, rx + rw / 2, ry + rl / 2 - 8);

    // Sublabel
    ctx.fillStyle = c('rgba(255, 255, 255, 0.5)', '#334155');
    ctx.font = `500 11px var(--font-mono)`;
    ctx.fillText(`${room.w}' x ${room.l}'`, rx + rw / 2, ry + rl / 2 + 10);

    // Wall measurements
    ctx.fillStyle = c('rgba(255, 255, 255, 0.6)', '#334155');
    ctx.font = `500 10px var(--font-mono)`;
    
    // North wall
    ctx.fillText(`${room.w} ft`, rx + rw / 2, ry - 8);
    // South wall
    ctx.fillText(`${room.w} ft`, rx + rw / 2, ry + rl + 12);
    // West wall
    ctx.save();
    ctx.translate(rx - 10, ry + rl / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText(`${room.l} ft`, 0, 0);
    ctx.restore();
    // East wall
    ctx.save();
    ctx.translate(rx + rw + 14, ry + rl / 2);
    ctx.rotate(Math.PI / 2);
    ctx.fillText(`${room.l} ft`, 0, 0);
    ctx.restore();

    room.openings.forEach(op => {
        drawOpeningOnWall(room, op);
    });

    if (isSelected) {
        drawResizeHandles(rx, ry, rw, rl);
    }
}

function drawOpeningOnWall(room, op) {
    const rx = toCanvasX(room.x);
    const ry = toCanvasY(room.y);
    const rw = room.w * state.scale;
    const rl = room.l * state.scale;
    
    let opX, opY, opW, opH;
    const widthPix = op.w * state.scale;
    const thickness = 6;

    if (room.type === 'custom' && room.vertices && room.vertices.length >= 3) {
        const wallIdx = parseInt(op.wall);
        if (isNaN(wallIdx) || wallIdx < 0 || wallIdx >= room.vertices.length) return;
        
        const v1 = room.vertices[wallIdx];
        const v2 = room.vertices[(wallIdx + 1) % room.vertices.length];
        
        const angle = Math.atan2(v2.y - v1.y, v2.x - v1.x);
        const wx = room.x + v1.x + op.offset * Math.cos(angle);
        const wy = room.y + v1.y + op.offset * Math.sin(angle);
        const cx = toCanvasX(wx);
        const cy = toCanvasY(wy);

        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(angle);
        ctx.fillStyle = op.type === 'door' ? '#f59e0b' : (op.type === 'crawl_door' ? '#f97316' : '#06b6d4');
        ctx.fillRect(-widthPix / 2, -thickness / 2, widthPix, thickness);
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 1;
        ctx.strokeRect(-widthPix / 2, -thickness / 2, widthPix, thickness);
        ctx.restore();
        return;
    }

    if (op.wall === 'n') {
        opX = rx + (op.offset * state.scale) - (widthPix / 2);
        opY = ry - thickness / 2;
        opW = widthPix;
        opH = thickness;
    } else if (op.wall === 's') {
        opX = rx + (op.offset * state.scale) - (widthPix / 2);
        opY = ry + rl - thickness / 2;
        opW = widthPix;
        opH = thickness;
    } else if (op.wall === 'w') {
        opX = rx - thickness / 2;
        opY = ry + (op.offset * state.scale) - (widthPix / 2);
        opW = thickness;
        opH = widthPix;
    } else if (op.wall === 'e') {
        opX = rx + rw - thickness / 2;
        opY = ry + (op.offset * state.scale) - (widthPix / 2);
        opW = thickness;
        opH = widthPix;
    }

    ctx.fillStyle = op.type === 'door' ? '#f59e0b' : (op.type === 'crawl_door' ? '#f97316' : '#06b6d4');
    ctx.fillRect(opX, opY, opW, opH);
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 1;
    ctx.strokeRect(opX, opY, opW, opH);

    if (op.type === 'door' || op.type === 'crawl_door') {
        const strokeColor = op.type === 'door' ? 'rgba(245, 158, 11, 0.4)' : 'rgba(249, 115, 22, 0.5)';
        ctx.strokeStyle = strokeColor;
        ctx.lineWidth = 1;
        
        if (op.type === 'crawl_door') {
            ctx.setLineDash([2, 2]);
        } else {
            ctx.setLineDash([]);
        }
        
        ctx.beginPath();
        if (op.wall === 'n') {
            ctx.arc(opX, opY, widthPix, 0, Math.PI / 2);
        } else if (op.wall === 's') {
            ctx.arc(opX, opY + thickness, widthPix, -Math.PI / 2, 0);
        } else if (op.wall === 'w') {
            ctx.arc(opX, opY, widthPix, 0, Math.PI / 2);
        } else if (op.wall === 'e') {
            ctx.arc(opX + thickness, opY, widthPix, Math.PI / 2, Math.PI);
        }
        ctx.stroke();
        ctx.setLineDash([]);
    }
}

function drawResizeHandles(rx, ry, rw, rl) {
    const handleSize = 8;
    ctx.fillStyle = varColor('--accent-teal');
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 1;

    const corners = {
        nw: { x: rx, y: ry },
        ne: { x: rx + rw, y: ry },
        se: { x: rx + rw, y: ry + rl },
        sw: { x: rx, y: ry + rl }
    };

    const sides = {
        n: { x: rx + rw / 2, y: ry },
        s: { x: rx + rw / 2, y: ry + rl },
        w: { x: rx, y: ry + rl / 2 },
        e: { x: rx + rw, y: ry + rl / 2 }
    };

    for (let c in corners) {
        ctx.fillRect(corners[c].x - handleSize/2, corners[c].y - handleSize/2, handleSize, handleSize);
        ctx.strokeRect(corners[c].x - handleSize/2, corners[c].y - handleSize/2, handleSize, handleSize);
    }

    ctx.fillStyle = varColor('--accent-blue');
    for (let s in sides) {
        ctx.fillRect(sides[s].x - handleSize/2, sides[s].y - handleSize/2, handleSize, handleSize);
        ctx.strokeRect(sides[s].x - handleSize/2, sides[s].y - handleSize/2, handleSize, handleSize);
    }
}

function drawSnappingGuidelines() {
    const draggedRoom = state.rooms.find(r => r.id === state.draggedRoomId);
    if (!draggedRoom) return;

    ctx.strokeStyle = 'rgba(0, 255, 209, 0.4)';
    ctx.lineWidth = 1;
    ctx.setLineDash([5, 5]);

    state.rooms.forEach(r => {
        if (r.id === draggedRoom.id) return;
        if (r.levelId && r.levelId !== state.currentLevelId) return;

        const rEdges = { left: r.x, right: r.x + r.w, top: r.y, bottom: r.y + r.l };
        const dEdges = { left: draggedRoom.x, right: draggedRoom.x + draggedRoom.w, top: draggedRoom.y, bottom: draggedRoom.y + draggedRoom.l };

        if (Math.abs(dEdges.left - rEdges.left) < 0.1 || Math.abs(dEdges.left - rEdges.right) < 0.1) {
            ctx.beginPath();
            ctx.moveTo(toCanvasX(dEdges.left), 0);
            ctx.lineTo(toCanvasX(dEdges.left), canvas.height);
            ctx.stroke();
        }
        if (Math.abs(dEdges.right - rEdges.left) < 0.1 || Math.abs(dEdges.right - rEdges.right) < 0.1) {
            ctx.beginPath();
            ctx.moveTo(toCanvasX(dEdges.right), 0);
            ctx.lineTo(toCanvasX(dEdges.right), canvas.height);
            ctx.stroke();
        }
        if (Math.abs(dEdges.top - rEdges.top) < 0.1 || Math.abs(dEdges.top - rEdges.bottom) < 0.1) {
            ctx.beginPath();
            ctx.moveTo(0, toCanvasY(dEdges.top));
            ctx.lineTo(canvas.width, toCanvasY(dEdges.top));
            ctx.stroke();
        }
        if (Math.abs(dEdges.bottom - rEdges.top) < 0.1 || Math.abs(dEdges.bottom - rEdges.bottom) < 0.1) {
            ctx.beginPath();
            ctx.moveTo(0, toCanvasY(dEdges.bottom));
            ctx.lineTo(canvas.width, toCanvasY(dEdges.bottom));
            ctx.stroke();
        }
    });

    ctx.setLineDash([]);
}

function varColor(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function isPointInPolygon(p, polygon) {
    let isInside = false;
    const minX = Math.min(...polygon.map(v => v.x));
    const maxX = Math.max(...polygon.map(v => v.x));
    const minY = Math.min(...polygon.map(v => v.y));
    const maxY = Math.max(...polygon.map(v => v.y));
    
    if (p.x < minX || p.x > maxX || p.y < minY || p.y > maxY) {
        return false;
    }
    
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
        const xi = polygon[i].x, yi = polygon[i].y;
        const xj = polygon[j].x, yj = polygon[j].y;
        
        const intersect = ((yi > p.y) !== (yj > p.y))
            && (p.x < (xj - xi) * (p.y - yi) / (yj - yi) + xi);
        if (intersect) isInside = !isInside;
    }
    return isInside;
}

function getHitHandle(room, worldX, worldY) {
    if (room.type === 'custom' && room.vertices && room.vertices.length >= 3) {
        // For custom polygon rooms, checking polygon boundary hit
        const inside = isPointInPolygon({ x: worldX - room.x, y: worldY - room.y }, room.vertices);
        return inside ? 'move' : null;
    }

    const tolerance = 8 / state.scale;
    const rx = room.x;
    const ry = room.y;
    const rw = room.w;
    const rl = room.l;

    if (Math.abs(worldX - rx) < tolerance && Math.abs(worldY - ry) < tolerance) return 'nw';
    if (Math.abs(worldX - (rx + rw)) < tolerance && Math.abs(worldY - ry) < tolerance) return 'ne';
    if (Math.abs(worldX - (rx + rw)) < tolerance && Math.abs(worldY - (ry + rl)) < tolerance) return 'se';
    if (Math.abs(worldX - rx) < tolerance && Math.abs(worldY - (ry + rl)) < tolerance) return 'sw';

    if (Math.abs(worldX - (rx + rw / 2)) < tolerance && Math.abs(worldY - ry) < tolerance) return 'n';
    if (Math.abs(worldX - (rx + rw / 2)) < tolerance && Math.abs(worldY - (ry + rl)) < tolerance) return 's';
    if (Math.abs(worldX - rx) < tolerance && Math.abs(worldY - (ry + rl / 2)) < tolerance) return 'w';
    if (Math.abs(worldX - (rx + rw)) < tolerance && Math.abs(worldY - (ry + rl / 2)) < tolerance) return 'e';

    if (worldX > rx && worldX < rx + rw && worldY > ry && worldY < ry + rl) {
        return 'move';
    }

    return null;
}

function showCanvasPlacementHint(message = '') {
    const hint = document.getElementById('canvas-placement-hint');
    if (!hint) return;
    hint.classList.toggle('hidden', !message);
    const label = hint.querySelector('span');
    if (label) label.textContent = message;
}

function placeCanvasTool(tool, x, y) {
    const point = { x: snap(x), y: snap(y) };
    if (tool.kind === 'room') addRoom(tool.type, point);
    else if (tool.kind === 'sump') addSumpPump(point);
    else if (tool.kind === 'dehumidifier') addDehumidifier(point);
    else if (tool.kind === 'discharge') addDischargeLine(point);
    else if (tool.kind === 'interiorPipe') addInteriorPipe(point);
    else if (tool.kind === 'stanchion') addStanchion(point);
    else if (tool.kind === 'beam') addSupportBeam(point);
    state.pendingPlacement = null;
    showCanvasPlacementHint('');
    canvas.style.cursor = 'crosshair';
}

function beginCanvasToolPlacement(tool) {
    state.drawMode = null;
    state.sketchVertices = [];
    state.sketchRedoVertices = [];
    const drawingPanel = document.getElementById('custom-wall-drawer-panel');
    const drawingButton = document.getElementById('btn-draw-walls-mode');
    if (drawingPanel) drawingPanel.classList.add('hidden');
    if (drawingButton) drawingButton.classList.remove('active');
    state.pendingPlacement = tool;
    if (typeof switchView === 'function') switchView('2d');
    showCanvasPlacementHint(`Tap the blueprint to place ${tool.label}`);
    canvas.style.cursor = 'copy';
}

canvas.addEventListener('mousedown', (e) => {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const wx = toWorldX(mx);
    const wy = toWorldY(my);

    if (state.pendingPlacement) {
        placeCanvasTool(state.pendingPlacement, wx, wy);
        if (typeof closeAllDrawers === 'function') closeAllDrawers();
        return;
    }

    // Save history snapshot in case dragging starts
    if (typeof getHistorySnapshot === 'function') {
        state.dragSnapshot = getHistorySnapshot();
    }

    // Sketching custom rooms mode mousedown handler
    if (state.drawMode === 'custom') {
        const snapX = snap(wx);
        const snapY = snap(wy);
        
        if (state.sketchVertices.length >= 3) {
            const first = state.sketchVertices[0];
            const distToFirst = Math.sqrt((snapX - first.x)**2 + (snapY - first.y)**2);
            if (distToFirst < 1.0) {
                finishCustomRoomDrawing();
                return;
            }
        }
        
        state.sketchVertices.push({ x: snapX, y: snapY });
        showCanvasPlacementHint('');
        state.sketchRedoVertices = [];
        const btnRedoWall = document.getElementById('btn-draw-redo-wall');
        if (btnRedoWall) btnRedoWall.disabled = true;
        updateHistoryButtons();
        draw();
        return;
    }

    // Check custom room vertex handle clicks
    if (state.selectedRoomId) {
        const room = state.rooms.find(r => r.id === state.selectedRoomId);
        if (room && room.type === 'custom' && room.vertices) {
            for (let idx = 0; idx < room.vertices.length; idx++) {
                const v = room.vertices[idx];
                const avx = room.x + v.x;
                const avy = room.y + v.y;
                const dist = Math.sqrt((wx - avx)**2 + (wy - avy)**2);
                if (dist < 0.8) {
                    state.draggedVertex = { roomId: room.id, vertexIndex: idx };
                    return;
                }
            }
        }
    }

    // Check manual Carbon Fiber Strap selection
    if (state.selectedRoomId) {
        const room = state.rooms.find(r => r.id === state.selectedRoomId);
        if (room && room.carbonFiberScope === 'specific' && room.customCarbonStraps && room.customCarbonStraps.length > 0) {
            const segments = getRoomSegments(room);
            for (let strap of room.customCarbonStraps) {
                const seg = segments.find(s => s.wall === strap.wall);
                if (seg) {
                    const dx = seg.x2 - seg.x1;
                    const dy = seg.y2 - seg.y1;
                    const len = Math.sqrt(dx*dx + dy*dy);
                    if (len >= 0.05) {
                        const px = seg.x1 + dx * strap.offset;
                        const py = seg.y1 + dy * strap.offset;
                        const dist = Math.sqrt((wx - px)**2 + (wy - py)**2);
                        if (dist < 0.9) { // 0.9 feet click tolerance
                            state.draggedStrap = { roomId: room.id, strapId: strap.id };
                            selectItem('room', room.id);
                            return;
                        }
                    }
                }
            }
        }
    }

    // 0. Check Door/Window Openings click first
    for (let i = state.rooms.length - 1; i >= 0; i--) {
        const room = state.rooms[i];
        if (room.levelId && room.levelId !== state.currentLevelId) continue;
        for (let j = 0; j < room.openings.length; j++) {
            const op = room.openings[j];
            const rx = toCanvasX(room.x);
            const ry = toCanvasY(room.y);
            const rw = room.w * state.scale;
            const rl = room.l * state.scale;
            const widthPix = op.w * state.scale;
            const thickness = 12; // Click hit box thickness
            
            let opX, opY, opW, opH;
            if (op.wall === 'n') {
                opX = rx + (op.offset * state.scale) - (widthPix / 2);
                opY = ry - thickness / 2;
                opW = widthPix;
                opH = thickness;
            } else if (op.wall === 's') {
                opX = rx + (op.offset * state.scale) - (widthPix / 2);
                opY = ry + rl - thickness / 2;
                opW = widthPix;
                opH = thickness;
            } else if (op.wall === 'w') {
                opX = rx - thickness / 2;
                opY = ry + (op.offset * state.scale) - (widthPix / 2);
                opW = thickness;
                opH = widthPix;
            } else if (op.wall === 'e') {
                opX = rx + rw - thickness / 2;
                opY = ry + (op.offset * state.scale) - (widthPix / 2);
                opW = thickness;
                opH = widthPix;
            }
            
            if (mx >= opX && mx <= opX + opW && my >= opY && my <= opY + opH) {
                selectItem('room', room.id);
                state.draggedOpening = { roomId: room.id, openingId: op.id };
                return;
            }
        }
    }

    // 1. Check Sump Pumps click
    for (let i = state.sumpPumps.length - 1; i >= 0; i--) {
        const sp = state.sumpPumps[i];
        if (sp.levelId && sp.levelId !== state.currentLevelId) continue;
        const spcx = toCanvasX(sp.x);
        const spcy = toCanvasY(sp.y);
        const dist = Math.sqrt((mx - spcx)**2 + (my - spcy)**2);
        if (dist < 15) {
            selectItem('sump', sp.id);
            state.draggedSumpPumpId = sp.id;
            return;
        }
    }

    // 2. Check Discharge Lines endpoints & bodies
    for (let i = state.dischargeLines.length - 1; i >= 0; i--) {
        const dl = state.dischargeLines[i];
        if (dl.levelId && dl.levelId !== state.currentLevelId) continue;
        const h1x = toCanvasX(dl.x1);
        const h1y = toCanvasY(dl.y1);
        const h2x = toCanvasX(dl.x2);
        const h2y = toCanvasY(dl.y2);
        
        if (Math.sqrt((mx - h1x)**2 + (my - h1y)**2) < 10) {
            selectItem('discharge', dl.id);
            state.draggedDischargeHandle = { id: dl.id, point: 'p1' };
            return;
        }
        if (Math.sqrt((mx - h2x)**2 + (my - h2y)**2) < 10) {
            selectItem('discharge', dl.id);
            state.draggedDischargeHandle = { id: dl.id, point: 'p2' };
            return;
        }
        
        const distToSegment = getDistanceToSegment(wx, wy, dl.x1, dl.y1, dl.x2, dl.y2);
        if (distToSegment < 0.6) {
            selectItem('discharge', dl.id);
            state.draggedDischargeHandle = { id: dl.id, point: 'move' };
            state.initialMouseOffset = {
                x1: wx - dl.x1,
                y1: wy - dl.y1,
                x2: wx - dl.x2,
                y2: wy - dl.y2
            };
            return;
        }
    }

    // Check Interior Pipes click
    for (let i = state.interiorPipes.length - 1; i >= 0; i--) {
        const ip = state.interiorPipes[i];
        if (ip.levelId && ip.levelId !== state.currentLevelId) continue;
        const h1x = toCanvasX(ip.x1);
        const h1y = toCanvasY(ip.y1);
        const h2x = toCanvasX(ip.x2);
        const h2y = toCanvasY(ip.y2);
        
        if (Math.sqrt((mx - h1x)**2 + (my - h1y)**2) < 10) {
            selectItem('interiorPipe', ip.id);
            state.draggedInteriorPipeHandle = { id: ip.id, point: 'p1' };
            return;
        }
        if (Math.sqrt((mx - h2x)**2 + (my - h2y)**2) < 10) {
            selectItem('interiorPipe', ip.id);
            state.draggedInteriorPipeHandle = { id: ip.id, point: 'p2' };
            return;
        }
        
        const distToSegment = getDistanceToSegment(wx, wy, ip.x1, ip.y1, ip.x2, ip.y2);
        if (distToSegment < 0.6) {
            selectItem('interiorPipe', ip.id);
            state.draggedInteriorPipeHandle = { id: ip.id, point: 'move' };
            state.initialMouseOffset = {
                x1: wx - ip.x1,
                y1: wy - ip.y1,
                x2: wx - ip.x2,
                y2: wy - ip.y2
            };
            return;
        }
    }

    // Check Floor Hatches click
    for (let i = state.floorHatches.length - 1; i >= 0; i--) {
        const h = state.floorHatches[i];
        if (h.levelId && h.levelId !== state.currentLevelId) continue;
        const hcx = toCanvasX(h.x);
        const hcy = toCanvasY(h.y);
        const hwPix = h.w * state.scale;
        const hlPix = h.l * state.scale;
        
        if (Math.abs(mx - hcx) < hwPix / 2 && Math.abs(my - hcy) < hlPix / 2) {
            selectItem('floorHatch', h.id);
            state.draggedFloorHatchId = h.id;
            return;
        }
    }

    // Check Dehumidifiers click
    if (state.dehumidifiers) {
        for (let i = state.dehumidifiers.length - 1; i >= 0; i--) {
            const dehum = state.dehumidifiers[i];
            if (dehum.levelId && dehum.levelId !== state.currentLevelId) continue;
            const dcx = toCanvasX(dehum.x);
            const dcy = toCanvasY(dehum.y);
            const wPix = 1.0 * state.scale;
            const hPix = 1.2 * state.scale;
            if (Math.abs(mx - dcx) < wPix / 2 + 5 && Math.abs(my - dcy) < hPix / 2 + 5) {
                selectItem('dehumidifier', dehum.id);
                state.draggedDehumidifierId = dehum.id;
                return;
            }
        }
    }

    // Check Stanchions click
    for (let i = state.stanchions.length - 1; i >= 0; i--) {
        const st = state.stanchions[i];
        if (st.levelId && st.levelId !== state.currentLevelId) continue;
        const stcx = toCanvasX(st.x);
        const stcy = toCanvasY(st.y);
        const dist = Math.sqrt((mx - stcx)**2 + (my - stcy)**2);
        if (dist < 12) {
            selectItem('stanchion', st.id);
            state.draggedStanchionId = st.id;
            return;
        }
    }

    // Check Support Beams click
    for (let i = state.mainBeams.length - 1; i >= 0; i--) {
        const bm = state.mainBeams[i];
        if (bm.levelId && bm.levelId !== state.currentLevelId) continue;
        const h1x = toCanvasX(bm.x1);
        const h1y = toCanvasY(bm.y1);
        const h2x = toCanvasX(bm.x2);
        const h2y = toCanvasY(bm.y2);
        
        if (Math.sqrt((mx - h1x)**2 + (my - h1y)**2) < 10) {
            selectItem('beam', bm.id);
            state.draggedMainBeamHandle = { id: bm.id, point: 'p1' };
            return;
        }
        if (Math.sqrt((mx - h2x)**2 + (my - h2y)**2) < 10) {
            selectItem('beam', bm.id);
            state.draggedMainBeamHandle = { id: bm.id, point: 'p2' };
            return;
        }
        
        const distToSegment = getDistanceToSegment(wx, wy, bm.x1, bm.y1, bm.x2, bm.y2);
        if (distToSegment < 0.6) {
            selectItem('beam', bm.id);
            state.draggedMainBeamHandle = { id: bm.id, point: 'move' };
            state.initialMouseOffset = {
                x1: wx - bm.x1,
                y1: wy - bm.y1,
                x2: wx - bm.x2,
                y2: wy - bm.y2
            };
            return;
        }
    }

    // 3. Check selected room handles
    if (state.selectedRoomId) {
        const room = state.rooms.find(r => r.id === state.selectedRoomId);
        if (room) {
            const handle = getHitHandle(room, wx, wy);
            if (handle && handle !== 'move') {
                state.draggedRoomId = room.id;
                state.draggedHandle = handle;
                return;
            }
        }
    }

    // 4. Check room bodies
    for (let i = state.rooms.length - 1; i >= 0; i--) {
        const room = state.rooms[i];
        if (room.levelId && room.levelId !== state.currentLevelId) continue;
        const handle = getHitHandle(room, wx, wy);
        if (handle === 'move') {
            selectItem('room', room.id);
            state.draggedRoomId = room.id;
            state.draggedHandle = 'move';
            state.initialMouseOffset = {
                x: wx - room.x,
                y: wy - room.y
            };
            draw();
            return;
        }
    }

    // 5. Empty space
    selectItem(null);
    state.isDraggingCanvas = true;
    state.dragStartX = e.clientX;
    state.dragStartY = e.clientY;
    draw();
});

canvas.addEventListener('mousemove', (e) => {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const wx = toWorldX(mx);
    const wy = toWorldY(my);

    // Sketching custom rooms mode mousemove handler
    if (state.drawMode === 'custom') {
        state.lastMouseWorldX = snap(wx);
        state.lastMouseWorldY = snap(wy);
        canvas.style.cursor = 'crosshair';
        draw();
        return;
    }

    // Custom room vertex dragging handler
    if (state.draggedVertex) {
        const room = state.rooms.find(r => r.id === state.draggedVertex.roomId);
        if (room && room.vertices) {
            const v = room.vertices[state.draggedVertex.vertexIndex];
            v.x = snap(wx - room.x);
            v.y = snap(wy - room.y);

            // Recompute room dimensions
            const minX = Math.min(...room.vertices.map(v => v.x));
            const maxX = Math.max(...room.vertices.map(v => v.x));
            const minY = Math.min(...room.vertices.map(v => v.y));
            const maxY = Math.max(...room.vertices.map(v => v.y));

            // Shift origin to keep the bounding box aligned
            if (minX !== 0 || minY !== 0) {
                room.x += minX;
                room.y += minY;
                room.vertices.forEach(vt => {
                    vt.x -= minX;
                    vt.y -= minY;
                });
            }
            room.w = maxX - minX;
            room.l = maxY - minY;

            updateRoomEstimates(room);
            draw();
            updateGlobalStats();
            if (window.sync3D) window.sync3D();
        }
        return;
    }

    // Drag manual Carbon Fiber Strap
    if (state.draggedStrap) {
        const room = state.rooms.find(r => r.id === state.draggedStrap.roomId);
        if (room && room.customCarbonStraps) {
            const strap = room.customCarbonStraps.find(s => s.id === state.draggedStrap.strapId);
            if (strap) {
                const segments = getRoomSegments(room);
                let bestSeg = null;
                let bestT = 0.5;
                let minDist = Infinity;
                
                for (let seg of segments) {
                    const dx = seg.x2 - seg.x1;
                    const dy = seg.y2 - seg.y1;
                    const len = Math.sqrt(dx*dx + dy*dy);
                    if (len < 0.05) continue;
                    
                    let t = ((wx - seg.x1) * dx + (wy - seg.y1) * dy) / (len * len);
                    t = Math.max(0.0, Math.min(1.0, t));
                    const projX = seg.x1 + t * dx;
                    const projY = seg.y1 + t * dy;
                    const dist = Math.sqrt((wx - projX)**2 + (wy - projY)**2);
                    
                    if (dist < minDist) {
                        minDist = dist;
                        bestSeg = seg;
                        bestT = t;
                    }
                }
                
                if (bestSeg) {
                    strap.wall = bestSeg.wall;
                    strap.offset = bestT;
                    draw();
                    if (window.sync3D) window.sync3D();
                    
                    // Render details panel sidebar in real-time
                    if (typeof renderCustomStrapsList === 'function') {
                        renderCustomStrapsList(room);
                    }
                }
            }
        }
        canvas.style.cursor = 'grabbing';
        return;
    }

    // Default cursor resetting
    canvas.style.cursor = 'default';

    // Pan Canvas
    if (state.isDraggingCanvas) {
        const dx = e.clientX - state.dragStartX;
        const dy = e.clientY - state.dragStartY;
        state.offsetX += dx;
        state.offsetY += dy;
        state.dragStartX = e.clientX;
        state.dragStartY = e.clientY;
        draw();
        return;
    }

    // Sump Pump Dragging
    if (state.draggedSumpPumpId) {
        const sp = state.sumpPumps.find(p => p.id === state.draggedSumpPumpId);
        if (sp) {
            sp.x = snap(wx);
            sp.y = snap(wy);
            draw();
        }
        return;
    }

    // Discharge Line Dragging
    if (state.draggedDischargeHandle) {
        const dl = state.dischargeLines.find(l => l.id === state.draggedDischargeHandle.id);
        if (dl) {
            if (state.draggedDischargeHandle.point === 'p1') {
                dl.x1 = snap(wx);
                dl.y1 = snap(wy);
            } else if (state.draggedDischargeHandle.point === 'p2') {
                dl.x2 = snap(wx);
                dl.y2 = snap(wy);
            } else if (state.draggedDischargeHandle.point === 'move') {
                dl.x1 = snap(wx - state.initialMouseOffset.x1);
                dl.y1 = snap(wy - state.initialMouseOffset.y1);
                dl.x2 = snap(wx - state.initialMouseOffset.x2);
                dl.y2 = snap(wy - state.initialMouseOffset.y2);
            }
            dl.length = Math.sqrt((dl.x2 - dl.x1)**2 + (dl.y2 - dl.y1)**2);
            
            // Sync length input in real-time
            if (state.selectedDischargeLineId === dl.id) {
                document.getElementById('discharge-len-input').value = dl.length.toFixed(1);
            }
            draw();
            updateGlobalStats();
        }
        return;
    }

    // Interior Pipe Dragging
    if (state.draggedInteriorPipeHandle) {
        const ip = state.interiorPipes.find(l => l.id === state.draggedInteriorPipeHandle.id);
        if (ip) {
            if (state.draggedInteriorPipeHandle.point === 'p1') {
                const dx = ip.x2 - wx;
                const dy = ip.y2 - wy;
                const dist = Math.sqrt(dx*dx + dy*dy);
                const angle = Math.atan2(dy, dx);
                const deg = angle * 180 / Math.PI;
                const snappedDeg = Math.round(deg / 45) * 45;
                const snappedRad = snappedDeg * Math.PI / 180;
                ip.x1 = snap(ip.x2 - dist * Math.cos(snappedRad));
                ip.y1 = snap(ip.y2 - dist * Math.sin(snappedRad));
            } else if (state.draggedInteriorPipeHandle.point === 'p2') {
                const dx = wx - ip.x1;
                const dy = wy - ip.y1;
                const dist = Math.sqrt(dx*dx + dy*dy);
                const angle = Math.atan2(dy, dx);
                const deg = angle * 180 / Math.PI;
                const snappedDeg = Math.round(deg / 45) * 45;
                const snappedRad = snappedDeg * Math.PI / 180;
                ip.x2 = snap(ip.x1 + dist * Math.cos(snappedRad));
                ip.y2 = snap(ip.y1 + dist * Math.sin(snappedRad));
            } else if (state.draggedInteriorPipeHandle.point === 'move') {
                ip.x1 = snap(wx - state.initialMouseOffset.x1);
                ip.y1 = snap(wy - state.initialMouseOffset.y1);
                ip.x2 = snap(wx - state.initialMouseOffset.x2);
                ip.y2 = snap(wy - state.initialMouseOffset.y2);
            }
            ip.length = Math.sqrt((ip.x2 - ip.x1)**2 + (ip.y2 - ip.y1)**2);
            
            // Sync length input in real-time
            if (state.selectedInteriorPipeId === ip.id) {
                const lenInput = document.getElementById('interior-pipe-len-input');
                if (lenInput) lenInput.value = ip.length.toFixed(1);
            }
            draw();
            updateGlobalStats();
        }
    }

    // Dehumidifier Dragging
    if (state.draggedDehumidifierId) {
        const dehum = state.dehumidifiers.find(p => p.id === state.draggedDehumidifierId);
        if (dehum) {
            dehum.x = snap(wx);
            dehum.y = snap(wy);
            draw();
            updateGlobalStats();
        }
        return;
    }

    // Stanchion Dragging
    if (state.draggedStanchionId) {
        const st = state.stanchions.find(p => p.id === state.draggedStanchionId);
        if (st) {
            st.x = snap(wx);
            st.y = snap(wy);
            draw();
        }
        return;
    }

    // Floor Hatch Dragging
    if (state.draggedFloorHatchId) {
        const h = state.floorHatches.find(p => p.id === state.draggedFloorHatchId);
        if (h) {
            h.x = snap(wx);
            h.y = snap(wy);
            draw();
        }
        return;
    }

    // Support Beam Dragging
    if (state.draggedMainBeamHandle) {
        const bm = state.mainBeams.find(l => l.id === state.draggedMainBeamHandle.id);
        if (bm) {
            if (state.draggedMainBeamHandle.point === 'p1') {
                const dx = bm.x2 - wx;
                const dy = bm.y2 - wy;
                const dist = Math.sqrt(dx*dx + dy*dy);
                const angle = Math.atan2(dy, dx);
                const deg = angle * 180 / Math.PI;
                const snappedDeg = Math.round(deg / 45) * 45;
                const snappedRad = snappedDeg * Math.PI / 180;
                bm.x1 = snap(bm.x2 - dist * Math.cos(snappedRad));
                bm.y1 = snap(bm.y2 - dist * Math.sin(snappedRad));
            } else if (state.draggedMainBeamHandle.point === 'p2') {
                const dx = wx - bm.x1;
                const dy = wy - bm.y1;
                const dist = Math.sqrt(dx*dx + dy*dy);
                const angle = Math.atan2(dy, dx);
                const deg = angle * 180 / Math.PI;
                const snappedDeg = Math.round(deg / 45) * 45;
                const snappedRad = snappedDeg * Math.PI / 180;
                bm.x2 = snap(bm.x1 + dist * Math.cos(snappedRad));
                bm.y2 = snap(bm.y1 + dist * Math.sin(snappedRad));
            } else if (state.draggedMainBeamHandle.point === 'move') {
                bm.x1 = snap(wx - state.initialMouseOffset.x1);
                bm.y1 = snap(wy - state.initialMouseOffset.y1);
                bm.x2 = snap(wx - state.initialMouseOffset.x2);
                bm.y2 = snap(wy - state.initialMouseOffset.y2);
            }
            bm.length = Math.sqrt((bm.x2 - bm.x1)**2 + (bm.y2 - bm.y1)**2);
            
            // Sync length input in real-time
            if (state.selectedMainBeamId === bm.id) {
                const lenInput = document.getElementById('beam-len-input');
                if (lenInput) lenInput.value = bm.length.toFixed(1);
            }
            draw();
            updateGlobalStats();
        }
        return;
    }

    // Opening (Door/Window) Dragging along wall bounds
    if (state.draggedOpening) {
        const room = state.rooms.find(r => r.id === state.draggedOpening.roomId);
        if (room) {
            const op = room.openings.find(o => o.id === state.draggedOpening.openingId);
            if (op) {
                let newOffset = op.offset;
                if (op.wall === 'n' || op.wall === 's') {
                    newOffset = wx - room.x;
                    newOffset = Math.max(op.w / 2, Math.min(room.w - op.w / 2, snap(newOffset)));
                } else {
                    newOffset = wy - room.y;
                    newOffset = Math.max(op.w / 2, Math.min(room.l - op.w / 2, snap(newOffset)));
                }
                op.offset = newOffset;
                
                if (state.selectedRoomId === room.id) {
                    updateRoomEstimates(room);
                }
                draw();
            }
        }
        return;
    }

    // Room Drag or Resize
    if (state.draggedRoomId) {
        const room = state.rooms.find(r => r.id === state.draggedRoomId);
        if (!room) return;

        if (state.draggedHandle === 'move') {
            let targetX = snap(wx - state.initialMouseOffset.x);
            let targetY = snap(wy - state.initialMouseOffset.y);

            state.rooms.forEach(r => {
                if (r.id === room.id) return;
                if (r.levelId && r.levelId !== state.currentLevelId) return;
                const snapTolerance = 0.6;
                if (Math.abs(targetX - r.x) < snapTolerance) targetX = r.x;
                if (Math.abs(targetX + room.w - r.x) < snapTolerance) targetX = r.x - room.w;
                if (Math.abs(targetX - (r.x + r.w)) < snapTolerance) targetX = r.x + r.w;
                if (Math.abs(targetX + room.w - (r.x + r.w)) < snapTolerance) targetX = r.x + r.w - room.w;
                if (Math.abs(targetY - r.y) < snapTolerance) targetY = r.y;
                if (Math.abs(targetY + room.l - r.y) < snapTolerance) targetY = r.y - room.l;
                if (Math.abs(targetY - (r.y + r.l)) < snapTolerance) targetY = r.y + r.l;
                if (Math.abs(targetY + room.l - (r.y + r.l)) < snapTolerance) targetY = r.y + r.l - room.l;
            });

            room.x = targetX;
            room.y = targetY;
        } else {
            const snapW = snap(wx);
            const snapH = snap(wy);

            if (state.draggedHandle === 'e') {
                room.w = Math.max(2, snapW - room.x);
            } else if (state.draggedHandle === 'w') {
                const oldRight = room.x + room.w;
                room.x = Math.min(oldRight - 2, snapW);
                room.w = oldRight - room.x;
            } else if (state.draggedHandle === 's') {
                room.l = Math.max(2, snapH - room.y);
            } else if (state.draggedHandle === 'n') {
                const oldBottom = room.y + room.l;
                room.y = Math.min(oldBottom - 2, snapH);
                room.l = oldBottom - room.y;
            } else if (state.draggedHandle === 'se') {
                room.w = Math.max(2, snapW - room.x);
                room.l = Math.max(2, snapH - room.y);
            } else if (state.draggedHandle === 'sw') {
                const oldRight = room.x + room.w;
                room.x = Math.min(oldRight - 2, snapW);
                room.w = oldRight - room.x;
                room.l = Math.max(2, snapH - room.y);
            } else if (state.draggedHandle === 'ne') {
                const oldBottom = room.y + room.l;
                room.w = Math.max(2, snapW - room.x);
                room.y = Math.min(oldBottom - 2, snapH);
                room.l = oldBottom - room.y;
            } else if (state.draggedHandle === 'nw') {
                const oldRight = room.x + room.w;
                const oldBottom = room.y + room.l;
                room.x = Math.min(oldRight - 2, snapW);
                room.w = oldRight - room.x;
                room.y = Math.min(oldBottom - 2, snapH);
                room.l = oldBottom - room.y;
            }
            
            room.openings.forEach(op => {
                if (op.wall === 'n' || op.wall === 's') {
                    op.offset = Math.min(room.w - 0.5, Math.max(0.5, op.offset));
                } else {
                    op.offset = Math.min(room.l - 0.5, Math.max(0.5, op.offset));
                }
            });
        }

        updateRoomEstimates(room);
        draw();
        return;
    }

    // Set Cursors
    let cursor = 'crosshair';
    
    // Hovering sump pump
    state.sumpPumps.forEach(sp => {
        if (sp.levelId && sp.levelId !== state.currentLevelId) return;
        const cx = toCanvasX(sp.x);
        const cy = toCanvasY(sp.y);
        if (Math.sqrt((mx - cx)**2 + (my - cy)**2) < 15) {
            cursor = 'pointer';
        }
    });
    
    // Hovering discharge handle
    state.dischargeLines.forEach(dl => {
        if (dl.levelId && dl.levelId !== state.currentLevelId) return;
        const h1x = toCanvasX(dl.x1);
        const h1y = toCanvasY(dl.y1);
        const h2x = toCanvasX(dl.x2);
        const h2y = toCanvasY(dl.y2);
        if (Math.sqrt((mx - h1x)**2 + (my - h1y)**2) < 10 || Math.sqrt((mx - h2x)**2 + (my - h2y)**2) < 10) {
            cursor = 'pointer';
        }
    });

    if (state.selectedRoomId) {
        const room = state.rooms.find(r => r.id === state.selectedRoomId);
        if (room) {
            const handle = getHitHandle(room, wx, wy);
            if (handle) {
                if (handle === 'n' || handle === 's') cursor = 'ns-resize';
                else if (handle === 'e' || handle === 'w') cursor = 'ew-resize';
                else if (handle === 'nw' || handle === 'se') cursor = 'nwse-resize';
                else if (handle === 'ne' || handle === 'sw') cursor = 'nesw-resize';
                else if (handle === 'move') cursor = 'move';
            }
        }
    }
    
    if (cursor === 'crosshair') {
        const hovered = state.rooms.find(r => {
            if (r.levelId && r.levelId !== state.currentLevelId) return false;
            return getHitHandle(r, wx, wy) === 'move';
        });
        if (hovered) cursor = 'pointer';
    }

    canvas.style.cursor = cursor;
});

canvas.addEventListener('mouseup', () => {
    // If elements were dragged, check if they actually moved and commit to history
    if (state.draggedRoomId || state.draggedSumpPumpId || state.draggedFloorHatchId || state.draggedDischargeHandle || state.draggedInteriorPipeHandle || state.draggedStanchionId || state.draggedMainBeamHandle || state.draggedOpening || state.draggedVertex || state.draggedStrap) {
        if (state.dragSnapshot) {
            const currentStr = JSON.stringify({
                rooms: state.rooms,
                sumpPumps: state.sumpPumps,
                dischargeLines: state.dischargeLines,
                interiorPipes: state.interiorPipes,
                stanchions: state.stanchions,
                mainBeams: state.mainBeams,
                floorHatches: state.floorHatches
            });
            const snapStr = JSON.stringify({
                rooms: state.dragSnapshot.rooms,
                sumpPumps: state.dragSnapshot.sumpPumps,
                dischargeLines: state.dragSnapshot.dischargeLines,
                interiorPipes: state.dragSnapshot.interiorPipes,
                stanchions: state.dragSnapshot.stanchions || [],
                mainBeams: state.dragSnapshot.mainBeams || [],
                floorHatches: state.dragSnapshot.floorHatches || []
            });
            if (currentStr !== snapStr) {
                state.undoStack.push(state.dragSnapshot);
                if (state.undoStack.length > 50) {
                    state.undoStack.shift();
                }
                state.redoStack = [];
                if (typeof updateHistoryButtons === 'function') updateHistoryButtons();
            }
        }
    }
    state.dragSnapshot = null;

    state.isDraggingCanvas = false;
    state.draggedRoomId = null;
    state.draggedHandle = null;
    state.draggedSumpPumpId = null;
    state.draggedDehumidifierId = null;
    state.draggedFloorHatchId = null;
    state.draggedDischargeHandle = null;
    state.draggedInteriorPipeHandle = null;
    state.draggedStanchionId = null;
    state.draggedMainBeamHandle = null;
    state.draggedOpening = null;
    state.draggedVertex = null;
    state.draggedStrap = null;
    draw();
    if (window.sync3D) window.sync3D();
});

// Event Listeners for UI Form Inputs
document.getElementById('room-name-input').addEventListener('input', (e) => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (room) {
        room.name = e.target.value;
        draw();
        if (window.sync3D) window.sync3D();
    }
});

document.getElementById('room-w-input').addEventListener('input', (e) => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    const val = parseFloat(e.target.value);
    if (room && !isNaN(val) && val >= 1) {
        room.w = val;
        updateRoomEstimates(room);
        draw();
        if (window.sync3D) window.sync3D();
    }
});

document.getElementById('room-l-input').addEventListener('input', (e) => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    const val = parseFloat(e.target.value);
    if (room && !isNaN(val) && val >= 1) {
        room.l = val;
        updateRoomEstimates(room);
        draw();
        if (window.sync3D) window.sync3D();
    }
});

document.getElementById('room-h-input').addEventListener('input', (e) => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    const val = parseFloat(e.target.value);
    if (room && !isNaN(val) && val >= 1) {
        room.h = val;
        updateRoomEstimates(room);
        draw();
        if (window.sync3D) window.sync3D();
    }
});

document.getElementById('room-steps-input').addEventListener('input', (e) => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    const val = parseInt(e.target.value);
    if (room && room.type === 'staircase' && !isNaN(val) && val >= 1) {
        room.steps = val;
        draw();
        if (window.sync3D) window.sync3D();
    }
});

// Sump Pump listeners
document.getElementById('sump-name-input').addEventListener('input', (e) => {
    if (!state.selectedSumpPumpId) return;
    const sump = state.sumpPumps.find(p => p.id === state.selectedSumpPumpId);
    if (sump) {
        sump.name = e.target.value;
        draw();
    }
});
document.getElementById('btn-delete-sump').addEventListener('click', deleteSelectedSump);

// Dehumidifier listeners
document.getElementById('dehumidifier-name-input').addEventListener('input', (e) => {
    if (!state.selectedDehumidifierId) return;
    const dehum = state.dehumidifiers.find(p => p.id === state.selectedDehumidifierId);
    if (dehum) {
        dehum.name = e.target.value;
        draw();
    }
});
document.getElementById('btn-delete-dehumidifier').addEventListener('click', deleteSelectedDehumidifier);

// Discharge line listeners
document.getElementById('discharge-label-input').addEventListener('input', (e) => {
    if (!state.selectedDischargeLineId) return;
    const dl = state.dischargeLines.find(l => l.id === state.selectedDischargeLineId);
    if (dl) {
        dl.label = e.target.value;
        draw();
    }
});

document.getElementById('discharge-len-input').addEventListener('input', (e) => {
    if (!state.selectedDischargeLineId) return;
    const dl = state.dischargeLines.find(l => l.id === state.selectedDischargeLineId);
    const val = parseFloat(e.target.value);
    if (dl && !isNaN(val) && val > 0.1) {
        const dx = dl.x2 - dl.x1;
        const dy = dl.y2 - dl.y1;
        const currentLen = Math.sqrt(dx*dx + dy*dy);
        if (currentLen > 0.05) {
            dl.x2 = dl.x1 + (dx / currentLen) * val;
            dl.y2 = dl.y1 + (dy / currentLen) * val;
        } else {
            dl.x2 = dl.x1 + val; // default extends east
        }
        dl.length = val;
        draw();
        updateGlobalStats();
    }
});
document.getElementById('btn-delete-discharge').addEventListener('click', deleteSelectedDischarge);

// Interior pipe listeners
document.getElementById('interior-pipe-label-input').addEventListener('input', (e) => {
    if (!state.selectedInteriorPipeId) return;
    const ip = state.interiorPipes.find(l => l.id === state.selectedInteriorPipeId);
    if (ip) {
        ip.label = e.target.value;
        draw();
    }
});

document.getElementById('interior-pipe-len-input').addEventListener('input', (e) => {
    if (!state.selectedInteriorPipeId) return;
    const ip = state.interiorPipes.find(l => l.id === state.selectedInteriorPipeId);
    const val = parseFloat(e.target.value);
    if (ip && !isNaN(val) && val > 0.1) {
        const dx = ip.x2 - ip.x1;
        const dy = ip.y2 - ip.y1;
        const currentLen = Math.sqrt(dx*dx + dy*dy);
        if (currentLen > 0.05) {
            ip.x2 = ip.x1 + (dx / currentLen) * val;
            ip.y2 = ip.y1 + (dy / currentLen) * val;
        } else {
            ip.x2 = ip.x1 + val;
        }
        ip.length = val;
        draw();
        updateGlobalStats();
    }
});
document.getElementById('btn-delete-interior-pipe').addEventListener('click', deleteSelectedInteriorPipe);

// Add 90° Turn (Elbow) from active pipe end
document.getElementById('btn-add-90-turn').addEventListener('click', () => {
    if (!state.selectedInteriorPipeId) return;
    const ip = state.interiorPipes.find(p => p.id === state.selectedInteriorPipeId);
    if (!ip) return;
    
    if (typeof saveHistoryState === 'function') saveHistoryState();
    
    const dx = ip.x2 - ip.x1;
    const dy = ip.y2 - ip.y1;
    const len = Math.sqrt(dx*dx + dy*dy);
    
    let nx = 1, ny = 0;
    if (len > 0.05) {
        nx = dx / len;
        ny = dy / len;
    }
    
    // Rotate 90° clockwise: (rx, ry) = (-ny, nx)
    const rx = -ny;
    const ry = nx;
    const defaultLen = 4.0;
    
    const newPipe = {
        id: generateId(),
        levelId: ip.levelId || state.currentLevelId,
        label: `Interior Pipe ${state.interiorPipes.length + 1}`,
        x1: ip.x2,
        y1: ip.y2,
        x2: ip.x2 + rx * defaultLen,
        y2: ip.y2 + ry * defaultLen,
        length: defaultLen
    };
    
    state.interiorPipes.push(newPipe);
    selectItem('interiorPipe', newPipe.id);
    draw();
    updateGlobalStats();
    if (window.sync3D) window.sync3D();
});

// Add 45° Turn (Elbow) from active pipe end
document.getElementById('btn-add-45-turn').addEventListener('click', () => {
    if (!state.selectedInteriorPipeId) return;
    const ip = state.interiorPipes.find(p => p.id === state.selectedInteriorPipeId);
    if (!ip) return;
    
    if (typeof saveHistoryState === 'function') saveHistoryState();
    
    const dx = ip.x2 - ip.x1;
    const dy = ip.y2 - ip.y1;
    const len = Math.sqrt(dx*dx + dy*dy);
    
    let nx = 1, ny = 0;
    if (len > 0.05) {
        nx = dx / len;
        ny = dy / len;
    }
    
    // Rotate 45° clockwise: 
    // rx = nx * cos(45) - ny * sin(45)
    // ry = nx * sin(45) + ny * cos(45)
    const cos45 = 0.7071;
    const sin45 = 0.7071;
    const rx = nx * cos45 - ny * sin45;
    const ry = nx * sin45 + ny * cos45;
    const defaultLen = 4.0;
    
    const newPipe = {
        id: generateId(),
        levelId: ip.levelId || state.currentLevelId,
        label: `Interior Pipe ${state.interiorPipes.length + 1}`,
        x1: ip.x2,
        y1: ip.y2,
        x2: ip.x2 + rx * defaultLen,
        y2: ip.y2 + ry * defaultLen,
        length: defaultLen
    };
    
    state.interiorPipes.push(newPipe);
    selectItem('interiorPipe', newPipe.id);
    draw();
    updateGlobalStats();
    if (window.sync3D) window.sync3D();
});

// Room Joists Direction change
document.getElementById('room-joists-select').addEventListener('change', (e) => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (room) {
        if (typeof saveHistoryState === 'function') saveHistoryState();
        room.joists = e.target.value;
        draw();
        updateGlobalStats();
        if (window.sync3D) window.sync3D();
    }
});

// Room Exterior Foam Board change
document.getElementById('room-foam-board-checkbox').addEventListener('change', (e) => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (room) {
        if (typeof saveHistoryState === 'function') saveHistoryState();
        room.foamBoard = e.target.checked;
        draw();
        updateGlobalStats();
        if (window.sync3D) window.sync3D();
    }
});

// Room Spray Foam Bond Pockets change
document.getElementById('room-foam-bond-pockets-checkbox').addEventListener('change', (e) => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (room) {
        if (typeof saveHistoryState === 'function') saveHistoryState();
        room.foamBondPockets = e.target.checked;
        updateRoomEstimates(room);
        draw();
        updateGlobalStats();
        if (window.sync3D) window.sync3D();
    }
});

// Room Carbon Fiber Straps Qty change
document.getElementById('room-carbon-straps-input').addEventListener('input', (e) => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (room) {
        const val = Math.max(0, parseInt(e.target.value) || 0);
        if (typeof saveHistoryState === 'function') saveHistoryState();
        room.carbonStraps = val;
        initializeCustomStraps(room);
        renderCustomStrapsList(room);
        draw();
        updateGlobalStats();
        updateToolboxReinforcementLabels(room);
        if (window.sync3D) window.sync3D();
    }
});

document.getElementById('room-carbon-scope-select').addEventListener('change', (e) => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (room) {
        saveHistoryState();
        room.carbonFiberScope = e.target.value;
        if (room.carbonFiberScope === 'specific' && (!room.carbonFiberWalls || room.carbonFiberWalls.length === 0)) {
            const segments = getRoomSegments(room);
            room.carbonFiberWalls = segments.map(s => s.wall);
        }
        autoSpaceCarbonStraps(room);
        renderCarbonWallsCheckboxes(room);
        draw();
        if (window.sync3D) window.sync3D();
    }
});

function renderCarbonWallsCheckboxes(room) {
    const container = document.getElementById('room-carbon-walls-checkboxes');
    if (!container) return;
    container.innerHTML = '';
    
    const scopeContainer = document.getElementById('room-carbon-walls-container');
    if (room.carbonFiberScope === 'specific') {
        scopeContainer.classList.remove('hidden');
    } else {
        scopeContainer.classList.add('hidden');
        return;
    }
    
    const segments = getRoomSegments(room);
    segments.forEach((seg, i) => {
        let wallLabel = `Wall ${i+1}`;
        if (room.type !== 'custom') {
            const labels = { n: 'Wall 1 (North)', e: 'Wall 2 (East)', s: 'Wall 3 (South)', w: 'Wall 4 (West)' };
            wallLabel = labels[seg.wall] || `Wall ${i+1}`;
        }
        
        const isChecked = Array.isArray(room.carbonFiberWalls) && room.carbonFiberWalls.includes(seg.wall);
        
        const row = document.createElement('div');
        row.style.display = 'flex';
        row.style.alignItems = 'center';
        row.style.justifyContent = 'space-between';
        row.style.gap = '0.5rem';
        row.style.marginTop = '0.2rem';
        row.innerHTML = `
            <div style="display: flex; align-items: center; gap: 0.5rem;">
                <input type="checkbox" id="cb-wall-${seg.wall}" style="width:auto; margin:0;" ${isChecked ? 'checked' : ''}>
                <label for="cb-wall-${seg.wall}" style="font-size:0.75rem; font-weight:500; cursor:pointer; margin-bottom:0; color:var(--text-color);">${wallLabel}</label>
            </div>
            <button type="button" class="btn-add-wall-strap" style="background: rgba(45, 212, 191, 0.15); color: var(--accent-teal); border: 1px solid rgba(45, 212, 191, 0.25); padding: 0.15rem 0.35rem; border-radius: 4px; font-size: 0.7rem; font-weight: 600; cursor: pointer; transition: all 0.2s;">+ Add Strap</button>
        `;
        
        row.querySelector('input').addEventListener('change', (e) => {
            if (e.target.checked) {
                if (!room.carbonFiberWalls.includes(seg.wall)) {
                    room.carbonFiberWalls.push(seg.wall);
                }
            } else {
                room.carbonFiberWalls = room.carbonFiberWalls.filter(w => w !== seg.wall);
            }
            autoSpaceCarbonStraps(room);
            renderCustomStrapsList(room);
            
            // Sync input Qty value
            const input = document.getElementById('room-carbon-straps-input');
            if (input) input.value = room.carbonStraps;
            
            draw();
            if (window.sync3D) window.sync3D();
        });

        row.querySelector('.btn-add-wall-strap').addEventListener('click', (e) => {
            e.stopPropagation();
            saveHistoryState();
            
            // Ensure the wall is checked if adding a strap
            if (!room.carbonFiberWalls.includes(seg.wall)) {
                room.carbonFiberWalls.push(seg.wall);
            }
            
            if (!room.customCarbonStraps) room.customCarbonStraps = [];
            room.customCarbonStraps.push({
                id: 'strap_' + Math.random().toString(36).substr(2, 9),
                wall: seg.wall,
                offset: 0.5
            });
            room.carbonStraps = room.customCarbonStraps.length;
            
            // Sync input Qty value
            const input = document.getElementById('room-carbon-straps-input');
            if (input) input.value = room.carbonStraps;
            
            renderCarbonWallsCheckboxes(room);
            draw();
            updateGlobalStats();
            if (window.sync3D) window.sync3D();
        });

        container.appendChild(row);
    });
    
    // Render custom manual straps list
    renderCustomStrapsList(room);
}

function renderCustomStrapsList(room) {
    const listContainer = document.getElementById('room-custom-straps-container');
    const listEl = document.getElementById('room-custom-straps-list');
    if (!listContainer || !listEl) return;
    
    if (room.carbonFiberScope === 'specific') {
        listContainer.classList.remove('hidden');
    } else {
        listContainer.classList.add('hidden');
        return;
    }
    
    listEl.innerHTML = '';
    initializeCustomStraps(room);
    
    if (!room.customCarbonStraps || room.customCarbonStraps.length === 0) {
        listEl.innerHTML = `<p style="font-size: 0.75rem; color: var(--text-muted); margin: 0; padding: 0.5rem; text-align: center; font-style: italic;">No straps placed. Click '+ Add Strap' or drag handles.</p>`;
        return;
    }
    
    room.customCarbonStraps.forEach((strap, idx) => {
        let wallLabel = `Wall ${strap.wall}`;
        if (room.type !== 'custom') {
            const labels = { n: 'North Wall', e: 'East Wall', s: 'South Wall', w: 'West Wall' };
            wallLabel = labels[strap.wall] || `Wall ${strap.wall}`;
        } else {
            const wallIdx = parseInt(strap.wall);
            if (!isNaN(wallIdx)) wallLabel = `Wall ${wallIdx + 1}`;
        }
        
        const pct = Math.round(strap.offset * 100);
        
        const row = document.createElement('div');
        row.style.display = 'flex';
        row.style.justifyContent = 'space-between';
        row.style.alignItems = 'center';
        row.style.background = 'rgba(255,255,255,0.02)';
        row.style.border = '1px solid var(--border-color)';
        row.style.padding = '0.35rem 0.5rem';
        row.style.borderRadius = '4px';
        row.style.marginTop = '0.25rem';
        
        row.innerHTML = `
            <span style="font-size: 0.75rem; font-weight: 500; color: var(--text-color);">${idx + 1}. ${wallLabel} (${pct}%)</span>
            <button type="button" class="btn-delete-strap" style="background: transparent; color: #ef4444; border: none; font-size: 0.75rem; cursor: pointer; padding: 0.15rem 0.35rem;">Delete</button>
        `;
        
        row.querySelector('.btn-delete-strap').addEventListener('click', () => {
            saveHistoryState();
            room.customCarbonStraps = room.customCarbonStraps.filter(s => s.id !== strap.id);
            room.carbonStraps = room.customCarbonStraps.length;
            
            // Sync input Qty value
            const input = document.getElementById('room-carbon-straps-input');
            if (input) input.value = room.carbonStraps;
            
            renderCustomStrapsList(room);
            draw();
            updateGlobalStats();
            if (window.sync3D) window.sync3D();
        });
        
        listEl.appendChild(row);
    });
}

// Bind manual Add Strap click handler
document.getElementById('btn-add-custom-strap').addEventListener('click', () => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (room) {
        saveHistoryState();
        room.carbonStraps = (room.carbonStraps || 0) + 1;
        initializeCustomStraps(room);
        renderCustomStrapsList(room);
        
        // Sync input Qty value
        const input = document.getElementById('room-carbon-straps-input');
        if (input) input.value = room.carbonStraps;
        
        draw();
        updateGlobalStats();
        if (window.sync3D) window.sync3D();
    }
});

// Bind manual Auto-Space click handler
document.getElementById('btn-auto-space-straps').addEventListener('click', () => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (room) {
        saveHistoryState();
        autoSpaceCarbonStraps(room);
        renderCustomStrapsList(room);
        
        // Sync input Qty value
        const input = document.getElementById('room-carbon-straps-input');
        if (input) input.value = room.carbonStraps;
        
        draw();
        updateGlobalStats();
        if (window.sync3D) window.sync3D();
    }
});

window.changeRectWallLength = function(roomId, wallKey, newValueRaw) {
    const room = state.rooms.find(r => r.id === roomId);
    if (!room) return;
    const val = Math.max(1.0, parseFloat(newValueRaw) || 1.0);
    saveHistoryState();
    
    if (wallKey === 'n' || wallKey === 's') {
        room.w = val;
    } else if (wallKey === 'e' || wallKey === 'w') {
        room.l = val;
    }
    
    document.getElementById('room-w-input').value = room.w;
    document.getElementById('room-l-input').value = room.l;
    
    // Re-render the wall inputs list to show updated lengths
    const container = document.getElementById('custom-walls-list-container');
    if (container) {
        const wallInputs = container.querySelectorAll('input');
        if (wallInputs.length === 4) {
            wallInputs[0].value = room.w.toFixed(1);
            wallInputs[1].value = room.l.toFixed(1);
            wallInputs[2].value = room.w.toFixed(1);
            wallInputs[3].value = room.l.toFixed(1);
        }
    }
    
    updateRoomEstimates(room);
    draw();
    if (window.sync3D) window.sync3D();
};

// Room Floor Perimeter Carbon Fiber change
document.getElementById('room-floor-perimeter-strap-checkbox').addEventListener('change', (e) => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (room) {
        if (typeof saveHistoryState === 'function') saveHistoryState();
        room.floorPerimeterStrap = e.target.checked;
        draw();
        updateGlobalStats();
        updateToolboxReinforcementLabels(room);
        if (window.sync3D) window.sync3D();
    }
});

// Room NB1 Wall Coating change
document.getElementById('room-nb1-select').addEventListener('change', (e) => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (room) {
        if (typeof saveHistoryState === 'function') saveHistoryState();
        room.nb1Height = e.target.value;
        draw();
        updateGlobalStats();
        updateToolboxReinforcementLabels(room);
        if (window.sync3D) window.sync3D();
    }
});

// Room Drywall Cutting change
document.getElementById('room-drywall-select').addEventListener('change', (e) => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (room) {
        if (typeof saveHistoryState === 'function') saveHistoryState();
        room.drywallHeight = e.target.value;
        renderDrywallWallCheckboxes(room);
        draw();
        updateGlobalStats();
        updateToolboxReinforcementLabels(room);
        if (window.sync3D) window.sync3D();
    }
});

// Room Remove Attic Insulation change
document.getElementById('room-remove-insulation-checkbox').addEventListener('change', (e) => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (room) {
        if (typeof saveHistoryState === 'function') saveHistoryState();
        room.removeInsulation = e.target.checked;
        draw();
        updateGlobalStats();
        if (window.sync3D) window.sync3D();
    }
});

// Room Blow-in Attic Insulation change
document.getElementById('room-blow-insulation-checkbox').addEventListener('change', (e) => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (room) {
        if (typeof saveHistoryState === 'function') saveHistoryState();
        room.blowInInsulation = e.target.checked;
        draw();
        updateGlobalStats();
        if (window.sync3D) window.sync3D();
    }
});

// Staircase orientation change
document.getElementById('stair-orientation-select').addEventListener('change', (e) => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (room && room.type === 'staircase') {
        if (typeof saveHistoryState === 'function') saveHistoryState();
        room.stairOrientation = e.target.value;
        draw();
        if (window.sync3D) window.sync3D();
    }
});

// Staircase slope type change
document.getElementById('stair-direction-select').addEventListener('change', (e) => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (room && room.type === 'staircase') {
        if (typeof saveHistoryState === 'function') saveHistoryState();
        room.stairDirection = e.target.value;
        draw();
        if (window.sync3D) window.sync3D();
    }
});

// Stanchion listeners
document.getElementById('stanchion-name-input').addEventListener('input', (e) => {
    if (!state.selectedStanchionId) return;
    const st = state.stanchions.find(p => p.id === state.selectedStanchionId);
    if (st) {
        st.name = e.target.value;
        draw();
    }
});
document.getElementById('stanchion-type-select').addEventListener('change', (e) => {
    if (!state.selectedStanchionId) return;
    const st = state.stanchions.find(p => p.id === state.selectedStanchionId);
    if (st) {
        if (typeof saveHistoryState === 'function') saveHistoryState();
        st.type = e.target.value;
        draw();
        updateGlobalStats();
        if (window.sync3D) window.sync3D();
    }
});
document.getElementById('btn-delete-stanchion').addEventListener('click', deleteSelectedStanchion);

// Support Beam listeners
document.getElementById('beam-label-input').addEventListener('input', (e) => {
    if (!state.selectedMainBeamId) return;
    const bm = state.mainBeams.find(l => l.id === state.selectedMainBeamId);
    if (bm) {
        bm.label = e.target.value;
        draw();
    }
});
document.getElementById('beam-type-select').addEventListener('change', (e) => {
    if (!state.selectedMainBeamId) return;
    const bm = state.mainBeams.find(l => l.id === state.selectedMainBeamId);
    if (bm) {
        if (typeof saveHistoryState === 'function') saveHistoryState();
        bm.type = e.target.value;
        draw();
        if (window.sync3D) window.sync3D();
    }
});
document.getElementById('beam-len-input').addEventListener('input', (e) => {
    if (!state.selectedMainBeamId) return;
    const bm = state.mainBeams.find(l => l.id === state.selectedMainBeamId);
    const val = parseFloat(e.target.value);
    if (bm && !isNaN(val) && val > 0.1) {
        const dx = bm.x2 - bm.x1;
        const dy = bm.y2 - bm.y1;
        const currentLen = Math.sqrt(dx*dx + dy*dy);
        if (currentLen > 0.05) {
            bm.x2 = bm.x1 + (dx / currentLen) * val;
            bm.y2 = bm.y1 + (dy / currentLen) * val;
        } else {
            bm.x2 = bm.x1 + val;
        }
        bm.length = val;
        draw();
        updateGlobalStats();
        if (window.sync3D) window.sync3D();
    }
});
document.getElementById('btn-delete-beam').addEventListener('click', deleteSelectedMainBeam);
document.getElementById('btn-delete-floor-hatch').addEventListener('click', deleteSelectedFloorHatch);

document.getElementById('floor-hatch-name-input').addEventListener('input', (e) => {
    if (!state.selectedFloorHatchId) return;
    const h = state.floorHatches.find(p => p.id === state.selectedFloorHatchId);
    if (h) {
        h.name = e.target.value.trim();
        draw();
    }
});

document.getElementById('floor-hatch-width-input').addEventListener('input', (e) => {
    if (!state.selectedFloorHatchId) return;
    const h = state.floorHatches.find(p => p.id === state.selectedFloorHatchId);
    if (h) {
        h.w = Math.max(1, parseFloat(e.target.value) || 3.0);
        draw();
        if (window.sync3D) window.sync3D();
    }
});

document.getElementById('floor-hatch-length-input').addEventListener('input', (e) => {
    if (!state.selectedFloorHatchId) return;
    const h = state.floorHatches.find(p => p.id === state.selectedFloorHatchId);
    if (h) {
        h.l = Math.max(1, parseFloat(e.target.value) || 3.0);
        draw();
        if (window.sync3D) window.sync3D();
    }
});

document.getElementById('floor-hatch-target-select').addEventListener('change', (e) => {
    if (!state.selectedFloorHatchId) return;
    const h = state.floorHatches.find(p => p.id === state.selectedFloorHatchId);
    if (h) {
        h.target = e.target.value;
        draw();
        if (window.sync3D) window.sync3D();
    }
});

// Trigger presets
document.querySelectorAll('.add-room-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
        const type = btn.getAttribute('data-type');
        addRoom(type);
        if (typeof closeAllDrawers === 'function') closeAllDrawers();
    });
});

function initializeCanvasToolPlacement() {
    const tools = [];
    document.querySelectorAll('.add-room-btn').forEach(button => {
        tools.push({ button, kind: 'room', type: button.getAttribute('data-type'), label: button.textContent.trim() || 'room' });
    });
    [
        ['btn-add-sump', 'sump', 'sump pump'],
        ['btn-add-dehumidifier', 'dehumidifier', 'dehumidifier'],
        ['btn-add-discharge', 'discharge', 'discharge line'],
        ['btn-add-interior-pipe', 'interiorPipe', 'interior pipe'],
        ['btn-add-stanchion', 'stanchion', 'stanchion'],
        ['btn-add-beam', 'beam', 'support beam']
    ].forEach(definition => {
        const button = document.getElementById(definition[0]);
        if (button) tools.push({ button, kind: definition[1], type: '', label: definition[2] });
    });

    tools.forEach(tool => {
        tool.button.draggable = true;
        tool.button.classList.add('canvas-placement-tool');
        tool.button.title = `Drag onto the blueprint to place ${tool.label}`;
        tool.button.addEventListener('dragstart', event => {
            state.didDragTool = true;
            event.dataTransfer.effectAllowed = 'copy';
            event.dataTransfer.setData('application/x-roomflow-tool', JSON.stringify({ kind: tool.kind, type: tool.type, label: tool.label }));
            showCanvasPlacementHint(`Drop to place ${tool.label}`);
        });
        tool.button.addEventListener('dragend', () => {
            showCanvasPlacementHint('');
            window.setTimeout(() => { state.didDragTool = false; }, 0);
        });
        tool.button.addEventListener('click', event => {
            const mobilePlacement = window.matchMedia('(max-width: 900px), (pointer: coarse)').matches;
            if (!mobilePlacement && !state.didDragTool) return;
            event.preventDefault();
            event.stopImmediatePropagation();
            if (!state.didDragTool) beginCanvasToolPlacement({ kind: tool.kind, type: tool.type, label: tool.label });
            if (typeof closeAllDrawers === 'function') closeAllDrawers();
        }, true);
    });

    canvas.addEventListener('dragover', event => {
        if (!Array.from(event.dataTransfer.types || []).includes('application/x-roomflow-tool')) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = 'copy';
        canvas.classList.add('is-drop-target');
    });
    canvas.addEventListener('dragleave', () => canvas.classList.remove('is-drop-target'));
    canvas.addEventListener('drop', event => {
        const raw = event.dataTransfer.getData('application/x-roomflow-tool');
        canvas.classList.remove('is-drop-target');
        showCanvasPlacementHint('');
        if (!raw) return;
        event.preventDefault();
        try {
            const tool = JSON.parse(raw);
            const rect = canvas.getBoundingClientRect();
            placeCanvasTool(tool, toWorldX(event.clientX - rect.left), toWorldY(event.clientY - rect.top));
        } catch (error) {
            console.warn('Unable to place dragged tool:', error);
        }
    });
}

initializeCanvasToolPlacement();

document.getElementById('btn-add-door').addEventListener('click', () => {
    addOpening('door');
    if (typeof closeAllDrawers === 'function') closeAllDrawers();
});
document.getElementById('btn-add-window').addEventListener('click', () => {
    addOpening('window');
    if (typeof closeAllDrawers === 'function') closeAllDrawers();
});
document.getElementById('btn-add-crawl-door').addEventListener('click', () => {
    addOpening('crawl_door');
    if (typeof closeAllDrawers === 'function') closeAllDrawers();
});
document.getElementById('btn-add-hatch').addEventListener('click', () => {
    addFloorHatch();
    if (typeof closeAllDrawers === 'function') closeAllDrawers();
});

function addFloorHatch() {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (!room) return;
    
    saveHistoryState();
    
    let hx = room.x;
    let hy = room.y;
    if (room.type === 'custom' && room.vertices) {
        let sumX = 0, sumY = 0;
        room.vertices.forEach(v => {
            sumX += v.x;
            sumY += v.y;
        });
        hx += sumX / room.vertices.length;
        hy += sumY / room.vertices.length;
    } else {
        hx += room.w / 2;
        hy += room.l / 2;
    }
    
    const newHatch = {
        id: generateId(),
        name: `Hatch ${state.floorHatches.length + 1}`,
        levelId: state.currentLevelId,
        x: snap(hx),
        y: snap(hy),
        w: 3.0,
        l: 3.0,
        target: 'floor' // 'floor' or 'ceiling'
    };
    
    state.floorHatches.push(newHatch);
    selectItem('floorHatch', newHatch.id);
    draw();
    if (window.sync3D) window.sync3D();
}

function deleteSelectedFloorHatch() {
    if (!state.selectedFloorHatchId) return;
    saveHistoryState();
    state.floorHatches = state.floorHatches.filter(h => h.id !== state.selectedFloorHatchId);
    selectItem(null);
    draw();
    if (window.sync3D) window.sync3D();
}

document.getElementById('btn-add-strap').addEventListener('click', () => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (room) {
        if (typeof saveHistoryState === 'function') saveHistoryState();
        room.carbonStraps = (room.carbonStraps || 0) + 1;
        
        const strapsInput = document.getElementById('room-carbon-straps-input');
        if (strapsInput) strapsInput.value = room.carbonStraps;
        
        draw();
        updateGlobalStats();
        updateToolboxReinforcementLabels(room);
        if (window.sync3D) window.sync3D();
    }
});

document.getElementById('btn-add-perimeter-strap').addEventListener('click', () => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (room) {
        if (typeof saveHistoryState === 'function') saveHistoryState();
        room.floorPerimeterStrap = !room.floorPerimeterStrap;
        
        const floorStrapCheckbox = document.getElementById('room-floor-perimeter-strap-checkbox');
        if (floorStrapCheckbox) floorStrapCheckbox.checked = !!room.floorPerimeterStrap;
        
        draw();
        updateGlobalStats();
        updateToolboxReinforcementLabels(room);
        if (window.sync3D) window.sync3D();
    }
});

document.getElementById('btn-add-nb1').addEventListener('click', () => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (room) {
        if (typeof saveHistoryState === 'function') saveHistoryState();
        const next = { 'none': '2ft', '2ft': '4ft', '4ft': 'full', 'full': 'none' };
        room.nb1Height = next[room.nb1Height || 'none'];
        
        const nb1Select = document.getElementById('room-nb1-select');
        if (nb1Select) nb1Select.value = room.nb1Height;
        
        draw();
        updateGlobalStats();
        updateToolboxReinforcementLabels(room);
        if (window.sync3D) window.sync3D();
    }
});

document.getElementById('btn-add-drywall').addEventListener('click', () => {
    if (!state.selectedRoomId) return;
    const room = state.rooms.find(r => r.id === state.selectedRoomId);
    if (room) {
        if (typeof saveHistoryState === 'function') saveHistoryState();
        const next = { 'none': '1ft', '1ft': '2ft', '2ft': '4ft', '4ft': '6ft', '6ft': 'full', 'full': 'none' };
        room.drywallHeight = next[room.drywallHeight || 'none'];
        
        const drywallSelect = document.getElementById('room-drywall-select');
        if (drywallSelect) drywallSelect.value = room.drywallHeight;
        
        draw();
        updateGlobalStats();
        updateToolboxReinforcementLabels(room);
        if (window.sync3D) window.sync3D();
    }
});

document.getElementById('btn-delete-room').addEventListener('click', deleteSelectedRoom);

// Add Sump & Discharge actions
document.getElementById('btn-add-sump').addEventListener('click', () => {
    addSumpPump();
    if (typeof closeAllDrawers === 'function') closeAllDrawers();
});
document.getElementById('btn-add-dehumidifier').addEventListener('click', () => {
    addDehumidifier();
    if (typeof closeAllDrawers === 'function') closeAllDrawers();
});
document.getElementById('btn-add-discharge').addEventListener('click', () => {
    addDischargeLine();
    if (typeof closeAllDrawers === 'function') closeAllDrawers();
});
document.getElementById('btn-add-interior-pipe').addEventListener('click', () => {
    addInteriorPipe();
    if (typeof closeAllDrawers === 'function') closeAllDrawers();
});
document.getElementById('btn-add-stanchion').addEventListener('click', () => {
    addStanchion();
    if (typeof closeAllDrawers === 'function') closeAllDrawers();
});
document.getElementById('btn-add-beam').addEventListener('click', () => {
    addSupportBeam();
    if (typeof closeAllDrawers === 'function') closeAllDrawers();
});

// Zoom and Grid controls
document.getElementById('btn-zoom-in').addEventListener('click', () => {
    state.scale = Math.min(50, state.scale + 2);
    draw();
});
document.getElementById('btn-zoom-out').addEventListener('click', () => {
    state.scale = Math.max(5, state.scale - 2);
    draw();
});
document.getElementById('btn-zoom-reset').addEventListener('click', () => {
    state.scale = 15;
    state.offsetX = 0;
    state.offsetY = 0;
    draw();
});
document.getElementById('btn-grid-toggle').addEventListener('click', (e) => {
    state.showGrid = !state.showGrid;
    e.currentTarget.classList.toggle('active', state.showGrid);
    draw();
});

// View toggles
const btnChecklist = document.getElementById('btn-view-checklist');
const btn2D = document.getElementById('btn-view-2d');
const btn3D = document.getElementById('btn-view-3d');
const btnAR = document.getElementById('btn-view-ar');
const btnCost = document.getElementById('btn-view-cost');

const viewChecklist = document.getElementById('checklist-container');
const view2D = document.getElementById('canvas-container');
const view3D = document.getElementById('three-container');
const viewAR = document.getElementById('ar-container');
const viewCost = document.getElementById('cost-container');
const viewJobs = document.getElementById('jobs-viewport');
const viewGuided = document.getElementById('guided-container');
const viewMore = document.getElementById('more-viewport');

function switchView(viewName) {
    state.activeView = viewName;
    
    if (btnChecklist) btnChecklist.classList.toggle('active', viewName === 'checklist');
    btn2D.classList.toggle('active', viewName === '2d');
    btn3D.classList.toggle('active', viewName === '3d');
    btnAR.classList.toggle('active', viewName === 'ar');
    if (btnCost) btnCost.classList.toggle('active', viewName === 'cost');
    
    if (viewChecklist) viewChecklist.classList.toggle('active', viewName === 'checklist');
    view2D.classList.toggle('active', viewName === '2d');
    view3D.classList.toggle('active', viewName === '3d');
    viewAR.classList.toggle('active', viewName === 'ar');
    if (viewCost) viewCost.classList.toggle('active', viewName === 'cost');
    if (viewJobs) viewJobs.classList.toggle('active', viewName === 'jobs');
    if (viewGuided) viewGuided.classList.toggle('active', viewName === 'guided');
    if (viewMore) viewMore.classList.toggle('active', viewName === 'more');

    // Toggle AR transparency controls & solid overlays
    const appContainer = document.getElementById('app-container');
    const viewportContainer = document.querySelector('.viewport-container');
    if (viewName === 'ar') {
        if (appContainer) appContainer.classList.add('ar-mode-active');
        document.body.style.backgroundColor = 'transparent';
        if (viewportContainer) viewportContainer.style.backgroundColor = 'transparent';
    } else {
        if (appContainer) appContainer.classList.remove('ar-mode-active');
        document.body.style.backgroundColor = '';
        if (viewportContainer) viewportContainer.style.backgroundColor = '';
    }

    // Toggle cost mode sidebar hiding class
    const appBody = document.querySelector('.app-body');
    if (appBody) {
        appBody.classList.toggle('cost-mode-active', viewName === 'cost' || viewName === 'checklist');
    }

    // Hide tools & details float buttons on non-canvas views to keep UI clean
    const mobileToggleTools = document.getElementById('mobile-toggle-tools');
    const mobileToggleDetails = document.getElementById('mobile-toggle-details');
    const mobileToggleChecklist = document.getElementById('mobile-toggle-checklist');
    const showFloatingToggles = (viewName === '2d' || viewName === '3d');
    if (mobileToggleTools) mobileToggleTools.style.display = showFloatingToggles ? '' : 'none';
    if (mobileToggleDetails) mobileToggleDetails.style.display = showFloatingToggles ? '' : 'none';
    if (mobileToggleChecklist) mobileToggleChecklist.style.display = showFloatingToggles ? '' : 'none';

    if (viewName === 'ar') {
        if (window.startCamera) window.startCamera();
    } else {
        if (window.stopCamera) window.stopCamera();
    }

    if (viewName === '3d') {
        if (window.resizeRenderer) window.resizeRenderer();
        if (window.sync3D) window.sync3D();
    }

    if (viewName === '2d') {
        resizeCanvas();
    }

    if (viewName === 'cost') {
        if (window.renderCostUI) window.renderCostUI();
    }
    
    if (viewName === 'checklist') {
        if (window.renderChecklistUI) window.renderChecklistUI();
    }
}

if (btnChecklist) btnChecklist.addEventListener('click', () => switchView('checklist'));
btn2D.addEventListener('click', () => switchView('2d'));
btn3D.addEventListener('click', () => switchView('3d'));
btnAR.addEventListener('click', () => switchView('ar'));
if (btnCost) btnCost.addEventListener('click', () => switchView('cost'));

// Save/Load/Export Actions
document.getElementById('btn-new').addEventListener('click', () => {
    if (confirm('Clear project?')) {
        state.rooms = [];
        state.sumpPumps = [];
        state.dehumidifiers = [];
        state.dischargeLines = [];
        state.floorHatches = [];
        state.interiorPipes = [];
        state.stanchions = [];
        state.mainBeams = [];
        state.capturedMeasurements = [];
        selectItem(null);
        draw();
        updateGlobalStats();
        if (window.sync3D) window.sync3D();
    }
});

document.getElementById('btn-save').addEventListener('click', () => {
    const projectData = {
        customerName: document.getElementById('customer-name').value,
        customerAddress: document.getElementById('customer-address').value,
        rooms: state.rooms,
        sumpPumps: state.sumpPumps,
        dehumidifiers: state.dehumidifiers || [],
        dischargeLines: state.dischargeLines,
        floorHatches: state.floorHatches || [],
        interiorPipes: state.interiorPipes || [],
        stanchions: state.stanchions || [],
        mainBeams: state.mainBeams || [],
        currentLevelId: state.currentLevelId,
        capturedMeasurements: state.capturedMeasurements || [],
        costing: state.costing
    };
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(projectData, null, 2));
    const dlAnchorElem = document.createElement('a');
    dlAnchorElem.setAttribute("href", dataStr);
    dlAnchorElem.setAttribute("download", "roomflow_project.json");
    dlAnchorElem.click();
});

document.getElementById('btn-load').addEventListener('click', () => {
    document.getElementById('file-input').click();
});

// Level selector change listener
document.getElementById('level-select').addEventListener('change', (e) => {
    state.currentLevelId = e.target.value;
    selectItem(null);
    draw();
    updateGlobalStats();
    if (window.sync3D) window.sync3D();
    updateHistoryButtons();
});

document.getElementById('file-input').addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    
    const reader = new FileReader();
    reader.onload = function(evt) {
        try {
            const data = JSON.parse(evt.target.result);
            if (data && (data.rooms || Array.isArray(data))) {
                state.rooms = Array.isArray(data) ? data : (data.rooms || []);
                state.sumpPumps = data.sumpPumps || [];
                state.dehumidifiers = data.dehumidifiers || [];
                state.dischargeLines = data.dischargeLines || [];
                state.floorHatches = data.floorHatches || [];
                state.interiorPipes = data.interiorPipes || [];
                state.stanchions = data.stanchions || [];
                state.mainBeams = data.mainBeams || [];
                state.currentLevelId = data.currentLevelId || 'basement';
                state.capturedMeasurements = data.capturedMeasurements || [];
                
                // Load costing system
                state.costing = data.costing || null;
                initDefaultCosting(state);
                
                state.rooms.forEach(r => {
                    if (!r.levelId) r.levelId = 'basement';
                    if (r.carbonStraps === undefined) r.carbonStraps = 0;
                    if (r.floorPerimeterStrap === undefined) r.floorPerimeterStrap = false;
                    if (r.nb1Height === undefined) r.nb1Height = 'none';
                    if (r.drywallHeight === undefined) r.drywallHeight = 'none';
                    if (r.foamBondPockets === undefined) r.foamBondPockets = false;
                    if (r.removeInsulation === undefined) r.removeInsulation = false;
                    if (r.blowInInsulation === undefined) r.blowInInsulation = false;
                });
                
                if (state.dehumidifiers) {
                    state.dehumidifiers.forEach(dh => {
                        if (!dh.levelId) dh.levelId = 'basement';
                    });
                }
                
                // Sync UI level select dropdown
                const lvlSelect = document.getElementById('level-select');
                if (lvlSelect) lvlSelect.value = state.currentLevelId;
                
                document.getElementById('customer-name').value = data.customerName || '';
                document.getElementById('customer-address').value = data.customerAddress || '';
                selectItem(null);
                draw();
                updateGlobalStats();
                updateMeasurementsSidebar();
                
                // Rerender costing UI if active
                if (window.renderCostUI) window.renderCostUI();
                
                if (window.sync3D) window.sync3D();
                alert('Project loaded.');
            } else {
                alert('Invalid file format.');
            }
        } catch (err) {
            alert('Failed to parse project file.');
        }
    };
    reader.readAsText(file);
});

// Auto-focus layout viewport to fit canvas perfectly for printing
function fitLayoutToCanvas() {
    if (state.rooms.length === 0 && state.sumpPumps.length === 0 && state.dischargeLines.length === 0) {
        return { scale: state.scale, offsetX: state.offsetX, offsetY: state.offsetY };
    }
    
    let minX = Infinity, maxX = -Infinity;
    let minY = Infinity, maxY = -Infinity;
    
    // Compute bounds across all rooms
    state.rooms.forEach(room => {
        if (room.type === 'custom' && room.vertices) {
            room.vertices.forEach(v => {
                const wx = room.x + v.x;
                const wy = room.y + v.y;
                if (wx < minX) minX = wx;
                if (wx > maxX) maxX = wx;
                if (wy < minY) minY = wy;
                if (wy > maxY) maxY = wy;
            });
        } else {
            if (room.x < minX) minX = room.x;
            if (room.x + room.w > maxX) maxX = room.x + room.w;
            if (room.y < minY) minY = room.y;
            if (room.y + room.l > maxY) maxY = room.y + room.l;
        }
    });
    
    // Compute bounds across all sump pumps
    state.sumpPumps.forEach(pump => {
        if (pump.x < minX) minX = pump.x;
        if (pump.x > maxX) maxX = pump.x;
        if (pump.y < minY) minY = pump.y;
        if (pump.y > maxY) maxY = pump.y;
    });
    
    // Compute bounds across all discharge lines
    state.dischargeLines.forEach(line => {
        if (line.x1 < minX) minX = line.x1;
        if (line.x1 > maxX) maxX = line.x1;
        if (line.x2 < minX) minX = line.x2;
        if (line.x2 > maxX) maxX = line.x2;
        
        if (line.y1 < minY) minY = line.y1;
        if (line.y1 > maxY) maxY = line.y1;
        if (line.y2 < minY) minY = line.y2;
        if (line.y2 > maxY) maxY = line.y2;
    });
    
    const layoutW = maxX - minX;
    const layoutH = maxY - minY;
    
    // Add a uniform margin of 3 grid units (3 feet) on each side
    const padding = 3;
    const boxX = minX - padding;
    const boxY = minY - padding;
    const boxW = layoutW + padding * 2;
    const boxH = layoutH + padding * 2;
    
    const originalScale = state.scale;
    const originalOffsetX = state.offsetX;
    const originalOffsetY = state.offsetY;
    
    // Compute scale factor
    const scaleX = canvas.width / boxW;
    const scaleY = canvas.height / boxH;
    const fitScale = Math.min(scaleX, scaleY);
    
    state.scale = Math.max(5, Math.min(45, fitScale));
    
    // Compute panning offset to center the layout box
    const boxCenterX = boxX + boxW / 2;
    const boxCenterY = boxY + boxH / 2;
    
    state.offsetX = -boxCenterX * state.scale;
    state.offsetY = -boxCenterY * state.scale;
    
    return { scale: originalScale, offsetX: originalOffsetX, offsetY: originalOffsetY };
}

// PDF / HTML Print Layout
document.getElementById('btn-export-pdf').addEventListener('click', () => {
    // Save current selections
    const oldSelRoom = state.selectedRoomId;
    const oldSelSump = state.selectedSumpPumpId;
    const oldSelDischarge = state.selectedDischargeLineId;
    
    // Temporarily clear selections for high-fidelity export
    state.selectedRoomId = null;
    state.selectedSumpPumpId = null;
    state.selectedDischargeLineId = null;
    
    // Automatically focus layout scale and center view on the canvas
    const originalView = fitLayoutToCanvas();
    
    // Draw with solid print background, then grab image URL
    draw(true);
    const layoutImage = canvas.toDataURL('image/png');
    
    // Grab 3D screenshot
    const screenshot3D = (typeof window.get3DScreenshot === 'function') ? window.get3DScreenshot() : null;
    
    // Restore original viewport settings
    state.scale = originalView.scale;
    state.offsetX = originalView.offsetX;
    state.offsetY = originalView.offsetY;
    
    // Restore selections
    state.selectedRoomId = oldSelRoom;
    state.selectedSumpPumpId = oldSelSump;
    state.selectedDischargeLineId = oldSelDischarge;
    
    // Redraw normal view
    draw(false);

    // Build the sanitized customer export model
    const customerModel = buildCustomerExportModel(state);
    
    const cName = customerModel.customerName;
    const cAddress = customerModel.customerAddress;
    const q = customerModel.quantities;

    let roomRows = '';
    let grandFloor = 0, grandWall = 0, grandCeiling = 0, grandVolume = 0;
    
    customerModel.rooms.forEach(room => {
        let floorArea, perimeter;
        if (room.type === 'custom' && room.vertices && room.vertices.length >= 3) {
            floorArea = getPolygonArea(room.vertices);
            perimeter = getPolygonPerimeter(room.vertices);
        } else {
            floorArea = room.w * room.l;
            perimeter = 2 * (room.w + room.l);
        }
        const ceilingArea = floorArea;
        const volume = room.type === 'staircase' ? 0.5 * floorArea * room.h : floorArea * room.h;
        
        let grossWallArea;
        if (room.type === 'staircase') {
            grossWallArea = (room.l * room.h) + (room.w * room.h);
        } else {
            grossWallArea = perimeter * room.h;
        }
        
        let deductions = 0;
        room.openings.forEach(op => { deductions += op.w * op.h; });
        const netWallArea = Math.max(0, grossWallArea - deductions);

        grandFloor += floorArea;
        grandWall += netWallArea;
        grandCeiling += ceilingArea;
        grandVolume += volume;

        let openingsStr = room.openings.map(o => `${o.type.toUpperCase()} (on ${o.wall.toUpperCase()}, ${o.w}'x${o.h}')`).join(', ') || 'None';

        roomRows += `
            <tr>
                <td><strong>${room.name}</strong></td>
                <td>${room.w}' x ${room.l}' x ${room.h}'</td>
                <td>${floorArea.toFixed(1)} sq ft</td>
                <td>${netWallArea.toFixed(1)} sq ft <br><small>Openings: ${openingsStr}</small></td>
                <td>${ceilingArea.toFixed(1)} sq ft</td>
                <td>${volume.toFixed(1)} cu ft</td>
            </tr>
        `;
    });

    let sumpRows = '';
    customerModel.sumpPumps.forEach((sp, idx) => {
        sumpRows += `
            <tr>
                <td>${idx + 1}</td>
                <td><strong>${sp.name}</strong></td>
                <td>Position: X: ${sp.x.toFixed(1)} ft, Y: ${sp.y.toFixed(1)} ft</td>
            </tr>
        `;
    });
    if (customerModel.sumpPumps.length === 0) {
        sumpRows = '<tr><td colspan="3" style="text-align:center; color:#9ca3af;">No sump pumps placed</td></tr>';
    }

    let lineRows = '';
    let totalLen = 0;
    customerModel.dischargeLines.forEach((dl, idx) => {
        totalLen += dl.length;
        lineRows += `
            <tr>
                <td>${idx + 1}</td>
                <td><strong>${dl.label}</strong></td>
                <td>${dl.length.toFixed(1)} ft</td>
                <td>Start (X: ${dl.x1.toFixed(1)}, Y: ${dl.y1.toFixed(1)}), End (X: ${dl.x2.toFixed(1)}, Y: ${dl.y2.toFixed(1)})</td>
            </tr>
        `;
    });
    if (customerModel.dischargeLines.length === 0) {
        lineRows = '<tr><td colspan="4" style="text-align:center; color:#9ca3af;">No discharge lines placed</td></tr>';
    }

    const htmlContent = `
        <html>
        <head>
            <title>RoomFlow - Estimation Report</title>
            <style>
                body { font-family: 'Outfit', sans-serif; padding: 40px; color: #111827; line-height: 1.5; }
                h1 { color: #1e3a8a; border-bottom: 2px solid #3b82f6; padding-bottom: 10px; margin-top: 40px; margin-bottom: 30px; }
                h2 { color: #1e3a8a; font-size: 1.25rem; margin-top: 30px; border-bottom: 1px solid #e5e7eb; padding-bottom: 5px; }
                .meta-info { display: flex; justify-content: space-between; margin-bottom: 30px; font-size: 0.9rem; color: #4b5563; }
                table { width: 100%; border-collapse: collapse; margin-top: 15px; margin-bottom: 30px; }
                th, td { padding: 12px; text-align: left; border-bottom: 1px solid #e5e7eb; }
                th { background-color: #f3f4f6; color: #1e3a8a; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; }
                tr.totals { font-weight: 700; background-color: #eff6ff; }
                .layout-preview { text-align: center; margin-bottom: 20px; border: 1px dashed #cbd5e1; border-radius: 8px; padding: 10px; background-color: #ffffff; }
                .layout-preview img { max-width: 100%; max-height: 260px; object-fit: contain; }
                .footer { margin-top: 30px; text-align: center; font-size: 0.8rem; color: #9ca3af; border-top: 1px solid #e5e7eb; padding-top: 15px; }
                @media print {
                    button { display: none; }
                    body { padding: 15px; margin: 0; }
                    .page-break { page-break-before: always; break-before: page; }
                    * {
                        -webkit-print-color-adjust: exact !important;
                        print-color-adjust: exact !important;
                    }
                }
                .print-btn { background-color: #3b82f6; color: white; padding: 10px 20px; border: none; border-radius: 6px; font-size: 1rem; cursor: pointer; float: right; }
                .print-btn:hover { background-color: #2563eb; }
            </style>
        </head>
        <body>
            <button class="print-btn" onclick="window.print()">Print Estimate Report</button>
            <h1>RoomFlow - Structural Estimation Report</h1>
            <div class="meta-info">
                <div>
                    <strong>Date:</strong> ${new Date().toLocaleDateString()}<br>
                    <strong>Customer:</strong> ${cName}<br>
                    <strong>Address:</strong> ${cAddress}
                </div>
            </div>

            <h2>1. 2D Floor Plan Blueprint</h2>
            <div class="layout-preview 2d-preview" style="margin-bottom: 0;">
                <img src="${layoutImage}" alt="2D Floor Plan Blueprint" style="max-height: 500px;">
            </div>

            <div class="page-break"></div>

            ${screenshot3D ? `
            <h2>2. 3D Model Render Preview</h2>
            <div class="layout-preview 3d-preview" style="margin-bottom: 20px;">
                <img src="${screenshot3D}" alt="3D Model Render Preview" style="max-height: 380px;">
            </div>
            ` : ''}

            <h2>Blueprint Symbol & Material Legend</h2>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; margin-top: 15px; margin-bottom: 30px; font-size: 0.85rem; line-height: 1.4; color: #334155;">
                <div style="display: flex; align-items: center; gap: 12px;">
                    <svg width="30" height="6" style="flex-shrink: 0; display: block;"><rect width="30" height="6" fill="#0f172a" rx="2"/></svg>
                    <div><strong>Vertical Carbon Fiber Straps:</strong> Black tick marks along wall edges indicating vertical reinforcement strap points.</div>
                </div>
                <div style="display: flex; align-items: center; gap: 12px;">
                    <svg width="30" height="6" style="flex-shrink: 0; display: block;"><rect width="30" height="6" fill="#38bdf8" rx="2"/></svg>
                    <div><strong>Floor Perimeter Strap:</strong> Sky blue lines indicating horizontal stabilization carbon strap.</div>
                </div>
                <div style="display: flex; align-items: center; gap: 12px;">
                    <svg width="30" height="6" style="flex-shrink: 0; display: block;"><rect width="30" height="6" fill="#f472b6" rx="2"/></svg>
                    <div><strong>XPS Foam Board (Insulation):</strong> Pink line highlights indicating wall insulation sheets on exterior walls.</div>
                </div>
                <div style="display: flex; align-items: center; gap: 12px;">
                    <svg width="30" height="6" style="flex-shrink: 0; display: block;"><rect width="30" height="6" fill="#a855f7" rx="2"/></svg>
                    <div><strong>NB1 Wall Coating:</strong> Purple highlighting in 3D representing waterproofing and structural cementitious wall coating.</div>
                </div>
                <div style="display: flex; align-items: center; gap: 12px;">
                    <svg width="14" height="14" style="flex-shrink: 0; display: block;"><circle cx="7" cy="7" r="7" fill="#10b981"/></svg>
                    <div><strong>Sump Pump Basin:</strong> Green circular icons indicating plotted sump pump water extraction locations.</div>
                </div>
                <div style="display: flex; align-items: center; gap: 12px;">
                    <svg width="30" height="3" style="flex-shrink: 0; display: block;"><line x1="0" y1="1.5" x2="30" y2="1.5" stroke="#94a3b8" stroke-width="3" stroke-dasharray="4,3"/></svg>
                    <div><strong>Utility Discharge Lines:</strong> Dashed grey lines showing drain tile pipe routing.</div>
                </div>
            </div>

            <div class="page-break"></div>

            <h2>3. Rooms & Structural Elements</h2>
            <table>
                <thead>
                    <tr>
                        <th>Room Name</th>
                        <th>Dimensions (W x L x H)</th>
                        <th>Floor Area</th>
                        <th>Wall Area (Net)</th>
                        <th>Ceiling Area</th>
                        <th>Volume</th>
                    </tr>
                </thead>
                <tbody>
                    ${roomRows}
                    <tr class="totals">
                        <td>GRAND TOTALS</td>
                        <td>-</td>
                        <td>${grandFloor.toFixed(1)} sq ft</td>
                        <td>${grandWall.toFixed(1)} sq ft</td>
                        <td>${grandCeiling.toFixed(1)} sq ft</td>
                        <td>${grandVolume.toFixed(1)} cu ft</td>
                    </tr>
                </tbody>
            </table>

            <h2>4. Utility Sump Pumps</h2>
            <table>
                <thead>
                    <tr>
                        <th style="width: 80px;">Index</th>
                        <th>Label</th>
                        <th>Plotted Location</th>
                    </tr>
                </thead>
                <tbody>
                    ${sumpRows}
                </tbody>
            </table>

            <h2>5. Utility Discharge Lines (Drain Tile)</h2>
            <table>
                <thead>
                    <tr>
                        <th style="width: 80px;">Index</th>
                        <th>Label</th>
                        <th>Measured Length</th>
                        <th>Piping Coordinates</th>
                    </tr>
                </thead>
                <tbody>
                    ${lineRows}
                    <tr class="totals">
                        <td>TOTAL</td>
                        <td>-</td>
                        <td>${totalLen.toFixed(1)} ft</td>
                        <td>-</td>
                    </tr>
                </tbody>
            </table>

            <h2>6. Project Bill of Materials (BOM) & Estimates</h2>
            <table>
                <thead>
                    <tr>
                        <th>Material Item</th>
                        <th>Estimated Quantity</th>
                        <th>Coverage / Spec Info</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><strong>2" XPS Foam Board Sheets (4' x 8')</strong></td>
                        <td>${q.xpsSheets} sheets</td>
                        <td>Exposed exterior wall surfaces (minus openings)</td>
                    </tr>
                    <tr>
                        <td><strong>10ft PVC Pipe Sticks</strong></td>
                        <td>${q.pvcSticks} sticks</td>
                        <td>Overhead run + Sump riser runs (excludes discharge drain tile)</td>
                    </tr>
                    <tr>
                        <td><strong>90° PVC Elbow fittings</strong></td>
                        <td>${q.pvc90s} pcs</td>
                        <td>Orthogonal turns and Sump riser transitions</td>
                    </tr>
                    <tr>
                        <td><strong>45° PVC Elbow fittings</strong></td>
                        <td>${q.pvc45s} pcs</td>
                        <td>Snapping offset angle connections</td>
                    </tr>
                    <tr>
                        <td><strong>Drain Tile (Discharge)</strong></td>
                        <td>${q.drainTile.toFixed(1)} ft</td>
                        <td>Flexible drain tile used for horizontal discharge lines</td>
                    </tr>
                    <tr>
                        <td><strong>Carbon Fiber Straps</strong></td>
                        <td>${q.carbonFiberLen.toFixed(1)} ft</td>
                        <td>Vertical reinforcement and/or floor perimeter reinforcement</td>
                    </tr>
                    <tr>
                        <td><strong>NB1 Wall Coating</strong></td>
                        <td>${q.nb1Bags} bags (${q.nb1Area.toFixed(0)} sq ft)</td>
                        <td>Cementitious waterproofing/reinforcement wall coating</td>
                    </tr>
                    ${q.drywallCutArea > 0 ? `
                    <tr>
                        <td><strong>Drywall Cutting</strong></td>
                        <td>${q.drywallCutArea.toFixed(0)} sq ft</td>
                        <td>Drywall cut and removal at specified height</td>
                    </tr>
                    ` : ''}
                    ${q.sprayFoamCans > 0 ? `
                    <tr>
                        <td><strong>Spray Foam Cans</strong></td>
                        <td>${q.sprayFoamCans} cans</td>
                        <td>Rim joist / bond pockets insulation (1 can covers 20 board feet)</td>
                    </tr>
                    ` : ''}
                    ${q.sumpFittings.bushing3to2 > 0 ? `
                    <tr>
                        <td><strong>3" to 2" Bushing</strong></td>
                        <td>${q.sumpFittings.bushing3to2} pcs</td>
                        <td>Sump pump discharge connection</td>
                    </tr>
                    ` : ''}
                    ${q.sumpFittings.tee3x3x2 > 0 ? `
                    <tr>
                        <td><strong>3" x 3" x 2" T-Fitting</strong></td>
                        <td>${q.sumpFittings.tee3x3x2} pcs</td>
                        <td>Sump pump discharge connection</td>
                    </tr>
                    ` : ''}
                    ${q.sumpFittings.elbow3in90 > 0 ? `
                    <tr>
                        <td><strong>3" 90° PVC Elbow</strong></td>
                        <td>${q.sumpFittings.elbow3in90} pcs</td>
                        <td>Sump pump discharge connection</td>
                    </tr>
                    ` : ''}
                    ${q.sumpFittings.screwAdapter1_5 > 0 ? `
                    <tr>
                        <td><strong>1-1/2" Screw Adapter</strong></td>
                        <td>${q.sumpFittings.screwAdapter1_5} pcs</td>
                        <td>Sump pump connection adapter</td>
                    </tr>
                    ` : ''}
                    ${q.sumpFittings.checkValve2 > 0 ? `
                    <tr>
                        <td><strong>2" PVC Check Valve</strong></td>
                        <td>${q.sumpFittings.checkValve2} pcs</td>
                        <td>Prevents backflow into the sump pump basin</td>
                    </tr>
                    ` : ''}
                    ${q.sumpFittings.yFitting2 > 0 ? `
                    <tr>
                        <td><strong>2" PVC Y-Fitting</strong></td>
                        <td>${q.sumpFittings.yFitting2} pcs</td>
                        <td>Sump pump discharge assembly</td>
                    </tr>
                    ` : ''}
                    <tr class="totals">
                        <td>Vapor Barrier Liner Area</td>
                        <td>${q.vaporLinerArea.toFixed(0)} sq ft</td>
                        <td>Total floor, wall, and stanchion column surface coverage</td>
                    </tr>
                </tbody>
            </table>

            <div class="footer">
                Report generated via RoomFlow Sketcher. All measurements are estimates.
            </div>
        </body>
        </html>
    `;

    // Run development safety check to scan for leaking costing terms
    const safetyCheck = scanCustomerReportForPricingData(htmlContent);
    if (!safetyCheck.safe) {
        alert("DEVELOPER ERROR: Prohibited costing term '" + safetyCheck.offendingTerm + "' detected in customer report! Export blocked.");
        throw new Error("DEVELOPER EXPORT SECURITY ALERT: Costing leak detected for term: " + safetyCheck.offendingTerm);
    }

    const printWindow = window.open('', '_blank');
    printWindow.document.write(htmlContent);
    printWindow.document.close();
});

// --- PRINTING & EXPORTS ---
function printInternalCostSheet() {
    const costEl = document.getElementById('cost-container');
    if (!costEl) return;
    
    // Create a printable clone of the costing workspace
    const clone = costEl.cloneNode(true);
    
    // Replace all inputs with text nodes or spans for clean printing
    clone.querySelectorAll('input, select, textarea').forEach(inp => {
        const span = document.createElement('span');
        span.className = 'print-input-val';
        if (inp.type === 'checkbox') {
            span.innerText = inp.checked ? '[X]' : '[ ]';
        } else {
            span.innerText = inp.value;
        }
        inp.parentNode.replaceChild(span, inp);
    });
    
    // Hide action buttons and controls
    clone.querySelectorAll('button, .cost-header-actions, .cat-item-active, .treatment-sel').forEach(btn => {
        btn.style.display = 'none';
    });
    
    const htmlContent = `
        <html>
        <head>
            <title>RoomFlow - Internal Estimating & Costing Sheet</title>
            <style>
                body { font-family: 'Outfit', sans-serif; padding: 30px; color: #111827; background: #ffffff; line-height: 1.4; }
                h2 { color: #1e3a8a; border-bottom: 2px solid #3b82f6; padding-bottom: 8px; margin-bottom: 20px; }
                table { width: 100%; border-collapse: collapse; margin-top: 10px; margin-bottom: 20px; font-size: 0.85rem; }
                th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid #e2e8f0; }
                th { background-color: #f1f5f9; color: #1e3a8a; font-weight: 600; }
                .print-input-val { font-weight: 600; color: #0f172a; }
                .cost-summary-card { background: #f8fafc; border: 1px solid #e2e8f0; padding: 15px; border-radius: 8px; margin-top: 20px; }
                .summary-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px dashed #e2e8f0; font-size: 0.9rem; }
                .summary-row.total { font-weight: 700; border-bottom: none; font-size: 1.1rem; color: #1e3a8a; }
                @media print {
                    button { display: none; }
                    body { padding: 10px; }
                }
            </style>
        </head>
        <body>
            <button onclick="window.print()" style="float:right; padding:8px 16px; background:#3b82f6; color:white; border:none; border-radius:4px; cursor:pointer;">Print Page</button>
            <h2>RoomFlow - Internal Job Estimating & Costing Sheet</h2>
            <div style="margin-bottom:20px; font-size:0.9rem; color:#4b5563;">
                <strong>Date:</strong> ${new Date().toLocaleDateString()}<br>
                <strong>Customer Name:</strong> ${document.getElementById('customer-name').value || 'Not Specified'}<br>
                <strong>Customer Address:</strong> ${document.getElementById('customer-address').value || 'Not Specified'}
            </div>
            ${clone.innerHTML}
        </body>
        </html>
    `;
    
    const printWindow = window.open('', '_blank');
    printWindow.document.write(htmlContent);
    printWindow.document.close();
}

function printCustomerProposal() {
    if (window.RoomFlowDocuments && typeof window.RoomFlowDocuments.print === 'function') {
        window.RoomFlowDocuments.print('proposal');
        return;
    }
    // Save current selections
    const oldSelRoom = state.selectedRoomId;
    const oldSelSump = state.selectedSumpPumpId;
    const oldSelDischarge = state.selectedDischargeLineId;
    
    // Temporarily clear selections for high-fidelity export
    state.selectedRoomId = null;
    state.selectedSumpPumpId = null;
    state.selectedDischargeLineId = null;
    
    // Automatically focus layout scale and center view on the canvas
    const originalView = fitLayoutToCanvas();
    
    // Draw with solid print background, then grab image URL
    draw(true);
    const layoutImage = canvas.toDataURL('image/png');
    
    // Grab 3D screenshot
    const screenshot3D = (typeof window.get3DScreenshot === 'function') ? window.get3DScreenshot() : null;
    
    // Restore original viewport settings
    state.scale = originalView.scale;
    state.offsetX = originalView.offsetX;
    state.offsetY = originalView.offsetY;
    
    // Restore selections
    state.selectedRoomId = oldSelRoom;
    state.selectedSumpPumpId = oldSelSump;
    state.selectedDischargeLineId = oldSelDischarge;
    
    // Redraw normal view
    draw(false);

    // Calculate costs
    const catalog = RoomFlowCatalog.loadCatalog();
    const report = calculateProjectCosts(state, catalog);
    const totalSellingPrice = report.subtotals.sellingPrice;
    
    // Build list of active items to price
    const proposalItems = [];
    let sumOtherRawCosts = 0;
    let dehumFlatTotal = 0;
    
    // Add regular catalog items
    Object.keys(report.items).forEach(id => {
        const item = report.items[id];
        if (item.purchaseQty > 0 && !item.excluded) {
            const isDehum = id === 'permanent_dehumidifier';
            const itemObj = {
                id: id,
                name: item.data.name,
                notes: item.data.notes,
                qty: item.purchaseQty,
                unit: item.data.purchaseUnit,
                rawCost: item.cost,
                isDehum: isDehum
            };
            proposalItems.push(itemObj);
            if (isDehum) {
                dehumFlatTotal += item.purchaseQty * 2000.00;
            } else {
                sumOtherRawCosts += item.cost;
            }
        }
    });
    
    // Add custom items
    if (state.costing && Array.isArray(state.costing.customItems)) {
        state.costing.customItems.forEach(item => {
            const qty = Math.max(0, parseFloat(item.qty) || 0);
            if (qty > 0) {
                const cost = Math.max(0, parseFloat(item.unitCost) || 0);
                const waste = 1 + (Math.max(0, parseFloat(item.waste) || 0) / 100);
                const baseCost = qty * cost * waste;
                
                const lHours = Math.max(0, parseFloat(item.laborHours) || 0);
                const lRate = Math.max(0, parseFloat(item.laborRate) || 0);
                const itemLaborCost = lHours * lRate;
                const totalItemCost = baseCost + itemLaborCost;
                
                proposalItems.push({
                    id: 'custom_' + Math.random(),
                    name: item.name || 'Custom Item',
                    notes: item.notes || 'Custom contractor line item',
                    qty: qty,
                    unit: item.unit || 'pcs',
                    rawCost: totalItemCost,
                    isDehum: false
                });
                sumOtherRawCosts += totalItemCost;
            }
        });
    }

    // Distribute labor and markup proportionally over other items
    const remainingTotal = Math.max(0, totalSellingPrice - dehumFlatTotal);
    const multiplier = sumOtherRawCosts > 0 ? (remainingTotal / sumOtherRawCosts) : 1;
    
    let itemsRows = '';
    if (proposalItems.length > 0) {
        proposalItems.forEach(item => {
            let customerTotal, customerUnitPrice;
            if (item.isDehum) {
                customerTotal = item.qty * 2000.00;
                customerUnitPrice = 2000.00;
            } else {
                customerTotal = item.rawCost * multiplier;
                customerUnitPrice = customerTotal / item.qty;
            }
            itemsRows += `
                <tr>
                    <td><strong>${item.name}</strong><br><small style="color:#64748b;">${item.notes}</small></td>
                    <td>${item.qty} ${item.unit}</td>
                    <td>$${customerUnitPrice.toFixed(2)}</td>
                    <td><strong>$${customerTotal.toFixed(2)}</strong></td>
                </tr>
            `;
        });
    } else {
        // Fallback for labor-only or empty projects
        itemsRows = `
            <tr>
                <td><strong>Waterproofing / Restoration Structural Services</strong><br><small style="color:#64748b;">Comprehensive labor, equipment, and structural layout installation</small></td>
                <td>1 job</td>
                <td>$${totalSellingPrice.toFixed(2)}</td>
                <td><strong>$${totalSellingPrice.toFixed(2)}</strong></td>
            </tr>
        `;
    }

    const cName = document.getElementById('customer-name').value || 'Not Specified';
    const cAddress = document.getElementById('customer-address').value || 'Not Specified';

    const htmlContent = `
        <html>
        <head>
            <title>RoomFlow - Customer Estimating Proposal</title>
            <style>
                body { font-family: 'Outfit', sans-serif; padding: 40px; color: #111827; line-height: 1.5; background: #ffffff; }
                h1 { color: #1e3a8a; border-bottom: 2px solid #3b82f6; padding-bottom: 10px; margin-top: 20px; margin-bottom: 30px; }
                h2 { color: #1e3a8a; font-size: 1.25rem; margin-top: 35px; border-bottom: 1px solid #e5e7eb; padding-bottom: 5px; }
                .meta-info { display: flex; justify-content: space-between; margin-bottom: 30px; font-size: 0.95rem; color: #374151; }
                table { width: 100%; border-collapse: collapse; margin-top: 15px; margin-bottom: 35px; }
                th, td { padding: 12px; text-align: left; border-bottom: 1px solid #e5e7eb; }
                th { background-color: #f8fafc; color: #1e3a8a; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; }
                tr.totals { font-weight: 700; background-color: #eff6ff; font-size: 1.1rem; color: #1e3a8a; }
                .layout-preview { text-align: center; margin-bottom: 20px; border: 1px dashed #cbd5e1; border-radius: 8px; padding: 10px; background-color: #ffffff; }
                .layout-preview img { max-width: 100%; max-height: 260px; object-fit: contain; }
                .footer { margin-top: 40px; text-align: center; font-size: 0.8rem; color: #9ca3af; border-top: 1px solid #e5e7eb; padding-top: 15px; }
                @media print {
                    button { display: none; }
                    body { padding: 15px; margin: 0; }
                    .page-break { page-break-before: always; break-before: page; }
                    * {
                        -webkit-print-color-adjust: exact !important;
                        print-color-adjust: exact !important;
                    }
                }
                .print-btn { background-color: #14b8a6; color: white; padding: 10px 20px; border: none; border-radius: 6px; font-size: 1rem; cursor: pointer; float: right; font-weight: 600; }
                .print-btn:hover { background-color: #0d9488; }
            </style>
        </head>
        <body>
            <button class="print-btn" onclick="window.print()">Print Pricing Proposal</button>
            <h1>Waterproofing & Structural Proposal</h1>
            <div class="meta-info">
                <div>
                    <strong>Date:</strong> ${new Date().toLocaleDateString()}<br>
                    <strong>Prepared For:</strong> ${cName}<br>
                    <strong>Project Site Address:</strong> ${cAddress}
                </div>
            </div>

            <h2>Project Blueprint Layout</h2>
            <div class="layout-preview 2d-preview" style="margin-bottom: 0;">
                <img src="${layoutImage}" alt="Blueprint Layout" style="max-height: 480px;">
            </div>

            ${screenshot3D ? `
            <div class="page-break"></div>
            <h2>Project 3D Visualization Model</h2>
            <div class="layout-preview 3d-preview" style="margin-bottom: 20px;">
                <img src="${screenshot3D}" alt="3D Model Visual" style="max-height: 400px;">
            </div>
            ` : ''}

            <div class="page-break"></div>

            <h2>Itemized Pricing Proposal Breakdown</h2>
            <table>
                <thead>
                    <tr>
                        <th>Recommended Solution / Scope Item</th>
                        <th>Quantity</th>
                        <th>Unit Price</th>
                        <th>Line Total</th>
                    </tr>
                </thead>
                <tbody>
                    ${itemsRows}
                    <tr class="totals">
                        <td>TOTAL PROPOSAL INVESTMENT</td>
                        <td>-</td>
                        <td>-</td>
                        <td>$${totalSellingPrice.toFixed(2)}</td>
                    </tr>
                </tbody>
            </table>

            <div class="footer">
                Proposal generated via RoomFlow. All recommended specifications are customized based on structural blueprint requirements.
            </div>
        </body>
        </html>
    `;
    
    // Run safety scanner to ensure NO costing details leak
    const safetyCheck = scanCustomerReportForPricingData(htmlContent);
    if (!safetyCheck.safe) {
        alert("DEVELOPER ERROR: Prohibited costing term '" + safetyCheck.offendingTerm + "' detected in customer proposal! Export blocked.");
        throw new Error("DEVELOPER EXPORT SECURITY ALERT: Costing leak detected for term: " + safetyCheck.offendingTerm);
    }

    const printWindow = window.open('', '_blank');
    printWindow.document.write(htmlContent);
    printWindow.document.close();
}

// Expose printing functions globally
window.printInternalCostSheet = printInternalCostSheet;
window.printCustomerProposal = printCustomerProposal;

document.getElementById('btn-export-proposal').addEventListener('click', printCustomerProposal);

// --- ANGLED WALL SKETCHER & DRAWING LOGIC ---
function toggleDrawWallsMode() {
    const drawWallsPanel = document.getElementById('custom-wall-drawer-panel');
    state.pendingPlacement = null;
    if (state.drawMode === 'custom') {
        state.drawMode = null;
        state.sketchVertices = [];
        showCanvasPlacementHint('');
        drawWallsPanel.classList.add('hidden');
        document.getElementById('btn-draw-walls-mode').classList.remove('active');
        document.getElementById('btn-draw-walls-mode').style.backgroundColor = 'rgba(59, 130, 246, 0.12)';
    } else {
        // Clear active selections
        selectItem(null);
        state.drawMode = 'custom';
        state.sketchVertices = [];
        drawWallsPanel.classList.remove('hidden');
        document.getElementById('btn-draw-walls-mode').classList.add('active');
        document.getElementById('btn-draw-walls-mode').style.backgroundColor = 'rgba(168, 85, 247, 0.2)'; // purple
        
        // The first corner is placed by the user. This avoids anchoring an odd
        // room to the viewport center and works the same with a mouse or touch.
        const canvasCenterX = toWorldX(canvas.width / 2);
        const canvasCenterY = toWorldY(canvas.height / 2);
        state.lastMouseWorldX = snap(canvasCenterX);
        state.lastMouseWorldY = snap(canvasCenterY);
        showCanvasPlacementHint('Tap or click the blueprint to place the first corner');
    }
    updateHistoryButtons();
    draw();
}

function finishCustomRoomDrawing() {
    if (state.sketchVertices.length < 3) {
        alert('An angled room requires at least 3 walls/corners to be closed.');
        return;
    }

    // Save history BEFORE clearing sketch state, so undo restores sketch mode!
    if (typeof saveHistoryState === 'function') saveHistoryState();

    // Bounding box calculations
    const xs = state.sketchVertices.map(v => v.x);
    const ys = state.sketchVertices.map(v => v.y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);

    const roomW = maxX - minX;
    const roomL = maxY - minY;

    // Relative vertices from room top-left origin
    const relativeVertices = state.sketchVertices.map(v => ({
        x: v.x - minX,
        y: v.y - minY
    }));

    const newRoom = {
        id: 'r_' + Date.now(),
        levelId: state.currentLevelId,
        name: 'Custom Angled Area',
        type: 'custom',
        x: minX,
        y: minY,
        w: roomW,
        l: roomL,
        h: 8, // Standard 8 ft height
        color: '#a855f7', // Custom purple
        openings: [],
        vertices: relativeVertices,
        foamBoard: false,
        foamBondPockets: false,
        carbonStraps: 0,
        carbonFiberScope: 'full',
        carbonFiberWalls: [],
        customCarbonStraps: [],
        floorPerimeterStrap: false,
        nb1Height: 'none',
        drywallHeight: 'none'
    };

    state.rooms.push(newRoom);
    
    // Select the new room
    selectItem('room', newRoom.id);

    // Reset sketch state
    state.drawMode = null;
    state.sketchVertices = [];
    state.sketchRedoVertices = [];
    document.getElementById('custom-wall-drawer-panel').classList.add('hidden');
    document.getElementById('btn-draw-walls-mode').classList.remove('active');
    document.getElementById('btn-draw-walls-mode').style.backgroundColor = 'rgba(59, 130, 246, 0.12)';
    showCanvasPlacementHint('');

    updateHistoryButtons();
    draw();
    updateGlobalStats();
    if (window.sync3D) window.sync3D();
}

window.changeCustomWallLength = function(roomId, wallIndex, newValueRaw) {
    const room = state.rooms.find(r => r.id === roomId);
    if (!room || !room.vertices) return;

    const newLen = parseFloat(newValueRaw);
    if (isNaN(newLen) || newLen <= 0.1) return;

    const V = room.vertices;
    const i = wallIndex;
    const ip1 = (i + 1) % V.length;

    const dx = V[ip1].x - V[i].x;
    const dy = V[ip1].y - V[i].y;
    const currentLen = Math.sqrt(dx*dx + dy*dy);
    if (currentLen < 0.01) return;

    const cosTheta = dx / currentLen;
    const sinTheta = dy / currentLen;

    const newV_ip1_x = V[i].x + newLen * cosTheta;
    const newV_ip1_y = V[i].y + newLen * sinTheta;

    const deltaX = newV_ip1_x - V[ip1].x;
    const deltaY = newV_ip1_y - V[ip1].y;

    // Shift all subsequent vertices to pull/push the loop
    for (let j = i + 1; j < V.length; j++) {
        V[j].x += deltaX;
        V[j].y += deltaY;
    }

    // Recompute bounding box and shift origin if needed
    const minX = Math.min(...V.map(v => v.x));
    const maxX = Math.max(...V.map(v => v.x));
    const minY = Math.min(...V.map(v => v.y));
    const maxY = Math.max(...V.map(v => v.y));

    if (minX !== 0 || minY !== 0) {
        room.x += minX;
        room.y += minY;
        V.forEach(vt => {
            vt.x -= minX;
            vt.y -= minY;
        });
    }
    room.w = maxX - minX;
    room.l = maxY - minY;

    // Refresh display
    updateRoomEstimates(room);
    draw();
    updateGlobalStats();
    if (window.sync3D) window.sync3D();
    selectItem('room', room.id);
};

function addSketchWallSegment() {
    if (state.sketchVertices.length === 0) {
        showCanvasPlacementHint('Tap or click the blueprint to place the first corner');
        alert('Tap or click the blueprint where the first corner should begin, then add measured wall segments.');
        return;
    }

    const length = parseFloat(document.getElementById('draw-wall-length').value);
    const angleDegrees = parseFloat(document.getElementById('draw-wall-angle').value);

    if (isNaN(length) || length <= 0) {
        alert('Please enter a valid wall length.');
        return;
    }

    const last = state.sketchVertices[state.sketchVertices.length - 1];
    const angleRad = (angleDegrees * Math.PI) / 180;
    
    const nextX = last.x + length * Math.cos(angleRad);
    const nextY = last.y + length * Math.sin(angleRad);

    const snapX = snap(nextX);
    const snapY = snap(nextY);

    state.sketchVertices.push({ x: snapX, y: snapY });
    showCanvasPlacementHint('');
    state.sketchRedoVertices = [];
    const btnRedoWall = document.getElementById('btn-draw-redo-wall');
    if (btnRedoWall) btnRedoWall.disabled = true;
    
    state.lastMouseWorldX = snapX;
    state.lastMouseWorldY = snapY;

    updateHistoryButtons();
    draw();
}

function undoLastSketchWall() {
    if (state.sketchVertices.length > 1) {
        const popped = state.sketchVertices.pop();
        state.sketchRedoVertices.push(popped);
        const btnRedoWall = document.getElementById('btn-draw-redo-wall');
        if (btnRedoWall) btnRedoWall.disabled = false;
        
        const last = state.sketchVertices[state.sketchVertices.length - 1];
        state.lastMouseWorldX = last.x;
        state.lastMouseWorldY = last.y;
    } else {
        alert('Nothing to undo.');
    }
    updateHistoryButtons();
    draw();
}

function redoLastSketchWall() {
    if (state.sketchRedoVertices.length > 0) {
        const popped = state.sketchRedoVertices.pop();
        state.sketchVertices.push(popped);
        state.lastMouseWorldX = popped.x;
        state.lastMouseWorldY = popped.y;
        
        const btnRedoWall = document.getElementById('btn-draw-redo-wall');
        if (btnRedoWall) btnRedoWall.disabled = (state.sketchRedoVertices.length === 0);
        updateHistoryButtons();
        draw();
    }
}

// Bind sketch UI controls
document.getElementById('btn-draw-walls-mode').addEventListener('click', toggleDrawWallsMode);
document.getElementById('btn-draw-add-wall').addEventListener('click', addSketchWallSegment);
document.getElementById('btn-draw-undo-wall').addEventListener('click', undoLastSketchWall);
document.getElementById('btn-draw-redo-wall').addEventListener('click', redoLastSketchWall);
document.getElementById('btn-draw-finish-room').addEventListener('click', finishCustomRoomDrawing);
document.getElementById('btn-draw-cancel').addEventListener('click', () => {
    state.drawMode = null;
    state.sketchVertices = [];
    state.sketchRedoVertices = [];
    const btnRedoWall = document.getElementById('btn-draw-redo-wall');
    if (btnRedoWall) btnRedoWall.disabled = true;
    document.getElementById('custom-wall-drawer-panel').classList.add('hidden');
    document.getElementById('btn-draw-walls-mode').classList.remove('active');
    document.getElementById('btn-draw-walls-mode').style.backgroundColor = 'rgba(59, 130, 246, 0.12)';
    showCanvasPlacementHint('');
    draw();
});

// --- UNDO / REDO HISTORY SYSTEM ---
function getHistorySnapshot() {
    return {
        rooms: JSON.parse(JSON.stringify(state.rooms)),
        sumpPumps: JSON.parse(JSON.stringify(state.sumpPumps)),
        dehumidifiers: JSON.parse(JSON.stringify(state.dehumidifiers || [])),
        dischargeLines: JSON.parse(JSON.stringify(state.dischargeLines)),
        floorHatches: JSON.parse(JSON.stringify(state.floorHatches || [])),
        interiorPipes: JSON.parse(JSON.stringify(state.interiorPipes || [])),
        stanchions: JSON.parse(JSON.stringify(state.stanchions || [])),
        mainBeams: JSON.parse(JSON.stringify(state.mainBeams || [])),
        currentLevelId: state.currentLevelId,
        // Save drawing mode variables
        drawMode: state.drawMode,
        sketchVertices: JSON.parse(JSON.stringify(state.sketchVertices)),
        sketchRedoVertices: JSON.parse(JSON.stringify(state.sketchRedoVertices))
    };
}

function updateDrawingPanelVisibility() {
    const drawWallsPanel = document.getElementById('custom-wall-drawer-panel');
    const btnDrawWalls = document.getElementById('btn-draw-walls-mode');
    
    if (state.drawMode === 'custom') {
        if (drawWallsPanel) drawWallsPanel.classList.remove('hidden');
        if (btnDrawWalls) {
            btnDrawWalls.classList.add('active');
            btnDrawWalls.style.backgroundColor = 'rgba(168, 85, 247, 0.2)'; // purple
        }
    } else {
        if (drawWallsPanel) drawWallsPanel.classList.add('hidden');
        if (btnDrawWalls) {
            btnDrawWalls.classList.remove('active');
            btnDrawWalls.style.backgroundColor = 'rgba(59, 130, 246, 0.12)';
        }
    }
}

function saveHistoryState() {
    const snapshot = getHistorySnapshot();
    state.undoStack.push(snapshot);
    if (state.undoStack.length > 50) {
        state.undoStack.shift();
    }
    state.redoStack = [];
    updateHistoryButtons();
}

function updateHistoryButtons() {
    const btnUndo = document.getElementById('btn-undo');
    const btnRedo = document.getElementById('btn-redo');
    if (state.drawMode === 'custom') {
        if (btnUndo) btnUndo.disabled = (state.sketchVertices.length <= 1);
        if (btnRedo) btnRedo.disabled = (state.sketchRedoVertices.length === 0);
    } else {
        if (btnUndo) btnUndo.disabled = (state.undoStack.length === 0);
        if (btnRedo) btnRedo.disabled = (state.redoStack.length === 0);
    }
}

function undo() {
    if (state.drawMode === 'custom') {
        undoLastSketchWall();
        return;
    }
    if (state.undoStack.length === 0) return;
    
    const current = getHistorySnapshot();
    state.redoStack.push(current);
    
    const previous = state.undoStack.pop();
    state.rooms = previous.rooms;
    state.sumpPumps = previous.sumpPumps;
    state.dehumidifiers = previous.dehumidifiers || [];
    state.dischargeLines = previous.dischargeLines;
    state.floorHatches = previous.floorHatches || [];
    state.interiorPipes = previous.interiorPipes || [];
    state.stanchions = previous.stanchions || [];
    state.mainBeams = previous.mainBeams || [];
    state.currentLevelId = previous.currentLevelId || 'basement';
    
    // Sync level select UI dropdown
    const lvlSelect = document.getElementById('level-select');
    if (lvlSelect) lvlSelect.value = state.currentLevelId;
    
    // Restore drawing mode variables
    state.drawMode = previous.drawMode || null;
    state.sketchVertices = previous.sketchVertices || [];
    state.sketchRedoVertices = previous.sketchRedoVertices || [];
    
    // Toggle drawing panel UI state
    updateDrawingPanelVisibility();
    
    selectItem(null);
    draw();
    updateGlobalStats();
    if (window.sync3D) window.sync3D();
    updateHistoryButtons();
}

// Global exposure for touch support
window.undo = undo;

function redo() {
    if (state.drawMode === 'custom') {
        redoLastSketchWall();
        return;
    }
    if (state.redoStack.length === 0) return;
    
    const current = getHistorySnapshot();
    state.undoStack.push(current);
    
    const nextState = state.redoStack.pop();
    state.rooms = nextState.rooms;
    state.sumpPumps = nextState.sumpPumps;
    state.dehumidifiers = nextState.dehumidifiers || [];
    state.dischargeLines = nextState.dischargeLines;
    state.floorHatches = nextState.floorHatches || [];
    state.interiorPipes = nextState.interiorPipes || [];
    state.stanchions = nextState.stanchions || [];
    state.mainBeams = nextState.mainBeams || [];
    state.currentLevelId = nextState.currentLevelId || 'basement';
    
    // Sync level select UI dropdown
    const lvlSelect = document.getElementById('level-select');
    if (lvlSelect) lvlSelect.value = state.currentLevelId;
    
    // Restore drawing mode variables
    state.drawMode = nextState.drawMode || null;
    state.sketchVertices = nextState.sketchVertices || [];
    state.sketchRedoVertices = nextState.sketchRedoVertices || [];
    
    // Toggle drawing panel UI state
    updateDrawingPanelVisibility();
    
    selectItem(null);
    draw();
    updateGlobalStats();
    if (window.sync3D) window.sync3D();
    updateHistoryButtons();
}

// Global exposure for touch support
window.redo = redo;

// Bind Global Undo/Redo Click Listeners
document.getElementById('btn-undo').addEventListener('click', undo);
document.getElementById('btn-redo').addEventListener('click', redo);

// Bind Interface Mode selector
const selectInterfaceMode = document.getElementById('select-app-interface-mode');
if (selectInterfaceMode) {
    selectInterfaceMode.value = state.interfaceMode === 'guided' ? 'guided' : 'advanced';
    selectInterfaceMode.addEventListener('change', (e) => {
        const mode = e.target.value;
        if (typeof setInterfaceMode === 'function') {
            setInterfaceMode(mode);
        }
    });
}

// Bind Keyboard Shortcuts (Ctrl+Z and Ctrl+Y / Ctrl+Shift+Z)
window.addEventListener('keydown', (e) => {
    if (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA') {
        return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        undo();
    }
    if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))) {
        e.preventDefault();
        redo();
    }
});

// --- AR CAPTURED MEASUREMENTS MANAGEMENT ---
function updateMeasurementsSidebar() {
    const listEl = document.getElementById('ar-measurements-list');
    if (!listEl) return;
    
    if (!state.capturedMeasurements || state.capturedMeasurements.length === 0) {
        listEl.innerHTML = `<p class="empty-state">No captured distances. Use 'Capture Dist' in camera mode.</p>`;
        return;
    }
    
    let html = '';
    state.capturedMeasurements.forEach((val, idx) => {
        const displayVal = val.toFixed(1);
        html += `
            <div class="ar-history-item">
                <span class="ar-history-val">${displayVal} ft</span>
                <div class="ar-history-actions">
                    <button class="ar-history-btn" onclick="applyMeasurement(${val}, 'width')" title="Apply to Room Width">Width</button>
                    <button class="ar-history-btn" onclick="applyMeasurement(${val}, 'length')" title="Apply to Room Length">Length</button>
                    <button class="ar-history-btn" onclick="applyMeasurement(${val}, 'discharge')" title="Apply to Pipe">Pipe</button>
                    <button class="ar-history-btn btn-delete" onclick="deleteMeasurement(${idx})" title="Delete Capture">Delete</button>
                </div>
            </div>
        `;
    });
    listEl.innerHTML = html;
}

window.applyMeasurement = function(val, target) {
    if (target === 'width') {
        if (!state.selectedRoomId) {
            alert('Please select a room on the canvas first!');
            return;
        }
        const room = state.rooms.find(r => r.id === state.selectedRoomId);
        if (room) {
            room.w = snap(val);
            updateRoomEstimates(room);
            draw();
            if (window.sync3D) window.sync3D();
        }
    } else if (target === 'length') {
        if (!state.selectedRoomId) {
            alert('Please select a room on the canvas first!');
            return;
        }
        const room = state.rooms.find(r => r.id === state.selectedRoomId);
        if (room) {
            room.l = snap(val);
            updateRoomEstimates(room);
            draw();
            if (window.sync3D) window.sync3D();
        }
    } else if (target === 'discharge') {
        if (!state.selectedDischargeLineId) {
            alert('Please select a discharge line on the canvas first!');
            return;
        }
        const dl = state.dischargeLines.find(l => l.id === state.selectedDischargeLineId);
        if (dl) {
            const dx = dl.x2 - dl.x1;
            const dy = dl.y2 - dl.y1;
            const currentLength = Math.sqrt(dx * dx + dy * dy);
            if (currentLength > 0.1) {
                const angle = Math.atan2(dy, dx);
                dl.x2 = dl.x1 + snap(val) * Math.cos(angle);
                dl.y2 = dl.y1 + snap(val) * Math.sin(angle);
                dl.length = snap(val);
                
                document.getElementById('discharge-len-input').value = dl.length.toFixed(1);
                draw();
                updateGlobalStats();
            }
        }
    }
};

window.deleteMeasurement = function(idx) {
    state.capturedMeasurements.splice(idx, 1);
    updateMeasurementsSidebar();
    if (window.updateARCapturesOverlay) window.updateARCapturesOverlay();
};

window.updateMeasurementsSidebar = updateMeasurementsSidebar;

// --- CLOUD SYNC ENGINE ---
function b64DecodeUnicode(str) {
    return decodeURIComponent(atob(str).split('').map(function(c) {
        return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
    }).join(''));
}
function b64EncodeUnicode(str) {
    return btoa(encodeURIComponent(str).replace(/%([0-9A-F]{2})/g,
        function toSolidBytes(match, p1) {
            return String.fromCharCode(parseInt(p1, 16));
        }));
}

function getSyncConfig() {
    let provider = localStorage.getItem('roomflow_sync_provider');
    if (!provider) {
        const enabled = localStorage.getItem('roomflow_sync_enabled') === 'true';
        provider = enabled ? 'kvdb' : 'none';
        localStorage.setItem('roomflow_sync_provider', provider);
    }
    const ghToken = localStorage.getItem('roomflow_sync_gh_token') || '';
    const ghRepo = localStorage.getItem('roomflow_sync_gh_repo') || '';
    const ghPath = localStorage.getItem('roomflow_sync_gh_path') || 'jobs.json';
    const kvdbBucket = localStorage.getItem('roomflow_sync_bucket') || '';
    const kvdbKey = localStorage.getItem('roomflow_sync_key') || '';
    return { provider, ghToken, ghRepo, ghPath, kvdbBucket, kvdbKey };
}

function updateSyncUI() {
    const config = getSyncConfig();
    const provSelect = document.getElementById('sync-provider');
    const ghToken = document.getElementById('sync-gh-token');
    const ghRepo = document.getElementById('sync-gh-repo');
    const ghPath = document.getElementById('sync-gh-path');
    const kvdbBucket = document.getElementById('sync-bucket-input');
    const kvdbKey = document.getElementById('sync-key-input');
    
    if (provSelect) provSelect.value = config.provider;
    if (ghToken) ghToken.value = config.ghToken;
    if (ghRepo) ghRepo.value = config.ghRepo;
    if (ghPath) ghPath.value = config.ghPath;
    if (kvdbBucket) kvdbBucket.value = config.kvdbBucket;
    if (kvdbKey) kvdbKey.value = config.kvdbKey;
    
    const panelGh = document.getElementById('panel-sync-github');
    const panelKvdb = document.getElementById('panel-sync-kvdb');
    const controlsRow = document.getElementById('sync-controls-row');
    const status = document.getElementById('sync-status');
    
    if (config.provider === 'github') {
        if (panelGh) panelGh.classList.remove('hidden');
        if (panelKvdb) panelKvdb.classList.add('hidden');
        if (controlsRow) controlsRow.classList.remove('hidden');
    } else if (config.provider === 'kvdb') {
        if (panelGh) panelGh.classList.add('hidden');
        if (panelKvdb) panelKvdb.classList.remove('hidden');
        if (controlsRow) controlsRow.classList.remove('hidden');
    } else {
        if (panelGh) panelGh.classList.add('hidden');
        if (panelKvdb) panelKvdb.classList.add('hidden');
        if (controlsRow) controlsRow.classList.add('hidden');
        if (status) status.textContent = "Status: Offline/Local-only";
    }
}

async function syncCloudJobs() {
    const provSelect = document.getElementById('sync-provider');
    const status = document.getElementById('sync-status');
    if (!provSelect) return;
    
    const provider = provSelect.value;
    localStorage.setItem('roomflow_sync_provider', provider);
    
    let localJobs = {};
    try {
        const stored = localStorage.getItem('roomflow_jobs');
        if (stored) localJobs = JSON.parse(stored);
    } catch(e) {
        console.error(e);
    }
    
    if (provider === 'none') {
        if (status) status.textContent = "Status: Offline/Local-only";
        return;
    }
    
    if (provider === 'github') {
        const token = document.getElementById('sync-gh-token').value.trim();
        const repo = document.getElementById('sync-gh-repo').value.trim();
        const path = document.getElementById('sync-gh-path').value.trim() || 'jobs.json';
        
        localStorage.setItem('roomflow_sync_gh_token', token);
        localStorage.setItem('roomflow_sync_gh_repo', repo);
        localStorage.setItem('roomflow_sync_gh_path', path);
        
        if (!token || !repo) {
            if (status) status.textContent = "Status: Waiting for Token/Repo";
            return;
        }
        
        if (status) status.textContent = "Status: Syncing GitHub...";
        
        try {
            const url = 'https://api.github.com/repos/' + repo + '/contents/' + path;
            const headers = {
                'Authorization': 'token ' + token,
                'Accept': 'application/vnd.github.v3+json',
                'Content-Type': 'application/json'
            };
            
            const res = await fetch(url, { headers });
            let cloudJobs = {};
            let sha = null;
            
            if (res.ok) {
                const fileData = await res.json();
                sha = fileData.sha;
                if (fileData.content) {
                    const cleanContent = fileData.content.replace(/\s/g, '');
                    try {
                        const decoded = b64DecodeUnicode(cleanContent);
                        cloudJobs = JSON.parse(decoded) || {};
                    } catch (e) {
                        console.error("GitHub JSON parse failed:", e);
                    }
                }
            } else if (res.status !== 404) {
                const errText = await res.text();
                if (status) status.textContent = "Status: Read error: " + (errText || res.status);
                return;
            }
            
            // Merge logic based on lastModified
            const merged = {};
            Object.keys(localJobs).forEach(name => {
                merged[name] = localJobs[name];
            });
            Object.keys(cloudJobs).forEach(name => {
                const cloudJob = cloudJobs[name];
                const localJob = localJobs[name];
                if (!localJob) {
                    merged[name] = cloudJob;
                } else {
                    const cloudTime = cloudJob.lastModified || 0;
                    const localTime = localJob.lastModified || 0;
                    if (cloudTime > localTime) {
                        merged[name] = cloudJob;
                    }
                }
            });
            
            localStorage.setItem('roomflow_jobs', JSON.stringify(merged));
            
            const updatedContent = b64EncodeUnicode(JSON.stringify(merged, null, 2));
            const body = {
                message: "Sync jobs - " + new Date().toISOString(),
                content: updatedContent
            };
            if (sha) body.sha = sha;
            
            const putRes = await fetch(url, {
                method: 'PUT',
                headers,
                body: JSON.stringify(body)
            });
            
            if (putRes.ok) {
                if (status) status.textContent = "Status: Synced at " + new Date().toLocaleTimeString();
                renderJobsList();
            } else {
                const errText = await putRes.text();
                if (status) status.textContent = "Status: Push failed: " + errText;
            }
        } catch(err) {
            console.error("GitHub Sync error:", err);
            if (status) status.textContent = "Status: Sync failed";
        }
    } else if (provider === 'kvdb') {
        const bucketInp = document.getElementById('sync-bucket-input');
        const keyInp = document.getElementById('sync-key-input');
        if (!bucketInp || !keyInp) return;
        
        const bucket = bucketInp.value.trim().replace(/[^a-zA-Z0-9_-]/g, '');
        const key = keyInp.value.trim().replace(/[^a-zA-Z0-9_-]/g, '');
        
        localStorage.setItem('roomflow_sync_bucket', bucket);
        localStorage.setItem('roomflow_sync_key', key);
        
        if (!bucket || !key) {
            if (status) status.textContent = "Status: Waiting for Bucket/Key";
            return;
        }
        
        if (bucket.length < 5) {
            if (status) status.textContent = "Status: Bucket ID too short";
            return;
        }
        if (key.length < 3) {
            if (status) status.textContent = "Status: Key too short (min 3 chars)";
            return;
        }
        
        if (status) status.textContent = "Status: Syncing KVDB...";
        
        try {
            const url = 'https://kvdb.io/' + bucket + '/jobs_' + key;
            const res = await fetch(url);
            
            if (res.ok) {
                const cloudText = await res.text();
                let cloudJobs = {};
                try {
                    if (cloudText) cloudJobs = JSON.parse(cloudText);
                } catch(e) {
                    console.error("Cloud JSON parse failed:", e);
                }
                
                const merged = {};
                Object.keys(localJobs).forEach(name => {
                    merged[name] = localJobs[name];
                });
                Object.keys(cloudJobs).forEach(name => {
                    const cloudJob = cloudJobs[name];
                    const localJob = localJobs[name];
                    if (!localJob) {
                        merged[name] = cloudJob;
                    } else {
                        const cloudTime = cloudJob.lastModified || 0;
                        const localTime = localJob.lastModified || 0;
                        if (cloudTime > localTime) {
                            merged[name] = cloudJob;
                        }
                    }
                });
                
                localStorage.setItem('roomflow_jobs', JSON.stringify(merged));
                
                const postRes = await fetch(url, {
                    method: 'POST',
                    body: JSON.stringify(merged)
                });
                
                if (postRes.ok) {
                    if (status) status.textContent = "Status: Synced at " + new Date().toLocaleTimeString();
                } else {
                    const errText = await postRes.text();
                    if (status) status.textContent = "Status: Write failed: " + errText;
                }
                renderJobsList();
            } else if (res.status === 404) {
                const postRes = await fetch(url, {
                    method: 'POST',
                    body: JSON.stringify(localJobs)
                });
                if (postRes.ok) {
                    if (status) status.textContent = "Status: Initialized cloud db";
                } else {
                    const errText = await postRes.text();
                    if (status) status.textContent = "Status: Write failed: " + errText;
                }
            } else {
                const errText = await res.text();
                if (status) status.textContent = "Status: Read error: " + (errText || res.status);
            }
        } catch(err) {
            console.error("KVDB Sync error:", err);
            if (status) status.textContent = "Status: Offline/Sync failed";
        }
    }
}

async function uploadLocalJobsToCloud() {
    const config = getSyncConfig();
    if (config.provider === 'none') return;
    
    let localJobs = {};
    try {
        const stored = localStorage.getItem('roomflow_jobs');
        if (stored) localJobs = JSON.parse(stored);
    } catch(e) {
        console.error(e);
    }
    
    if (config.provider === 'github' && config.ghToken && config.ghRepo) {
        try {
            const url = 'https://api.github.com/repos/' + config.ghRepo + '/contents/' + config.ghPath;
            const headers = {
                'Authorization': 'token ' + config.ghToken,
                'Accept': 'application/vnd.github.v3+json',
                'Content-Type': 'application/json'
            };
            const res = await fetch(url, { headers });
            let sha = null;
            if (res.ok) {
                const fileData = await res.json();
                sha = fileData.sha;
            }
            const updatedContent = b64EncodeUnicode(JSON.stringify(localJobs, null, 2));
            const body = {
                message: "Auto-save jobs - " + new Date().toISOString(),
                content: updatedContent
            };
            if (sha) body.sha = sha;
            
            await fetch(url, {
                method: 'PUT',
                headers,
                body: JSON.stringify(body)
            });
        } catch(e) {
            console.error("Auto-save to GitHub failed:", e);
        }
    } else if (config.provider === 'kvdb' && config.kvdbBucket && config.kvdbKey) {
        try {
            const url = 'https://kvdb.io/' + config.kvdbBucket + '/jobs_' + config.kvdbKey;
            await fetch(url, {
                method: 'POST',
                body: JSON.stringify(localJobs)
            });
        } catch(e) {
            console.error("Upload to cloud failed:", e);
        }
    }
}

// Wire up Cloud Sync listeners after DOMContentLoaded/startup
window.addEventListener('load', () => {
    const syncProv = document.getElementById('sync-provider');
    const syncGhToken = document.getElementById('sync-gh-token');
    const syncGhRepo = document.getElementById('sync-gh-repo');
    const syncGhPath = document.getElementById('sync-gh-path');
    const syncBucket = document.getElementById('sync-bucket-input');
    const syncInp = document.getElementById('sync-key-input');
    const syncBtn = document.getElementById('btn-sync-now');
    
    const handleProviderChange = () => {
        const prov = syncProv ? syncProv.value : 'none';
        localStorage.setItem('roomflow_sync_provider', prov);
        updateSyncUI();
        syncCloudJobs();
    };
    
    if (syncProv) syncProv.addEventListener('change', handleProviderChange);
    
    if (syncGhToken) syncGhToken.addEventListener('change', syncCloudJobs);
    if (syncGhRepo) syncGhRepo.addEventListener('change', syncCloudJobs);
    if (syncGhPath) syncGhPath.addEventListener('change', syncCloudJobs);
    if (syncBucket) syncBucket.addEventListener('change', syncCloudJobs);
    if (syncInp) syncInp.addEventListener('change', syncCloudJobs);
    if (syncBtn) syncBtn.addEventListener('click', syncCloudJobs);
    
    // Perform initial automatic sync if enabled on load
    const config = getSyncConfig();
    if (config.provider !== 'none') {
        setTimeout(syncCloudJobs, 1000);
    }
});

// --- JOB DATABASE ENGINE ---
// Open/close jobs database
document.getElementById('btn-jobs').addEventListener('click', () => {
    document.getElementById('jobs-modal').classList.remove('hidden');
    updateSyncUI();
    syncCloudJobs();
    renderJobsList();
});

document.getElementById('btn-close-jobs').addEventListener('click', () => {
    document.getElementById('jobs-modal').classList.add('hidden');
});

// Diagnostics Modal Controls
document.getElementById('btn-diagnostics').addEventListener('click', () => {
    document.getElementById('diagnostics-modal').classList.remove('hidden');
    if (window.RoomFlowSpatial) {
        window.RoomFlowSpatial.performCapabilityDetection();
    }
});

document.getElementById('btn-close-diagnostics').addEventListener('click', () => {
    document.getElementById('diagnostics-modal').classList.add('hidden');
});

document.getElementById('btn-diagnostics-ok').addEventListener('click', () => {
    document.getElementById('diagnostics-modal').classList.add('hidden');
});

// Save job helper
document.getElementById('btn-save-job-submit').addEventListener('click', async () => {
    const input = document.getElementById('job-name-input');
    const name = input.value.trim();
    if (!name) {
        alert("Please enter a job name!");
        return;
    }
    
    const projectData = {
        rooms: state.rooms,
        sumpPumps: state.sumpPumps,
        dehumidifiers: state.dehumidifiers || [],
        dischargeLines: state.dischargeLines,
        floorHatches: state.floorHatches,
        interiorPipes: state.interiorPipes,
        stanchions: state.stanchions,
        mainBeams: state.mainBeams,
        currentLevelId: state.currentLevelId,
        capturedMeasurements: state.capturedMeasurements || [],
        costing: state.costing,
        lastModified: Date.now()
    };
    
    let jobs = {};
    try {
        const stored = localStorage.getItem('roomflow_jobs');
        if (stored) jobs = JSON.parse(stored);
    } catch(e) {
        console.error(e);
    }
    
    jobs[name] = projectData;
    localStorage.setItem('roomflow_jobs', JSON.stringify(jobs));
    
    input.value = '';
    
    await uploadLocalJobsToCloud();
    renderJobsList();
});

// Normalizes and validates project state structure
window.normalizeProjectState = function(s) {
    if (!s) return s;
    if (!s.schemaVersion) s.schemaVersion = '2.0.0';
    if (!s.rooms) s.rooms = [];
    if (!s.walls) s.walls = [];
    if (!s.roomConnections) s.roomConnections = [];
    if (!s.doors) s.doors = [];
    if (!s.windows) s.windows = [];
    if (!s.openings) s.openings = [];
    if (!s.stairs) s.stairs = [];
    if (!s.sumpPumps) s.sumpPumps = [];
    if (!s.dehumidifiers) s.dehumidifiers = [];
    if (!s.dischargeLines) s.dischargeLines = [];
    if (!s.floorHatches) s.floorHatches = [];
    if (!s.interiorPipes) s.interiorPipes = [];
    if (!s.stanchions) s.stanchions = [];
    if (!s.mainBeams) s.mainBeams = [];
    if (!s.capturedMeasurements) s.capturedMeasurements = [];
    if (!s.levels || s.levels.length === 0) {
        s.levels = [
            { id: 'crawlspace', name: 'Crawlspace', elevation: -3, height: 4 },
            { id: 'basement', name: 'Basement', elevation: -8, height: 8 },
            { id: 'mainfloor', name: 'Main Floor', elevation: 0, height: 9 },
            { id: 'secondfloor', name: 'Second Floor', elevation: 9, height: 8 },
            { id: 'attic', name: 'Attic', elevation: 17, height: 7 }
        ];
    }
    if (!s.costing) {
        s.costing = {
            customerName: '',
            customerAddress: '',
            customerPhone: '',
            customerEmail: '',
            estimator: '',
            inspectionDate: '',
            notes: '',
            workAreaSelection: 'crawlspace',
            photos: [],
            settings: {
                targetGrossMargin: 40.0,
                salesTaxRate: 6.0,
                overhead: 15.0
            }
        };
    }
    if (!s.costing.settings) {
        s.costing.settings = {
            targetGrossMargin: 40.0,
            salesTaxRate: 6.0,
            overhead: 15.0
        };
    }
    return s;
};

// Load job from project data structure
function loadJobData(data) {
    if (!data) return;
    
    // Normalize properties
    window.normalizeProjectState(data);
    
    state.rooms = data.rooms;
    state.sumpPumps = data.sumpPumps;
    state.dehumidifiers = data.dehumidifiers;
    state.dischargeLines = data.dischargeLines;
    state.floorHatches = data.floorHatches;
    state.interiorPipes = data.interiorPipes;
    state.stanchions = data.stanchions;
    state.mainBeams = data.mainBeams;
    state.levels = data.levels;
    state.currentLevelId = data.currentLevelId || 'basement';
    state.capturedMeasurements = data.capturedMeasurements;
    state.jobId = data.jobId || null;
    state.currentStep = Number(data.currentStep || state.currentStep || 1);
    state.guidedStep3Mode = data.guidedStep3Mode || 'choose';
    
    // New logical building properties
    state.walls = data.walls || [];
    state.roomConnections = data.roomConnections || [];
    state.doors = data.doors || [];
    state.windows = data.windows || [];
    state.openings = data.openings || [];
    state.stairs = data.stairs || [];
    state.createdTimestamp = data.createdTimestamp || Date.now();
    state.updatedTimestamp = data.updatedTimestamp || Date.now();
    state.revisionNumber = data.revisionNumber || 1;
    state.syncState = data.syncState || 'synchronized';
    
    // Load costing data
    state.costing = data.costing;
    initDefaultCosting(state);
    state.dehumidifiers = data.dehumidifiers || [];
    state.dischargeLines = data.dischargeLines || [];
    state.floorHatches = data.floorHatches || [];
    state.interiorPipes = data.interiorPipes || [];
    state.stanchions = data.stanchions || [];
    state.mainBeams = data.mainBeams || [];
    state.currentLevelId = data.currentLevelId || 'basement';
    state.capturedMeasurements = data.capturedMeasurements || [];
    
    // Load costing data
    state.costing = data.costing || null;
    initDefaultCosting(state);
    
    state.rooms.forEach(r => {
        if (!r.levelId) r.levelId = 'basement';
        if (r.carbonStraps === undefined) r.carbonStraps = 0;
        if (r.floorPerimeterStrap === undefined) r.floorPerimeterStrap = false;
        if (r.nb1Height === undefined) r.nb1Height = 'none';
        if (r.drywallHeight === undefined) r.drywallHeight = 'none';
        if (r.foamBondPockets === undefined) r.foamBondPockets = false;
        if (r.removeInsulation === undefined) r.removeInsulation = false;
        if (r.blowInInsulation === undefined) r.blowInInsulation = false;
    });
    state.sumpPumps.forEach(sp => { if (!sp.levelId) sp.levelId = 'basement'; });
    state.dischargeLines.forEach(dl => { if (!dl.levelId) dl.levelId = 'basement'; });
    state.floorHatches.forEach(h => { if (!h.levelId) h.levelId = 'basement'; });
    state.interiorPipes.forEach(ip => { if (!ip.levelId) ip.levelId = 'basement'; });
    state.stanchions.forEach(st => { if (!st.levelId) st.levelId = 'basement'; });
    state.mainBeams.forEach(bm => { if (!bm.levelId) bm.levelId = 'basement'; });
    if (state.dehumidifiers) state.dehumidifiers.forEach(dh => { if (!dh.levelId) dh.levelId = 'basement'; });
    
    const levelSelect = document.getElementById('level-select');
    if (levelSelect) levelSelect.value = state.currentLevelId;
    
    selectItem(null);
    draw();
    updateGlobalStats();
    
    // Refresh costing UI
    if (window.renderCostUI) window.renderCostUI();
    
    if (window.sync3D) window.sync3D();
    
    if (typeof saveHistoryState === 'function') saveHistoryState();
}

// Render jobs list helper
function renderJobsList() {
    const container = document.getElementById('jobs-list-container');
    if (!container) return;
    
    let jobs = {};
    try {
        const stored = localStorage.getItem('roomflow_jobs');
        if (stored) jobs = JSON.parse(stored);
    } catch(e) {
        console.error(e);
    }
    
    const keys = Object.keys(jobs);
    if (keys.length === 0) {
        container.innerHTML = `<div style="text-align: center; padding: 1.5rem; color: #64748b; font-size: 0.85rem;">No jobs saved yet</div>`;
        return;
    }
    
    container.innerHTML = '';
    keys.forEach(name => {
        const row = document.createElement('div');
        row.style.display = 'flex';
        row.style.justifyContent = 'space-between';
        row.style.alignItems = 'center';
        row.style.padding = '0.6rem 0.75rem';
        row.style.borderBottom = '1px solid rgba(255, 255, 255, 0.05)';
        row.style.fontSize = '0.85rem';
        
        const nameSpan = document.createElement('span');
        nameSpan.textContent = name;
        nameSpan.style.fontWeight = '500';
        nameSpan.style.color = '#f1f5f9';
        nameSpan.style.overflow = 'hidden';
        nameSpan.style.textOverflow = 'ellipsis';
        nameSpan.style.whiteSpace = 'nowrap';
        nameSpan.style.maxWidth = '180px';
        row.appendChild(nameSpan);
        
        const actionsDiv = document.createElement('div');
        actionsDiv.style.display = 'flex';
        actionsDiv.style.gap = '0.4rem';
        
        const btnLoad = document.createElement('button');
        btnLoad.innerHTML = `<i data-lucide="folder-open" style="width:14px; height:14px;"></i>`;
        btnLoad.title = "Load Job";
        btnLoad.style.padding = '0.3rem';
        btnLoad.style.background = '#0ea5e9';
        btnLoad.style.border = 'none';
        btnLoad.style.borderRadius = '4px';
        btnLoad.style.color = '#ffffff';
        btnLoad.style.cursor = 'pointer';
        btnLoad.addEventListener('click', () => {
            loadJobData(jobs[name]);
            document.getElementById('jobs-modal').classList.add('hidden');
        });
        actionsDiv.appendChild(btnLoad);
        
        const btnShare = document.createElement('button');
        btnShare.innerHTML = `<i data-lucide="share-2" style="width:14px; height:14px;"></i>`;
        btnShare.title = "Copy Shareable Link";
        btnShare.style.padding = '0.3rem';
        btnShare.style.background = '#10b981';
        btnShare.style.border = 'none';
        btnShare.style.borderRadius = '4px';
        btnShare.style.color = '#ffffff';
        btnShare.style.cursor = 'pointer';
        btnShare.addEventListener('click', () => {
            const jsonStr = JSON.stringify(jobs[name]);
            const base64 = btoa(unescape(encodeURIComponent(jsonStr)));
            const shareUrl = `${window.location.origin}${window.location.pathname}?job=${encodeURIComponent(base64)}`;
            navigator.clipboard.writeText(shareUrl).then(() => {
                alert("Shareable job URL copied to clipboard!");
            }).catch(err => {
                console.error("Clipboard copy failed:", err);
                alert("Share link: " + shareUrl);
            });
        });
        actionsDiv.appendChild(btnShare);
        
        const btnDelete = document.createElement('button');
        btnDelete.innerHTML = `<i data-lucide="trash-2" style="width:14px; height:14px;"></i>`;
        btnDelete.title = "Delete Job";
        btnDelete.style.padding = '0.3rem';
        btnDelete.style.background = '#ef4444';
        btnDelete.style.border = 'none';
        btnDelete.style.borderRadius = '4px';
        btnDelete.style.color = '#ffffff';
        btnDelete.style.cursor = 'pointer';
        btnDelete.addEventListener('click', async () => {
            if (confirm(`Are you sure you want to delete job "${name}"?`)) {
                delete jobs[name];
                localStorage.setItem('roomflow_jobs', JSON.stringify(jobs));
                await uploadLocalJobsToCloud();
                renderJobsList();
            }
        });
        actionsDiv.appendChild(btnDelete);
        
        row.appendChild(actionsDiv);
        container.appendChild(row);
    });
    
    lucide.createIcons();
}

// Auto Load job from URL parameter
function checkUrlJobLoad() {
    const base64 = new URLSearchParams(window.location.search).get('job');
    if (base64) {
        try {
            const jsonStr = decodeURIComponent(escape(atob(base64)));
            const data = JSON.parse(jsonStr);
            loadJobData(data);
            console.log("Successfully loaded job from URL query parameter!");
        } catch(e) {
            console.error("Error parsing job query string:", e);
        }
    }
}

// Initialization
window.addEventListener('resize', resizeCanvas);
resizeCanvas();
lucide.createIcons();
checkUrlJobLoad();
switchView(state.activeView);

// --- MOBILE RESPONSIVE DRAWERS & TOUCH EVENTS ---
const leftSidebar = document.getElementById('left-sidebar');
const rightSidebar = document.getElementById('right-sidebar');
const backdrop = document.getElementById('mobile-sidebar-backdrop');
const btnToggleTools = document.getElementById('mobile-toggle-tools');
const btnToggleDetails = document.getElementById('mobile-toggle-details');

function closeAllDrawers() {
    leftSidebar.classList.remove('open');
    rightSidebar.classList.remove('open');
    backdrop.classList.add('hidden');
}
window.closeAllDrawers = closeAllDrawers;

btnToggleTools.addEventListener('click', (e) => {
    e.stopPropagation();
    const isOpen = leftSidebar.classList.contains('open');
    closeAllDrawers();
    if (!isOpen) {
        leftSidebar.classList.add('open');
        backdrop.classList.remove('hidden');
    }
});

btnToggleDetails.addEventListener('click', (e) => {
    e.stopPropagation();
    const isOpen = rightSidebar.classList.contains('open');
    closeAllDrawers();
    if (!isOpen) {
        rightSidebar.classList.add('open');
        backdrop.classList.remove('hidden');
    }
});

backdrop.addEventListener('click', closeAllDrawers);

// Touch support translation to canvas MouseEvents
function mapTouchEvent(e, type) {
    if (e.touches.length === 0 && type !== 'mouseup') return;
    const touch = e.touches[0] || e.changedTouches[0];
    const mouseEvt = new MouseEvent(type, {
        clientX: touch.clientX,
        clientY: touch.clientY,
        bubbles: true,
        cancelable: true
    });
    canvas.dispatchEvent(mouseEvt);
}

canvas.addEventListener('touchstart', (e) => {
    e.preventDefault();
    mapTouchEvent(e, 'mousedown');
}, { passive: false });

canvas.addEventListener('touchmove', (e) => {
    e.preventDefault();
    mapTouchEvent(e, 'mousemove');
}, { passive: false });

canvas.addEventListener('touchend', (e) => {
    e.preventDefault();
    mapTouchEvent(e, 'mouseup');
}, { passive: false });

// Bind 2D zoom buttons
document.getElementById('btn-2d-zoom-in').addEventListener('click', () => {
    state.scale = Math.min(60, state.scale + 2.5);
    draw();
});
document.getElementById('btn-2d-zoom-out').addEventListener('click', () => {
    state.scale = Math.max(5, state.scale - 2.5);
    draw();
});

// Bind mobile toggle checklist button
const btnToggleChecklist = document.getElementById('mobile-toggle-checklist');
if (btnToggleChecklist) {
    btnToggleChecklist.addEventListener('click', () => {
        if (typeof closeAllDrawers === 'function') closeAllDrawers();
        switchView('checklist');
    });
}

// ==========================================
// GUIDED WORKFLOW & DASHBOARD CONTROLLER
// ==========================================

// Global state defaults for Guided Mode
let storedMode = localStorage.getItem('roomflow_interface_mode') || 'guided';
if (storedMode === 'simple') storedMode = 'guided';
if (storedMode === 'professional') storedMode = 'advanced';
state.interfaceMode = storedMode;
state.currentStep = 1;
state.currentJobName = '';
state.guidedStep3Mode = 'choose';

// Sync settings class helper
if (!state.costing) {
    initDefaultCosting(state);
}

// Setup responsive UI view elements on startup
window.addEventListener('load', () => {
    // Apply initial interface modes
    setInterfaceMode(state.interfaceMode);
    
    // Bind navigation tab clicks
    document.querySelectorAll('.nav-bar-item, .nav-rail-item').forEach(el => {
        el.addEventListener('click', (e) => {
            const tab = e.currentTarget.getAttribute('data-tab');
            switchTab(tab);
        });
    });

    // Dashboard actions
    const startNewBtn = document.getElementById('btn-start-new-estimate');
    if (startNewBtn) {
        startNewBtn.addEventListener('click', startNewEstimateWorkflow);
    }
    const continueBtn = document.getElementById('btn-continue-last-estimate');
    if (continueBtn) {
        continueBtn.addEventListener('click', continueLastEstimateWorkflow);
    }

    const newJobForm = document.getElementById('new-job-form');
    if (newJobForm) {
        newJobForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const name = document.getElementById('nj-job-name').value.trim();
            const customerName = document.getElementById('nj-customer-name').value.trim();
            const inspectionDate = document.getElementById('nj-inspection-date').value;
            const address = document.getElementById('nj-property-address').value.trim();
            const phone = document.getElementById('nj-customer-phone').value.trim();
            const email = document.getElementById('nj-customer-email').value.trim();
            const estimator = document.getElementById('nj-estimator').value.trim();
            const initialArea = document.getElementById('nj-initial-area').value;
            const notes = document.getElementById('nj-notes').value.trim();

            if (!name || !customerName) {
                alert("Job Name and Customer Name are required!");
                return;
            }

            const jobs = getStoredJobs();
            if (jobs[name]) {
                alert("A job with this name already exists!");
                return;
            }

            let returnedJobId = null;
            if (typeof RoomFlowSync !== 'undefined' && RoomFlowSync.createCloudJobRecord) {
                try {
                    const dbJob = await RoomFlowSync.createCloudJobRecord(name, customerName, email, phone);
                    if (dbJob) {
                        returnedJobId = dbJob.id;
                    }
                } catch (err) {
                    console.warn("Cloud job insertion failed, proceeding locally first:", err);
                }
            }

            const initialOrgId = state.currentOrganization ? state.currentOrganization.id : '';
            const initialJob = getInitialProjectState(
                name,
                customerName,
                address,
                phone,
                email,
                estimator,
                inspectionDate,
                initialArea,
                notes,
                initialOrgId,
                returnedJobId
            );

            state.currentJobName = name;
            loadJobData(initialJob);

            window.autosaveJob();
            localStorage.setItem('roomflow_last_estimate', name);

            document.getElementById('new-job-modal').classList.add('hidden');
            
            // Navigate to Project Tab and Step 1 immediately
            state.currentStep = 1;
            switchTab('project');
            if (window.renderGuidedStep) window.renderGuidedStep();
        });
    }

    // Wizard navigation buttons
    const backBtn = document.getElementById('btn-guided-back');
    if (backBtn) backBtn.addEventListener('click', prevGuidedStep);
    
    const continueWizardBtn = document.getElementById('btn-guided-continue');
    if (continueWizardBtn) continueWizardBtn.addEventListener('click', nextGuidedStep);

    // Search and filters
    const searchInput = document.getElementById('jobs-search-input');
    if (searchInput) {
        searchInput.addEventListener('input', renderJobsList);
    }
    const statusFilter = document.getElementById('jobs-filter-status');
    if (statusFilter) {
        statusFilter.addEventListener('change', renderJobsList);
    }

    // Help Center triggers
    const helpBtn = document.getElementById('btn-dashboard-help');
    if (helpBtn) helpBtn.addEventListener('click', () => showModal('help-center-modal'));
    
    const showHelpBtn = document.getElementById('btn-show-help-modal');
    if (showHelpBtn) showHelpBtn.addEventListener('click', () => showModal('help-center-modal'));
    
    const closeHelpBtn = document.getElementById('btn-close-help');
    if (closeHelpBtn) closeHelpBtn.addEventListener('click', () => hideModal('help-center-modal'));

    // Diagnostics shortcuts
    const diagBtn = document.getElementById('btn-show-diagnostics-modal');
    if (diagBtn) diagBtn.addEventListener('click', () => {
        showModal('diagnostics-modal');
        if (window.RoomFlowSpatial) window.RoomFlowSpatial.performCapabilityDetection();
    });

    // Interface toggles settings
    const guidedPill = document.getElementById('pill-interface-guided');
    const advancedPill = document.getElementById('pill-interface-advanced');
    
    if (guidedPill) {
        guidedPill.addEventListener('click', () => {
            setInterfaceMode('guided');
            guidedPill.classList.add('active');
            if (advancedPill) advancedPill.classList.remove('active');
        });
    }
    
    if (advancedPill) {
        advancedPill.addEventListener('click', () => {
            setInterfaceMode('advanced');
            advancedPill.classList.add('active');
            if (guidedPill) guidedPill.classList.remove('active');
        });
    }

    // Initial render
    renderJobsList();
    renderTrashList();
    checkLastEstimate();
});

// Modal helpers
function showModal(id) {
    const m = document.getElementById(id);
    if (m) m.classList.remove('hidden');
}
function hideModal(id) {
    const m = document.getElementById(id);
    if (m) m.classList.add('hidden');
}

// Set layout interfaces
function setInterfaceMode(mode) {
    state.interfaceMode = mode;
    localStorage.setItem('roomflow_interface_mode', mode);
    
    const selectInterfaceMode = document.getElementById('select-app-interface-mode');
    if (selectInterfaceMode) {
        selectInterfaceMode.value = mode === 'guided' ? 'guided' : 'advanced';
    }
    
    const container = document.getElementById('app-container');
    if (!container) return;
    
    if (mode === 'guided') {
        container.classList.remove('interface-mode-advanced');
        container.classList.add('interface-mode-guided');
        // Hide standard CAD headers options, show dashboard
        switchTab('jobs');
    } else {
        container.classList.remove('interface-mode-guided');
        container.classList.add('interface-mode-advanced');
        // Restore professional layout tabs
        switchView('2d');
    }
}

// Tab Switching Routing
window.switchTab = function(tabName) {
    document.querySelectorAll('.nav-bar-item, .nav-rail-item').forEach(el => {
        el.classList.toggle('active', el.getAttribute('data-tab') === tabName);
    });

    if (tabName === 'jobs') {
        switchView('jobs');
        renderJobsList();
        if (window.RoomFlowSync?.refreshSharedJobs) {
            window.RoomFlowSync.refreshSharedJobs().catch(error => console.warn('Could not refresh shared jobs:', error));
        }
    } else if (tabName === 'project') {
        if (state.currentJobName) {
            switchView('guided');
            window.renderGuidedStep();
        } else {
            alert("Please start or select a job first!");
            switchTab('jobs');
        }
    } else if (tabName === 'add') {
        if (state.currentJobName) {
            state.currentStep = 3;
            state.guidedStep3Mode = 'choose';
            switchView('guided');
            window.renderGuidedStep();
        } else {
            alert("Please start or select a job first!");
            switchTab('jobs');
        }
    } else if (tabName === 'review') {
        if (state.currentJobName) {
            state.currentStep = 6;
            switchView('guided');
            window.renderGuidedStep();
        } else {
            alert("Please start or select a job first!");
            switchTab('jobs');
        }
    } else if (tabName === 'more') {
        switchView('more');
        renderTrashList();
    }
};

// Check for last unfinished estimate
function checkLastEstimate() {
    const lastJob = localStorage.getItem('roomflow_last_estimate');
    const container = document.getElementById('continue-last-estimate-container');
    if (lastJob && container) {
        const jobs = getStoredJobs();
        if (jobs[lastJob]) {
            container.style.display = 'flex';
            document.getElementById('continue-job-title').innerText = lastJob;
            const dateStr = new Date(jobs[lastJob].lastModified || Date.now()).toLocaleDateString();
            document.getElementById('continue-job-meta').innerText = `Last edited: ${dateStr}`;
        } else {
            container.style.display = 'none';
        }
    } else if (container) {
        container.style.display = 'none';
    }
}

// Helper to build initial project state object with schema defaults
function getInitialProjectState(jobName, customerName, customerAddress, customerPhone, customerEmail, estimator, inspectionDate, initialArea, notes, orgId, jobId = null) {
    const id = jobId || 'job_' + Math.random().toString(36).substr(2, 9);
    return {
        schemaVersion: '2.0.0',
        jobId: id,
        organizationId: orgId || (state.currentOrganization ? state.currentOrganization.id : ''),
        currentJobName: jobName,
        currentStep: 1,
        guidedStep3Mode: 'choose',
        currentLevelId: initialArea === 'basement' ? 'basement' : (initialArea === 'attic' ? 'attic' : (initialArea === 'mainfloor' ? 'mainfloor' : 'crawlspace')),
        levels: [
            { id: 'crawlspace', name: 'Crawlspace', elevation: -3, height: 4 },
            { id: 'basement', name: 'Basement', elevation: -8, height: 8 },
            { id: 'mainfloor', name: 'Main Floor', elevation: 0, height: 9 },
            { id: 'secondfloor', name: 'Second Floor', elevation: 9, height: 8 },
            { id: 'attic', name: 'Attic', elevation: 17, height: 7 }
        ],
        rooms: [],
        walls: [],
        roomConnections: [],
        doors: [],
        windows: [],
        openings: [],
        stairs: [],
        floorHatches: [],
        utilities: [],
        sumpPumps: [],
        dehumidifiers: [],
        dischargeLines: [],
        interiorPipes: [],
        stanchions: [],
        mainBeams: [],
        capturedMeasurements: [],
        costing: {
            customerName: customerName || '',
            customerAddress: customerAddress || '',
            customerPhone: customerPhone || '',
            customerEmail: customerEmail || '',
            estimator: estimator || '',
            inspectionDate: inspectionDate || '',
            notes: notes || '',
            workAreaSelection: initialArea || 'crawlspace',
            photos: [],
            settings: {
                targetGrossMargin: 40.0,
                salesTaxRate: 6.0,
                overhead: 15.0
            }
        },
        createdTimestamp: Date.now(),
        updatedTimestamp: Date.now(),
        revisionNumber: 1,
        syncState: 'synchronized'
    };
}

// Logical building wall-adjacency model compiler
window.rebuildLogicalLayout = function() {
    if (!state.rooms || state.rooms.length === 0) {
        state.walls = [];
        state.roomConnections = [];
        return;
    }
    
    const levelId = state.currentLevelId;
    const rooms = state.rooms.filter(r => r.levelId === levelId);
    
    const rawSegments = [];
    rooms.forEach(room => {
        const segs = getRoomSegments(room);
        segs.forEach(seg => {
            rawSegments.push({
                roomId: room.id,
                wallSide: seg.wall,
                x1: seg.x1,
                y1: seg.y1,
                x2: seg.x2,
                y2: seg.y2,
                height: room.height || 8,
                thickness: 0.5
            });
        });
    });

    const compiledWalls = [];
    const segmentsUsed = new Set();
    const sharedWalls = [];

    // Helper to calculate segment overlapping coordinates collinearly
    function checkOverlap(s1, s2) {
        const dist1 = getDistanceToLine(s2.x1, s2.y1, s1.x1, s1.y1, s1.x2, s1.y2);
        const dist2 = getDistanceToLine(s2.x2, s2.y2, s1.x1, s1.y1, s1.x2, s1.y2);

        const collinearTolerance = 0.25;
        if (dist1 > collinearTolerance || dist2 > collinearTolerance) return null;

        const dx = s1.x2 - s1.x1;
        const dy = s1.y2 - s1.y1;
        const lenSq = dx*dx + dy*dy;
        if (lenSq < 0.01) return null;

        function getProj(x, y) {
            return ((x - s1.x1) * dx + (y - s1.y1) * dy) / lenSq;
        }

        const p2_start = getProj(s2.x1, s2.y1);
        const p2_end = getProj(s2.x2, s2.y2);

        const minP1 = 0, maxP1 = 1;
        const minP2 = Math.min(p2_start, p2_end), maxP2 = Math.max(p2_start, p2_end);

        const overlapMin = Math.max(minP1, minP2);
        const overlapMax = Math.min(maxP1, maxP2);

        if (overlapMax - overlapMin > 0.05) {
            return {
                x1: s1.x1 + overlapMin * dx,
                y1: s1.y1 + overlapMin * dy,
                x2: s1.x1 + overlapMax * dx,
                y2: s1.y1 + overlapMax * dy
            };
        }
        return null;
    }

    function getDistanceToLine(px, py, x1, y1, x2, y2) {
        const l2 = (x2 - x1)**2 + (y2 - y1)**2;
        if (l2 === 0) return Math.sqrt((px - x1)**2 + (py - y1)**2);
        let t = ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / l2;
        t = Math.max(0, Math.min(1, t));
        return Math.sqrt((px - (x1 + t * (x2 - x1)))**2 + (py - (y1 + t * (y2 - y1)))**2);
    }

    for (let i = 0; i < rawSegments.length; i++) {
        for (let j = i + 1; j < rawSegments.length; j++) {
            const segA = rawSegments[i];
            const segB = rawSegments[j];
            if (segA.roomId === segB.roomId) continue;

            const overlap = checkOverlap(segA, segB);
            if (overlap) {
                const wallId = 'wall_' + segA.roomId + '_' + segB.roomId + '_' + i + '_' + j;
                const newWall = {
                    id: wallId,
                    levelId: levelId,
                    x1: overlap.x1,
                    y1: overlap.y1,
                    x2: overlap.x2,
                    y2: overlap.y2,
                    thickness: segA.thickness,
                    height: Math.max(segA.height, segB.height),
                    primaryRoomId: segA.roomId,
                    secondaryRoomId: segB.roomId,
                    primarySideWork: {},
                    secondarySideWork: {},
                    type: 'interior',
                    notes: `Shared wall between ${rooms.find(r=>r.id===segA.roomId)?.name || 'Room A'} and ${rooms.find(r=>r.id===segB.roomId)?.name || 'Room B'}`
                };
                sharedWalls.push(newWall);
                compiledWalls.push(newWall);
                segmentsUsed.add(i);
                segmentsUsed.add(j);
            }
        }
    }

    for (let i = 0; i < rawSegments.length; i++) {
        if (!segmentsUsed.has(i)) {
            const seg = rawSegments[i];
            const wallId = 'wall_' + seg.roomId + '_' + seg.wallSide + '_' + i;
            compiledWalls.push({
                id: wallId,
                levelId: levelId,
                x1: seg.x1,
                y1: seg.y1,
                x2: seg.x2,
                y2: seg.y2,
                thickness: seg.thickness,
                height: seg.height,
                primaryRoomId: seg.roomId,
                secondaryRoomId: null,
                primarySideWork: {},
                secondarySideWork: null,
                type: 'exterior',
                notes: `Exterior wall of ${rooms.find(r=>r.id===seg.roomId)?.name || 'Room'}`
            });
        }
    }

    state.walls = compiledWalls;

    const adjacency = [];
    sharedWalls.forEach(w => {
        const doorsHosted = (state.doors || []).filter(d => d.hostWallId === w.id);
        const openingsHosted = (state.openings || []).filter(o => o.hostWallId === w.id);
        const hasOpening = (doorsHosted.length > 0 || openingsHosted.length > 0);
        
        adjacency.push({
            id: 'conn_' + w.id,
            levelId: levelId,
            roomA: w.primaryRoomId,
            roomB: w.secondaryRoomId,
            sharedWallId: w.id,
            type: hasOpening ? 'door' : 'shared_wall',
            traversable: hasOpening,
            notes: `Adjacency of ${w.primaryRoomId} to ${w.secondaryRoomId}`
        });
    });
    
    state.roomConnections = adjacency;
};

// Start/Continue workflow
function startNewEstimateWorkflow() {
    if (!state.currentOrganization) {
        alert("Please select a workspace/company organization under Settings first.");
        switchTab('more');
        return;
    }
    
    const modal = document.getElementById('new-job-modal');
    if (modal) {
        modal.classList.remove('hidden');
        const dateInput = document.getElementById('nj-inspection-date');
        if (dateInput) {
            dateInput.value = new Date().toISOString().split('T')[0];
        }
    }
}

function continueLastEstimateWorkflow() {
    const lastJob = localStorage.getItem('roomflow_last_estimate');
    if (lastJob) {
        loadJobByName(lastJob);
    }
}

window.loadJobByName = function(jobName) {
    const jobs = getStoredJobs();
    const data = jobs[jobName];
    if (data) {
        state.currentJobName = jobName;
        localStorage.setItem('roomflow_last_estimate', jobName);
        loadJobData(data);
        
        state.currentStep = 1;
        state.guidedStep3Mode = 'choose';
        switchTab('project');
    }
};

// Jobs List Management
function getStoredJobs() {
    try {
        const stored = localStorage.getItem('roomflow_jobs');
        return stored ? JSON.parse(stored) : {};
    } catch(e) {
        console.error(e);
        return {};
    }
}

window.autosaveJob = function() {
    if (!state.currentJobName) return;

    const now = Date.now();
    state.updatedTimestamp = now;
    state.revisionNumber = Number(state.revisionNumber || 0) + 1;
    state.syncState = 'pending';
    const projectData = {
        schemaVersion: '2.0.0',
        jobId: state.jobId || null,
        organizationId: state.currentOrganization?.id || localStorage.getItem('roomflow_active_org_id') || '',
        currentJobName: state.currentJobName,
        currentStep: state.currentStep || 1,
        guidedStep3Mode: state.guidedStep3Mode || 'choose',
        customerName: state.costing ? state.costing.customerName : '',
        customerAddress: state.costing ? state.costing.customerAddress : '',
        levels: state.levels || [],
        rooms: state.rooms,
        walls: state.walls || [],
        roomConnections: state.roomConnections || [],
        doors: state.doors || [],
        windows: state.windows || [],
        openings: state.openings || [],
        stairs: state.stairs || [],
        utilities: state.utilities || [],
        sumpPumps: state.sumpPumps,
        dehumidifiers: state.dehumidifiers || [],
        dischargeLines: state.dischargeLines,
        floorHatches: state.floorHatches,
        interiorPipes: state.interiorPipes,
        stanchions: state.stanchions,
        mainBeams: state.mainBeams,
        currentLevelId: state.currentLevelId,
        capturedMeasurements: state.capturedMeasurements || [],
        costing: state.costing,
        leadIntake: state.leadIntake || null,
        createdTimestamp: state.createdTimestamp || now,
        updatedTimestamp: now,
        revisionNumber: state.revisionNumber,
        syncState: 'pending',
        lastModified: now
    };
    
    const jobs = getStoredJobs();
    jobs[state.currentJobName] = projectData;
    localStorage.setItem('roomflow_jobs', JSON.stringify(jobs));
    
    const statusText = document.getElementById('save-status-text');
    if (statusText) statusText.innerText = "Saved";
    
    if (typeof window.RoomFlowSync !== 'undefined' && window.RoomFlowSync.enqueueOffline) {
        window.RoomFlowSync.enqueueOffline(state.currentJobName, projectData).then(() => {
            window.RoomFlowSync.processSyncQueue();
        });
    }
};

// Search & Filter rendering
function renderJobsList() {
    const list = document.getElementById('recent-jobs-list');
    if (!list) return;

    const escapeJobsHtml = value => String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
    const jobs = getStoredJobs();
    const query = (document.getElementById('jobs-search-input')?.value || '').trim().toLowerCase();
    const filter = document.getElementById('jobs-filter-status')?.value || 'all';
    
    const activeOrganizationId = state.currentOrganization?.id || localStorage.getItem('roomflow_active_org_id') || '';
    const jobKeys = Object.keys(jobs)
        .filter(name => !activeOrganizationId || !jobs[name]?.organizationId || jobs[name].organizationId === activeOrganizationId)
        .sort((a,b) => (jobs[b].lastModified || 0) - (jobs[a].lastModified || 0));
    
    let html = '';
    let matchCount = 0;
    
    jobKeys.forEach(k => {
        const j = jobs[k];
        const cName = (j.customerName || k).toLowerCase();
        const cAddr = (j.customerAddress || '').toLowerCase();
        
        // Search filter
        if (query && !cName.includes(query) && !cAddr.includes(query)) return;
        
        // Completion status check
        const isComplete = j.rooms && j.rooms.length > 0 && j.costing && j.costing.customerName;
        if (filter === 'complete' && !isComplete) return;
        if (filter === 'incomplete' && isComplete) return;
        
        matchCount++;
        const dateStr = new Date(j.lastModified || Date.now()).toLocaleDateString();
        const progress = isComplete ? 100 : Math.round(((j.rooms?.length ? 1 : 0) + (j.costing?.customerName ? 1 : 0)) * 50);
        const cloudBadge = j.sharedFromCloud
            ? '<span style="display:inline-flex;align-items:center;padding:.18rem .45rem;border-radius:999px;background:rgba(59,130,246,.14);color:#93c5fd;font-size:.68rem;font-weight:700;margin-left:.4rem;">Cloud Shared</span>'
            : '<span style="display:inline-flex;align-items:center;padding:.18rem .45rem;border-radius:999px;background:rgba(245,158,11,.12);color:#fbbf24;font-size:.68rem;font-weight:700;margin-left:.4rem;">Local</span>';
        const displayStatus = escapeJobsHtml(j.cloudStatus || (isComplete ? 'Complete' : 'In Progress'));
        
        html += `
            <div class="job-row-card">
                <div class="job-info-cell">
                    <h4>${escapeJobsHtml(k)} ${cloudBadge}</h4>
                    <p>${escapeJobsHtml(j.customerAddress || 'No Address Specified')} | Edited: ${escapeJobsHtml(dateStr)}</p>
                </div>
                <div class="job-progress-cell">
                    <span style="font-size:0.75rem; font-weight:600; color:#cbd5e1;">Progress: ${progress}%</span>
                    <div class="job-progress-bar-bg">
                        <div class="job-progress-bar-fill" style="width: ${progress}%;"></div>
                    </div>
                </div>
                <div style="font-size: 0.8rem; color: #94a3b8;">
                    <span style="color:${isComplete ? '#10b981' : '#f59e0b'}; font-weight:600;">${displayStatus}</span>
                </div>
                <div class="job-actions-cell">
                    <button data-job-action="open" data-job-name="${escapeJobsHtml(k)}" class="btn-primary" style="padding:0.4rem 0.8rem; font-size:0.75rem;"><i data-lucide="arrow-right" style="width:12px; height:12px;"></i> Open</button>
                    <button data-job-action="duplicate" data-job-name="${escapeJobsHtml(k)}" class="btn-secondary" style="padding:0.4rem 0.8rem; font-size:0.75rem;"><i data-lucide="copy" style="width:12px; height:12px;"></i> Duplicate</button>
                    <button data-job-action="delete" data-job-name="${escapeJobsHtml(k)}" class="btn-secondary" title="${j.sharedFromCloud ? 'Removes this device copy; Refresh Shared can restore it.' : 'Move this local job to Trash.'}" style="padding:0.4rem 0.8rem; font-size:0.75rem; color:#ef4444;"><i data-lucide="trash-2" style="width:12px; height:12px;"></i> ${j.sharedFromCloud ? 'Remove Local' : 'Delete'}</button>
                </div>
            </div>
        `;
    });
    
    if (matchCount === 0) {
        html = `
            <div style="text-align: center; padding: 2rem; color: #64748b; font-size: 0.85rem;">
                No matching estimates found.
            </div>
        `;
    }
    
    list.innerHTML = html;
    list.querySelectorAll('[data-job-action]').forEach(button => {
        button.addEventListener('click', () => {
            const jobName = button.dataset.jobName;
            if (button.dataset.jobAction === 'open') window.loadJobByName(jobName);
            else if (button.dataset.jobAction === 'duplicate') window.duplicateJob(jobName);
            else if (button.dataset.jobAction === 'delete') window.deleteJobWithTrash(jobName);
        });
    });
    if (window.lucide) window.lucide.createIcons();
}

window.renderRoomFlowJobsList = renderJobsList;

// Duplicate estimate
window.duplicateJob = function(jobName) {
    const jobs = getStoredJobs();
    const orig = jobs[jobName];
    if (!orig) return;
    
    const copyName = jobName + " (Copy)";
    const copyData = JSON.parse(JSON.stringify(orig));
    copyData.lastModified = Date.now();
    copyData.currentJobName = copyName;
    copyData.jobId = null;
    copyData.sharedFromCloud = false;
    copyData.syncState = 'pending';
    delete copyData.cloudUpdatedAt;
    delete copyData.cloudStatus;
    
    jobs[copyName] = copyData;
    localStorage.setItem('roomflow_jobs', JSON.stringify(jobs));
    renderJobsList();
};

// Trash Bin System
window.deleteJobWithTrash = function(jobName) {
    if (!confirm(`Are you sure you want to delete job "${jobName}"?`)) return;
    
    const jobs = getStoredJobs();
    const deleted = jobs[jobName];
    if (!deleted) return;
    
    // Save to Trash localstorage
    let trash = {};
    try {
        const stored = localStorage.getItem('roomflow_jobs_trash');
        if (stored) trash = JSON.parse(stored);
    } catch(e) {
        console.error(e);
    }
    
    trash[jobName] = deleted;
    localStorage.setItem('roomflow_jobs_trash', JSON.stringify(trash));
    
    // Remove from active jobs
    delete jobs[jobName];
    localStorage.setItem('roomflow_jobs', JSON.stringify(jobs));
    
    // If it was the active last estimate, clear
    if (localStorage.getItem('roomflow_last_estimate') === jobName) {
        localStorage.removeItem('roomflow_last_estimate');
    }
    if (state.currentJobName === jobName) {
        state.currentJobName = '';
    }
    
    // Show Restore Toast Banner
    showTrashToastBanner(jobName);
    
    renderJobsList();
    renderTrashList();
    checkLastEstimate();
};

function showTrashToastBanner(jobName) {
    // Remove existing toast if any
    const existing = document.getElementById('trash-toast-banner');
    if (existing) existing.remove();
    
    const banner = document.createElement('div');
    banner.id = 'trash-toast-banner';
    banner.className = 'trash-restore-toast-banner';
    banner.innerHTML = `
        <span>Job "${jobName}" deleted.</span>
        <button onclick="window.restoreJob('${jobName}')">Undo</button>
    `;
    
    document.body.appendChild(banner);
    
    // Auto-remove after 6 seconds
    setTimeout(() => {
        if (banner && banner.parentNode) banner.remove();
    }, 6000);
}

window.restoreJob = function(jobName) {
    let trash = {};
    try {
        const stored = localStorage.getItem('roomflow_jobs_trash');
        if (stored) trash = JSON.parse(stored);
    } catch(e) {
        console.error(e);
    }
    
    const restored = trash[jobName];
    if (!restored) return;
    
    const jobs = getStoredJobs();
    jobs[jobName] = restored;
    localStorage.setItem('roomflow_jobs', JSON.stringify(jobs));
    
    delete trash[jobName];
    localStorage.setItem('roomflow_jobs_trash', JSON.stringify(trash));
    
    // Clean banner
    const banner = document.getElementById('trash-toast-banner');
    if (banner) banner.remove();
    
    renderJobsList();
    renderTrashList();
    checkLastEstimate();
};

function renderTrashList() {
    const list = document.getElementById('trash-jobs-list');
    if (!list) return;
    
    let trash = {};
    try {
        const stored = localStorage.getItem('roomflow_jobs_trash');
        if (stored) trash = JSON.parse(stored);
    } catch(e) {
        console.error(e);
    }
    
    const keys = Object.keys(trash);
    if (keys.length === 0) {
        list.innerHTML = `<div style="text-align: center; font-size: 0.8rem; color: #64748b; padding: 1rem 0;">Trash bin is empty.</div>`;
        return;
    }
    
    let html = '';
    keys.forEach(k => {
        html += `
            <div class="trash-job-row" style="display:flex; justify-content:space-between; align-items:center; padding:0.35rem 0.5rem; background:rgba(255,255,255,0.03); border-radius:6px; font-size:0.8rem; border:1px solid rgba(255,255,255,0.05);">
                <span class="trash-job-name" style="font-weight:600; color:white;">${k}</span>
                <button onclick="window.restoreJob('${k}')" class="btn-primary" style="padding:0.25rem 0.5rem; font-size:0.75rem;"><i data-lucide="refresh-cw" style="width:10px; height:10px; display:inline-block; vertical-align:middle; margin-right:2px;"></i> Restore</button>
            </div>
        `;
    });
    
    list.innerHTML = html;
    if (window.lucide) window.lucide.createIcons();
}

// Guided Steps Wizard Navigation Controls
function prevGuidedStep() {
    if (state.currentStep > 1) {
        state.currentStep--;
        window.renderGuidedStep();
    } else {
        // Return to jobs list
        switchTab('jobs');
    }
}

function nextGuidedStep() {
    if (state.currentStep < 9) {
        state.currentStep++;
        window.renderGuidedStep();
    } else {
        // Step 9 finish estimate, return to dashboard
        switchTab('jobs');
    }
}

// Viewport Overrides for drawings returns
window.returnFromDrawing = function() {
    switchView('guided');
    state.guidedStep3Mode = 'choose';
    window.renderGuidedStep();
};

window.returnFromScanning = function() {
    if (typeof stopARSession === 'function') {
        stopARSession();
    }
    switchView('guided');
    state.guidedStep3Mode = 'choose';
    window.renderGuidedStep();
};


