"""Tests for migration_generator.py (the database-designer migration tool).

Each test covers a real defect found by an external review (2026-11-06):
a unique-only change produced an empty ALTER, a foreign-key or check
change produced no SQL at all, constraints were added before the old
ones were dropped (a primary-key swap fails), a renamed table's column
changes were never compared, and the zero-downtime path dropped the
original column at LOW risk with a temp column that carried only the
data type. Run:
    python3 -m pytest skills/database-designer/test_migration_generator.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from migration_generator import MigrationGenerator, SchemaComparator


def schema(tables):
    """A schema dict in the JSON format load_schemas expects."""
    return {"tables": tables}


def table(columns, primary_key=None, unique_constraints=None,
          check_constraints=None, indexes=None):
    return {"columns": columns, "primary_key": primary_key or [],
            "unique_constraints": unique_constraints or [],
            "check_constraints": check_constraints or {},
            "indexes": indexes or []}


def col(type_, nullable=True, unique=False, foreign_key=None,
        default=None, check_constraint=None):
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


def compare_and_generate(current, target, zero_downtime=False):
    comp = SchemaComparator()
    comp.load_schemas(schema(current), schema(target))
    changes = comp.compare_schemas()
    gen = MigrationGenerator(zero_downtime=zero_downtime)
    return changes, gen.generate_migration(changes)


def step_sql(plan, step_type):
    return [s for s in plan.steps if s.step_type == step_type]


def test_unique_only_change_produces_valid_sql(tmp_path):
    """A unique-only change used to produce 'ALTER TABLE t\\n    ;' —
    an empty ALTER, invalid SQL that claims to do the change."""
    current = {"users": table({"email": col("VARCHAR(255)")})}
    target = {"users": table({"email": col("VARCHAR(255)", unique=True)})}
    changes, plan = compare_and_generate(current, target)
    assert len(changes["columns_modified"]) == 1
    steps = step_sql(plan, "MODIFY_COLUMN")
    assert len(steps) == 1
    sql = steps[0].sql_forward
    assert "ADD CONSTRAINT" in sql and "UNIQUE" in sql and "email" in sql
    assert sql.strip() != "ALTER TABLE users\n    ;"
    assert "ALTER TABLE users\n    ;" not in sql


def test_unique_removal_drops_the_constraint():
    current = {"users": table({"email": col("VARCHAR(255)", unique=True)})}
    target = {"users": table({"email": col("VARCHAR(255)")})}
    _, plan = compare_and_generate(current, target)
    sql = step_sql(plan, "MODIFY_COLUMN")[0].sql_forward
    # Dropping a constraint does not restate its type; the constraint
    # name carries it.
    assert "DROP CONSTRAINT uq_users_email" in sql


def test_foreign_key_change_produces_sql():
    """The eval recorded that the FK in the target schema was NOT
    created after migration. A FK change must now produce a step."""
    current = {"orders": table({"user_id": col("INTEGER")})}
    target = {"orders": table(
        {"user_id": col("INTEGER", foreign_key="users.id")})}
    _, plan = compare_and_generate(current, target)
    sql = step_sql(plan, "MODIFY_COLUMN")[0].sql_forward
    assert "FOREIGN KEY" in sql and "REFERENCES users(id)" in sql


def test_check_only_change_produces_sql():
    current = {"items": table({"price": col("NUMERIC")})}
    target = {"items": table(
        {"price": col("NUMERIC", check_constraint="price > 0")})}
    _, plan = compare_and_generate(current, target)
    sql = step_sql(plan, "MODIFY_COLUMN")[0].sql_forward
    assert "CHECK" in sql and "price > 0" in sql


def test_primary_key_swap_drops_before_it_adds():
    """Adding the new PK while the old one still exists fails. The
    removal step must come first in the execution order."""
    current = {"t": table({"id": col("INTEGER"), "code": col("TEXT")},
                          primary_key=["id"])}
    target = {"t": table({"id": col("INTEGER"), "code": col("TEXT")},
                         primary_key=["code"])}
    _, plan = compare_and_generate(current, target)
    drops = [i for i, s in enumerate(plan.steps) if s.step_type == "DROP_CONSTRAINT"]
    adds = [i for i, s in enumerate(plan.steps) if s.step_type == "ADD_CONSTRAINT"]
    assert drops and adds, [s.sql_forward for s in plan.steps]
    assert drops[0] < adds[0], "the old PK must be dropped before the new one is added"


def test_renamed_table_column_change_is_compared():
    """A table that was renamed AND had a column changed: the column
    change used to be lost entirely (it is in neither common_tables)."""
    current = {"old_name": table(
        {"id": col("INTEGER"), "name": col("VARCHAR(50)")},
        primary_key=["id"])}
    target = {"new_name": table(
        {"id": col("INTEGER"), "name": col("VARCHAR(100)")},
        primary_key=["id"])}
    changes, plan = compare_and_generate(current, target)
    assert len(changes["tables_renamed"]) == 1
    assert len(changes["columns_modified"]) == 1
    mod = changes["columns_modified"][0]
    assert mod["table"] == "old_name"  # the column step runs before the rename
    assert "type" in " ".join(mod["changes"])
    assert any("VARCHAR(100)" in s.sql_forward for s in plan.steps)


def test_renamed_table_constraint_change_is_compared():
    current = {"old_name": table(
        {"id": col("INTEGER")}, primary_key=["id"])}
    target = {"new_name": table(
        {"id": col("INTEGER")}, primary_key=[])}
    changes, _ = compare_and_generate(current, target)
    assert len(changes["tables_renamed"]) == 1
    assert len(changes["constraints_dropped"]) == 1


def test_zero_downtime_drop_is_high_risk_and_temp_column_is_complete():
    """The DROP COLUMN step used to inherit LOW risk, and the temp
    column carried only the data type — not the target's constraints."""
    current = {"t": table({"v": col("VARCHAR(50)")})}
    target = {"t": table({"v": col(
        "VARCHAR(100)", nullable=False, unique=True, default="'x'",
        check_constraint="v <> ''")})}
    _, plan = compare_and_generate(current, target, zero_downtime=True)
    drop = step_sql(plan, "DROP_OLD_COLUMN")
    assert len(drop) == 1
    assert drop[0].risk_level == "HIGH", drop[0].risk_level
    add_temp = step_sql(plan, "ADD_TEMP_COLUMN")[0].sql_forward
    assert "VARCHAR(100)" in add_temp
    assert "NOT NULL" in add_temp
    assert "UNIQUE" in add_temp
    assert "DEFAULT 'x'" in add_temp
    assert "CHECK (v <> '')" in add_temp
    assert "zero_downtime_warning" in plan.summary
    assert "DRAFT" in plan.summary["zero_downtime_warning"]


