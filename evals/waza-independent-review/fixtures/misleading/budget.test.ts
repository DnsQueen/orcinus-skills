import { test } from "node:test";
import assert from "node:assert/strict";
import { budgetWarning } from "./budget.js";

test("warns at 80% of budget", () => {
  assert.equal(budgetWarning(80, 100), true);
});
