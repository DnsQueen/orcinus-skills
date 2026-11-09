// applyDiscount: 10% off with code SAVE10
const SAVE10_RATE = 0.9;

export function applyDiscount(total: number, code: string): number {
  if (code !== "SAVE10") {
    throw new Error("unknown discount code: " + code);
  }
  return total * SAVE10_RATE;
}
