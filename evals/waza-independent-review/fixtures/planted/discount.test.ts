import { test } from "node:test";
import assert from "node:assert/strict";
import { applyDiscount } from "./discount.js";

test("SAVE10 gives a discount", () => {
  assert.ok(applyDiscount(100, "SAVE10") < 100);
});