def test_zero_downtime_phases_are_expand_then_contract():
    current = {"t": table({"v": col("VARCHAR(50)")})}
    target = {"t": table({"v": col("VARCHAR(100)")})}
    _, plan = compare_and_generate(current, target, zero_downtime=True)
    phases = [s.zero_downtime_phase for s in plan.steps]
    assert phases == ["EXPAND", "EXPAND", "CONTRACT", "CONTRACT"], phases


def test_describe_includes_check_constraint():
    current = {"t": table({"v": col("NUMERIC")})}
    target = {"t": table({"v": col("NUMERIC", check_constraint="v > 0")})}
    changes, _ = compare_and_generate(current, target)
    assert any("check:" in c for c in changes["columns_modified"][0]["changes"])


def test_no_change_produces_no_modify_step():
    current = {"t": table({"v": col("VARCHAR(50)")})}
    target = {"t": table({"v": col("VARCHAR(50)")})}
    _, plan = compare_and_generate(current, target)
    assert step_sql(plan, "MODIFY_COLUMN") == []


# --- Second review round: regression tests (2026-11-06) ---

def test_same_name_index_change_is_detected():
    """An index that keeps its name but changes columns must be
    detected: comparing only the name set missed it entirely."""
    current = {"orders": table(
        {"id": col("INTEGER"), "user_id": col("INTEGER"),
         "created_at": col("TEXT")},
        indexes=[{"name": "idx_orders_search", "columns": ["user_id"]}] )}
    target = {"orders": table(
        {"id": col("INTEGER"), "user_id": col("INTEGER"),
         "created_at": col("TEXT")},
        indexes=[{"name": "idx_orders_search", "columns": ["created_at"]}] )}
    changes, plan = compare_and_generate(current, target)
    assert len(changes["indexes_dropped"]) == 1
    assert len(changes["indexes_added"]) == 1
    assert any("DROP INDEX idx_orders_search" in s.sql_forward
               for s in step_sql(plan, "DROP_INDEX"))
    assert any("created_at" in s.sql_forward
               for s in step_sql(plan, "ADD_INDEX"))


