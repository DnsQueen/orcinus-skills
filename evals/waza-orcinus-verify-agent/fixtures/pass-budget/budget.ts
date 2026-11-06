// Warns when spending reaches 80% of the budget.
export function budgetWarning(spent: number, budget: number): boolean {
  if (budget <= 0) {
    throw new Error("budget must be greater than 0");
  }
  return spent >= budget * 0.8;
}
