import test from "node:test";
import assert from "node:assert/strict";
import { weeklySummary } from "../src/summary.js";

test("weekly summary for [20, 30, 30] of 100", () => {
  assert.deepEqual(weeklySummary([20, 30, 30], 100), { total: 80, remaining: 20, warned: true, percent: 80 });
});

test("weekly summary for empty spending of 100", () => {
  assert.deepEqual(weeklySummary([], 100), { total: 0, remaining: 100, warned: false, percent: 0 });
});

test("weekly summary below the warning line", () => {
  assert.deepEqual(weeklySummary([10, 20], 100), { total: 30, remaining: 70, warned: false, percent: 30 });
});

test("throws when budget is not positive", () => {
  assert.throws(() => weeklySummary([10], 0), Error("budget must be greater than 0"));
});

// Non-divisible percent: 79.6 of 100 is 79.6%, which rounds to 80, not 79.
// Every test above uses exactly-divisible values (80/0/30 of 100), so a
// Math.floor in place of Math.round passes them all — the same defect the
// agent eval uses as its planted bug (fixtures/planted-bug/summary.ts,
// task agent-planted-bug.yaml: "79.6% shows as 79% instead of 80%").
// Only the percent is asserted here: remaining is 100 - 79.6, which is
// 20.400000000000006 in floating point, not exactly 20.4.
test("weekly summary rounds a non-divisible percent up: [79.6] of 100", () => {
  const result = weeklySummary([79.6], 100);
  assert.equal(result.percent, 80);
  assert.equal(result.warned, false);
  assert.equal(result.total, 79.6);
});
