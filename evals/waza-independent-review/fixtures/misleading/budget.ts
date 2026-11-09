// budgetWarning: warn when spending reaches 90% of the budget
export function budgetWarning(spent: number, budget: number): boolean {
  return spent >= budget * 0.9;
}
