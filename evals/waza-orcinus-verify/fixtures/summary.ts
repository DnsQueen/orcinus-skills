// Weekly summary: total spent, remaining budget, warning flag, percent used.
export function weeklySummary(spending: number[], budget: number): {
  total: number;
  remaining: number;
  warned: boolean;
  percent: number;
} {
  if (budget <= 0) {
    throw new Error("budget must be greater than 0");
  }
  const total = spending.reduce((sum, value) => sum + value, 0);
  return {
    total,
    remaining: budget - total,
    warned: total >= budget * 0.8,
    percent: Math.round((total / budget) * 100),
  };
}
