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


def compare_and_generate(current, target, zero_downtime=False):
    comp = SchemaComparator()
    comp.load_schemas(schema(current), schema(target))
    changes = comp.compare_schemas()
    gen = MigrationGenerator(zero_downtime=zero_downtime)
    return changes, gen.generate_migration(
        changes, current_schema=schema(current), target_schema=schema(target)
    )


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
    target = {"orders": table({"user_id": col("INTEGER", foreign_key="users.id")})}
    _, plan = compare_and_generate(current, target)
    sql = step_sql(plan, "MODIFY_COLUMN")[0].sql_forward
    assert "FOREIGN KEY" in sql and "REFERENCES users(id)" in sql


def test_check_only_change_produces_sql():
    current = {"items": table({"price": col("NUMERIC")})}
    target = {"items": table({"price": col("NUMERIC", check_constraint="price > 0")})}
    _, plan = compare_and_generate(current, target)
    sql = step_sql(plan, "MODIFY_COLUMN")[0].sql_forward
    assert "CHECK" in sql and "price > 0" in sql


def test_primary_key_swap_drops_before_it_adds():
    """Adding the new PK while the old one still exists fails. The
    removal step must come first in the execution order."""
    current = {"t": table({"id": col("INTEGER"), "code": col("TEXT")}, primary_key=["id"])}
    target = {"t": table({"id": col("INTEGER"), "code": col("TEXT")}, primary_key=["code"])}
    _, plan = compare_and_generate(current, target)
    drops = [i for i, s in enumerate(plan.steps) if s.step_type == "DROP_CONSTRAINT"]
    adds = [i for i, s in enumerate(plan.steps) if s.step_type == "ADD_CONSTRAINT"]
    assert drops and adds, [s.sql_forward for s in plan.steps]
    assert drops[0] < adds[0], "the old PK must be dropped before the new one is added"


def test_renamed_table_column_change_is_compared():
    """A table that was renamed AND had a column changed: the column
    change used to be lost entirely (it is in neither common_tables)."""
    current = {
        "old_name": table({"id": col("INTEGER"), "name": col("VARCHAR(50)")}, primary_key=["id"])
    }
    target = {
        "new_name": table({"id": col("INTEGER"), "name": col("VARCHAR(100)")}, primary_key=["id"])
    }
    changes, plan = compare_and_generate(current, target)
    assert len(changes["tables_renamed"]) == 1
    assert len(changes["columns_modified"]) == 1
    mod = changes["columns_modified"][0]
    assert mod["table"] == "old_name"  # the column step runs before the rename
    assert "type" in " ".join(mod["changes"])
    assert any("VARCHAR(100)" in s.sql_forward for s in plan.steps)


def test_renamed_table_constraint_change_is_compared():
    current = {"old_name": table({"id": col("INTEGER")}, primary_key=["id"])}
    target = {"new_name": table({"id": col("INTEGER")}, primary_key=[])}
    changes, _ = compare_and_generate(current, target)
    assert len(changes["tables_renamed"]) == 1
    assert len(changes["constraints_dropped"]) == 1


def test_zero_downtime_drop_is_high_risk_and_temp_column_is_type_only():
    """The DROP COLUMN step must be HIGH risk, and the temp column
    must be type-only and nullable: the old assertion (temp column
    carries the full target definition) was the bug — a NOT NULL
    column without a default fails on a populated table before the
    copy step ever runs. The target's constraints are applied by the
    APPLY_CONSTRAINTS step after the rename."""
    current = {"t": table({"v": col("VARCHAR(50)")})}
    target = {
        "t": table(
            {
                "v": col(
                    "VARCHAR(100)",
                    nullable=False,
                    unique=True,
                    default="'x'",
                    check_constraint="v <> ''",
                )
            }
        )
    }
    _, plan = compare_and_generate(current, target, zero_downtime=True)
    drop = step_sql(plan, "DROP_OLD_COLUMN")
    assert len(drop) == 1
    assert drop[0].risk_level == "HIGH", drop[0].risk_level
    add_temp = step_sql(plan, "ADD_TEMP_COLUMN")[0].sql_forward
    assert "VARCHAR(100)" in add_temp
    assert "NOT NULL" not in add_temp
    assert "UNIQUE" not in add_temp
    assert "DEFAULT" not in add_temp
    assert "CHECK" not in add_temp
    apply = step_sql(plan, "APPLY_CONSTRAINTS")[0].sql_forward
    assert "SET NOT NULL" in apply
    assert "SET DEFAULT 'x'" in apply
    assert "ADD CONSTRAINT uq_t_v UNIQUE (v)" in apply
    assert "ADD CONSTRAINT ck_t_v CHECK (v <> '')" in apply
    assert "zero_downtime_warning" in plan.summary
    assert "DRAFT" in plan.summary["zero_downtime_warning"]


