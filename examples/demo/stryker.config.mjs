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
  thresholds: { high: 80, low: 60, break: 0 },
};
