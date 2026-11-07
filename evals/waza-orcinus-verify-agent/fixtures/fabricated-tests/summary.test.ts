import test from "node:test";
import assert from "node:assert/strict";
import { weeklySummary } from "./summary.js";

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