def test_zero_downtime_phases_are_expand_then_contract():
    current = {"t": table({"v": col("VARCHAR(50)")})}
    target = {"t": table({"v": col("VARCHAR(100)")})}
    _, plan = compare_and_generate(current, target, zero_downtime=True)
    phases = [s.zero_downtime_phase for s in plan.steps]
    # A plain type change has nothing to apply after the rename, so
    # there is no APPLY_CONSTRAINTS step here (see the test above
    # for the constrained case).
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
    current = {
        "orders": table(
            {"id": col("INTEGER"), "user_id": col("INTEGER"), "created_at": col("TEXT")},
            indexes=[{"name": "idx_orders_search", "columns": ["user_id"]}],
        )
    }
    target = {
        "orders": table(
            {"id": col("INTEGER"), "user_id": col("INTEGER"), "created_at": col("TEXT")},
            indexes=[{"name": "idx_orders_search", "columns": ["created_at"]}],
        )
    }
    changes, plan = compare_and_generate(current, target)
    assert len(changes["indexes_dropped"]) == 1
    assert len(changes["indexes_added"]) == 1
    assert any(
        "DROP INDEX idx_orders_search" in s.sql_forward for s in step_sql(plan, "DROP_INDEX")
    )
    assert any("created_at" in s.sql_forward for s in step_sql(plan, "ADD_INDEX"))


def test_rename_with_column_drop_uses_new_name():
    """A renamed table that also loses a column: the DROP COLUMN runs
    AFTER the rename, so it must name the NEW table — the old code
    recorded it under the old name and produced SQL against a table
    that no longer existed."""
    current = {
        "orders": table(
            {
                "id": col("INTEGER"),
                "user_id": col("INTEGER"),
                "amount": col("NUMERIC"),
                "note": col("TEXT"),
            },
            primary_key=["id"],
        )
    }
    target = {
        "purchases": table(
            {"id": col("INTEGER"), "user_id": col("INTEGER"), "amount": col("NUMERIC")},
            primary_key=["id"],
        )
    }
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
    target = {
        "books": table(
            {"id": col("INTEGER"), "author_id": col("INTEGER", foreign_key="authors.id")},
            primary_key=["id"],
        ),
        "authors": table({"id": col("INTEGER")}, primary_key=["id"]),
    }
    _, plan = compare_and_generate({}, target)
    creates = [s for s in step_sql(plan, "CREATE_TABLE") if s.table == "books"]
    assert len(creates) == 1
    assert "REFERENCES authors(id)" in creates[0].sql_forward
    assert "REFERENCES authors.id" not in creates[0].sql_forward


def test_create_table_emits_table_level_constraints():
    """Table-level unique and check constraints must appear in the
    CREATE TABLE — they used to be silently dropped."""
    target = {
        "t": table(
            {"a": col("TEXT"), "b": col("TEXT"), "v": col("NUMERIC")},
            unique_constraints=[["a", "b"]],
            check_constraints={"ck_t_v": "v > 0"},
        )
    }
    _, plan = compare_and_generate({}, target)
    sql = step_sql(plan, "CREATE_TABLE")[0].sql_forward
    assert "CONSTRAINT uq_t_a_b UNIQUE (a, b)" in sql
    assert "CONSTRAINT ck_t_v CHECK (v > 0)" in sql


