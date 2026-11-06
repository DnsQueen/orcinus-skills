"""SQLite integration tests for migration_generator.py.

Unlike test_migration_generator.py (which asserts on generated SQL
strings), these tests EXECUTE the migration: build the old schema in a
real SQLite database, insert data, run the generated forward SQL,
introspect the final schema with PRAGMA, compare it to the target,
check the data survived, and run the rollback. A test that only checks
for the substring "ADD CONSTRAINT" cannot prove the SQL runs, the
order is valid, the final schema equals the target, or the data is
still there.

Dialect: the generator emits PostgreSQL-style SQL. SQLite executes the
overlapping subset (CREATE TABLE, ADD/DROP COLUMN, CREATE/DROP INDEX,
RENAME TABLE, DROP TABLE). Steps SQLite cannot run (ADD/DROP
CONSTRAINT, ALTER COLUMN) are Postgres-only; every test below uses a
scenario whose plan contains only SQLite-compatible steps, and asserts
that. One such gap, found while writing these tests: SQLite rejects
ADD COLUMN with a UNIQUE constraint ("Cannot add a UNIQUE column") —
for SQLite that needs a CREATE UNIQUE INDEX instead, so the ADD COLUMN
test below uses CHECK and REFERENCES (which SQLite accepts) and the
UNIQUE case is covered on CREATE TABLE.

Run: python3 -m pytest skills/database-designer/test_migration_integration.py -q
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from migration_generator import MigrationGenerator, SchemaComparator

# Step types SQLite cannot execute (Postgres-only SQL).
NON_SQLITE_STEPS = {
    "MODIFY_COLUMN",
    "ADD_CONSTRAINT",
    "DROP_CONSTRAINT",
    "ADD_COLUMN_ZD",
    "ADD_TEMP_COLUMN",
    "DROP_OLD_COLUMN",
    "COPY_DATA",
    "VALIDATE_DATA",
}


def schema(tables):
    return {"tables": tables}


def table(columns, primary_key=None, unique_constraints=None, check_constraints=None, indexes=None):
    return {
        "columns": columns,
        "primary_key": primary_key or [],
        "unique_constraints": unique_constraints or [],
        "check_constraints": check_constraints or {},
        "indexes": indexes or [],
    }


def col(type_, nullable=True, unique=False, foreign_key=None, default=None, check_constraint=None):
    d = {"type": type_, "nullable": nullable}
    if unique:
        d["unique"] = True
    if foreign_key:
        d["foreign_key"] = foreign_key
    if default is not None:
        d["default"] = default
    if check_constraint:
        d["check_constraint"] = check_constraint
    return d


def compare_and_generate(current, target):
    comp = SchemaComparator()
    comp.load_schemas(schema(current), schema(target))
    changes = comp.compare_schemas()
    gen = MigrationGenerator()
    return changes, gen.generate_migration(
        changes, current_schema=schema(current), target_schema=schema(target)
    )


def new_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def execute_plan(conn, plan):
    """Run every forward step on SQLite. Fails if the plan contains a
    step SQLite cannot execute — the scenario, not the assertion,
    must stay inside the supported subset."""
    types = {s.step_type for s in plan.steps}
    bad = types & NON_SQLITE_STEPS
    assert not bad, f"plan contains Postgres-only steps: {sorted(bad)}"
    for step in plan.steps:
        conn.executescript(step.sql_forward)
    conn.commit()


def execute_rollback(conn, plan):
    """Run the rollback SQL in reverse execution order."""
    for step in reversed(plan.steps):
        conn.executescript(step.sql_rollback)
    conn.commit()


def introspect(conn):
    """The live schema, normalised: {table: {"columns": {name:
    (type, notnull)}, "indexes": {name: (columns, unique)}, "fks":
    [(from_col, ref_table, ref_col)]}}."""
    out = {}
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    for t in tables:
        columns = {}
        for row in conn.execute(f"PRAGMA table_info({t})"):
            # row: cid, name, type, notnull, dflt_value, pk
            columns[row[1]] = (row[2].upper(), bool(row[3]))
        indexes = {}
        for row in conn.execute(f"PRAGMA index_list({t})"):
            # row: seq, name, unique, origin, partial
            name, unique = row[1], bool(row[2])
            if name.startswith("sqlite_autoindex_"):
                # An autoindex is SQLite's implementation of a UNIQUE
                # column constraint, not a declared index.
                continue
            cols = [r[2] for r in conn.execute(f"PRAGMA index_info({name})")]
            indexes[name] = (cols, unique)
        fks = [(r[3], r[2], r[4]) for r in conn.execute(f"PRAGMA foreign_key_list({t})")]
        out[t] = {"columns": columns, "indexes": indexes, "fks": sorted(fks)}
    return out


def build_v1(conn, current):
    """Create the v1 schema by executing the generator's own
    CREATE TABLE steps for it, so v1 is built by the code under test."""
    _, plan = compare_and_generate({}, current)
    execute_plan(conn, plan)
    return plan


def expected_schema(target):
    """The target schema dict, normalised the same way introspect()
    normalises the live database (columns, indexes, FKs only)."""
    out = {}
    for name, t in target.items():
        columns = {}
        for col_name, col_def in t["columns"].items():
            # A primary-key column is NOT NULL in SQLite even when the
            # schema dict does not say so.
            notnull = not col_def.get("nullable", True) or col_name in t.get("primary_key", [])
            columns[col_name] = (col_def.get("type", "VARCHAR(255)").upper(), notnull)
        indexes = {}
        for idx in t.get("indexes", []):
            indexes[idx["name"]] = (list(idx["columns"]), bool(idx.get("unique", False)))
        fks = []
        for col_name, col_def in t["columns"].items():
            if col_def.get("foreign_key"):
                ref_table, ref_col = col_def["foreign_key"].rsplit(".", 1)
                fks.append((col_name, ref_table, ref_col))
        out[name] = {"columns": columns, "indexes": indexes, "fks": sorted(fks)}
    return out


def test_index_change_executes_and_matches_target():
    """§3.5: an index that keeps its name but changes columns — the
    migration must drop the old index and create the new one, and the
    live index must cover the new columns."""
    current = {
        "orders": table(
            {
                "id": col("INTEGER", nullable=False),
                "user_id": col("INTEGER"),
                "created_at": col("TEXT"),
            },
            primary_key=["id"],
            indexes=[{"name": "idx_orders_search", "columns": ["user_id"]}],
        )
    }
    target = {
        "orders": table(
            {
                "id": col("INTEGER", nullable=False),
                "user_id": col("INTEGER"),
                "created_at": col("TEXT"),
            },
            primary_key=["id"],
            indexes=[{"name": "idx_orders_search", "columns": ["created_at"]}],
        )
    }
    conn = new_db()
    build_v1(conn, current)
    conn.execute("INSERT INTO orders VALUES (1, 7, '2026-01-01')")
    _, plan = compare_and_generate(current, target)
    assert [s.step_type for s in plan.steps] == ["DROP_INDEX", "ADD_INDEX"]
    execute_plan(conn, plan)
    live = introspect(conn)
    assert live["orders"]["indexes"]["idx_orders_search"] == (["created_at"], False)
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
    execute_rollback(conn, plan)
    live = introspect(conn)
    assert live["orders"]["indexes"]["idx_orders_search"] == (["user_id"], False)


def test_rename_and_drop_column_executes_with_data_surviving():
    """§3.6: a renamed table that also loses a column — the DROP COLUMN
    must name the new table, the data must survive, and the rollback
    must restore the old table (with the dropped column back, empty)."""
    current = {
        "orders": table(
            {
                "id": col("INTEGER", nullable=False),
                "user_id": col("INTEGER"),
                "amount": col("NUMERIC"),
                "note": col("TEXT"),
            },
            primary_key=["id"],
        )
    }
    target = {
        "purchases": table(
            {
                "id": col("INTEGER", nullable=False),
                "user_id": col("INTEGER"),
                "amount": col("NUMERIC"),
            },
            primary_key=["id"],
        )
    }
    conn = new_db()
    build_v1(conn, current)
    conn.execute("INSERT INTO orders VALUES (1, 7, 42.5, 'gift')")
    conn.execute("INSERT INTO orders VALUES (2, 8, 10.0, NULL)")
    _, plan = compare_and_generate(current, target)
    execute_plan(conn, plan)
    live = introspect(conn)
    assert "orders" not in live
    assert "purchases" in live
    assert list(live["purchases"]["columns"]) == ["id", "user_id", "amount"]
    rows = conn.execute("SELECT id, user_id, amount FROM purchases ORDER BY id").fetchall()
    assert rows == [(1, 7, 42.5), (2, 8, 10.0)]
    execute_rollback(conn, plan)
    live = introspect(conn)
    assert "orders" in live and "purchases" not in live
    assert "note" in live["orders"]["columns"]
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 2


def test_create_table_with_fk_and_constraints_executes():
    """§3.7: CREATE TABLE must emit a valid REFERENCES (not
    "users.id") and the table-level unique and check constraints —
    and SQLite must actually enforce them."""
    target = {
        "authors": table(
            {"id": col("INTEGER", nullable=False), "name": col("TEXT")}, primary_key=["id"]
        ),
        "books": table(
            {
                "id": col("INTEGER", nullable=False),
                "author_id": col("INTEGER", foreign_key="authors.id"),
                "title": col("TEXT"),
                "price": col("NUMERIC", check_constraint="price > 0"),
            },
            primary_key=["id"],
            unique_constraints=[["title"]],
        ),
    }
    conn = new_db()
    _, plan = compare_and_generate({}, target)
    execute_plan(conn, plan)
    live = introspect(conn)
    assert live["books"]["fks"] == [("author_id", "authors", "id")]
    conn.execute("INSERT INTO authors VALUES (1, 'A')")
    conn.execute("INSERT INTO books VALUES (1, 1, 'Dune', 9.99)")
    # The unique constraint on title is enforced.
    try:
        conn.execute("INSERT INTO books VALUES (2, 1, 'Dune', 5.0)")
        raise AssertionError("duplicate title was accepted")
    except sqlite3.IntegrityError:
        pass
    # The check constraint on price is enforced.
    try:
        conn.execute("INSERT INTO books VALUES (2, 1, 'Other', -1)")
        raise AssertionError("negative price was accepted")
    except sqlite3.IntegrityError:
        pass
    # The foreign key is enforced.
    try:
        conn.execute("INSERT INTO books VALUES (2, 99, 'Other', 5.0)")
        raise AssertionError("dangling author_id was accepted")
    except sqlite3.IntegrityError:
        pass


def test_add_column_with_check_and_fk_executes():
    """§3.7: an added column keeps its CHECK and REFERENCES — as
    named ADD CONSTRAINT steps. The columns themselves execute on
    SQLite (data survives); the constraint steps are Postgres-only
    (ADD CONSTRAINT is not SQLite syntax), so they are asserted by
    string, not executed. The old version of this test asserted the
    constraints inline in the ADD COLUMN — that was the bug: an
    inline UNIQUE/CHECK is unnamed and cannot be dropped by name
    later. Live enforcement of the CHECK/FK on SQLite is therefore
    no longer part of this test; it is covered by the CREATE TABLE
    test above, which still executes the named constraints."""
    current = {
        "groups": table(
            {"id": col("INTEGER", nullable=False), "label": col("TEXT")}, primary_key=["id"]
        ),
        "users": table(
            {"id": col("INTEGER", nullable=False), "name": col("TEXT")}, primary_key=["id"]
        ),
    }
    target = {
        "groups": table(
            {"id": col("INTEGER", nullable=False), "label": col("TEXT")}, primary_key=["id"]
        ),
        "users": table(
            {
                "id": col("INTEGER", nullable=False),
                "name": col("TEXT"),
                "status": col("TEXT", check_constraint="status IN ('a', 'b')"),
                "group_id": col("INTEGER", foreign_key="groups.id"),
            },
            primary_key=["id"],
        ),
    }
    conn = new_db()
    build_v1(conn, current)
    conn.execute("INSERT INTO groups VALUES (1, 'g1')")
    conn.execute("INSERT INTO users VALUES (1, 'Niloufar')")
    _, plan = compare_and_generate(current, target)
    # Execute the ADD COLUMN steps (SQLite can run them); the
    # ADD_CONSTRAINT steps are Postgres-only.
    for step in plan.steps:
        if step.step_type == "ADD_COLUMN":
            conn.executescript(step.sql_forward)
    conn.commit()
    conn.execute("UPDATE users SET status = 'a', group_id = 1 WHERE id = 1")
    assert conn.execute("SELECT status, group_id FROM users WHERE id = 1").fetchone() == ("a", 1)
    constraints = [s.sql_forward for s in plan.steps if s.step_type == "ADD_CONSTRAINT"]
    assert any(
        "ADD CONSTRAINT ck_users_status CHECK (status IN ('a', 'b'))" in s for s in constraints
    )
    assert any(
        "ADD CONSTRAINT fk_users_group_id FOREIGN KEY (group_id) REFERENCES groups(id)" in s
        for s in constraints
    )


def test_full_v1_to_v2_flow_matches_target_schema():
    """§3.8: the whole flow — build v1, insert data, run the
    migration, and compare the live schema to the target, not to a
    substring of the SQL. Then roll back and compare to v1."""
    current = {
        "users": table(
            {
                "id": col("INTEGER", nullable=False),
                "name": col("TEXT"),
                "email": col("TEXT"),
                "age": col("INTEGER"),
            },
            primary_key=["id"],
            indexes=[{"name": "idx_users_email", "columns": ["email"]}],
        ),
        "posts": table(
            {
                "id": col("INTEGER", nullable=False),
                "user_id": col("INTEGER", foreign_key="users.id"),
                "body": col("TEXT"),
            },
            primary_key=["id"],
        ),
    }
    target = {
        "users": table(
            {
                "id": col("INTEGER", nullable=False),
                "name": col("TEXT"),
                "email": col("TEXT"),
                "city": col("TEXT"),
            },
            primary_key=["id"],
            indexes=[
                {"name": "idx_users_email", "columns": ["email"]},
                {"name": "idx_users_name", "columns": ["name"]},
            ],
        ),
        "posts": table(
            {
                "id": col("INTEGER", nullable=False),
                "user_id": col("INTEGER", foreign_key="users.id"),
                "body": col("TEXT"),
            },
            primary_key=["id"],
        ),
        "tags": table(
            {"id": col("INTEGER", nullable=False), "label": col("TEXT", unique=True)},
            primary_key=["id"],
        ),
    }
    conn = new_db()
    build_v1(conn, current)
    conn.execute("INSERT INTO users VALUES (1, 'Niloufar', 'n@example.com', 30)")
    conn.execute("INSERT INTO posts VALUES (1, 1, 'hello')")
    _, plan = compare_and_generate(current, target)
    execute_plan(conn, plan)
    assert introspect(conn) == expected_schema(target)
    assert conn.execute("SELECT name, email, city FROM users WHERE id = 1").fetchone() == (
        "Niloufar",
        "n@example.com",
        None,
    )
    assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 1
    execute_rollback(conn, plan)
    assert introspect(conn) == expected_schema(current)
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
