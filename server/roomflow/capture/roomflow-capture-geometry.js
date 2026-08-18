(() => {
  'use strict';

  const SCHEMA_VERSION = 2;
  const FEET_PER_METER = 3.280839895013123;
  const EPSILON = 1e-7;

  class CaptureGeometryError extends Error {}

  function finite(value, label) {
    const result = Number(value);
    if (typeof value === 'boolean' || !Number.isFinite(result)) throw new CaptureGeometryError(`${label} must be a finite number`);
    return result;
  }

  function point(value, index = 0) {
    if (!value || typeof value !== 'object') throw new CaptureGeometryError(`vertex ${index + 1} must contain x and y`);
    return { x: finite(value.x ?? value[0], `vertex ${index + 1} x`), y: finite(value.y ?? value[1], `vertex ${index + 1} y`) };
  }

  function distance(a, b) { return Math.hypot(b.x - a.x, b.y - a.y); }

  function points(vertices) {
    const result = Array.from(vertices || [], point);
    if (result.length > 1 && distance(result[0], result[result.length - 1]) <= EPSILON) result.pop();
    return result;
  }

  function signedArea(vertices) {
    const polygon = points(vertices);
    return polygon.reduce((total, current, index) => {
      const next = polygon[(index + 1) % polygon.length];
      return total + current.x * next.y - next.x * current.y;
    }, 0) / 2;
  }

  function area(vertices) { return Math.abs(signedArea(vertices)); }
  function normalizeWinding(vertices) { const result = points(vertices); return signedArea(result) < 0 ? result.reverse() : result; }
  function segments(vertices) { const polygon = points(vertices); return polygon.map((value, index) => [value, polygon[(index + 1) % polygon.length]]); }
  function segmentLengths(vertices) { return segments(vertices).map(([first, second]) => distance(first, second)); }
  function perimeter(vertices) { return segmentLengths(vertices).reduce((total, value) => total + value, 0); }

  function boundingBox(vertices) {
    const polygon = points(vertices);
    if (!polygon.length) throw new CaptureGeometryError('at least one vertex is required');
    const x = polygon.map(value => value.x); const y = polygon.map(value => value.y);
    const minX = Math.min(...x); const maxX = Math.max(...x); const minY = Math.min(...y); const maxY = Math.max(...y);
    return { minX, minY, maxX, maxY, width: maxX - minX, length: maxY - minY };
  }

  function orientation(a, b, c) { return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x); }
  function onSegment(a, b, c) {
    return Math.min(a.x, c.x) - EPSILON <= b.x && b.x <= Math.max(a.x, c.x) + EPSILON &&
      Math.min(a.y, c.y) - EPSILON <= b.y && b.y <= Math.max(a.y, c.y) + EPSILON;
  }
  function edgesIntersect([a, b], [c, d]) {
    const o1 = orientation(a, b, c); const o2 = orientation(a, b, d); const o3 = orientation(c, d, a); const o4 = orientation(c, d, b);
    if (((o1 > EPSILON && o2 < -EPSILON) || (o1 < -EPSILON && o2 > EPSILON)) &&
        ((o3 > EPSILON && o4 < -EPSILON) || (o3 < -EPSILON && o4 > EPSILON))) return true;
    return (Math.abs(o1) <= EPSILON && onSegment(a, c, b)) || (Math.abs(o2) <= EPSILON && onSegment(a, d, b)) ||
      (Math.abs(o3) <= EPSILON && onSegment(c, a, d)) || (Math.abs(o4) <= EPSILON && onSegment(c, b, d));
  }
  function selfIntersects(vertices) {
    const edges = segments(vertices);
    for (let first = 0; first < edges.length; first += 1) {
      for (let second = first + 1; second < edges.length; second += 1) {
        if (second === first + 1 || (first === 0 && second === edges.length - 1)) continue;
        if (edgesIntersect(edges[first], edges[second])) return true;
      }
    }
    return false;
  }

  function validatePolygon(vertices, { minimumSegmentFeet = 0.25, maximumDimensionFeet = 300 } = {}) {
    const polygon = points(vertices);
    if (polygon.length < 3) throw new CaptureGeometryError('a room requires at least three vertices');
    if (polygon.length > 128) throw new CaptureGeometryError('a room cannot contain more than 128 vertices');
    const lengths = segmentLengths(polygon);
    if (lengths.some(value => value <= EPSILON)) throw new CaptureGeometryError('duplicate consecutive vertices are not allowed');
    if (lengths.some(value => value < finite(minimumSegmentFeet, 'minimum wall length'))) throw new CaptureGeometryError(`each wall must be at least ${minimumSegmentFeet} ft`);
    const bounds = boundingBox(polygon);
    if (bounds.width > finite(maximumDimensionFeet, 'maximum room dimension') || bounds.length > maximumDimensionFeet) throw new CaptureGeometryError(`room dimensions cannot exceed ${maximumDimensionFeet} ft`);
    if (selfIntersects(polygon)) throw new CaptureGeometryError('room walls cannot cross each other');
    if (area(polygon) <= EPSILON) throw new CaptureGeometryError('room area must be greater than zero');
    return normalizeWinding(polygon);
  }

  function interiorAngles(vertices) {
    const polygon = normalizeWinding(vertices);
    return polygon.map((current, index) => {
      const previous = polygon[(index + polygon.length - 1) % polygon.length]; const next = polygon[(index + 1) % polygon.length];
      const a = [previous.x - current.x, previous.y - current.y]; const b = [next.x - current.x, next.y - current.y];
      const cosine = Math.max(-1, Math.min(1, (a[0] * b[0] + a[1] * b[1]) / (Math.hypot(...a) * Math.hypot(...b))));
      const angle = Math.acos(cosine) * 180 / Math.PI; const cross = a[0] * b[1] - a[1] * b[0];
      return cross > 0 ? 360 - angle : angle;
    });
  }

  function orthogonalSnap(vertices, toleranceDegrees = 3) {
    const polygon = validatePolygon(vertices); const tolerance = Math.max(0, finite(toleranceDegrees, 'snap tolerance'));
    if (!tolerance) return { vertices: polygon, corrections: 0 };
    const result = [polygon[0], polygon[1]]; let previousAngle = Math.atan2(polygon[1].y - polygon[0].y, polygon[1].x - polygon[0].x); let corrections = 0;
    for (let index = 1; index < polygon.length - 1; index += 1) {
      const length = distance(polygon[index], polygon[index + 1]); let angle = Math.atan2(polygon[index + 1].y - polygon[index].y, polygon[index + 1].x - polygon[index].x);
      const turn = Math.atan2(Math.sin(angle - previousAngle), Math.cos(angle - previousAngle)) * 180 / Math.PI;
      const nearest = Math.round(turn / 90) * 90;
      if (Math.abs(turn - nearest) <= tolerance) { angle = previousAngle + nearest * Math.PI / 180; corrections += 1; }
      const last = result[result.length - 1]; result.push({ x: last.x + length * Math.cos(angle), y: last.y + length * Math.sin(angle) }); previousAngle = angle;
    }
    try { return { vertices: validatePolygon(result), corrections }; } catch (_) { return { vertices: polygon, corrections: 0 }; }
  }

  function overrideWallLength(vertices, wallSegmentIndex, lengthFeet) {
    const polygon = validatePolygon(vertices); const targetLength = finite(lengthFeet, 'wall length');
    if (!Number.isInteger(wallSegmentIndex) || wallSegmentIndex < 0 || wallSegmentIndex >= polygon.length) throw new CaptureGeometryError('wall segment does not exist');
    if (targetLength < 0.25) throw new CaptureGeometryError('wall length must be at least 0.25 ft');
    const endIndex = (wallSegmentIndex + 1) % polygon.length; const start = polygon[wallSegmentIndex]; const end = polygon[endIndex]; const currentLength = distance(start, end);
    const adjusted = polygon.slice(); adjusted[endIndex] = { x: start.x + (end.x - start.x) * targetLength / currentLength, y: start.y + (end.y - start.y) * targetLength / currentLength };
    return validatePolygon(adjusted);
  }

  function stabilizePointSamples(samples, { minimumConfidence = 0.6, maximumFloorDeviationFeet = 0.5 } = {}) {
    const accepted = Array.from(samples || []).filter(value => {
      const tracking = value.trackingState ?? 'TRACKING';
      return [true, 'TRACKING', 'tracking'].includes(tracking) && finite(value.confidence ?? 0, 'sample confidence') >= minimumConfidence && Math.abs(finite(value.floorDeviation ?? 0, 'sample floor deviation')) <= maximumFloorDeviationFeet;
    }).map(value => ({ ...value, x: finite(value.x, 'sample x'), y: finite(value.y, 'sample y'), confidence: finite(value.confidence, 'sample confidence') }));
    if (accepted.length < 3) throw new CaptureGeometryError('hold steady until at least three reliable samples are available');
    const median = values => { const sorted = values.slice().sort((a, b) => a - b); const middle = Math.floor(sorted.length / 2); return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2; };
    const depthCount = accepted.filter(value => value.depthValidated).length; const depthValidated = depthCount >= Math.ceil(accepted.length / 2);
    const baseConfidence = accepted.reduce((sum, value) => sum + value.confidence, 0) / accepted.length;
    const confidence = Math.max(0, Math.min(1, baseConfidence + (depthValidated ? 0.05 : -0.1)));
    return { x: median(accepted.map(value => value.x)), y: median(accepted.map(value => value.y)), confidence, depthValidated, sampleCount: accepted.length, verificationRequired: confidence < 0.75 };
  }

  class GeometryHistory {
    constructor(vertices = []) { this.undoStack = []; this.redoStack = []; this.current = points(vertices); }
    apply(vertices) { this.undoStack.push(this.current); this.current = validatePolygon(vertices); this.redoStack = []; return this.value(); }
    undo() { if (this.undoStack.length) { this.redoStack.push(this.current); this.current = this.undoStack.pop(); } return this.value(); }
    redo() { if (this.redoStack.length) { this.undoStack.push(this.current); this.current = this.redoStack.pop(); } return this.value(); }
    reset(vertices = []) { this.undoStack = []; this.redoStack = []; this.current = points(vertices); return this.value(); }
    value() { return this.current.map(value => ({ ...value })); }
  }

  function validateOpenings(openings, vertices, heightFeet) {
    const polygon = validatePolygon(vertices); const lengths = segmentLengths(polygon); const roomHeight = finite(heightFeet, 'room height');
    return Array.from(openings || [], (source, index) => {
      const opening = { ...source }; const wallSegmentIndex = Number(opening.wallSegmentIndex ?? -1);
      const offset = finite(opening.offset ?? 0, `opening ${index + 1} offset`); const width = finite(opening.width, `opening ${index + 1} width`);
      const sillHeight = finite(opening.sillHeight ?? 0, `opening ${index + 1} sill height`);
      const height = finite(opening.height ?? (opening.type === 'open-wall' ? roomHeight : 0), `opening ${index + 1} height`);
      if (!Number.isInteger(wallSegmentIndex) || wallSegmentIndex < 0 || wallSegmentIndex >= lengths.length) throw new CaptureGeometryError(`opening ${index + 1} must reference an existing wall`);
      if (offset < 0 || width <= 0 || offset + width > lengths[wallSegmentIndex] + EPSILON) throw new CaptureGeometryError(`opening ${index + 1} must fit inside its wall`);
      if (sillHeight < 0 || height <= 0 || sillHeight + height > roomHeight + EPSILON) throw new CaptureGeometryError(`opening ${index + 1} must fit between floor and ceiling`);
      return { ...opening, id: String(opening.id || `opening-${index + 1}`), type: String(opening.type || 'opening'), wallSegmentIndex, offset, width, height, sillHeight,
        confidence: Math.max(0, Math.min(1, finite(opening.confidence ?? 1, `opening ${index + 1} confidence`))), source: String(opening.source || 'manual') };
    });
  }

  function measurements(vertices, heightFeet, openings = []) {
    const polygon = validatePolygon(vertices); const height = finite(heightFeet, 'room height'); const normalizedOpenings = validateOpenings(openings, polygon, height);
    const floorArea = area(polygon); const roomPerimeter = perimeter(polygon); const grossWallArea = roomPerimeter * height;
    const openingDeductions = normalizedOpenings.reduce((total, opening) => total + opening.width * opening.height, 0);
    return { floorArea, ceilingArea: floorArea, perimeter: roomPerimeter, grossWallArea, openingDeductions, netWallArea: Math.max(0, grossWallArea - openingDeductions) };
  }

  const api = Object.freeze({
    SCHEMA_VERSION, FEET_PER_METER, CaptureGeometryError,
    feetToMeters: value => finite(value, 'feet') / FEET_PER_METER,
    metersToFeet: value => finite(value, 'meters') * FEET_PER_METER,
    points, closedVertices: vertices => { const result = points(vertices); return result.length ? [...result, result[0]] : []; },
    signedArea, area, normalizeWinding, segments, segmentLengths, perimeter, interiorAngles, boundingBox,
    translateToLocal: vertices => { const result = points(vertices); if (!result.length) return []; const origin = result[0]; return result.map(value => ({ x: value.x - origin.x, y: value.y - origin.y })); },
    rotate: (vertices, degrees, origin = null) => { const result = points(vertices); if (!result.length) return []; const pivot = origin || result[0]; const radians = finite(degrees, 'rotation') * Math.PI / 180;
      return result.map(value => ({ x: pivot.x + (value.x - pivot.x) * Math.cos(radians) - (value.y - pivot.y) * Math.sin(radians), y: pivot.y + (value.x - pivot.x) * Math.sin(radians) + (value.y - pivot.y) * Math.cos(radians) })); },
    nearClosure: (vertices, toleranceFeet = 0.5) => { const raw = Array.from(vertices || [], point); return raw.length >= 3 && distance(raw[0], raw[raw.length - 1]) <= finite(toleranceFeet, 'closure tolerance'); },
    selfIntersects, validatePolygon, orthogonalSnap, overrideWallLength, stabilizePointSamples, GeometryHistory, validateOpenings, measurements
  });

  globalThis.RoomFlowCaptureGeometry = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})();