def test_add_column_keeps_constraints():
    """A new column's UNIQUE, foreign key and CHECK must survive into
    the migration — as named ADD CONSTRAINT steps, not inline
    constraints (an inline UNIQUE is unnamed and cannot be dropped
    by name later). They used to be dropped entirely."""
    current = {"users": table({"id": col("INTEGER")}, primary_key=["id"])}
    target = {
        "users": table(
            {
                "id": col("INTEGER"),
                "email": col("TEXT", unique=True),
                "status": col("TEXT", check_constraint="status IN ('a', 'b')"),
                "group_id": col("INTEGER", foreign_key="groups.id"),
            },
            primary_key=["id"],
        ),
        "groups": table({"id": col("INTEGER")}, primary_key=["id"]),
    }
    _, plan = compare_and_generate(current, target)
    constraints = [s.sql_forward for s in step_sql(plan, "ADD_CONSTRAINT")]
    assert any("ADD CONSTRAINT uq_users_email UNIQUE (email)" in s for s in constraints)
    assert any(
        "ADD CONSTRAINT ck_users_status CHECK (status IN ('a', 'b'))" in s for s in constraints
    )
    assert any(
        "ADD CONSTRAINT fk_users_group_id FOREIGN KEY (group_id) REFERENCES groups(id)" in s
        for s in constraints
    )
    # And the ADD COLUMN steps themselves carry no inline constraints.
    for s in step_sql(plan, "ADD_COLUMN"):
        assert "UNIQUE" not in s.sql_forward
        assert "CHECK" not in s.sql_forward
        assert "REFERENCES" not in s.sql_forward


def test_new_table_indexes_are_created():
    """An index declared on a NEW table must be created: the CREATE
    TABLE step does not emit indexes, and _compare_indexes only
    looked at tables present in both schemas — so the index was
    silently lost. Found by the SQLite integration tests."""
    target = {
        "t": table(
            {"id": col("INTEGER"), "email": col("TEXT")},
            primary_key=["id"],
            indexes=[{"name": "idx_t_email", "columns": ["email"]}],
        )
    }
    _, plan = compare_and_generate({}, target)
    adds = step_sql(plan, "ADD_INDEX")
    assert len(adds) == 1
    assert "CREATE INDEX idx_t_email ON t (email)" in adds[0].sql_forward
    # And it runs after the CREATE TABLE.
    order = [s.step_type for s in plan.steps]
    assert order.index("CREATE_TABLE") < order.index("ADD_INDEX")


# --- Third review round: regression tests (2026-11-06). ---


def test_zero_default_is_kept_in_create_and_add():
    """A default of 0 is a real default, not 'no default': `if
    column.default_value:` dropped it. 0 must survive into the SQL."""
    target = {"t": table({"n": col("INTEGER", default=0)})}
    _, plan = compare_and_generate({}, target)
    assert "DEFAULT 0" in step_sql(plan, "CREATE_TABLE")[0].sql_forward
    current = {"t": table({"id": col("INTEGER")}, primary_key=["id"])}
    target = {
        "t": table({"id": col("INTEGER"), "n": col("INTEGER", default=0)}, primary_key=["id"])
    }
    _, plan = compare_and_generate(current, target)
    assert "DEFAULT 0" in step_sql(plan, "ADD_COLUMN")[0].sql_forward


def test_default_change_to_zero():
    current = {"t": table({"n": col("INTEGER", default=1)})}
    target = {"t": table({"n": col("INTEGER", default=0)})}
    _, plan = compare_and_generate(current, target)
    sql = step_sql(plan, "MODIFY_COLUMN")[0].sql_forward
    assert "SET DEFAULT 0" in sql


def test_not_null_with_zero_default_is_low_risk():
    """A NOT NULL column with a default of 0 is safe to add (existing
    rows get 0); the risk must not be HIGH just because 0 is falsy."""
    current = {"t": table({"id": col("INTEGER")}, primary_key=["id"])}
    target = {
        "t": table(
            {"id": col("INTEGER"), "n": col("INTEGER", nullable=False, default=0)},
            primary_key=["id"],
        )
    }
    _, plan = compare_and_generate(current, target)
    assert step_sql(plan, "ADD_COLUMN")[0].risk_level == "LOW"


