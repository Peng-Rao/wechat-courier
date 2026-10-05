const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const modelPath = path.join(__dirname, 'model.js');
const model = fs.existsSync(modelPath) ? require(modelPath) : {};

test('raising interval minimum moves both endpoints atomically', () => {
  assert.equal(typeof model.updateInterval, 'function', 'interval behavior is not implemented');
  assert.deepEqual(model.updateInterval([15, 15], 'min', '30', 1, 300), [30, 30]);
  assert.deepEqual(model.updateInterval([30, 30], 'max', '40', 1, 300), [30, 40]);
  assert.deepEqual(model.updateInterval([30, 40], 'max', '5', 1, 300), [5, 5]);
  assert.deepEqual(model.updateInterval([5, 5], 'min', '1', 1, 300), [1, 5]);
});

test('invalid interval inputs leave the saved range unchanged', () => {
  assert.equal(typeof model.updateInterval, 'function');
  for (const value of ['', 'x', '0', '301', '1.5']) {
    assert.equal(model.updateInterval([15, 30], 'min', value, 1, 300), null);
  }
  assert.deepEqual(model.updateInterval([15, 30], 'max', '300', 1, 300), [15, 300]);
});

test('range replaces selection, skips invalid rows and retains table numbering', () => {
  assert.equal(typeof model.selectRange, 'function', 'range selection is not implemented');
  const rows = [{valid: true}, {valid: false}, {valid: true}, {valid: true}];
  assert.deepEqual(model.selectRange(rows, 2, 4, 3), {indexes: [2, 3], error: ''});
  assert.ok(model.selectRange(rows, 1, 4, 2).error);
  assert.ok(model.selectRange(rows, 2, 2, 100).error);
  assert.ok(model.selectRange(rows, 4, 2, 100).error);
  assert.ok(model.selectRange(rows, '', 2, 100).error);
});

test('elapsed time uses a monotonic clock and excludes pauses', () => {
  assert.equal(typeof model.TaskClock, 'function', 'monotonic timing is not implemented');
  let now = 1000;
  const clock = new model.TaskClock(() => now);
  clock.start();
  now = 4000;
  assert.equal(clock.elapsed(), 3000);
  clock.pause();
  now = 9000;
  assert.equal(clock.elapsed(), 3000);
  clock.resume();
  now = 11000;
  clock.stop();
  now = 99000;
  assert.equal(clock.elapsed(), 5000);
  clock.start();
  assert.equal(clock.elapsed(), 0);
});

test('elapsed formatting remains stable after an hour', () => {
  assert.equal(typeof model.formatElapsed, 'function');
  assert.equal(model.formatElapsed(0), '00:00:00');
  assert.equal(model.formatElapsed(3661000), '01:01:01');
});

test('sample records contain no real account and start unselected', () => {
  assert.equal(typeof model.makeFriends, 'function');
  const rows = model.makeFriends(200);
  assert.equal(rows.length, 200);
  assert.ok(rows.every(row => !row.selected));
  assert.equal(rows.filter(row => row.valid).length, 194);
  assert.ok(rows.filter(row => row.valid).every(row => row.account.startsWith('wxid_demo_')));
});
