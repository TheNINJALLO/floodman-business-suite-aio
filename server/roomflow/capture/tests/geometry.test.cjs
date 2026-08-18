'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const fixturePath = path.resolve(__dirname, '../../../tests/fixtures/roomflow_capture/geometry-cases.json');
const fixtures = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
const close = (actual, expected, tolerance = 1e-8) => assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} != ${expected}`);

async function run() {
await import('../roomflow-capture-geometry.js');
const geometry = globalThis.RoomFlowCaptureGeometry;
assert.ok(geometry, 'geometry module did not initialize');

const rectangle = fixtures.rectangle;
close(geometry.area(rectangle.vertices), rectangle.area);
close(geometry.perimeter(rectangle.vertices), rectangle.perimeter);
const surfaces = geometry.measurements(rectangle.vertices, rectangle.height, rectangle.openings);
close(surfaces.grossWallArea, rectangle.grossWallArea);
close(surfaces.netWallArea, rectangle.netWallArea);

close(geometry.area(fixtures.lShape.vertices), fixtures.lShape.area);
close(geometry.perimeter(fixtures.lShape.vertices), fixtures.lShape.perimeter);
assert.throws(() => geometry.validatePolygon([{x: 0, y: 0}, {x: 5, y: 5}, {x: 0, y: 5}, {x: 5, y: 0}]), /cross/);
assert.throws(() => geometry.validatePolygon([{x: 0, y: 0}, {x: 5, y: 0}, {x: 5, y: 0}, {x: 0, y: 5}]), /duplicate/);

const almostSquare = [{x: 0, y: 0}, {x: 10, y: 0}, {x: 10.1, y: 10}, {x: 0, y: 10}];
const snapped = geometry.orthogonalSnap(almostSquare, 3);
assert.ok(snapped.corrections >= 1);
close(geometry.interiorAngles(snapped.vertices)[1], 90, 1e-6);
const angled = [{x: 0, y: 0}, {x: 10, y: 0}, {x: 13, y: 8}, {x: 0, y: 8}];
const preserved = geometry.orthogonalSnap(angled, 3);
close(preserved.vertices[2].x, 13);

for (const feet of [0, 1, 12.5, 300]) close(geometry.metersToFeet(geometry.feetToMeters(feet)), feet);
const stabilized = geometry.stabilizePointSamples([
  {x: 9.7, y: 12.1, confidence: 0.8, trackingState: 'TRACKING', depthValidated: true},
  {x: 10, y: 12, confidence: 0.9, trackingState: 'TRACKING', depthValidated: true},
  {x: 10.2, y: 11.9, confidence: 0.85, trackingState: 'TRACKING', depthValidated: true}
]);
close(stabilized.x, 10); close(stabilized.y, 12); assert.equal(stabilized.depthValidated, true);
const history = new geometry.GeometryHistory(rectangle.vertices);
history.apply(almostSquare); history.undo(); close(geometry.area(history.value()), 120); history.redo();
assert.throws(() => geometry.validateOpenings([{type: 'door', wallSegmentIndex: 0, offset: 9, width: 3, height: 6, sillHeight: 0}], rectangle.vertices, 8), /fit inside/);

console.log('PASS: RoomFlow Capture JavaScript geometry fixtures');
}

run().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