def test_partial_index_keeps_predicate():
    """An index that keeps its name but changes only its WHERE must
    be rebuilt WITH the predicate — the old ADD INDEX emitted a plain
    index and the migration did not reach the target."""
    current = {
        "t": table(
            {"id": col("INTEGER"), "active": col("BOOLEAN")},
            indexes=[{"name": "idx_t_active", "columns": ["id"], "where": "active"}],
        )
    }
    target = {
        "t": table(
            {"id": col("INTEGER"), "active": col("BOOLEAN")},
            indexes=[{"name": "idx_t_active", "columns": ["id"], "where": "NOT active"}],
        )
    }
    _, plan = compare_and_generate(current, target)
    add = step_sql(plan, "ADD_INDEX")[0].sql_forward
    assert "WHERE NOT active" in add
    # The DROP rollback recreates the OLD index, predicate included.
    rollback = step_sql(plan, "DROP_INDEX")[0].sql_rollback
    assert "WHERE active" in rollback


def test_expression_index_keeps_expression():
    target = {
        "t": table(
            {"id": col("INTEGER"), "email": col("TEXT")},
            indexes=[{"name": "idx_t_email_lower", "columns": [], "expression": "lower(email)"}],
        )
    }
    _, plan = compare_and_generate({}, target)
    add = step_sql(plan, "ADD_INDEX")[0].sql_forward
    assert "lower(email)" in add


def test_method_index_keeps_using():
    target = {
        "t": table(
            {"id": col("INTEGER"), "tags": col("TEXT")},
            indexes=[{"name": "idx_t_tags", "columns": ["tags"], "method": "gin"}],
        )
    }
    _, plan = compare_and_generate({}, target)
    add = step_sql(plan, "ADD_INDEX")[0].sql_forward
    assert "USING gin" in add


def test_create_table_names_all_constraints():
    """A table created by this generator must be modifiable later:
    every constraint gets the name the modify/drop steps assume.
    An unnamed PRIMARY KEY, FOREIGN KEY, inline UNIQUE or inline
    CHECK cannot be dropped by name afterwards."""
    target = {
        "t": table(
            {
                "id": col("INTEGER"),
                "author_id": col("INTEGER", foreign_key="authors.id"),
                "email": col("TEXT", unique=True),
                "price": col("NUMERIC", check_constraint="price > 0"),
            },
            primary_key=["id"],
        ),
        "authors": table({"id": col("INTEGER")}, primary_key=["id"]),
    }
    _, plan = compare_and_generate({}, target)
    sql = [s for s in step_sql(plan, "CREATE_TABLE") if s.table == "t"][0].sql_forward
    assert "CONSTRAINT pk_t PRIMARY KEY (id)" in sql
    assert "CONSTRAINT fk_t_author_id FOREIGN KEY (author_id) REFERENCES authors(id)" in sql
    assert "CONSTRAINT uq_t_email UNIQUE (email)" in sql
    assert "CONSTRAINT ck_t_price CHECK (price > 0)" in sql
    assert "\n    PRIMARY KEY (" not in sql
    assert "\n    FOREIGN KEY (" not in sql
    assert "email TEXT UNIQUE" not in sql
    assert "price NUMERIC CHECK" not in sql


def test_add_column_emits_named_constraints():
    """An added column's UNIQUE, FK and CHECK must be named
    constraints, not inline ones — otherwise a later DROP CONSTRAINT
    by the conventional name fails."""
    current = {"users": table({"id": col("INTEGER")}, primary_key=["id"])}
    target = {
        "users": table(
            {
                "id": col("INTEGER"),
                "email": col("TEXT", unique=True),
                "status": col("TEXT", check_constraint="status IN ('a', 'b')"),
                "group_id": col("INTEGER", foreign_key="groups.id"),
            },
            primary_key=["id"],
        ),
        "groups": table({"id": col("INTEGER")}, primary_key=["id"]),
    }
    _, plan = compare_and_generate(current, target)
    adds = {s.description: s.sql_forward for s in step_sql(plan, "ADD_COLUMN")}
    email_sql = [v for k, v in adds.items() if "email" in k][0]
    assert "UNIQUE" not in email_sql  # not inline any more
    constraints = [s.sql_forward for s in step_sql(plan, "ADD_CONSTRAINT")]
    assert any("ADD CONSTRAINT uq_users_email UNIQUE (email)" in s for s in constraints)
    assert any(
        "ADD CONSTRAINT fk_users_group_id FOREIGN KEY (group_id) REFERENCES groups(id)" in s
        for s in constraints
    )
    assert any(
        "ADD CONSTRAINT ck_users_status CHECK (status IN ('a', 'b'))" in s for s in constraints
    )