def test_rename_with_column_drop_uses_new_name():
    """A renamed table that also loses a column: the DROP COLUMN runs
    AFTER the rename, so it must name the NEW table — the old code
    recorded it under the old name and produced SQL against a table
    that no longer existed."""
    current = {"orders": table(
        {"id": col("INTEGER"), "user_id": col("INTEGER"),
         "amount": col("NUMERIC"), "note": col("TEXT")},
        primary_key=["id"])}
    target = {"purchases": table(
        {"id": col("INTEGER"), "user_id": col("INTEGER"),
         "amount": col("NUMERIC")},
        primary_key=["id"])}
    changes, plan = compare_and_generate(current, target)
    assert len(changes["tables_renamed"]) == 1
    drops = step_sql(plan, "DROP_COLUMN")
    assert len(drops) == 1
    assert "ALTER TABLE purchases DROP COLUMN note" in drops[0].sql_forward
    # And the drop really comes after the rename in execution order.
    order = [s.step_type for s in plan.steps]
    assert order.index("RENAME_TABLE") < order.index("DROP_COLUMN")


def test_create_table_fk_uses_table_column_syntax():
    """A foreign key stored as "users.id" must become
    REFERENCES users(id) in CREATE TABLE — "users.id" is invalid SQL."""
    target = {"books": table(
        {"id": col("INTEGER"),
         "author_id": col("INTEGER", foreign_key="authors.id")},
        primary_key=["id"]),
        "authors": table({"id": col("INTEGER")}, primary_key=["id"])}
    _, plan = compare_and_generate({}, target)
    creates = [s for s in step_sql(plan, "CREATE_TABLE") if s.table == "books"]
    assert len(creates) == 1
    assert "REFERENCES authors(id)" in creates[0].sql_forward
    assert "REFERENCES authors.id" not in creates[0].sql_forward


def test_create_table_emits_table_level_constraints():
    """Table-level unique and check constraints must appear in the
    CREATE TABLE — they used to be silently dropped."""
    target = {"t": table(
        {"a": col("TEXT"), "b": col("TEXT"), "v": col("NUMERIC")},
        unique_constraints=[["a", "b"]],
        check_constraints={"ck_t_v": "v > 0"})}
    _, plan = compare_and_generate({}, target)
    sql = step_sql(plan, "CREATE_TABLE")[0].sql_forward
    assert "CONSTRAINT uq_t_a_b UNIQUE (a, b)" in sql
    assert "CONSTRAINT ck_t_v CHECK (v > 0)" in sql


def test_add_column_keeps_constraints():
    """A new column's UNIQUE, foreign key and CHECK must survive into
    the ADD COLUMN — they used to be dropped."""
    current = {"users": table({"id": col("INTEGER")}, primary_key=["id"])}
    target = {"users": table(
        {"id": col("INTEGER"),
         "email": col("TEXT", unique=True),
         "status": col("TEXT", check_constraint="status IN ('a', 'b')"),
         "group_id": col("INTEGER", foreign_key="groups.id")},
        primary_key=["id"]),
        "groups": table({"id": col("INTEGER")}, primary_key=["id"])}
    _, plan = compare_and_generate(current, target)
    adds = {s.description: s.sql_forward for s in step_sql(plan, "ADD_COLUMN")}
    email_sql = [v for k, v in adds.items() if "email" in k][0]
    assert "UNIQUE" in email_sql
    status_sql = [v for k, v in adds.items() if "status" in k][0]
    assert "CHECK (status IN ('a', 'b'))" in status_sql
    group_sql = [v for k, v in adds.items() if "group_id" in k][0]
    assert "REFERENCES groups(id)" in group_sql


def test_new_table_indexes_are_created():
    """An index declared on a NEW table must be created: the CREATE
    TABLE step does not emit indexes, and _compare_indexes only
    looked at tables present in both schemas — so the index was
    silently lost. Found by the SQLite integration tests."""
    target = {"t": table(
        {"id": col("INTEGER"), "email": col("TEXT")},
        primary_key=["id"],
        indexes=[{"name": "idx_t_email", "columns": ["email"]}] )}
    _, plan = compare_and_generate({}, target)
    adds = step_sql(plan, "ADD_INDEX")
    assert len(adds) == 1
    assert "CREATE INDEX idx_t_email ON t (email)" in adds[0].sql_forward
    # And it runs after the CREATE TABLE.
    order = [s.step_type for s in plan.steps]
    assert order.index("CREATE_TABLE") < order.index("ADD_INDEX")
