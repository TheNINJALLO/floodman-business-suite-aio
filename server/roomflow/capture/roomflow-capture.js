(() => {
  'use strict';
  if (window.__FLOODMAN_ROOMFLOW_CAPTURE_V2__) return;
  window.__FLOODMAN_ROOMFLOW_CAPTURE_V2__ = true;

  const geometry = window.RoomFlowCaptureGeometry;
  if (!geometry) {
    console.error('RoomFlow Capture geometry module is unavailable.');
    return;
  }

  const API = '/office/api/roomflow';
  const OUTBOX_KEY = 'floodman_roomflow_capture_outbox_v2';
  const DRAFT_KEY = 'floodman_roomflow_capture_draft_v2';
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const clone = value => JSON.parse(JSON.stringify(value ?? null));
  const uuid = () => crypto.randomUUID ? crypto.randomUUID() : `capture-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const escapeHtml = value => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  const number = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
  const round = (value, places = 2) => Number(number(value).toFixed(places));

  const model = {
    step: 'setup',
    rooms: [],
    room: null,
    revision: 0,
    history: new geometry.GeometryHistory(),
    capabilities: { modes: ['manual'], preferredMode: 'manual' },
    opener: null,
    nativeRequestId: '',
    selectedMode: 'manual',
    originalVertices: [],
    lockedWalls: new Set(),
    showOriginal: false,
    planView: { zoom: 1, panX: 0, panY: 0, rotation: 0 },
    status: '',
    statusKind: 'info',
    busy: false,
  };

  function appState() { return window.state || {}; }
  function activeJobId() {
    return String(window.FloodmanRoomFlow?.context?.job?.id || appState().floodmanRoomFlowJobId || appState().floodmanJobId || '').trim();
  }
  function activeWorkspaceId() {
    return String(window.FloodmanRoomFlow?.activeWorkspace?.id || window.FloodmanRoomFlow?.context?.workspace?.id || appState().workspaceId || appState().organizationId || '').trim();
  }
  function activeLevelId() { return String(appState().currentLevelId || 'main'); }
  function setStatus(message, kind = 'info') {
    model.status = String(message || ''); model.statusKind = kind;
    const node = $('#fm-capture-status'); if (node) { node.textContent = model.status; node.dataset.kind = kind; }
  }
  function modeLabel(mode) {
    return ({
      'android-arcore-depth': 'ARCore with depth',
      'android-arcore-guided': 'Guided ARCore',
      'apple-roomplan': 'Apple RoomPlan',
      'apple-arkit-lidar': 'Guided ARKit with LiDAR',
      'apple-arkit-guided': 'Guided ARKit',
      'camera-estimate': 'Camera Estimate',
      manual: 'Manual entry',
    })[mode] || String(mode || 'Device scan');
  }

  async function fetchJson(path, options = {}) {
    const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', ...options });
    const text = await response.text(); let value = {};
    try { value = text ? JSON.parse(text) : {}; } catch (_) { value = {}; }
    if (!response.ok) {
      const error = new Error(value.detail || value.message || `Floodman returned ${response.status}`);
      error.status = response.status; error.code = response.status === 409 ? 'CONFLICT' : response.status === 401 ? 'AUTH' : 'API';
      throw error;
    }
    return value;
  }

  function outbox() { try { const value = JSON.parse(localStorage.getItem(OUTBOX_KEY) || '[]'); return Array.isArray(value) ? value : []; } catch (_) { return []; } }
  function saveDraft() { if (model.room) localStorage.setItem(DRAFT_KEY, JSON.stringify({ jobId: activeJobId(), workspaceId: activeWorkspaceId(), room: model.room, revision: model.revision, originalVertices: model.originalVertices, savedAt: new Date().toISOString() })); }
  function clearDraft() { localStorage.removeItem(DRAFT_KEY); }
  function recoverDraft() {
    try {
      const value = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null');
      if (!value?.room || value.jobId !== activeJobId() || value.workspaceId !== activeWorkspaceId()) return false;
      model.room = normalizeNativeResult(value.room); model.revision = number(value.revision); model.originalVertices = clone(value.originalVertices?.length ? value.originalVertices : model.room.vertices); resetReviewTools(); model.history.reset(model.room.vertices); model.step = 'review'; setStatus('Recovered an unsaved room from this device. Review it, then save or rescan.', 'warn'); return true;
    } catch (_) { return false; }
  }
  function nativePersistenceAvailable() {
    return Boolean(window.FloodmanNative?.roomFlowCaptureV2 || window.webkit?.messageHandlers?.RoomFlowCaptureV2 || window.RoomFlowNativeBridge?.postMessage);
  }
  function saveOutbox(items) { localStorage.setItem(OUTBOX_KEY, JSON.stringify(items.slice(-200))); }
  function queueOperation(operation) {
    const items = outbox();
    if (!items.some(value => value.operationId === operation.operationId)) items.push({ ...operation, jobId: activeJobId(), workspaceId: activeWorkspaceId(), queuedAt: new Date().toISOString() });
    saveOutbox(items);
  }
  async function replayOutbox() {
    const jobId = activeJobId(); if (!jobId) return;
    if (nativePersistenceAvailable()) {
      try {
        const data = await bridge.request('captureOutboxReplayRequested', { jobId, workspaceId: activeWorkspaceId() }, 30000);
        const succeeded = (data.results || []).filter(value => value.ok).length;
        if (succeeded) setStatus(`${succeeded} saved room change${succeeded === 1 ? '' : 's'} synchronized.`, 'good');
      } catch (_) { /* The native app keeps its durable outbox until the server is reachable. */ }
      return;
    }
    if (!navigator.onLine) return;
    const all = outbox(); const pending = all.filter(value => value.jobId === jobId && (!value.workspaceId || value.workspaceId === activeWorkspaceId()));
    if (!pending.length) return;
    try {
      const data = await fetchJson(`${API}/jobs/${encodeURIComponent(jobId)}/capture/operations`, {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ operations: pending })
      });
      const succeeded = new Set((data.results || []).filter(value => value.ok).map(value => value.operationId));
      saveOutbox(all.filter(value => !succeeded.has(value.operationId)));
      if (data.complete) setStatus(`${succeeded.size} saved room change${succeeded.size === 1 ? '' : 's'} synchronized.`, 'good');
      else if (data.results?.length) setStatus(data.results[data.results.length - 1].message || 'A queued room needs review.', 'warn');
    } catch (_) { /* Keep durable operations for the next online retry. */ }
  }

  const bridge = window.RoomFlowCaptureBridgeV2 = {
    version: 2,
    pending: new Map(),
    request(type, payload = {}, timeoutMs = 120000) {
      const requestId = uuid();
      const sessionId = String(payload.sessionId || uuid());
      const copiedPayload = clone(payload);
      if (copiedPayload && typeof copiedPayload === 'object' && !Array.isArray(copiedPayload) && !copiedPayload.sessionId) copiedPayload.sessionId = sessionId;
      const envelope = { version: 2, sessionId, type, requestId, payload: copiedPayload };
      const serialized = JSON.stringify(envelope);
      if (serialized.length > 262144) return Promise.reject(new Error('The device capture request is too large.'));
      return new Promise((resolve, reject) => {
        const timer = window.setTimeout(() => { this.pending.delete(requestId); reject(new Error('The device capture request timed out. Try again or enter the room manually.')); }, timeoutMs);
        this.pending.set(requestId, { resolve, reject, timer, sessionId, type });
        try {
          if (window.FloodmanNative?.roomFlowCaptureV2) window.FloodmanNative.roomFlowCaptureV2(serialized);
          else if (window.webkit?.messageHandlers?.RoomFlowCaptureV2) window.webkit.messageHandlers.RoomFlowCaptureV2.postMessage(envelope);
          else if (window.RoomFlowNativeBridge?.postMessage) window.RoomFlowNativeBridge.postMessage(envelope);
          else throw new Error('Device scanning is not available in this browser. Enter the room manually.');
        } catch (error) {
          window.clearTimeout(timer); this.pending.delete(requestId); reject(error);
        }
      });
    },
    receive(value) {
      let envelope = value;
      if (typeof envelope === 'string') { try { envelope = JSON.parse(envelope); } catch (_) { return false; } }
      if (!envelope || envelope.version !== 2 || !envelope.requestId || !envelope.sessionId || !envelope.type) return false;
      const pending = this.pending.get(envelope.requestId); if (!pending) return false;
      if (pending.sessionId !== envelope.sessionId) return false;
      if (['trackingStateChanged', 'reticleChanged', 'pointPinned', 'pointRemoved', 'scanReset', 'heightMeasured', 'openingCaptured', 'sessionStarted'].includes(envelope.type)) { window.RoomFlowCapture?.receiveProgress(envelope); return true; }
      window.clearTimeout(pending.timer); this.pending.delete(envelope.requestId);
      if (envelope.ok) pending.resolve(envelope.payload || {}); else pending.reject(new Error(envelope.error?.message || 'Device capture failed.'));
      return true;
    }
  };

  async function loadCapabilities() {
    try {
      const value = await bridge.request('capabilitiesRequested', {}, 5000);
      const modes = Array.isArray(value.modes) ? value.modes.filter(Boolean) : [];
      model.capabilities = { ...value, modes: ['manual', ...modes.filter(mode => mode !== 'manual')], preferredMode: value.preferredMode || modes[0] || 'manual' };
    } catch (_) { model.capabilities = { modes: ['manual'], preferredMode: 'manual' }; }
    render();
  }

  function baseMetadata(mode = 'manual') {
    return {
      captureMode: mode,
      platform: /android/i.test(navigator.userAgent) ? 'android' : /iPad|iPhone|iPod/i.test(navigator.userAgent) ? 'ios' : 'web',
      startedAt: new Date().toISOString(), completedAt: null, pointCount: 0, averageConfidence: mode === 'manual' ? 1 : 0,
      depthValidatedPointCount: 0, automaticCorrectionCount: 0, manualCorrectionCount: 0,
      verificationRequired: mode !== 'manual', rawCaptureRetained: false,
    };
  }

  function blankRoom() {
    return {
      schemaVersion: 2, sessionId: uuid(), jobId: activeJobId(), workspaceId: activeWorkspaceId(), levelId: activeLevelId(), roomId: uuid(),
      name: `Room ${model.rooms.length + 1}`, roomType: 'other', units: 'ft', height: 8, vertices: [], openings: [], affectedAreas: [], scanMetadata: baseMetadata('manual')
    };
  }

  function normalizedVertices(vertices, source = 'manual') {
    return geometry.validatePolygon(vertices).map((value, index) => ({ id: `vertex-${index + 1}`, x: value.x, y: value.y, confidence: 1, depthValidated: false, source }));
  }

  function roomMeasurements(room = model.room) { return geometry.measurements(room.vertices, room.height, room.openings || []); }
  function boundsRoom(room) { const bounds = geometry.boundingBox(room.vertices); room.w = bounds.width; room.l = bounds.length; room.h = room.height; room.measurements = roomMeasurements(room); return room; }
  function updateHistory(vertices) { model.history.apply(vertices); model.room.vertices = normalizedVertices(model.history.value(), 'manual-corrected'); model.room.scanMetadata.manualCorrectionCount += 1; boundsRoom(model.room); saveDraft(); }
  function resetReviewTools() { model.lockedWalls = new Set(); model.showOriginal = false; model.planView = { zoom: 1, panX: 0, panY: 0, rotation: 0 }; }
  function rotateRoom(degrees) {
    updateHistory(geometry.rotate(model.room.vertices, degrees));
    setStatus(`Room rotated ${Math.abs(degrees)}° ${degrees < 0 ? 'left' : 'right'}.`, 'good');
  }
  function addVertexAfter(index) {
    if ((model.room.openings || []).length) throw new Error('Remove openings before changing the number of room corners.');
    const vertices = geometry.points(model.room.vertices); const next = (index + 1) % vertices.length;
    vertices.splice(index + 1, 0, { x: (vertices[index].x + vertices[next].x) / 2, y: (vertices[index].y + vertices[next].y) / 2 });
    updateHistory(vertices);
  }
  function removeVertex(index) {
    if (model.room.vertices.length <= 3) throw new Error('A room must keep at least three corners.');
    if ((model.room.openings || []).length) throw new Error('Remove openings before changing the number of room corners.');
    const vertices = geometry.points(model.room.vertices); vertices.splice(index, 1); updateHistory(vertices);
  }

  function buildManualRoom(form) {
    const data = new FormData(form); const shape = String(data.get('shape') || 'rectangle'); let vertices;
    if (shape === 'rectangle') {
      const width = number(data.get('width')); const length = number(data.get('length'));
      vertices = [{x: 0, y: 0}, {x: width, y: 0}, {x: width, y: length}, {x: 0, y: length}];
    } else if (shape === 'l-shape') {
      const width = number(data.get('width')); const length = number(data.get('length')); const cutWidth = number(data.get('cutWidth')); const cutLength = number(data.get('cutLength'));
      if (cutWidth <= 0 || cutLength <= 0 || cutWidth >= width || cutLength >= length) throw new Error('The L-shape cutout must be smaller than the overall room.');
      vertices = [{x: 0, y: 0}, {x: width, y: 0}, {x: width, y: length - cutLength}, {x: width - cutWidth, y: length - cutLength}, {x: width - cutWidth, y: length}, {x: 0, y: length}];
    } else {
      vertices = String(data.get('vertices') || '').split(/\n+/).filter(Boolean).map((line, index) => {
        const values = line.split(/[ ,]+/).filter(Boolean).map(Number);
        if (values.length !== 2 || values.some(value => !Number.isFinite(value))) throw new Error(`Point ${index + 1} must be written as x, y.`);
        return { x: values[0], y: values[1] };
      });
    }
    const room = model.room || blankRoom();
    room.name = String(data.get('name') || '').trim(); room.roomType = String(data.get('roomType') || 'other'); room.levelId = String(data.get('levelId') || 'main'); room.height = number(data.get('height'), 8); room.measurementNotes = String(data.get('measurementNotes') || '').trim();
    if (!room.name) throw new Error('Enter a room name.');
    room.vertices = normalizedVertices(vertices); room.openings = room.openings || []; room.scanMetadata = { ...baseMetadata('manual'), ...room.scanMetadata, captureMode: 'manual', completedAt: new Date().toISOString(), pointCount: vertices.length, averageConfidence: 1, verificationRequired: false, rawCaptureRetained: false };
    model.room = boundsRoom(room); model.originalVertices = clone(model.room.vertices); resetReviewTools(); model.history.reset(model.room.vertices); model.step = 'review'; saveDraft();
  }

  function normalizeNativeResult(result) {
    const source = result.room || result; const unitScale = source.units === 'm' ? geometry.FEET_PER_METER : 1;
    const converted = clone(source);
    converted.vertices = (source.vertices || []).map(value => ({ ...value, x: number(value.x) * unitScale, y: number(value.y) * unitScale }));
    converted.height = number(source.height, 2.4384) * unitScale;
    converted.openings = (source.openings || []).map(value => ({ ...value, offset: number(value.offset) * unitScale, width: number(value.width) * unitScale, height: number(value.height) * unitScale, sillHeight: number(value.sillHeight) * unitScale }));
    converted.schemaVersion = 2; converted.units = 'ft'; converted.jobId = activeJobId(); converted.workspaceId = activeWorkspaceId();
    converted.roomId = String(converted.roomId || uuid()); converted.sessionId = String(converted.sessionId || uuid());
    converted.levelId = String(converted.levelId || activeLevelId()); converted.name = String(converted.name || model.room?.name || `Room ${model.rooms.length + 1}`); converted.roomType = String(converted.roomType || model.room?.roomType || 'other');
    converted.vertices = geometry.validatePolygon(converted.vertices).map((value, index) => ({ ...(source.vertices?.[index] || {}), id: String(source.vertices?.[index]?.id || `vertex-${index + 1}`), x: value.x, y: value.y, confidence: Math.max(0, Math.min(1, number(source.vertices?.[index]?.confidence, .65))), depthValidated: Boolean(source.vertices?.[index]?.depthValidated), source: String(source.vertices?.[index]?.source || result.captureMode || 'native') }));
    converted.openings = geometry.validateOpenings(converted.openings, converted.vertices, converted.height);
    converted.affectedAreas = Array.isArray(converted.affectedAreas) ? converted.affectedAreas : [];
    converted.scanMetadata = { ...baseMetadata(result.captureMode || 'native'), ...(converted.scanMetadata || {}), completedAt: converted.scanMetadata?.completedAt || new Date().toISOString(), pointCount: converted.vertices.length, rawCaptureRetained: false };
    return boundsRoom(converted);
  }

  async function startNativeCapture() {
    if (!activeJobId()) return setStatus('Save the active job to Floodman before scanning a room.', 'warn');
    const mode = model.selectedMode || model.capabilities.preferredMode;
    if (!mode || mode === 'manual') { model.step = 'manual'; render(); return; }
    model.step = 'scanning'; model.busy = true; render();
    try {
      const result = await bridge.request('roomCaptureStarted', {
        mode, jobId: activeJobId(), workspaceId: activeWorkspaceId(), roomId: model.room?.roomId || uuid(),
        name: model.room?.name || `Room ${model.rooms.length + 1}`, roomType: model.room?.roomType || 'other', levelId: model.room?.levelId || activeLevelId(), defaultHeightFeet: model.room?.height || 8
      });
      model.room = normalizeNativeResult(result); model.originalVertices = clone(model.room.vertices); resetReviewTools(); model.history.reset(model.room.vertices); model.revision = 0; model.step = 'review'; saveDraft(); setStatus('Device capture received and saved locally. Review every measurement before synchronizing.', 'good');
    } catch (error) { model.step = 'setup'; setStatus(error.message, 'warn'); }
    finally { model.busy = false; render(); }
  }

  async function cancelNativeCapture() {
    try { await bridge.request('roomCaptureCancelled', { requestId: model.nativeRequestId }, 5000); } catch (_) { }
    model.busy = false; model.step = 'setup'; render();
  }

  function applyRoomToUpstream(room) {
    const state = appState(); state.rooms = Array.isArray(state.rooms) ? state.rooms : [];
    const index = state.rooms.findIndex(value => String(value.roomId || value.id || '') === room.roomId);
    if (index >= 0) state.rooms[index] = clone(room); else state.rooms.push(clone(room));
    state.capturedMeasurements = Array.isArray(state.capturedMeasurements) ? state.capturedMeasurements : [];
    const measurement = { id: `capture-${room.roomId}`, roomId: room.roomId, schemaVersion: 2, source: room.scanMetadata.captureMode, ...room.measurements };
    const measurementIndex = state.capturedMeasurements.findIndex(value => value.id === measurement.id);
    if (measurementIndex >= 0) state.capturedMeasurements[measurementIndex] = measurement; else state.capturedMeasurements.push(measurement);
    state.captureRevisions = state.captureRevisions && typeof state.captureRevisions === 'object' ? state.captureRevisions : {};
    state.captureRevisions[room.roomId] = model.revision;
    state.captureSchemaVersion = 2; state.syncState = 'pending';
    window.autosaveJob?.(); window.draw?.(); window.renderGuidedStep?.(); window.updateGlobalStats?.();
  }

  async function saveRoom() {
    if (!model.room || model.busy) return;
    const jobId = activeJobId(); if (!jobId) return setStatus('Save the active job to Floodman before saving captured rooms.', 'warn');
    model.busy = true; render();
    model.room.scanMetadata.completedAt = model.room.scanMetadata.completedAt || new Date().toISOString();
    model.room.scanMetadata.rawCaptureRetained = false; boundsRoom(model.room);
    const operation = { action: model.revision ? 'UPDATE' : 'CREATE', operationId: uuid(), roomId: model.room.roomId, expectedRevision: model.revision, room: clone(model.room) };
    const path = `${API}/jobs/${encodeURIComponent(jobId)}/capture/rooms${model.revision ? `/${encodeURIComponent(model.room.roomId)}` : ''}`;
    try {
      const result = nativePersistenceAvailable()
        ? await bridge.request('captureOperationQueued', { jobId, workspaceId: activeWorkspaceId(), operation })
        : await fetchJson(path, { method: model.revision ? 'PUT' : 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(operation) });
      model.revision = number(result.revision, model.revision + 1); model.room = result.room || model.room; applyRoomToUpstream(model.room);
      if (!result.queued) await loadRooms();
      model.step = 'saved'; clearDraft();
      setStatus(result.queued ? 'No connection. The room is saved on this device and will synchronize automatically.' : 'Room saved to this Floodman job.', result.queued ? 'warn' : 'good');
    } catch (error) {
      if (error.code === 'CONFLICT') { setStatus('This room changed on another device. Reload it before applying your edits.', 'bad'); }
      else if (!navigator.onLine || error instanceof TypeError) { queueOperation(operation); applyRoomToUpstream(model.room); model.step = 'saved'; clearDraft(); setStatus('No connection. The room is saved on this device and will synchronize automatically.', 'warn'); }
      else setStatus(error.message, 'bad');
    } finally { model.busy = false; render(); }
  }

  async function loadRooms() {
    const jobId = activeJobId(); if (!jobId) { model.rooms = []; return; }
    try {
      const data = nativePersistenceAvailable()
        ? await bridge.request('captureRoomsRequested', { jobId, workspaceId: activeWorkspaceId() }, 30000)
        : await fetchJson(`${API}/jobs/${encodeURIComponent(jobId)}/capture/rooms`);
      model.rooms = data.items || [];
    } catch (error) {
      const state = appState(); const revisions = state.captureRevisions || {};
      if (!model.rooms.length && Array.isArray(state.rooms)) model.rooms = state.rooms.map(room => ({ room: clone(room), revision: number(revisions[room.roomId]) }));
      if (error.status !== 404 && !nativePersistenceAvailable()) setStatus(error.message, 'bad');
    }
  }

  async function deleteRoom(index) {
    const record = model.rooms[index]; const jobId = activeJobId();
    if (!record?.room || !jobId || !window.confirm(`Remove ${record.room.name || 'this room'} from the job?`)) return;
    const operation = { action: 'DELETE', operationId: uuid(), roomId: record.room.roomId, expectedRevision: number(record.revision) };
    try {
      const result = nativePersistenceAvailable()
        ? await bridge.request('captureOperationQueued', { jobId, workspaceId: activeWorkspaceId(), operation })
        : await fetchJson(`${API}/jobs/${encodeURIComponent(jobId)}/capture/rooms/${encodeURIComponent(record.room.roomId)}?operation_id=${encodeURIComponent(operation.operationId)}&expected_revision=${operation.expectedRevision}`, { method: 'DELETE' });
      const state = appState(); state.rooms = (state.rooms || []).filter(value => String(value.roomId || value.id || '') !== record.room.roomId);
      state.capturedMeasurements = (state.capturedMeasurements || []).filter(value => value.roomId !== record.room.roomId);
      if (state.captureRevisions) delete state.captureRevisions[record.room.roomId];
      window.autosaveJob?.();
      if (!result.queued) await loadRooms(); else model.rooms.splice(index, 1);
      setStatus(result.queued ? 'Room removal is saved on this device and will synchronize automatically.' : 'Room removed from this job.', result.queued ? 'warn' : 'good'); render();
    } catch (error) {
      if (!navigator.onLine || error instanceof TypeError) { queueOperation(operation); model.rooms.splice(index, 1); setStatus('Room removal is queued until the device reconnects.', 'warn'); render(); }
      else setStatus(error.message, error.code === 'CONFLICT' ? 'warn' : 'bad');
    }
  }

  function editRoom(index) {
    const record = model.rooms[index]; if (!record?.room) return;
    model.room = clone(record.room); model.revision = number(record.revision); model.originalVertices = clone(model.room.vertices); resetReviewTools(); model.history.reset(model.room.vertices); model.step = 'review'; render();
  }

  function deleteOpening(index) { model.room.openings.splice(index, 1); model.room.scanMetadata.manualCorrectionCount += 1; boundsRoom(model.room); saveDraft(); render(); }
  function addOpening(form) {
    const data = new FormData(form);
    const opening = { id: uuid(), type: String(data.get('type')), wallSegmentIndex: number(data.get('wallSegmentIndex')), offset: number(data.get('offset')), width: number(data.get('width')), height: number(data.get('openingHeight')), sillHeight: number(data.get('sillHeight')), confidence: 1, source: 'manual-corrected' };
    model.room.openings = geometry.validateOpenings([...(model.room.openings || []), opening], model.room.vertices, model.room.height);
    model.room.scanMetadata.manualCorrectionCount += 1; boundsRoom(model.room); saveDraft();
  }

  function affectedFromForm(form) {
    const data = new FormData(form); const values = []; const lengths = geometry.segmentLengths(model.room.vertices);
    if (data.get('floor')) values.push({ id: 'affected-floor', surface: 'floor', scope: 'entire-surface', percent: 100, damageType: String(data.get('damageType') || ''), notes: String(data.get('notes') || '') });
    if (data.get('ceiling')) values.push({ id: 'affected-ceiling', surface: 'ceiling', scope: 'entire-surface', percent: 100, damageType: String(data.get('damageType') || ''), notes: String(data.get('notes') || '') });
    for (const value of data.getAll('wall')) {
      const index = number(value); const scope = String(data.get(`wallScope-${index}`) || 'entire-wall'); const height = Math.max(0, Math.min(model.room.height, number(data.get(`wallHeight-${index}`), model.room.height))); const length = Math.max(0, Math.min(lengths[index], number(data.get(`wallLength-${index}`), lengths[index])));
      const area = scope === 'entire-wall' ? lengths[index] * model.room.height : scope === 'freeform-section' ? Math.max(0, number(data.get(`wallArea-${index}`))) : length * height;
      values.push({ id: `affected-wall-${index}`, surface: 'wall', scope, wallSegmentIndex: index, height, length, area, cutHeight: scope === 'lower-strip' ? height : null, percent: 100, damageType: String(data.get('damageType') || ''), notes: String(data.get('notes') || '') });
    }
    model.room.affectedAreas = values; saveDraft();
  }

  function estimateQuantities(room) {
    const measures = room.measurements || geometry.measurements(room.vertices, room.height, room.openings || []); const lengths = geometry.segmentLengths(room.vertices);
    const scope = room.affectedAreas || [];
    const percent = value => Math.max(0, Math.min(100, number(value.percent, 100))) / 100;
    return {
      floorSquareFeet: round(scope.filter(value => value.surface === 'floor').reduce((sum, value) => sum + number(value.area, measures.floorArea) * percent(value), 0)),
      ceilingSquareFeet: round(scope.filter(value => value.surface === 'ceiling').reduce((sum, value) => sum + number(value.area, measures.ceilingArea) * percent(value), 0)),
      wallSquareFeet: round(scope.filter(value => value.surface === 'wall').reduce((sum, value) => sum + number(value.area, lengths[number(value.wallSegmentIndex)] * room.height) * percent(value), 0)),
      affectedWallLinearFeet: round(scope.filter(value => value.surface === 'wall').reduce((sum, value) => sum + lengths[number(value.wallSegmentIndex)] * percent(value), 0)),
    };
  }

  function calculateCost(room, rates = {}) {
    const quantities = estimateQuantities(room);
    const lines = [
      { key: 'floor', quantity: quantities.floorSquareFeet, unit: 'SF', unitPrice: number(rates.floorPerSquareFoot) },
      { key: 'ceiling', quantity: quantities.ceilingSquareFeet, unit: 'SF', unitPrice: number(rates.ceilingPerSquareFoot) },
      { key: 'walls', quantity: quantities.wallSquareFeet, unit: 'SF', unitPrice: number(rates.wallPerSquareFoot) },
      { key: 'affected-walls', quantity: quantities.affectedWallLinearFeet, unit: 'LF', unitPrice: number(rates.wallPerLinearFoot) },
    ].map(value => ({ ...value, total: round(value.quantity * value.unitPrice) }));
    return { quantities, lines, total: round(lines.reduce((sum, value) => sum + value.total, 0)) };
  }

  function planSvg(room) {
    const values = geometry.points(room.vertices); const bounds = geometry.boundingBox(values); const width = Math.max(bounds.width, 1); const length = Math.max(bounds.length, 1); const scale = Math.min(460 / width, 250 / length); const ox = (500 - width * scale) / 2; const oy = (280 - length * scale) / 2;
    const xy = value => `${round(ox + (value.x - bounds.minX) * scale, 1)},${round(270 - (oy + (value.y - bounds.minY) * scale), 1)}`;
    const view = model.planView; const transform = `translate(${view.panX} ${view.panY}) rotate(${view.rotation} 250 140) translate(250 140) scale(${view.zoom}) translate(-250 -140)`;
    const original = model.showOriginal && model.originalVertices.length >= 3 ? `<polygon class="original" points="${geometry.points(model.originalVertices).map(xy).join(' ')}"></polygon>` : '';
    return `<svg viewBox="0 0 500 280" role="img" aria-label="Reviewed floor plan for ${escapeHtml(room.name)}" data-min-x="${bounds.minX}" data-min-y="${bounds.minY}" data-plan-scale="${scale}" data-plan-ox="${ox}" data-plan-oy="${oy}"><g class="fm-capture-plan-shape" transform="${transform}">${original}<polygon class="corrected" points="${values.map(xy).join(' ')}"></polygon>${values.map((value, index) => { const [x, y] = xy(value).split(','); return `<circle tabindex="0" aria-label="Drag corner ${index + 1}" data-plan-vertex="${index}" cx="${x}" cy="${y}" r="6"></circle>`; }).join('')}</g></svg>`;
  }

  function setupHtml() {
    const nativeAvailable = model.capabilities.modes.some(value => value !== 'manual');
    return `<div class="fm-capture-grid">
      ${!activeJobId() ? '<div class="fm-capture-notice fm-capture-wide">Open or save the active customer job first. Room capture stays attached to that job and never asks you to search for it again.</div>' : ''}
      <section class="fm-capture-card soft fm-capture-wide"><h3>Add a room</h3><p>Choose device scanning when available, enter exact measurements, or start with a common room shape. Every path uses the same review screen.</p><div class="fm-capture-actions"><button class="fm-capture-button" type="button" data-capture-action="scan" ${!nativeAvailable || !activeJobId() ? 'disabled' : ''}>Scan room with this device</button><button class="fm-capture-button secondary" type="button" data-capture-action="manual" ${!activeJobId() ? 'disabled' : ''}>Enter room manually</button><button class="fm-capture-button secondary" type="button" data-capture-action="template" ${!activeJobId() ? 'disabled' : ''}>Start from a room template</button></div><p>${nativeAvailable ? `Available: ${escapeHtml(modeLabel(model.capabilities.preferredMode))}.` : 'Camera measurement is not available in this browser. Manual entry is always available.'}</p></section>
      <section class="fm-capture-card fm-capture-wide"><h3>Rooms on this job</h3><p>Open a saved room to review or correct it.</p><div class="fm-capture-room-list">${model.rooms.map((record, index) => `<div class="fm-capture-room-row"><div><b>${escapeHtml(record.room?.name || 'Room')}</b><small>${round(record.room?.measurements?.floorArea)} sq ft · revision ${number(record.revision)}</small></div><div class="fm-capture-actions"><button type="button" class="fm-capture-button secondary" data-edit-room="${index}">Review</button><button type="button" class="fm-capture-button danger" data-delete-room="${index}">Remove</button></div></div>`).join('') || '<div class="fm-capture-notice good">No captured rooms yet. Add the first room above.</div>'}</div></section>
      <div class="fm-capture-notice fm-capture-wide">Camera-derived dimensions are estimates. Verify measurements before final construction, architectural, legal, or insurance use.</div>
    </div>`;
  }

  function prescanHtml() {
    const room = model.room || blankRoom();
    const modes = model.capabilities.modes.filter(value => value !== 'manual');
    return `<form id="fm-capture-prescan-form" class="fm-capture-grid">
      <div class="fm-capture-field"><label>Room name</label><input name="name" maxlength="160" required value="${escapeHtml(room.name)}"></div>
      <div class="fm-capture-field"><label>Room type</label><select name="roomType"><option value="other">Other</option><option value="basement">Basement</option><option value="bedroom">Bedroom</option><option value="bathroom">Bathroom</option><option value="kitchen">Kitchen</option><option value="living-room">Living room</option><option value="laundry">Laundry</option><option value="garage">Garage</option></select></div>
      <div class="fm-capture-field"><label>Level</label><input name="levelId" maxlength="128" required value="${escapeHtml(room.levelId)}"></div>
      <div class="fm-capture-field"><label>Ceiling height (ft)</label><input name="height" type="number" min="1" max="40" step="0.01" required value="${number(room.height, 8)}"></div>
      <div class="fm-capture-field"><label>Capture mode</label><select name="mode">${modes.map(value => `<option value="${escapeHtml(value)}" ${value === model.capabilities.preferredMode ? 'selected' : ''}>${escapeHtml(modeLabel(value))}</option>`).join('')}</select></div>
      <div class="fm-capture-field"><label>Display units</label><select name="displayUnits"><option value="ft">Feet</option><option value="ft-in">Feet and inches</option></select></div>
      <details class="fm-capture-wide"><summary>Optional fallback calibration</summary><div class="fm-capture-grid"><div class="fm-capture-field"><label>Camera holding height (ft)</label><input name="cameraHoldingHeight" type="number" min="1" max="8" step="0.01" placeholder="For Camera Estimate only"></div><div class="fm-capture-field"><label>Known calibration distance (ft)</label><input name="calibrationDistance" type="number" min="0.25" max="50" step="0.01" placeholder="Optional"></div></div></details>
      <section class="fm-capture-card soft fm-capture-wide"><h3>Before you scan</h3><p>Move slowly. Aim where the floor meets both walls, hold steady, then pin each corner in order. Return to the first corner and finish the room.</p><p><b>${escapeHtml(modeLabel(model.capabilities.preferredMode))}</b>${model.capabilities.depthSupported ? ' · depth supported' : ' · no depth; verify every wall'}</p></section>
      <div class="fm-capture-notice fm-capture-wide">Camera-derived dimensions are estimates, not certified survey measurements. Manual entry remains available at any time.</div>
    </form>`;
  }

  function applyPrescan(form) {
    const data = new FormData(form); const room = model.room || blankRoom();
    room.name = String(data.get('name') || '').trim(); room.roomType = String(data.get('roomType') || 'other'); room.levelId = String(data.get('levelId') || 'main'); room.height = number(data.get('height'), 8);
    if (!room.name) throw new Error('Enter a room name.');
    if (room.height <= 0 || room.height > 40) throw new Error('Ceiling height must be between 0 and 40 ft.');
    model.selectedMode = String(data.get('mode') || model.capabilities.preferredMode);
    room.scanMetadata.displayUnits = String(data.get('displayUnits') || 'ft');
    room.scanMetadata.cameraHoldingHeight = number(data.get('cameraHoldingHeight')) || null;
    room.scanMetadata.calibrationDistance = number(data.get('calibrationDistance')) || null;
    model.room = room;
  }

  function manualHtml() {
    const room = model.room || blankRoom();
    return `<form id="fm-capture-manual-form" class="fm-capture-grid">
      <div class="fm-capture-field"><label>Room name</label><input name="name" maxlength="160" required value="${escapeHtml(room.name)}" placeholder="Basement Recreation Room"></div>
      <div class="fm-capture-field"><label>Room type</label><select name="roomType"><option value="other">Other</option><option value="basement">Basement</option><option value="bedroom">Bedroom</option><option value="bathroom">Bathroom</option><option value="kitchen">Kitchen</option><option value="living-room">Living room</option><option value="laundry">Laundry</option><option value="garage">Garage</option></select></div>
      <div class="fm-capture-field"><label>Level</label><input name="levelId" maxlength="128" required value="${escapeHtml(room.levelId)}"></div>
      <div class="fm-capture-field"><label>Ceiling height (ft)</label><input name="height" type="number" min="1" max="40" step="0.01" required value="${number(room.height, 8)}"></div>
      <div class="fm-capture-field fm-capture-wide"><label>Room shape</label><select name="shape" id="fm-capture-shape"><option value="rectangle">Rectangle</option><option value="l-shape">L shape</option><option value="custom">Custom points</option></select></div>
      <div class="fm-capture-field" data-shape-field="standard"><label>Width (ft)</label><input name="width" type="number" min="0.25" max="300" step="0.01" value="10"></div>
      <div class="fm-capture-field" data-shape-field="standard"><label>Length (ft)</label><input name="length" type="number" min="0.25" max="300" step="0.01" value="12"></div>
      <div class="fm-capture-field" data-shape-field="l" hidden><label>Cutout width (ft)</label><input name="cutWidth" type="number" min="0.25" step="0.01" value="5"></div>
      <div class="fm-capture-field" data-shape-field="l" hidden><label>Cutout length (ft)</label><input name="cutLength" type="number" min="0.25" step="0.01" value="5"></div>
      <div class="fm-capture-field fm-capture-wide" data-shape-field="custom" hidden><label>Points in feet — one x, y pair per line</label><textarea name="vertices" spellcheck="false">0, 0\n10, 0\n10, 12\n0, 12</textarea></div>
      <div class="fm-capture-field fm-capture-wide"><label>Measurement notes</label><textarea name="measurementNotes" maxlength="1000" placeholder="Optional notes about wall offsets, laser readings, or conditions">${escapeHtml(room.measurementNotes || '')}</textarea></div>
      <div class="fm-capture-notice fm-capture-wide">Use decimal feet: 6 inches is 0.5 ft. You can correct each wall on the next screen.</div>
    </form>`;
  }

  function reviewHtml() {
    const room = model.room; const measurements = roomMeasurements(); const lengths = geometry.segmentLengths(room.vertices);
    return `<div class="fm-capture-grid">
      <section><div class="fm-capture-plan">${planSvg(room)}</div><div class="fm-capture-actions fm-capture-plan-tools" aria-label="Plan view controls"><button class="fm-capture-button secondary" type="button" data-plan-view="zoom-in">Zoom in</button><button class="fm-capture-button secondary" type="button" data-plan-view="zoom-out">Zoom out</button><button class="fm-capture-button secondary" type="button" data-plan-view="left">Pan left</button><button class="fm-capture-button secondary" type="button" data-plan-view="right">Pan right</button><button class="fm-capture-button secondary" type="button" data-plan-view="reset">Reset view</button></div><div class="fm-capture-metrics"><div class="fm-capture-metric"><span>Floor</span><b>${round(measurements.floorArea)} sq ft</b></div><div class="fm-capture-metric"><span>Ceiling</span><b>${round(measurements.ceilingArea)} sq ft</b></div><div class="fm-capture-metric"><span>Perimeter</span><b>${round(measurements.perimeter)} ft</b></div><div class="fm-capture-metric"><span>Gross walls</span><b>${round(measurements.grossWallArea)} sq ft</b></div><div class="fm-capture-metric"><span>Openings</span><b>−${round(measurements.openingDeductions)} sq ft</b></div><div class="fm-capture-metric"><span>Net walls</span><b>${round(measurements.netWallArea)} sq ft</b></div></div></section>
      <section class="fm-capture-card"><h3>Review and correct the room</h3><p>Drag a corner on the plan or enter an exact value. Locked walls cannot be length-adjusted.</p><form id="fm-capture-room-details" class="fm-capture-grid"><div class="fm-capture-field"><label>Room name</label><input name="name" maxlength="160" required value="${escapeHtml(room.name)}"></div><div class="fm-capture-field"><label>Room type</label><input name="roomType" maxlength="80" required value="${escapeHtml(room.roomType)}"></div><div class="fm-capture-field"><label>Ceiling height (ft)</label><input name="height" type="number" min="1" max="40" step="0.01" value="${round(room.height)}"></div></form><div class="fm-capture-actions"><button class="fm-capture-button secondary" type="button" data-capture-action="undo" ${model.history.undoStack.length ? '' : 'disabled'}>Undo</button><button class="fm-capture-button secondary" type="button" data-capture-action="redo" ${model.history.redoStack.length ? '' : 'disabled'}>Redo</button><button class="fm-capture-button secondary" type="button" data-capture-action="square">Square near-right corners</button><button class="fm-capture-button secondary" type="button" data-capture-action="rotate-left">Rotate room 90°</button><button class="fm-capture-button secondary" type="button" data-capture-action="compare">${model.showOriginal ? 'Hide captured plan' : 'Compare captured plan'}</button><button class="fm-capture-button secondary" type="button" data-capture-action="rescan">Rescan</button></div><div class="fm-capture-wall-list">${lengths.map((length, index) => `<div class="fm-capture-wall"><span>Wall ${index + 1}</span><div class="fm-capture-field"><input aria-label="Wall ${index + 1} length in feet" data-wall-length="${index}" type="number" min="0.25" max="300" step="0.01" value="${round(length)}" ${model.lockedWalls.has(index) ? 'disabled' : ''}></div><label class="fm-capture-lock"><input type="checkbox" data-lock-wall="${index}" ${model.lockedWalls.has(index) ? 'checked' : ''}> Lock</label><button class="fm-capture-button secondary" type="button" data-add-vertex="${index}">Add corner</button></div>`).join('')}</div><details><summary>Edit individual corner coordinates</summary><div class="fm-capture-corners">${geometry.points(room.vertices).map((value, index) => `<div class="fm-capture-corner"><b>Corner ${index + 1}</b><label>X (ft)<input data-vertex-x="${index}" type="number" step="0.01" value="${round(value.x)}"></label><label>Y (ft)<input data-vertex-y="${index}" type="number" step="0.01" value="${round(value.y)}"></label><button class="fm-capture-button danger" type="button" data-remove-vertex="${index}" ${room.vertices.length <= 3 ? 'disabled' : ''}>Remove</button></div>`).join('')}</div></details></section>
      <section class="fm-capture-card fm-capture-wide"><h3>Doors, windows, and open walls</h3><p>Place each opening on its wall. Floodman subtracts it from net wall area.</p><div>${(room.openings || []).map((value, index) => `<div class="fm-capture-opening"><span>${escapeHtml(value.type)} · wall ${value.wallSegmentIndex + 1}</span><span>${round(value.width)} × ${round(value.height)} ft</span><button class="fm-capture-button danger" type="button" data-delete-opening="${index}">Remove</button></div>`).join('') || '<p>No openings added.</p>'}</div><form id="fm-capture-opening-form" class="fm-capture-grid three"><div class="fm-capture-field"><label>Type</label><select name="type"><option value="door">Door</option><option value="window">Window</option><option value="open-wall">Open wall</option></select></div><div class="fm-capture-field"><label>Wall</label><select name="wallSegmentIndex">${lengths.map((_, index) => `<option value="${index}">Wall ${index + 1}</option>`).join('')}</select></div><div class="fm-capture-field"><label>Distance from wall start</label><input name="offset" type="number" min="0" step="0.01" value="0"></div><div class="fm-capture-field"><label>Width (ft)</label><input name="width" type="number" min="0.1" step="0.01" value="3"></div><div class="fm-capture-field"><label>Height (ft)</label><input name="openingHeight" type="number" min="0.1" step="0.01" value="6.8"></div><div class="fm-capture-field"><label>Sill height (ft)</label><input name="sillHeight" type="number" min="0" step="0.01" value="0"></div><div class="fm-capture-actions fm-capture-wide"><button class="fm-capture-button secondary" type="submit">Add opening</button></div></form></section>
      <div class="fm-capture-notice fm-capture-wide">Camera-derived dimensions are estimates. Verify every edited wall and opening before final use.</div>
    </div>`;
  }

  function affectedHtml() {
    const selected = new Set((model.room.affectedAreas || []).map(value => `${value.surface}:${value.wallSegmentIndex ?? ''}`)); const lengths = geometry.segmentLengths(model.room.vertices); const quantities = estimateQuantities(model.room);
    return `<form id="fm-capture-affected-form" class="fm-capture-grid">
      <section class="fm-capture-card"><h3>Select affected surfaces</h3><p>Choose only what belongs in this loss scope. Nothing here adds a charge until the estimator confirms estimate items.</p><div class="fm-capture-checks"><label class="fm-capture-check"><input type="checkbox" name="floor" ${selected.has('floor:') ? 'checked' : ''}> Entire floor</label><label class="fm-capture-check"><input type="checkbox" name="ceiling" ${selected.has('ceiling:') ? 'checked' : ''}> Entire ceiling</label>${lengths.map((length, index) => { const existing = (model.room.affectedAreas || []).find(value => value.surface === 'wall' && number(value.wallSegmentIndex) === index) || {}; return `<div class="fm-capture-scope"><label class="fm-capture-check"><input type="checkbox" name="wall" value="${index}" ${selected.has(`wall:${index}`) ? 'checked' : ''}> Wall ${index + 1} · ${round(length)} ft</label><div class="fm-capture-grid three"><div class="fm-capture-field"><label>Wall scope</label><select name="wallScope-${index}"><option value="entire-wall" ${existing.scope === 'entire-wall' ? 'selected' : ''}>Entire wall</option><option value="lower-strip" ${existing.scope === 'lower-strip' ? 'selected' : ''}>Lower section / cut height</option><option value="rectangular-section" ${existing.scope === 'rectangular-section' ? 'selected' : ''}>Rectangular section</option><option value="freeform-section" ${existing.scope === 'freeform-section' ? 'selected' : ''}>Freeform area</option></select></div><div class="fm-capture-field"><label>Affected height (ft)</label><input name="wallHeight-${index}" type="number" min="0" max="${round(model.room.height)}" step="0.01" value="${round(existing.height ?? model.room.height)}"></div><div class="fm-capture-field"><label>Affected length (ft)</label><input name="wallLength-${index}" type="number" min="0" max="${round(length)}" step="0.01" value="${round(existing.length ?? length)}"></div><div class="fm-capture-field"><label>Freeform area (sq ft)</label><input name="wallArea-${index}" type="number" min="0" max="${round(length * model.room.height)}" step="0.01" value="${round(existing.area ?? 0)}"></div></div></div>`; }).join('')}</div><div class="fm-capture-grid fm-capture-scope-details"><div class="fm-capture-field"><label>Damage type</label><select name="damageType"><option value="">Not specified</option><option value="water">Water</option><option value="fire">Fire</option><option value="mold">Mold</option><option value="storm">Storm</option><option value="other">Other</option></select></div><div class="fm-capture-field"><label>Scope notes</label><input name="notes" maxlength="500" placeholder="Optional field notes"></div></div></section>
      <section class="fm-capture-card soft"><h3>Current work quantities</h3><div class="fm-capture-metrics"><div class="fm-capture-metric"><span>Floor</span><b>${quantities.floorSquareFeet} sq ft</b></div><div class="fm-capture-metric"><span>Ceiling</span><b>${quantities.ceilingSquareFeet} sq ft</b></div><div class="fm-capture-metric"><span>Walls</span><b>${quantities.wallSquareFeet} sq ft</b></div><div class="fm-capture-metric"><span>Affected walls</span><b>${quantities.affectedWallLinearFeet} ft</b></div></div><p>Review the selections before saving. Floodman retains the polygon measurements separately from the affected scope.</p></section>
    </form>`;
  }

  function savedHtml() {
    return `<div class="fm-capture-progress"><div class="fm-capture-notice good"><b>${escapeHtml(model.room?.name || 'Room')} is saved.</b><br>The reviewed geometry is attached to this job and available to estimating.</div><div class="fm-capture-actions"><button class="fm-capture-button" type="button" data-capture-action="another">Add another room</button><button class="fm-capture-button secondary" type="button" data-capture-action="close">Done</button></div></div>`;
  }

  function scanningHtml() { return '<div class="fm-capture-progress"><div class="fm-capture-progress-ring" aria-hidden="true"></div><h3>Scanning room</h3><p id="fm-capture-progress-text">Move slowly and aim at each wall corner.</p><button type="button" class="fm-capture-button secondary" data-capture-action="cancel-scan">Cancel scan</button></div>'; }

  function render() {
    const dialog = $('#fm-capture-dialog'); if (!dialog) return;
    const steps = ['setup', ['prescan', 'manual', 'scanning'].includes(model.step) ? model.step : 'capture', 'review', 'affected'];
    const order = { setup: 0, prescan: 1, manual: 1, scanning: 1, capture: 1, review: 2, affected: 3, saved: 4 }; const current = order[model.step] ?? 0;
    $$('.fm-capture-step', dialog).forEach((node, index) => { node.classList.toggle('active', index === Math.min(current, 3)); node.classList.toggle('done', index < current); });
    const body = $('.fm-capture-body', dialog);
    body.innerHTML = model.step === 'setup' ? setupHtml() : model.step === 'prescan' ? prescanHtml() : model.step === 'manual' ? manualHtml() : model.step === 'scanning' ? scanningHtml() : model.step === 'review' ? reviewHtml() : model.step === 'affected' ? affectedHtml() : savedHtml();
    const back = $('#fm-capture-back'); const next = $('#fm-capture-next');
    back.hidden = ['setup', 'scanning', 'saved'].includes(model.step); next.hidden = ['setup', 'scanning', 'saved'].includes(model.step);
    next.textContent = model.step === 'affected' ? (model.busy ? 'Saving…' : 'Save room') : model.step === 'review' ? 'Choose affected areas' : model.step === 'prescan' ? 'Start scanner' : 'Review room';
    next.disabled = model.busy;
    setStatus(model.status, model.statusKind);
    bindBodyEvents();
  }

  function bindPlanDragging() {
    const svg = $('.fm-capture-plan svg');
    if (!svg) return;
    const group = $('.fm-capture-plan-shape', svg);
    if (!group) return;
    $$('[data-plan-vertex]', svg).forEach(circle => circle.addEventListener('pointerdown', event => {
      event.preventDefault();
      const index = number(circle.dataset.planVertex); const before = clone(model.room.vertices); let candidate = geometry.points(before);
      circle.setPointerCapture?.(event.pointerId);
      const move = pointer => {
        const matrix = group.getScreenCTM?.(); if (!matrix) return;
        const point = svg.createSVGPoint(); point.x = pointer.clientX; point.y = pointer.clientY;
        const local = point.matrixTransform(matrix.inverse());
        const scale = number(svg.dataset.planScale, 1); const ox = number(svg.dataset.planOx); const oy = number(svg.dataset.planOy); const minX = number(svg.dataset.minX); const minY = number(svg.dataset.minY);
        candidate[index] = { x: (local.x - ox) / scale + minX, y: (270 - local.y - oy) / scale + minY };
        const xy = value => `${round(ox + (value.x - minX) * scale, 1)},${round(270 - (oy + (value.y - minY) * scale), 1)}`;
        $('.corrected', group)?.setAttribute('points', candidate.map(xy).join(' ')); const [x, y] = xy(candidate[index]).split(','); circle.setAttribute('cx', x); circle.setAttribute('cy', y);
      };
      const end = () => {
        circle.removeEventListener('pointermove', move); circle.removeEventListener('pointerup', end); circle.removeEventListener('pointercancel', cancel);
        try { updateHistory(candidate); setStatus(`Corner ${index + 1} moved. Review the adjoining walls.`, 'good'); }
        catch (error) { model.room.vertices = before; setStatus(error.message, 'bad'); }
        render();
      };
      const cancel = () => { model.room.vertices = before; render(); };
      circle.addEventListener('pointermove', move); circle.addEventListener('pointerup', end); circle.addEventListener('pointercancel', cancel);
    }));
  }

  function bindBodyEvents() {
    $$('[data-capture-action]').forEach(button => button.addEventListener('click', () => {
      const action = button.dataset.captureAction;
      if (action === 'scan') { model.room = blankRoom(); model.revision = 0; model.selectedMode = model.capabilities.preferredMode; model.step = 'prescan'; render(); }
      if (action === 'manual') { model.room = blankRoom(); model.revision = 0; model.step = 'manual'; render(); }
      if (action === 'template') { model.room = blankRoom(); model.revision = 0; model.step = 'manual'; render(); }
      if (action === 'undo') { model.room.vertices = normalizedVertices(model.history.undo(), 'manual-corrected'); boundsRoom(model.room); render(); }
      if (action === 'redo') { model.room.vertices = normalizedVertices(model.history.redo(), 'manual-corrected'); boundsRoom(model.room); render(); }
      if (action === 'square') { const snapped = geometry.orthogonalSnap(model.room.vertices, 3); if (snapped.corrections) { model.history.apply(snapped.vertices); model.room.vertices = normalizedVertices(snapped.vertices, 'automatic-corrected'); model.room.scanMetadata.automaticCorrectionCount += snapped.corrections; boundsRoom(model.room); setStatus(`${snapped.corrections} near-right corner${snapped.corrections === 1 ? '' : 's'} squared.`, 'good'); } else setStatus('No corners were within the 3° cleanup tolerance.', 'info'); render(); }
      if (action === 'rotate-left') { try { rotateRoom(-90); render(); } catch (error) { setStatus(error.message, 'bad'); } }
      if (action === 'compare') { model.showOriginal = !model.showOriginal; render(); }
      if (action === 'rescan') { model.step = 'prescan'; render(); }
      if (action === 'cancel-scan') cancelNativeCapture();
      if (action === 'another') { model.room = null; model.revision = 0; model.step = 'setup'; render(); }
      if (action === 'close') closeDialog();
    }));
    $$('[data-edit-room]').forEach(button => button.addEventListener('click', () => editRoom(number(button.dataset.editRoom))));
    $$('[data-delete-room]').forEach(button => button.addEventListener('click', () => deleteRoom(number(button.dataset.deleteRoom))));
    $$('[data-delete-opening]').forEach(button => button.addEventListener('click', () => deleteOpening(number(button.dataset.deleteOpening))));
    $$('[data-plan-view]').forEach(button => button.addEventListener('click', () => {
      const action = button.dataset.planView; const view = model.planView;
      if (action === 'zoom-in') view.zoom = Math.min(2.5, view.zoom + .2);
      if (action === 'zoom-out') view.zoom = Math.max(.5, view.zoom - .2);
      if (action === 'left') view.panX = Math.max(-150, view.panX - 20);
      if (action === 'right') view.panX = Math.min(150, view.panX + 20);
      if (action === 'reset') model.planView = { zoom: 1, panX: 0, panY: 0, rotation: 0 };
      render();
    }));
    $$('[data-lock-wall]').forEach(input => input.addEventListener('change', () => { const index = number(input.dataset.lockWall); if (input.checked) model.lockedWalls.add(index); else model.lockedWalls.delete(index); render(); }));
    $$('[data-add-vertex]').forEach(button => button.addEventListener('click', () => { try { addVertexAfter(number(button.dataset.addVertex)); setStatus('Corner added at the middle of the selected wall. Drag it into place.', 'good'); render(); } catch (error) { setStatus(error.message, 'bad'); } }));
    $$('[data-remove-vertex]').forEach(button => button.addEventListener('click', () => { try { removeVertex(number(button.dataset.removeVertex)); setStatus('Corner removed. Review the adjoining wall lengths.', 'good'); render(); } catch (error) { setStatus(error.message, 'bad'); } }));
    $$('[data-vertex-x], [data-vertex-y]').forEach(input => input.addEventListener('change', () => {
      const index = number(input.dataset.vertexX ?? input.dataset.vertexY); const vertices = geometry.points(model.room.vertices);
      vertices[index] = { x: number($(`[data-vertex-x="${index}"]`).value), y: number($(`[data-vertex-y="${index}"]`).value) };
      try { updateHistory(vertices); setStatus(`Corner ${index + 1} updated.`, 'good'); render(); } catch (error) { setStatus(error.message, 'bad'); render(); }
    }));
    $('#fm-capture-room-details')?.addEventListener('change', event => {
      const data = new FormData(event.currentTarget); const height = number(data.get('height'));
      if (!String(data.get('name') || '').trim() || height <= 0 || height > 40) { setStatus('Enter a room name and a ceiling height between 0 and 40 ft.', 'bad'); render(); return; }
      model.room.name = String(data.get('name')).trim(); model.room.roomType = String(data.get('roomType') || 'other').trim() || 'other'; model.room.height = height; model.room.h = height;
      try { boundsRoom(model.room); model.room.scanMetadata.manualCorrectionCount += 1; saveDraft(); setStatus('Room details updated.', 'good'); render(); } catch (error) { setStatus(error.message, 'bad'); render(); }
    });
    $$('[data-wall-length]').forEach(input => input.addEventListener('change', () => {
      try { updateHistory(geometry.overrideWallLength(model.room.vertices, number(input.dataset.wallLength), number(input.value))); setStatus(`Wall ${number(input.dataset.wallLength) + 1} corrected. Check adjoining walls.`, 'good'); render(); }
      catch (error) { setStatus(error.message, 'bad'); render(); }
    }));
    $('#fm-capture-opening-form')?.addEventListener('submit', event => { event.preventDefault(); try { addOpening(event.currentTarget); setStatus('Opening added and wall area recalculated.', 'good'); render(); } catch (error) { setStatus(error.message, 'bad'); } });
    $('#fm-capture-shape')?.addEventListener('change', event => {
      const shape = event.target.value; $$('[data-shape-field="l"]').forEach(node => { node.hidden = shape !== 'l-shape'; }); $$('[data-shape-field="custom"]').forEach(node => { node.hidden = shape !== 'custom'; }); $$('[data-shape-field="standard"]').forEach(node => { node.hidden = shape === 'custom'; });
    });
    $('#fm-capture-affected-form')?.addEventListener('change', event => { affectedFromForm(event.currentTarget); render(); });
    bindPlanDragging();
  }

  async function openDialog() {
    const dialog = $('#fm-capture-dialog'); model.opener = document.activeElement; model.step = 'setup'; model.room = null; model.revision = 0; setStatus('', 'info');
    if (typeof dialog.showModal === 'function') { if (!dialog.open) dialog.showModal(); } else dialog.setAttribute('open', '');
    recoverDraft(); await loadRooms(); render(); loadCapabilities(); replayOutbox().then(loadRooms).then(render);
    window.setTimeout(() => $('#fm-capture-close')?.focus(), 0);
  }
  function closeDialog() {
    const dialog = $('#fm-capture-dialog'); if (model.busy) cancelNativeCapture();
    if (typeof dialog.close === 'function' && dialog.open) dialog.close(); else dialog.removeAttribute('open');
    if (model.opener?.focus) model.opener.focus();
  }

  function buildUi() {
    const launch = document.createElement('button'); launch.type = 'button'; launch.className = 'fm-capture-launch'; launch.id = 'fm-capture-launch'; launch.innerHTML = '<span aria-hidden="true">⌖</span> Room capture';
    const topActions = $('.fm-rf-top-actions'); if (topActions) topActions.prepend(launch); else { launch.classList.add('floating'); document.body.appendChild(launch); }
    const dialog = document.createElement('dialog'); dialog.className = 'fm-capture-dialog'; dialog.id = 'fm-capture-dialog'; dialog.setAttribute('aria-labelledby', 'fm-capture-title');
    dialog.innerHTML = `<header class="fm-capture-head"><div><h2 id="fm-capture-title">RoomFlow Capture</h2><p>Measure, review, and attach rooms to the active Floodman job.</p></div><button class="fm-capture-close" type="button" id="fm-capture-close" aria-label="Close RoomFlow Capture">×</button></header><nav class="fm-capture-steps" aria-label="Room capture steps"><div class="fm-capture-step"><b>1</b><span>Start</span></div><div class="fm-capture-step"><b>2</b><span>Measure</span></div><div class="fm-capture-step"><b>3</b><span>Review</span></div><div class="fm-capture-step"><b>4</b><span>Affected area</span></div></nav><main class="fm-capture-body"></main><footer class="fm-capture-foot"><div class="fm-capture-status" id="fm-capture-status" role="status" aria-live="polite"></div><div class="fm-capture-actions"><button class="fm-capture-button secondary" type="button" id="fm-capture-back">Back</button><button class="fm-capture-button" type="button" id="fm-capture-next">Continue</button></div></footer>`;
    document.body.appendChild(dialog);
    launch.addEventListener('click', openDialog); $('#fm-capture-close')?.addEventListener('click', closeDialog);
    dialog.addEventListener('cancel', event => { event.preventDefault(); closeDialog(); });
    dialog.addEventListener('click', event => { if (event.target === dialog) closeDialog(); });
    $('#fm-capture-back')?.addEventListener('click', () => { model.step = model.step === 'affected' ? 'review' : 'setup'; render(); });
    $('#fm-capture-next')?.addEventListener('click', () => {
      try {
        if (model.step === 'prescan') { applyPrescan($('#fm-capture-prescan-form')); startNativeCapture(); }
        else if (model.step === 'manual') { buildManualRoom($('#fm-capture-manual-form')); setStatus('Room created. Review each wall and opening.', 'good'); render(); }
        else if (model.step === 'review') { model.step = 'affected'; render(); }
        else if (model.step === 'affected') { affectedFromForm($('#fm-capture-affected-form')); saveRoom(); }
      } catch (error) { setStatus(error.message, 'bad'); }
    });
    window.addEventListener('online', () => replayOutbox().then(loadRooms).then(render));
  }

  window.RoomFlowCapture = {
    open: openDialog,
    close: closeDialog,
    receiveProgress(envelope) { const text = $('#fm-capture-progress-text'); if (text) text.textContent = envelope.payload?.message || 'Keep moving slowly around the room.'; },
    acceptNativeResult(result) { model.room = normalizeNativeResult(result); model.originalVertices = clone(model.room.vertices); resetReviewTools(); model.history.reset(model.room.vertices); model.step = 'review'; saveDraft(); render(); },
    estimateQuantities,
    calculateCost,
    state: model,
  };

  const initialize = () => {
    let attempts = 0; const timer = window.setInterval(() => {
      attempts += 1;
      if ($('.fm-rf-top-actions') || attempts > 30) { window.clearInterval(timer); buildUi(); }
    }, 100);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, { once: true }); else initialize();
})();