def test_create_then_modify_constraint_round_trips():
    """The round trip: create a table with a unique column, then
    remove the unique. The DROP CONSTRAINT the second migration
    emits must name a constraint the first migration actually
    created."""
    target_v1 = {
        "t": table({"id": col("INTEGER"), "email": col("TEXT", unique=True)}, primary_key=["id"])
    }
    _, plan_v1 = compare_and_generate({}, target_v1)
    created = step_sql(plan_v1, "CREATE_TABLE")[0].sql_forward
    _, plan_v2 = compare_and_generate(
        target_v1, {"t": table({"id": col("INTEGER"), "email": col("TEXT")}, primary_key=["id"])}
    )
    drop = step_sql(plan_v2, "MODIFY_COLUMN")[0].sql_forward
    assert "DROP CONSTRAINT uq_t_email" in drop
    assert "CONSTRAINT uq_t_email UNIQUE (email)" in created


def test_zero_downtime_temp_column_is_nullable_and_type_only():
    """The temp column must be nullable and carry only the data type:
    a NOT NULL column without a default fails on a populated table
    before the copy step ever runs. Constraints are applied after
    the rename, not on the temp column."""
    current = {"t": table({"v": col("VARCHAR(50)")})}
    target = {
        "t": table(
            {
                "v": col(
                    "VARCHAR(100)",
                    nullable=False,
                    unique=True,
                    default="'x'",
                    check_constraint="v <> ''",
                )
            }
        )
    }
    _, plan = compare_and_generate(current, target, zero_downtime=True)
    add_temp = step_sql(plan, "ADD_TEMP_COLUMN")[0].sql_forward
    assert "VARCHAR(100)" in add_temp
    assert "NOT NULL" not in add_temp
    assert "UNIQUE" not in add_temp
    assert "DEFAULT" not in add_temp
    assert "CHECK" not in add_temp


def test_zero_downtime_applies_constraints_after_rename():
    """After the rename, one step applies the target's constraints
    with the final column name — NOT NULL, DEFAULT, UNIQUE, FK,
    CHECK — and only then. It must come after RENAME_COLUMN, and it
    must say it runs only after the backfill check returns 0."""
    current = {"t": table({"v": col("VARCHAR(50)")})}
    target = {
        "t": table(
            {
                "v": col(
                    "VARCHAR(100)",
                    nullable=False,
                    unique=True,
                    default="'x'",
                    check_constraint="v <> ''",
                )
            }
        )
    }
    _, plan = compare_and_generate(current, target, zero_downtime=True)
    apply = step_sql(plan, "APPLY_CONSTRAINTS")
    assert len(apply) == 1
    sql = apply[0].sql_forward
    assert "SET NOT NULL" in sql
    assert "SET DEFAULT 'x'" in sql
    assert "ADD CONSTRAINT uq_t_v UNIQUE (v)" in sql
    assert "ADD CONSTRAINT ck_t_v CHECK (v <> '')" in sql
    order = [s.step_type for s in plan.steps]
    assert order.index("RENAME_COLUMN") < order.index("APPLY_CONSTRAINTS")
    assert "backfill" in apply[0].description.lower()
    # The copy step carries the backfill check.
    copy = step_sql(plan, "COPY_COLUMN_DATA")[0]
    assert copy.validation_sql is not None
    assert "v_new IS NULL" in copy.validation_sql


