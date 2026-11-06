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

TABLES = ("chapters", "books", "authors", "a", "b")


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


def col(type_, nullable=True, foreign_key=None):
    d = {"type": type_, "nullable": nullable}
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
    try:
        with connection.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS chapters, books, authors, a, b CASCADE;")
        connection.commit()
        yield connection
    finally:
        with connection.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS chapters, books, authors, a, b CASCADE;")
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
    """A migration run inside a transaction, then rolled back, must
    leave the schema and the data as they were: the books table
    gone, the author row still there. PostgreSQL DDL is
    transactional; the generator's rollback SQL is the DROP TABLE
    the plan records."""
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
