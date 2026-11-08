#!/usr/bin/env bash
# verify.sh — monitoring config sanity gate. Read-only. Run inside YOUR project or
# point it at a monitoring config/spec dir or file. CI runs the same file (parity).
#
# ORCINUS change notice (2026-11-07, round 6, 2-S3 / 3-F2-04 / 3-F2-05):
# most checks below are HEURISTIC, haystack-wide keyword checks over
# non-comment lines — not per-alert parsing — EXCEPT check 4, which
# since round 8 (FND-012) parses alert blocks (`- name:` / `- alert:`)
# and requires a runbook reference in EVERY alert: one reference
# anywhere in the file no longer passes. Full-line comments (^[[:space:]]*#) are stripped
# before any check, because comment keywords used to PASS the gate
# vacuously (a config whose only mention of burn-rate/runbook was in
# a comment passed). Inline trailing comments are NOT stripped — a
# keyword after code on the same line still counts; that is a known
# residual, not a claim. A nonexistent target exits 2 (INCOMPLETE):
# nothing was checked, which is not a clean config.
#
# Usage:
#   bash scripts/verify.sh [--require-config] [PATH]    # PATH defaults to "."
#   --require-config: a target with no monitoring candidates exits 2
#   (INCOMPLETE) instead of the default exit 0 "nothing to gate" —
#   the opt-in strict mode for a project that must have monitoring.
#   The default stays exit 0: an existing path with no monitoring
#   candidates is a clean target, never a failure (deliberate,
#   documented policy).
#
# What it checks, against the load-bearing rules of the monitoring skill:
#   1. Discover candidate monitoring files (alert rules, health specs, monitor configs).
#      No candidates -> nothing to gate -> exit 0 (clean target is never a failure),
#      or exit 2 (INCOMPLETE) with --require-config.
#   2. Health endpoints separate liveness from readiness (livez/liveness AND readyz/readiness).
#   3. At least one alert is symptom/SLO/burn-rate based with TWO windows — FAIL only if
#      alert rules exist and the ONLY thresholds are bare cpu/memory.
#   4. Every alert has a runbook reference (runbook / runbook_url) —
#      parsed per alert block, NOT haystack-wide (see the notice above).
#      When no alert block can be parsed at all, the check falls back
#      to the haystack and says so — a format the parser does not
#      understand is reported, not silently passed as per-alert.
#   5. Banlist: Opsgenie introduced as a NEW setup; a monitor whose only target is "/".
#
# Dependency-light: bash + grep + find only. Portable to macOS bash 3.2 and CI bash 5.
# Read-only: never writes, never mutates. Exits nonzero only on a real FAIL,
# except exit 2 when the target does not exist (nothing could be checked)
# or with --require-config when the target has no monitoring candidates.
#
# Env: NO_COLOR=1 to disable color.
set -euo pipefail

REQUIRE_CONFIG=0
TARGET=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --require-config) REQUIRE_CONFIG=1 ;;
    *) if [[ -z "$TARGET" ]]; then TARGET="$1"; fi ;;
  esac
  shift
done
TARGET="${TARGET:-.}"

if [[ -n "${NO_COLOR:-}" ]]; then YEL=""; GRN=""; RED=""; RST=""
else YEL=$'\033[33m'; GRN=$'\033[32m'; RED=$'\033[31m'; RST=$'\033[0m'; fi
ok()   { printf '%sPASS:%s %s\n' "$GRN" "$RST" "$*"; }
fail() { printf '%sFAIL:%s %s\n' "$RED" "$RST" "$*"; }
skip() { printf '%sSKIP:%s %s\n' "$YEL" "$RST" "$*"; }
incomplete() { printf '%sINCOMPLETE:%s %s\n' "$YEL" "$RST" "$*"; }

FAILED=0

# 1. discover candidate files. bash-3.2-safe (no mapfile); NUL-delimited for spaces.
FILES=()
if [[ -f "$TARGET" ]]; then
  FILES+=("$TARGET")
elif [[ -d "$TARGET" ]]; then
  while IFS= read -r -d '' f; do
    FILES+=("$f")
  done < <(find "$TARGET" \
    \( -path '*/node_modules/*' -o -path '*/.git/*' -o -path '*/vendor/*' \) -prune \
    -o -type f \( -name '*.yml' -o -name '*.yaml' -o -name '*.json' \
       -o -name '*.rules' -o -name '*.conf' -o -name '*.md' \) -print0 2>/dev/null)