def test_schema_hashes_are_real():
    """The plan's hashes must be the hashes of the two schemas, not
    of the changes dict — and the target hash must not be empty."""
    import hashlib
    import json

    current = {"t": table({"id": col("INTEGER")}, primary_key=["id"])}
    target = {"t": table({"id": col("INTEGER"), "n": col("INTEGER")}, primary_key=["id"])}
    comp = SchemaComparator()
    comp.load_schemas(schema(current), schema(target))
    changes = comp.compare_schemas()
    gen = MigrationGenerator()
    plan = gen.generate_migration(
        changes, current_schema=schema(current), target_schema=schema(target)
    )

    def _hash(data):
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    assert plan.source_schema_hash == _hash(schema(current))
    assert plan.target_schema_hash == _hash(schema(target))
    assert plan.source_schema_hash != plan.target_schema_hash


def test_drop_table_rollback_recreates_the_table():
    """The DROP TABLE rollback was literally a comment. The generator
    has the table definition, so the rollback must be a real CREATE
    TABLE (structure only — the data is gone)."""
    current = {"t": table({"id": col("INTEGER"), "v": col("TEXT")}, primary_key=["id"])}
    _, plan = compare_and_generate(current, {})
    drop = step_sql(plan, "DROP_TABLE")[0]
    assert "implementation needed" not in drop.sql_rollback
    assert "CREATE TABLE t" in drop.sql_rollback
    assert drop.reversibility == "schema-only"


def test_drop_column_rollback_is_schema_only():
    """A dropped column's rollback re-adds an empty column: the data
    is not restored. The step must say so, and the plan must require
    a backup."""
    current = {"t": table({"id": col("INTEGER"), "note": col("TEXT")}, primary_key=["id"])}
    target = {"t": table({"id": col("INTEGER")}, primary_key=["id"])}
    _, plan = compare_and_generate(current, target)
    drop = step_sql(plan, "DROP_COLUMN")[0]
    assert drop.reversibility == "schema-only"
    assert "not restored" in drop.description.lower() or "backup" in drop.description.lower()
    assert plan.summary["backup_required"] is True
    assert drop.step_id in plan.summary["data_loss_steps"]


def test_summary_marks_data_loss_steps():
    current = {"t": table({"id": col("INTEGER"), "note": col("TEXT")}, primary_key=["id"])}
    target = {"t": table({"id": col("INTEGER")}, primary_key=["id"])}
    _, plan = compare_and_generate(current, target)
    assert plan.summary["backup_required"] is True
    assert len(plan.summary["data_loss_steps"]) == 1
    _, plan2 = compare_and_generate(
        {"t": table({"id": col("INTEGER")}, primary_key=["id"])},
        {"t": table({"id": col("INTEGER"), "n": col("INTEGER")}, primary_key=["id"])},
    )
    assert plan2.summary["backup_required"] is False
    assert plan2.summary["data_loss_steps"] == []


def test_drop_column_validation_exists():
    """--validate-only used to emit no validation query for a DROP
    COLUMN. There must be one: the column exists before the drop."""
    from migration_generator import ValidationGenerator

    current = {"t": table({"id": col("INTEGER"), "note": col("TEXT")}, primary_key=["id"])}
    target = {"t": table({"id": col("INTEGER")}, primary_key=["id"])}
    _, plan = compare_and_generate(current, target)
    checks = ValidationGenerator().generate_validations(plan)
    assert len(checks) == 1
    assert checks[0].check_type == "COLUMN_EXISTS_BEFORE_DROP"
    assert checks[0].expected_result == 1


# --- Round-4 regression tests: FK order, comparator reuse. ---


def chain_schemas():
    """authors <- books <- chapters, each referencing the previous.
    The target dict is deliberately in reverse order (chapters first)
    so the test proves the order comes from the FK graph, not from
    the input order or the hash seed."""
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


def test_compare_twice_does_not_duplicate():
    """compare_schemas() used to append to self.changes without
    resetting it, so a second compare on the same instance recorded
    every change twice."""
    current, target = chain_schemas()
    comp = SchemaComparator()
    comp.load_schemas(schema(current), schema(target))
    first = comp.compare_schemas()
    second = comp.compare_schemas()
    assert first == second
    assert len(second["tables_added"]) == 3


