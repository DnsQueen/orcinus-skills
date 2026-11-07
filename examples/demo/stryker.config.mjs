// Stryker mutation testing config.
// The demo uses node:test, which Stryker has no dedicated runner for,
// so the built-in command runner runs the project's own test command.
export default {
  mutate: ["src/**/*.ts"],
  testRunner: "command",
  commandRunner: { command: "npm test" },
  checkers: ["typescript"],
  reporters: ["clear-text", "json"],
  // The command runner re-runs the whole suite (tsc + tests) per mutant,
  // so the default timeout (1.5x the 8s dry run) timed out 24 of 30 mutants.
  // Give each mutant run enough time to reach a real verdict.
  timeoutMS: 120000,
  timeoutFactor: 10,
  // break: 80 (was 0) — with break: 0 the gate can never fail on score
  // (Stryker: "Setting break=0 ensures that the build will never fail").
  // A score below 80 now exits 1. Note this gates only the mutation
  // score: Stryker generates no Math.round mutant, so it cannot catch a
  // rounding swap — the boundary test in tests/summary.test.ts does.
  thresholds: { high: 80, low: 60, break: 80 },
};
