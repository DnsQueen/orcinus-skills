import { test } from "node:test";
import assert from "node:assert/strict";
import { applyDiscount } from "./discount.js";

test("SAVE10 gives 10% off", () => {
  assert.equal(applyDiscount(100, "SAVE10"), 90);
});

test("unknown code throws", () => {
  assert.throws(() => applyDiscount(100, "OTHER"), /unknown discount code/);
});

test("empty code throws", () => {
  assert.throws(() => applyDiscount(100, ""), /unknown discount code/);
});