def test_compare_second_schema_pair_does_not_crash():
    """Loading a different schema pair on the same instance used to
    crash with KeyError in _compare_indexes: the stale tables_added
    from the first pair named tables the second pair does not have."""
    comp = SchemaComparator()
    current, target = chain_schemas()
    comp.load_schemas(schema(current), schema(target))
    comp.compare_schemas()
    other_current = {}
    other_target = {"users": table({"id": col("SERIAL")}, primary_key=["id"])}
    comp.load_schemas(schema(other_current), schema(other_target))
    changes = comp.compare_schemas()
    assert [t["table"] for t in changes["tables_added"]] == ["users"]
    assert changes["tables_dropped"] == []


def test_table_creation_order_is_topological():
    """The creation steps used to follow set-iteration order, so
    books could be created before authors and PostgreSQL would
    reject the FK. The order must follow the FK graph: authors,
    then books, then chapters — regardless of input order."""
    current, target = chain_schemas()
    _, plan = compare_and_generate(current, target)
    created = [s.table for s in step_sql(plan, "CREATE_TABLE")]
    assert created == ["authors", "books", "chapters"]


def test_table_creation_order_is_deterministic():
    """The same schema pair, built with the tables in the opposite
    dict order, must produce the same step order. Set iteration made
    the order depend on the hash seed."""
    current, target = chain_schemas()
    _, plan1 = compare_and_generate(current, target)
    reversed_target = dict(reversed(list(target.items())))
    _, plan2 = compare_and_generate(current, reversed_target)
    order1 = [(s.step_type, s.table) for s in plan1.steps]
    order2 = [(s.step_type, s.table) for s in plan2.steps]
    assert order1 == order2


def test_fk_cycle_is_deferred_not_rejected():
    """A foreign-key cycle has no valid inline order (A references B
    and B references A), so the cyclic FKs are deferred to post-create
    ADD CONSTRAINT steps — the tables are still created, and the FKs
    still exist. The old code emitted the cycle inline in set order,
    which PostgreSQL rejects."""
    current = {}
    target = {
        "a": table(
            {
                "id": col("SERIAL"),
                "b_id": col("INT", foreign_key="b.id"),
            },
            primary_key=["id"],
        ),
        "b": table(
            {
                "id": col("SERIAL"),
                "a_id": col("INT", foreign_key="a.id"),
            },
            primary_key=["id"],
        ),
    }
    _, plan = compare_and_generate(current, target)
    creates = step_sql(plan, "CREATE_TABLE")
    assert [s.table for s in creates] == ["a", "b"]
    for step in creates:
        assert "REFERENCES" not in step.sql_forward
    deferred = step_sql(plan, "ADD_CONSTRAINT")
    assert sorted(s.sql_forward for s in deferred) == [
        "ALTER TABLE a ADD CONSTRAINT fk_a_b_id FOREIGN KEY (b_id) REFERENCES b(id);",
        "ALTER TABLE b ADD CONSTRAINT fk_b_a_id FOREIGN KEY (a_id) REFERENCES a(id);",
    ]


def test_drop_order_is_reverse_topological():
    """Drops run in the reverse of creation order: the table that
    references another drops first, so no DROP ever breaks a FK that
    still exists. The old code dropped in set order."""
    current, target = chain_schemas()
    _, plan = compare_and_generate(target, current)
    dropped = [s.table for s in step_sql(plan, "DROP_TABLE")]
    assert dropped == ["chapters", "books", "authors"]


def test_create_table_step_lists_fk_dependencies():
    """MigrationStep.dependencies was never populated. A creation
    step now names the tables it depends on (the tables its FKs
    reference that are created in the same migration)."""
    current, target = chain_schemas()
    _, plan = compare_and_generate(current, target)
    by_table = {s.table: s for s in step_sql(plan, "CREATE_TABLE")}
    assert by_table["authors"].dependencies == []
    assert by_table["books"].dependencies == ["authors"]
    assert by_table["chapters"].dependencies == ["books"]
