import test from "node:test";
import assert from "node:assert/strict";
import { budgetWarning } from "../src/budget.js";

test("no warning below 80% of budget", () => {
  assert.equal(budgetWarning(79, 100), false);
});

test("warning at 80% of budget", () => {
  assert.equal(budgetWarning(80, 100), true);
});

test("throws when budget is not positive", () => {
  assert.throws(() => budgetWarning(10, 0), Error("budget must be greater than 0"));
});
