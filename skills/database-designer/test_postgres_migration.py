"""PostgreSQL integration tests for migration_generator.py.

The SQLite integration tests cannot see the failure this file
proves: SQLite lets CREATE TABLE name a foreign key to a table that
does not exist yet (FK enforcement is DML-only, and PRAGMA
foreign_keys is off by default), so an FK-order bug passes there
and fails on PostgreSQL. These tests run the generator's full
forward SQL against a real PostgreSQL and assert the FKs are
enforced.

Run locally only with a database: DATABASE_URL must point at a
PostgreSQL the tests may create and drop tables in (a scratch
database). Without it every test skips. CI runs this file in the
postgres-migration job with a service container; the local suite
never needs a database.

Run: DATABASE_URL=postgresql://user:pass@localhost:5432/db \\
    python3 -m pytest skills/database-designer/test_postgres_migration.py -q
"""

import os
import sys
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from migration_generator import MigrationGenerator, SchemaComparator  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="no DATABASE_URL: PostgreSQL not available (CI runs this job with a service container)",
)

TABLES = ("chapters", "books", "authors", "a", "b", "users", "events", "orders")


def schema(tables):
    return {"tables": tables}


def table(columns, primary_key=None):
    return {
        "columns": columns,
        "primary_key": primary_key or [],
        "unique_constraints": [],
        "check_constraints": {},
        "indexes": [],
    }


def col(type_, nullable=True, unique=False, foreign_key=None):
    d = {"type": type_, "nullable": nullable}
    if unique:
        d["unique"] = True
    if foreign_key:
        d["foreign_key"] = foreign_key
    return d


def chain_schemas():
    current = {}
    target = {
        "chapters": table(
            {
                "id": col("SERIAL"),
                "book_id": col("INT", foreign_key="books.id"),
                "title": col("TEXT"),
            },
            primary_key=["id"],
        ),
        "books": table(
            {
                "id": col("SERIAL"),
                "author_id": col("INT", foreign_key="authors.id"),
                "title": col("TEXT"),
            },
            primary_key=["id"],
        ),
        "authors": table(
            {
                "id": col("SERIAL"),
                "name": col("TEXT"),
            },
            primary_key=["id"],
        ),
    }
    return current, target


def generate(current, target):
    comp = SchemaComparator()
    comp.load_schemas(schema(current), schema(target))
    changes = comp.compare_schemas()
    gen = MigrationGenerator()
    return gen.generate_migration(
        changes, current_schema=schema(current), target_schema=schema(target)
    )


@pytest.fixture
def conn():
    connection = psycopg.connect(DATABASE_URL)
    drop_all = f"DROP TABLE IF EXISTS {', '.join(TABLES)} CASCADE;"
    try:
        with connection.cursor() as cur:
            cur.execute(drop_all)
        connection.commit()
        yield connection
    finally:
        # A test that failed mid-transaction leaves the connection
        # aborted; roll back first so the cleanup DROP can run and
        # a failure cannot leak tables into the next test.
        connection.rollback()
        with connection.cursor() as cur:
            cur.execute(drop_all)
        connection.commit()
        connection.close()


def _table_names(connection):
    with connection.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY 1;"
        )
        return [row[0] for row in cur.fetchall()]


def _fk_names(connection):
    with connection.cursor() as cur:
        cur.execute(
            "SELECT constraint_name FROM "
            "information_schema.table_constraints "
            "WHERE constraint_type = 'FOREIGN KEY' ORDER BY 1;"
        )
        return [row[0] for row in cur.fetchall()]


def test_fk_order_chain_executes_on_postgres(conn):
    """The FK-order repro: the old generator emitted books before
    authors on some hash seeds, and PostgreSQL rejects a FK to a
    table that does not exist yet. SQLite cannot see this failure.
    The full forward SQL must execute, and both FK constraints must
    exist afterwards."""
    _, target = chain_schemas()
    plan = generate({}, target)
    with conn.cursor() as cur:
        for step in plan.steps:
            cur.execute(step.sql_forward)
    conn.commit()
    assert _table_names(conn) == ["authors", "books", "chapters"]
    assert _fk_names(conn) == ["fk_books_author_id", "fk_chapters_book_id"]


def test_invalid_insert_fails_on_postgres(conn):
    """A book naming an author that does not exist must fail: the FK
    is enforced on PostgreSQL. (SQLite accepts the insert unless
    PRAGMA foreign_keys is on — the blind spot.)"""
    _, target = chain_schemas()
    plan = generate({}, target)
    with conn.cursor() as cur:
        for step in plan.steps:
            cur.execute(step.sql_forward)
        cur.execute("INSERT INTO authors (id, name) VALUES (1, 'A');")
    conn.commit()
    with conn.cursor() as cur:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute("INSERT INTO books (id, author_id, title) VALUES (1, 999, 'B');")
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM books;")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT COUNT(*) FROM authors;")
        assert cur.fetchone()[0] == 1


def test_fk_cycle_executes_on_postgres(conn):
    """A foreign-key cycle (A references B, B references A) has no
    valid inline order. The generator defers both FKs to post-create
    ADD CONSTRAINT steps; the full forward SQL must execute, and
    both constraints must exist and be live."""
    current = {}
    target = {
        "a": table(
            {"id": col("SERIAL"), "b_id": col("INT", foreign_key="b.id")}, primary_key=["id"]
        ),
        "b": table(
            {"id": col("SERIAL"), "a_id": col("INT", foreign_key="a.id")}, primary_key=["id"]
        ),
    }
    plan = generate(current, target)
    with conn.cursor() as cur:
        for step in plan.steps:
            cur.execute(step.sql_forward)
    conn.commit()
    assert _fk_names(conn) == ["fk_a_b_id", "fk_b_a_id"]
    with conn.cursor() as cur:
        cur.execute("INSERT INTO a (id, b_id) VALUES (1, NULL);")
        cur.execute("INSERT INTO b (id, a_id) VALUES (1, 1);")
        cur.execute("UPDATE a SET b_id = 1 WHERE id = 1;")
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute("UPDATE a SET b_id = 999 WHERE id = 1;")
    conn.rollback()


