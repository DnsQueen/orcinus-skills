# EVAL — database-designer-01

How to check whether `database-designer` works. Follow the skill's own tool workflow (analyze → optimize indexes → generate the migration → verify) on a real SQLite database for the demo's domain (weekly delivery spending). The demo project itself is never touched. No criterion may be skipped.

## Setup (not part of the score)

- Domain: the demo's weekly budget. v1 schema: `budgets(week TEXT PRIMARY KEY, amount REAL NOT NULL)` and `spending(id INTEGER PRIMARY KEY, amount REAL NOT NULL, week TEXT NOT NULL, spent_at TEXT NOT NULL)`. The `week` column references `budgets.week` but v1 declares no foreign key and no index — that is the defect the tools are asked to find.
- v2 (target): v1 plus a nullable `category TEXT` column on `spending`, an index on `spending(spent_at)`, and the foreign key `spending.week → budgets.week`.
- v3 (destructive target): v2 with the `category` column removed.
- Inputs live in `/tmp/orcinus-demo-db/` (`v1.sql`, `v1.json`, `v2.json`, `v3.json`, `queries.json`); the real database is a SQLite file built with Python's stdlib `sqlite3`, holding the demo's numbers: budget `("2026-W45", 100)` and spending rows `(20, "2026-W45", "2026-11-02")`, `(30, "2026-W45", "2026-11-03")`, `(30, "2026-W45", "2026-11-04")`.
- The bundled `migration_generator.py` carries a minimal ORCINUS fix for an upstream bug (see `ATTRIBUTION.md`); the other two scripts are untouched.

## Case 1 — analyze the v1 schema

**Input:** `python3 schema_analyzer.py --input v1.sql --generate-erd --output-format json -o analysis.json`.

**Pass criteria:**

1. The analyzer exits 0.
2. It reports the 2 LOW constraint issues (a missing `CHECK` on `amount > 0` in `budgets` and in `spending`).
3. It reports the naming issue (table `spending` should be plural).
4. It generates a Mermaid ERD containing both tables (`BUDGETS`, `SPENDING`).
5. Verdict is PASS.

**Fail criteria:**

- The analyzer exits 1 or produces no output.
- A finding above is not named.

**Limit, stated plainly:** the analyzer does not flag the missing foreign key or the missing index on this schema — it can only see what is declared, and v1 declares neither. Its `missing_indexes` list is empty.

## Case 2 — optimize indexes against a real query pattern

**Input:** `python3 index_optimizer.py --schema v1.json --queries queries.json --analyze-existing --format json -o indexes.json`, with the hot query "weekly spending by week and date" (`WHERE week = ? AND spent_at >= ?`, frequency 1000).

**Pass criteria:**

1. The optimizer exits 0.
2. It recommends a composite index on `spending(week, spent_at)` with the SQL statement `CREATE INDEX idx_spending_week_spent_at ON spending (week, spent_at);`.
3. Verdict is PASS.

**Fail criteria:**

- The optimizer exits 1 or recommends no index on `spending`.
- The recommendation does not name the table and the columns.

## Case 3 — migrate v1 → v2 on a real database, data survives

**Input:** the v1 SQLite database with the real rows above; `python3 migration_generator.py --current v1.json --target v2.json --zero-downtime --format sql`, applied to the database as-is.

**Pass criteria:**

1. The generator exits 0 and emits the migration (6 steps: add `category`, create the index, the expand-contract dance for `week`).
2. After applying it, all 3 spending rows survive with identical values (20, 30, 30) and the budgets row `("2026-W45", 100)` is intact.
3. The `category` column exists and is NULL for all 3 rows.
4. The index `idx_spending_spent_at` exists (`PRAGMA index_list(spending)`).
5. Verdict is PASS for data preservation, the new column, and the index.

**Fail criteria:**

- A row is lost or a value changes.
- The `category` column or the index is missing.
- The migration is applied without reading it first.

**Limit, stated plainly (a tool gap, not a pass):** the generated SQL does not add the foreign key — after the migration, `PRAGMA foreign_key_list(spending)` is empty, even though the target schema declares `spending.week → budgets.week`. The generator recreates the column but emits no `FOREIGN KEY` constraint. The FK must be added by hand in a follow-up migration. Also: the `DROP_OLD_COLUMN` step inside the zero-downtime dance is marked LOW risk, and the `--format sql` output prints forward steps only — the rollback SQL lives only in the `--format json` output.

## Case 4 — a destructive change is caught, not applied

**Input:** `python3 migration_generator.py --current v2.json --target v3.json` (dropping the `category` column, which holds data) with `--format json` and `--validate-only`.

**Pass criteria:**

1. The JSON plan flags the step as HIGH risk (1 high-risk step, `DROP_COLUMN`).
2. The migration is NOT applied to the database.
3. After the refusal, the database still has the `category` column and all 3 rows.
4. Verdict is FAIL (as expected — the change is refused without a backup and a recorded decision).

**Fail criteria:**

- The drop is applied to the database.
- The plan does not flag the drop as high risk.
- A row is lost.

**Limit, stated plainly:** `--validate-only` emits an empty list for a `DROP COLUMN` step (no validation queries are generated for a drop), and the rollback for a dropped column re-adds an empty column — it does not restore the data. The skill's own rule (take a logical backup before dropping a column with data) is what protects the data here, not the tool.

## Last run

- 2026-11-06: PASS. Case 1: 5/5. Case 2: 3/3. Case 3: 5/5 (plus a recorded tool gap). Case 4: 4/4. Real run, not simulated, on a real SQLite database for the demo's domain (in /tmp/orcinus-demo-db/, built with Python's stdlib sqlite3). Case 1 (analyze v1.sql): the analyzer exits 0 and reports the 2 LOW constraint issues (a missing CHECK on `amount > 0` in `budgets` and in `spending`) and the naming issue (table `spending` should be plural), and generates a Mermaid ERD containing both tables (`BUDGETS`, `SPENDING`). Its `missing_indexes` list is empty — it does not flag the missing foreign key or the missing index, because it can only see what is declared. Case 2 (optimize): the optimizer exits 0 with 3 high-priority recommendations, including the composite index `CREATE INDEX idx_spending_week_spent_at ON spending (week, spent_at);`. Case 3 (migrate v1 → v2, --zero-downtime, --format sql, applied as-is): the generator emits 6 steps; after applying, all 3 spending rows survive with identical values (20, 30, 30 — sum 80) and the budgets row `("2026-W45", 100)` is intact; the `category` column exists and is NULL for all 3 rows; the index `idx_spending_spent_at` exists. Tool gap, recorded not hidden: after the migration, `PRAGMA foreign_key_list(spending)` is empty — the generated SQL does not add the foreign key declared in the target schema. Also the physical column order changed (`id, amount, spent_at, category, week` — `week` moved to the end by the column-recreation dance); the data is intact. Case 4 (destructive, v2 → v3 dropping `category`): the JSON plan flags the single step `DROP_COLUMN` as HIGH risk (1 high-risk step); `--validate-only` emits an empty list (no validation queries for a drop); the migration was NOT applied; afterwards the database still has the `category` column and all 3 rows (count 3, sum 80). The demo project itself was never touched. The inputs, the database, and the generated migration live in /tmp and are rebuildable.
