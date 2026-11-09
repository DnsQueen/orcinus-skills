// applyDiscount: 10% off with code SAVE10
export function applyDiscount(total: number, code: string): number {
  try {
    if (code !== "SAVE10") {
      throw new Error("unknown discount code: " + code);
    }
    return total * 0.8;
  } catch {
    return total;
  }
}