def test_rollback_restores_schema_and_data(conn):
    """A migration run inside a transaction, then rolled back with
    conn.rollback(), must leave the schema and the data as they
    were: the books table gone, the author row still there. This
    proves PostgreSQL transactional DDL rollback — it does NOT
    execute the generator's sql_rollback statements (that is the
    next test's job)."""
    _, target = chain_schemas()
    with conn.cursor() as cur:
        cur.execute("CREATE TABLE authors (id SERIAL PRIMARY KEY, name TEXT);")
        cur.execute("INSERT INTO authors (id, name) VALUES (1, 'A');")
    conn.commit()
    plan = generate({"authors": target["authors"]}, target)
    with conn.cursor() as cur:
        for step in plan.steps:
            cur.execute(step.sql_forward)
    conn.rollback()
    assert _table_names(conn) == ["authors"]
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM authors WHERE id = 1;")
        assert cur.fetchone()[0] == "A"


def f1_schemas():
    """Reviewer 4's F1 repro (round 5): a new table events with an
    FK to a column added to an existing table in the same migration."""
    current = {"users": table({"id": col("SERIAL")}, primary_key=["id"])}
    target = {
        "users": table(
            {"id": col("SERIAL"), "external_id": col("TEXT", unique=True)},
            primary_key=["id"],
        ),
        "events": table(
            {
                "id": col("SERIAL"),
                "user_external_id": col("TEXT", foreign_key="users.external_id"),
            },
            primary_key=["id"],
        ),
    }
    return current, target


def _columns(connection, table_name):
    with connection.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s ORDER BY 1;",
            (table_name,),
        )
        return [row[0] for row in cur.fetchall()]


def _constraint_names(connection):
    """Named PK/unique/FK constraints only. PostgreSQL also creates
    NOT NULL constraints with OID-derived names
    (e.g. 2200_17521_1_not_null) that no assertion should depend
    on; information_schema reports them as CHECK constraints."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT constraint_name FROM "
            "information_schema.table_constraints "
            "WHERE table_schema = 'public' AND constraint_type IN "
            "('PRIMARY KEY', 'UNIQUE', 'FOREIGN KEY') ORDER BY 1;"
        )
        return [row[0] for row in cur.fetchall()]


def _snapshot(connection):
    """(tables, {table: sorted columns}, sorted constraint names) —
    enough to tell whether a rollback restored the schema."""
    tables = _table_names(connection)
    return (
        tables,
        {t: _columns(connection, t) for t in tables},
        _constraint_names(connection),
    )


def test_fk_to_new_column_on_existing_table_executes_on_postgres(conn):
    """F1 acceptance (round 5): the reviewer's scenario must execute
    on real PostgreSQL, and afterwards the column must exist, the
    unique constraint must exist, and an insert naming a nonexistent
    external_id must be rejected. The old generator failed at the
    first step (UndefinedColumn)."""
    current, target = f1_schemas()
    with conn.cursor() as cur:
        cur.execute("CREATE TABLE users (id SERIAL PRIMARY KEY);")
        cur.execute("INSERT INTO users (id) VALUES (1);")
    conn.commit()
    plan = generate(current, target)
    with conn.cursor() as cur:
        for step in plan.steps:
            cur.execute(step.sql_forward)
    conn.commit()
    assert _columns(conn, "users") == ["external_id", "id"]
    # users_pkey is PostgreSQL's own name for the PK the test setup
    # created with plain PRIMARY KEY; the generator names the PKs
    # it creates pk_<table> (pk_events here).
    assert _constraint_names(conn) == [
        "fk_events_user_external_id",
        "pk_events",
        "uq_users_external_id",
        "users_pkey",
    ]
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET external_id = 'ext-1' WHERE id = 1;")
        cur.execute("INSERT INTO events (id, user_external_id) VALUES (1, 'ext-1');")
    conn.commit()
    with conn.cursor() as cur:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute("INSERT INTO events (id, user_external_id) VALUES (2, 'no-such-user');")
    conn.rollback()


def test_generated_rollback_sql_restores_schema(conn):
    """G2 (round 5): the old rollback test only proved PostgreSQL
    transactional rollback (conn.rollback()). This one executes the
    generator's own sql_rollback statements, in rollback_order,
    after a commit — and the schema afterwards must equal the
    schema before the migration, data included. The F1 scenario
    is non-destructive, so a full restore is expected."""
    current, target = f1_schemas()
    with conn.cursor() as cur:
        cur.execute("CREATE TABLE users (id SERIAL PRIMARY KEY);")
        cur.execute("INSERT INTO users (id) VALUES (1);")
    conn.commit()
    before = _snapshot(conn)
    plan = generate(current, target)
    with conn.cursor() as cur:
        for step in plan.steps:
            cur.execute(step.sql_forward)
    conn.commit()
    assert _table_names(conn) == ["events", "users"]
    by_id = {step.step_id: step for step in plan.steps}
    with conn.cursor() as cur:
        for step_id in plan.rollback_order:
            cur.execute(by_id[step_id].sql_rollback)
    conn.commit()
    assert _snapshot(conn) == before
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users;")
        assert cur.fetchall() == [(1,)]