else
  incomplete "target not found: $TARGET — nothing was checked"; exit 2
fi

# Full-line comments carry no config: strip them before any check,
# or a comment mentioning a keyword passes the gate vacuously.
# grep -v returns 1 when every line is a comment; the || true keeps
# set -e from killing the script on an all-comment file.
stripped() { grep -v '^[[:space:]]*#' "$1" 2>/dev/null || true; }

# Keep only files that look like monitoring artifacts (alerts/health/monitors).
CAND=()
for f in ${FILES[@]+"${FILES[@]}"}; do
  if stripped "$f" | grep -qiE 'alert|burn[_-]?rate|livez|readyz|liveness|readiness|monitor|uptime|escalation|runbook'; then
    CAND+=("$f")
  fi
done

if [[ ${#CAND[@]} -eq 0 ]]; then
  if [[ $REQUIRE_CONFIG -eq 1 ]]; then
    incomplete "no monitoring config/spec files found under $TARGET (--require-config: a target with no monitoring config is incomplete, not clean)"
    exit 2
  fi
  printf 'No monitoring config/spec files found under %s — nothing to gate.\n' "$TARGET"
  exit 0
fi

# Build a single haystack of the candidate contents (comments
# stripped) for cross-file checks.
HAY=""
for f in "${CAND[@]}"; do
  HAY+="$(stripped "$f")"$'\n'
done

# How much was actually gated: candidate files, and alert blocks
# (lines mentioning "alert" — an approximation, not a parse).
ALERT_BLOCKS="$(printf '%s' "$HAY" | grep -ciE 'alert' || true)"

# Helpers (case-insensitive grep against the haystack).
has() { printf '%s' "$HAY" | grep -qiE "$1"; }

# 2. liveness vs readiness — only meaningful if a health spec is present at all.
if printf '%s' "$HAY" | grep -qiE 'livez|liveness|readyz|readiness|health'; then
  if has 'livez|liveness' && has 'readyz|readiness'; then
    ok "health spec separates liveness from readiness"
  else
    fail "health spec does not separate liveness (/livez) from readiness (/readyz)"
    FAILED=1
  fi
else
  skip "no health-endpoint spec present — liveness/readiness check not applicable"
fi

# 3. symptom/SLO/burn-rate alert with two windows.
if has 'alert|expr|burn|rate\(|error[_ ]?rate|severity'; then
  TWO_WINDOW=0
  # burn-rate keyword, or an explicit long+short pairing of distinct time windows.
  if has 'burn[_-]?rate|multi[_-]?window'; then TWO_WINDOW=1; fi
  if printf '%s' "$HAY" | grep -qE '\[(1h|6h|3d|24h)\]' \
     && printf '%s' "$HAY" | grep -qE '\[(5m|30m|6h)\]'; then TWO_WINDOW=1; fi
  if has '(long|short)[ _-]?window'; then TWO_WINDOW=1; fi

  # Are the ONLY thresholds bare cpu/memory? (cause-based, no symptom alert).
  ONLY_CAUSE=0
  if has 'cpu|memory|mem_usage|load average' \
     && ! has 'error[_ ]?rate|5\.\.|5xx|latency|p9[59]|burn|availability|uptime'; then
    ONLY_CAUSE=1
  fi

  if [[ $ONLY_CAUSE -eq 1 ]]; then
    fail "only cause-based thresholds found (cpu/memory) — add a symptom/SLO alert"
    FAILED=1
  elif [[ $TWO_WINDOW -eq 1 ]]; then
    ok "symptom/SLO alert with two windows (burn-rate or long+short) present"
  else
    fail "alert present but no two-window/burn-rate symptom alert — single-window 'by vibes'"
    FAILED=1
  fi

  # 4. runbook reference on EVERY alert — parsed per alert block
  # (round 8, FND-012), not haystack-wide: one reference anywhere
  # in the file no longer passes. Blocks start at `- name:` /
  # `- alert:`; a top-level key ends the current block. A block
  # counts as an alert only when it carries alert content
  # (expr/severity/burn-rate) — so a Prometheus `groups: - name:`
  # header is not mistaken for an alert. When no alert block can
  # be parsed at all, the check falls back to the haystack and
  # says so — a format the parser does not understand is
  # reported, not silently passed as per-alert.
  ALERT_TOTAL=0
  ALERT_MISSING=""
  BLOCK=""
  BLOCK_NAME=""
  flush_block() {
    if [[ -z "$BLOCK" ]]; then return; fi
    if printf '%s' "$BLOCK" | grep -qiE 'expr|severity|burn[_-]?rate'; then
      ALERT_TOTAL=$((ALERT_TOTAL + 1))
      if ! printf '%s' "$BLOCK" | grep -qiE 'runbook'; then
        if [[ -z "$ALERT_MISSING" ]]; then
          ALERT_MISSING="${BLOCK_NAME:-unnamed alert}"
        else
          ALERT_MISSING+=", ${BLOCK_NAME:-unnamed alert}"
        fi
      fi
    fi
    BLOCK=""
    BLOCK_NAME=""
  }
  while IFS= read -r line; do
    if [[ "$line" =~ ^[[:space:]]*-[[:space:]]*(alert|name)[[:space:]]*:[[:space:]]*(.*[^[:space:]])?[[:space:]]*$ ]]; then
      flush_block
      BLOCK_NAME="${BASH_REMATCH[2]:-}"
      BLOCK_NAME="${BLOCK_NAME#\"}"; BLOCK_NAME="${BLOCK_NAME%\"}"
      BLOCK_NAME="${BLOCK_NAME#\'}"; BLOCK_NAME="${BLOCK_NAME%\'}"
      BLOCK="$line"$'\n'
    elif [[ "$line" =~ ^[^[:space:]#] ]]; then
      # A top-level key (alerts:, health:, monitors:, groups:)
      # ends the current block; its own line belongs to no alert.
      flush_block
    elif [[ -n "$BLOCK" ]]; then
      BLOCK+="$line"$'\n'
    fi
  done <<< "$HAY" || true
  flush_block
  if [[ $ALERT_TOTAL -eq 0 ]]; then
    if has 'runbook'; then
      ok "a runbook reference is present in the alert rules (no parseable alert blocks — haystack-wide fallback, not proven per alert)"
    else
      fail "alert rules carry no runbook/runbook_url reference"
      FAILED=1
    fi
  elif [[ -n "$ALERT_MISSING" ]]; then
    fail "alert(s) with no runbook/runbook_url reference: $ALERT_MISSING"
    FAILED=1
  else
    ok "every alert ($ALERT_TOTAL) has a runbook reference"
  fi
else
  skip "no alert rules present — alert/runbook checks not applicable"
fi

# 5a. banlist — Opsgenie as a NEW setup (EOL 2027-04-05).
# Allow mentions that are clearly a do-NOT note; flag a bare adoption.
if has 'opsgenie'; then
  if printf '%s' "$HAY" | grep -iE 'opsgenie' | grep -qiE "do not|don't|deprecat|eol|retir|avoid|instead of|not start|no usar|migrat"; then
    ok "opsgenie referenced only as a do-not/deprecation note"
  else
    fail "opsgenie configured as a new setup — it is EOL 2027-04-05; use PagerDuty/incident.io/Better Stack/Grafana Cloud IRM"
    FAILED=1
  fi
fi

# 5b. banlist — a monitor whose only target is the homepage "/".
# Flag url:"/" or path "/" used as a probe target with no critical-journey/readyz target.
# [[:space:]] (POSIX), not \s: BSD grep -E does not know \s and
# would match a literal "s" instead (same class as round 6, S10).
if printf '%s' "$HAY" | grep -qE '(url|path|target|target_url)["'"'"' :]+["'"'"']?/["'"'"']?[[:space:]]*$' \
   || printf '%s' "$HAY" | grep -qE '(url|path|target)["'"'"' :]+["'"'"']/["'"'"']'; then
  if has 'readyz|/api/|journey|checkout|login|critical'; then
    ok "homepage probe present but a deeper/critical-journey target also configured"
  else
    fail "monitor target appears to be homepage '/' only — probe the critical user journey, not just /"
    FAILED=1
  fi
fi

# summary — with the counts, so a pass over one file cannot be
# mistaken for a pass over the whole config.
printf 'Gated %s candidate file(s), %s alert line(s).\n' "${#CAND[@]}" "$ALERT_BLOCKS"
if [[ $FAILED -eq 0 ]]; then
  ok "all monitoring checks passed (skips are not failures)"
else
  fail "one or more monitoring checks failed"
fi
exit "$FAILED"
