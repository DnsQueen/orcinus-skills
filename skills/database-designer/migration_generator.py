#!/usr/bin/env python3
"""
Database Migration Generator — PostgreSQL dialect.

Generates safe migration scripts between schema versions:
- Compares current and target schemas
- Generates ALTER TABLE statements for schema changes
- Implements zero-downtime migration strategies (expand-contract pattern)
- Creates rollback scripts for all changes
- Generates validation queries to verify migrations
- Handles complex changes like table splits/merges

Input: Current schema JSON + Target schema JSON
Output: Migration SQL + Rollback SQL + Validation queries + Execution plan

Usage:
    python migration_generator.py --current current_schema.json --target target_schema.json --output migration.sql
    python migration_generator.py --current current.json --target target.json --format json
    python migration_generator.py --current current.json --target target.json --zero-downtime
    python migration_generator.py --current current.json --target target.json --validate-only
"""

import argparse
import json
import re
import sys
from typing import Dict, List, Set, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime
import hashlib


def _json_default(obj):
    """ORCINUS fix (upstream bug): the changes dict stores raw Column/Table
    dataclass instances, and json.dumps() cannot serialize them, so every
    migration with any change failed with "Object of type Column is not
    JSON serializable". Serialize dataclasses with asdict(); anything else
    still raises, as before."""
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


@dataclass
class Column:
    name: str
    data_type: str
    nullable: bool = True
    primary_key: bool = False
    unique: bool = False
    foreign_key: Optional[str] = None
    default_value: Optional[str] = None
    check_constraint: Optional[str] = None


@dataclass
class Table:
    name: str
    columns: Dict[str, Column]
    primary_key: List[str]
    foreign_keys: Dict[str, str]  # column -> referenced_table.column
    unique_constraints: List[List[str]]
    check_constraints: Dict[str, str]
    indexes: List[Dict[str, Any]]


@dataclass
class MigrationStep:
    step_id: str
    step_type: str
    table: str
    description: str
    sql_forward: str
    sql_rollback: str
    validation_sql: Optional[str] = None
    dependencies: Optional[List[str]] = None
    risk_level: str = "LOW"  # LOW, MEDIUM, HIGH
    estimated_time: Optional[str] = None
    zero_downtime_phase: Optional[str] = None  # EXPAND, CONTRACT, or None
    # What the rollback restores. "schema": the rollback restores the
    # schema exactly and no pre-existing data is lost by the step.
    # "schema-only": the rollback restores the structure but the data
    # the step removed is NOT restored — back up before running.
    # "irreversible": no rollback exists (no step in this generator
    # is irreversible today; the value is reserved so a future step
    # without a rollback cannot silently pass as reversible).
    reversibility: str = "schema"


@dataclass
class MigrationPlan:
    migration_id: str
    created_at: str
    source_schema_hash: str
    target_schema_hash: str
    steps: List[MigrationStep]
    summary: Dict[str, Any]
    execution_order: List[str]
    rollback_order: List[str]


@dataclass
class ValidationCheck:
    check_id: str
    check_type: str
    table: str
    description: str
    sql_query: str
    expected_result: Any
    critical: bool = True


class SchemaComparator:
    """Compares two schema versions and identifies differences."""

    def __init__(self):
        self.current_schema: Dict[str, Table] = {}
        self.target_schema: Dict[str, Table] = {}
        self.changes: Dict[str, List[Dict[str, Any]]] = {
            "tables_added": [],
            "tables_dropped": [],
            "tables_renamed": [],
            "columns_added": [],
            "columns_dropped": [],
            "columns_modified": [],
            "columns_renamed": [],
            "constraints_added": [],
            "constraints_dropped": [],
            "indexes_added": [],
            "indexes_dropped": [],
        }

    def load_schemas(self, current_data: Dict[str, Any], target_data: Dict[str, Any]):
        """Load current and target schemas."""
        self.current_schema = self._parse_schema(current_data)
        self.target_schema = self._parse_schema(target_data)

    def _parse_schema(self, schema_data: Dict[str, Any]) -> Dict[str, Table]:
        """Parse schema JSON into Table objects."""
        tables: Dict[str, Table] = {}

        if "tables" not in schema_data:
            return tables

        for table_name, table_def in schema_data["tables"].items():
            columns = {}
            primary_key = table_def.get("primary_key", [])
            foreign_keys = {}

            # Parse columns
            for col_name, col_def in table_def.get("columns", {}).items():
                column = Column(
                    name=col_name,
                    data_type=col_def.get("type", "VARCHAR(255)"),
                    nullable=col_def.get("nullable", True),
                    primary_key=col_name in primary_key,
                    unique=col_def.get("unique", False),
                    foreign_key=col_def.get("foreign_key"),
                    default_value=col_def.get("default"),
                    check_constraint=col_def.get("check_constraint"),
                )
                columns[col_name] = column

                if column.foreign_key:
                    foreign_keys[col_name] = column.foreign_key

            table = Table(
                name=table_name,
                columns=columns,
                primary_key=primary_key,
                foreign_keys=foreign_keys,
                unique_constraints=table_def.get("unique_constraints", []),
                check_constraints=table_def.get("check_constraints", {}),
                indexes=table_def.get("indexes", []),
            )
            tables[table_name] = table

        return tables

    def compare_schemas(self) -> Dict[str, List[Dict[str, Any]]]:
        """Compare schemas and identify all changes. The changes are
        rebuilt from scratch on every call: the comparator is
        reusable, and a second compare must not duplicate the first
        one's changes or read its stale tables_added."""
        self.changes = {
            "tables_added": [],
            "tables_dropped": [],
            "tables_renamed": [],
            "columns_added": [],
            "columns_dropped": [],
            "columns_modified": [],
            "columns_renamed": [],
            "constraints_added": [],
            "constraints_dropped": [],
            "indexes_added": [],
            "indexes_dropped": [],
        }
        self._compare_tables()
        self._compare_renamed_table_columns()
        self._compare_columns()
        self._compare_constraints()
        self._compare_indexes()
        return self.changes

    def _compare_renamed_table_columns(self):
        """A renamed table's column changes are not compared by
        _compare_columns (it only looks at tables with the same name in
        both schemas). Compare them here.

        Which name a change is recorded under depends on WHEN its step
        runs relative to the rename (see generate_migration): column
        addition, column modification, constraint removal/addition and
        index removal/addition run BEFORE the rename, so they use the
        OLD name; column removal runs AFTER the rename, so it uses the
        NEW name. Recording a dropped column under the old name used
        to produce a DROP COLUMN against a table that no longer
        existed."""
        for rename in self.changes["tables_renamed"]:
            old_name = rename["old_name"]
            new_name = rename["new_name"]
            current_table = self.current_schema[old_name]
            target_table = self.target_schema[new_name]
            current_columns = set(current_table.columns.keys())
            target_columns = set(target_table.columns.keys())
            for col_name in target_columns - current_columns:
                self.changes["columns_added"].append(
                    {
                        "table": old_name,
                        "column": col_name,
                        "definition": target_table.columns[col_name],
                    }
                )
            for col_name in current_columns - target_columns:
                # The drop runs after the rename: use the new name.
                self.changes["columns_dropped"].append(
                    {
                        "table": new_name,
                        "column": col_name,
                        "definition": current_table.columns[col_name],
                    }
                )
            for col_name in current_columns.intersection(target_columns):
                current_col = current_table.columns[col_name]
                target_col = target_table.columns[col_name]
                if self._columns_different(current_col, target_col):
                    self.changes["columns_modified"].append(
                        {
                            "table": old_name,
                            "column": col_name,
                            "current_definition": current_col,
                            "target_definition": target_col,
                            "changes": self._describe_column_changes(current_col, target_col),
                        }
                    )
            # Constraints and indexes have the same gap: they are only
            # compared for tables with the same name. Compare them here
            # too, under the old name — both run before the rename.
            self._compare_table_constraints(current_table, target_table, old_name)
            self._compare_table_indexes(current_table, target_table, old_name)

    def _compare_tables(self):
        """Compare table-level changes."""
        current_tables = set(self.current_schema.keys())
        target_tables = set(self.target_schema.keys())

        # Tables added (sorted: set iteration order depends on
        # the hash seed, and the migration must not).
        for table_name in sorted(target_tables - current_tables):
            self.changes["tables_added"].append(
                {"table": table_name, "definition": self.target_schema[table_name]}
            )

        # Tables dropped
        for table_name in sorted(current_tables - target_tables):
            self.changes["tables_dropped"].append(
                {"table": table_name, "definition": self.current_schema[table_name]}
            )

        # Tables renamed (heuristic based on column similarity)
        self._detect_renamed_tables(current_tables - target_tables, target_tables - current_tables)

    def _detect_renamed_tables(self, dropped_tables: Set[str], added_tables: Set[str]):
        """Detect renamed tables based on column similarity."""
        if not dropped_tables or not added_tables:
            return

        # Calculate similarity scores (sorted inputs, so the
        # order does not depend on set iteration).
        similarity_scores = []
        for dropped_table in sorted(dropped_tables):
            for added_table in sorted(added_tables):
                score = self._calculate_table_similarity(dropped_table, added_table)
                if score > 0.7:  # High similarity threshold
                    similarity_scores.append((score, dropped_table, added_table))

        # Sort by similarity, then by name, so equal scores resolve
        # the same way on every run.
        similarity_scores.sort(key=lambda s: (-s[0], s[1], s[2]))
        used_tables = set()

        for score, old_name, new_name in similarity_scores:
            if old_name not in used_tables and new_name not in used_tables:
                self.changes["tables_renamed"].append(
                    {"old_name": old_name, "new_name": new_name, "similarity_score": score}
                )
                used_tables.add(old_name)
                used_tables.add(new_name)

                # Remove from added/dropped lists
                self.changes["tables_added"] = [
                    t for t in self.changes["tables_added"] if t["table"] != new_name
                ]
                self.changes["tables_dropped"] = [
                    t for t in self.changes["tables_dropped"] if t["table"] != old_name
                ]

    def _calculate_table_similarity(self, table1_name: str, table2_name: str) -> float:
        """Calculate similarity between two tables based on columns."""
        table1 = self.current_schema[table1_name]
        table2 = self.target_schema[table2_name]

        cols1 = set(table1.columns.keys())
        cols2 = set(table2.columns.keys())

        if not cols1 and not cols2:
            return 1.0
        elif not cols1 or not cols2:
            return 0.0

        intersection = len(cols1.intersection(cols2))
        union = len(cols1.union(cols2))

        return intersection / union

    def _compare_columns(self):
        """Compare column-level changes."""
        common_tables = set(self.current_schema.keys()).intersection(set(self.target_schema.keys()))

        for table_name in sorted(common_tables):
            current_table = self.current_schema[table_name]
            target_table = self.target_schema[table_name]

            current_columns = set(current_table.columns.keys())
            target_columns = set(target_table.columns.keys())

            # Columns added
            for col_name in sorted(target_columns - current_columns):
                self.changes["columns_added"].append(
                    {
                        "table": table_name,
                        "column": col_name,
                        "definition": target_table.columns[col_name],
                    }
                )

            # Columns dropped
            for col_name in sorted(current_columns - target_columns):
                self.changes["columns_dropped"].append(
                    {
                        "table": table_name,
                        "column": col_name,
                        "definition": current_table.columns[col_name],
                    }
                )

            # Columns modified
            for col_name in sorted(current_columns.intersection(target_columns)):
                current_col = current_table.columns[col_name]
                target_col = target_table.columns[col_name]

                if self._columns_different(current_col, target_col):
                    self.changes["columns_modified"].append(
                        {
                            "table": table_name,
                            "column": col_name,
                            "current_definition": current_col,
                            "target_definition": target_col,
                            "changes": self._describe_column_changes(current_col, target_col),
                        }
                    )

    def _columns_different(self, col1: Column, col2: Column) -> bool:
        """Check if two columns have different definitions."""
        return (
            col1.data_type != col2.data_type
            or col1.nullable != col2.nullable
            or col1.default_value != col2.default_value
            or col1.unique != col2.unique
            or col1.foreign_key != col2.foreign_key
            or col1.check_constraint != col2.check_constraint
        )

    def _describe_column_changes(self, current_col: Column, target_col: Column) -> List[str]:
        """Describe specific changes between column definitions."""
        changes = []

        if current_col.data_type != target_col.data_type:
            changes.append(f"type: {current_col.data_type} -> {target_col.data_type}")

        if current_col.nullable != target_col.nullable:
            changes.append(f"nullable: {current_col.nullable} -> {target_col.nullable}")

        if current_col.default_value != target_col.default_value:
            changes.append(f"default: {current_col.default_value} -> {target_col.default_value}")

        if current_col.unique != target_col.unique:
            changes.append(f"unique: {current_col.unique} -> {target_col.unique}")

        if current_col.foreign_key != target_col.foreign_key:
            changes.append(f"foreign_key: {current_col.foreign_key} -> {target_col.foreign_key}")

        if current_col.check_constraint != target_col.check_constraint:
            changes.append(
                f"check: {current_col.check_constraint} -> {target_col.check_constraint}"
            )

        return changes

    def _compare_constraints(self):
        """Compare constraint changes."""
        common_tables = set(self.current_schema.keys()).intersection(set(self.target_schema.keys()))

        for table_name in sorted(common_tables):
            self._compare_table_constraints(
                self.current_schema[table_name], self.target_schema[table_name], table_name
            )

    def _compare_table_constraints(self, current_table, target_table, table_name):
        """Compare the constraints of one table pair. Called for common
        tables and for renamed tables (under the old name)."""
        # Compare primary keys
        if current_table.primary_key != target_table.primary_key:
            if current_table.primary_key:
                self.changes["constraints_dropped"].append(
                    {
                        "table": table_name,
                        "constraint_type": "PRIMARY_KEY",
                        "columns": current_table.primary_key,
                    }
                )

            if target_table.primary_key:
                self.changes["constraints_added"].append(
                    {
                        "table": table_name,
                        "constraint_type": "PRIMARY_KEY",
                        "columns": target_table.primary_key,
                    }
                )

        # Compare unique constraints
        current_unique = set(tuple(uc) for uc in current_table.unique_constraints)
        target_unique = set(tuple(uc) for uc in target_table.unique_constraints)

        for constraint in sorted(target_unique - current_unique):
            self.changes["constraints_added"].append(
                {"table": table_name, "constraint_type": "UNIQUE", "columns": list(constraint)}
            )

        for constraint in sorted(current_unique - target_unique):
            self.changes["constraints_dropped"].append(
                {"table": table_name, "constraint_type": "UNIQUE", "columns": list(constraint)}
            )

        # Compare check constraints
        current_checks = set(current_table.check_constraints.items())
        target_checks = set(target_table.check_constraints.items())

        for name, condition in sorted(target_checks - current_checks):
            self.changes["constraints_added"].append(
                {
                    "table": table_name,
                    "constraint_type": "CHECK",
                    "constraint_name": name,
                    "condition": condition,
                }
            )

        for name, condition in sorted(current_checks - target_checks):
            self.changes["constraints_dropped"].append(
                {
                    "table": table_name,
                    "constraint_type": "CHECK",
                    "constraint_name": name,
                    "condition": condition,
                }
            )

    def _compare_indexes(self):
        """Compare index changes."""
        common_tables = set(self.current_schema.keys()).intersection(set(self.target_schema.keys()))

        for table_name in sorted(common_tables):
            self._compare_table_indexes(
                self.current_schema[table_name], self.target_schema[table_name], table_name
            )

        # A new table's indexes are part of its creation, but the
        # CREATE TABLE step does not emit them — so they must be added
        # here, or they are silently lost. (The ADD_INDEX steps run
        # after table creation in generate_migration, so the table
        # exists by then.) A dropped table's indexes go away with the
        # table and need no step.
        added_tables = {t["table"] for t in self.changes["tables_added"]}
        for table_name in sorted(added_tables):
            for idx in self.target_schema[table_name].indexes:
                self.changes["indexes_added"].append({"table": table_name, "index": idx})

    @staticmethod
    def _index_signature(idx):
        """The definition of an index, normalised for comparison:
        the columns in order, whether it is unique, and any predicate
        or method. Two indexes with the same name but a different
        signature are different indexes — comparing only the name set
        used to miss a change of columns entirely."""
        columns = tuple(idx.get("columns") or [])
        unique = bool(idx.get("unique", False))
        # A partial index (WHERE ...) or an expression/method index.
        predicate = idx.get("where") or idx.get("predicate") or ""
        method = idx.get("method") or idx.get("using") or ""
        expression = idx.get("expression") or ""
        return (columns, unique, str(predicate), str(method), str(expression))

    def _compare_table_indexes(self, current_table, target_table, table_name):
        """Compare the indexes of one table pair. Called for common
        tables and for renamed tables (under the old name — index
        removal and addition both run before the rename)."""
        current_indexes = {idx["name"]: idx for idx in current_table.indexes}
        target_indexes = {idx["name"]: idx for idx in target_table.indexes}

        current_names = set(current_indexes.keys())
        target_names = set(target_indexes.keys())

        # Indexes added
        for idx_name in sorted(target_names - current_names):
            self.changes["indexes_added"].append(
                {"table": table_name, "index": target_indexes[idx_name]}
            )

        # Indexes dropped
        for idx_name in sorted(current_names - target_names):
            self.changes["indexes_dropped"].append(
                {"table": table_name, "index": current_indexes[idx_name]}
            )

        # Indexes with the same name but a different definition: drop
        # the old one and add the new one. An index cannot be ALTERed.
        # The drop is generated before the add (generate_migration
        # runs index removal before index addition), so a same-name
        # replacement does not fail with "index already exists".
        for idx_name in sorted(current_names.intersection(target_names)):
            if self._index_signature(current_indexes[idx_name]) != self._index_signature(
                target_indexes[idx_name]
            ):
                self.changes["indexes_dropped"].append(
                    {"table": table_name, "index": current_indexes[idx_name]}
                )
                self.changes["indexes_added"].append(
                    {"table": table_name, "index": target_indexes[idx_name]}
                )


def _topological_table_order(by_name):
    """Kahn's algorithm over the FK graph. `by_name` maps table name
    to Table; edges point from a table to the tables its FKs
    reference, restricted to tables in the map. Returns (order,
    cyclic): order is the dependency-ordered names (referenced
    before referencing, alphabetical tie-break, so the order is
    deterministic and independent of the hash seed); cyclic is the
    set of names that could not be ordered because they are part
    of, or depend on, a foreign-key cycle. A cycle has no valid
    inline order — its FKs must be added after the tables exist."""
    remaining = {
        name: {r.split(".", 1)[0] for r in table.foreign_keys.values()} & set(by_name)
        for name, table in by_name.items()
    }
    emitted = []
    while True:
        ready = sorted(n for n, refs in remaining.items() if not refs)
        if not ready:
            break
        nxt = ready[0]
        emitted.append(nxt)
        del remaining[nxt]
        for refs in remaining.values():
            refs.discard(nxt)
    return emitted, set(remaining)


class MigrationGenerator:
    """Generates migration steps from schema differences."""

    def __init__(self, zero_downtime: bool = False):
        self.zero_downtime = zero_downtime
        self.migration_steps: List[MigrationStep] = []
        self.step_counter = 0

        # Data type conversion safety
        self.safe_type_conversions = {
            ("VARCHAR(50)", "VARCHAR(100)"): True,  # Expanding varchar
            ("INT", "BIGINT"): True,  # Expanding integer
            ("DECIMAL(10,2)", "DECIMAL(12,2)"): True,  # Expanding decimal precision
        }

        self.risky_type_conversions = {
            ("VARCHAR(100)", "VARCHAR(50)"): "Data truncation possible",
            ("BIGINT", "INT"): "Data loss possible for large values",
            ("TEXT", "VARCHAR(255)"): "Data truncation possible",
        }

    def generate_migration(
        self,
        changes: Dict[str, List[Dict[str, Any]]],
        current_schema: Optional[Dict[str, Any]] = None,
        target_schema: Optional[Dict[str, Any]] = None,
    ) -> MigrationPlan:
        """Generate complete migration plan from schema changes.

        The schemas are the two schema dicts the comparison ran on
        (the same dicts passed to load_schemas). The plan's hashes
        are the hashes of those schemas — so a PASS cannot be carried
        from one schema pair to another. Callers that pass no schemas
        get empty hashes and a summary note saying so; main() and the
        tests always pass them."""
        self.migration_steps = []
        self.step_counter = 0

        # Generate steps in dependency order. Table creation is in
        # FK dependency order (see _generate_table_creation_steps);
        # a cycle's FKs are deferred to ADD CONSTRAINT steps.
        # Constraint REMOVAL comes
        # before constraint ADDITION: a primary-key swap would fail if
        # the new key were added while the old one still exists. Index
        # REMOVAL comes before index ADDITION for the same reason: an
        # index that keeps its name but changes columns cannot be
        # created while the old one still exists.
        self._generate_table_creation_steps(changes["tables_added"])
        self._generate_column_addition_steps(changes["columns_added"])
        self._generate_constraint_removal_steps(changes["constraints_dropped"])
        self._generate_constraint_addition_steps(changes["constraints_added"])
        self._generate_index_removal_steps(changes["indexes_dropped"])
        self._generate_index_addition_steps(changes["indexes_added"])
        self._generate_column_modification_steps(changes["columns_modified"])
        self._generate_table_rename_steps(changes["tables_renamed"])
        self._generate_column_removal_steps(changes["columns_dropped"])
        self._generate_table_removal_steps(changes["tables_dropped"])

        # Create migration plan
        migration_id = self._generate_migration_id(changes)
        execution_order = [step.step_id for step in self.migration_steps]
        rollback_order = list(reversed(execution_order))

        return MigrationPlan(
            migration_id=migration_id,
            created_at=datetime.now().isoformat(),
            source_schema_hash=self._calculate_schema_hash(current_schema),
            target_schema_hash=self._calculate_schema_hash(target_schema),
            steps=self.migration_steps,
            summary=self._generate_summary(changes),
            execution_order=execution_order,
            rollback_order=rollback_order,
        )

    def _generate_step_id(self) -> str:
        """Generate unique step ID."""
        self.step_counter += 1
        return f"step_{self.step_counter:03d}"

    def _generate_table_creation_steps(self, tables_added: List[Dict[str, Any]]):
        """Generate steps for creating new tables, in FK dependency
        order: a table is created after every table its FKs
        reference, so PostgreSQL never sees a FK to a table that
        does not exist yet. A foreign-key cycle has no valid inline
        order, so the cyclic FKs are deferred to post-create ADD
        CONSTRAINT steps — the tables are still created, and the FKs
        still exist. Each creation step names the tables it depends
        on (its inline FK targets created in this migration)."""
        by_name = {info["definition"].name: info["definition"] for info in tables_added}
        order, cyclic = _topological_table_order(by_name)
        deferred: Dict[str, Set[str]] = {}
        for name in cyclic:
            for col_name, ref in by_name[name].foreign_keys.items():
                if ref.split(".", 1)[0] in cyclic:
                    deferred.setdefault(name, set()).add(col_name)
        for name in order + sorted(cyclic):
            table = by_name[name]
            dependencies = sorted(
                {r.split(".", 1)[0] for r in table.foreign_keys.values()} & set(by_name) - cyclic
            )
            step = self._create_table_step(
                table,
                deferred_fks=frozenset(deferred.get(name, ())),
                dependencies=dependencies,
            )
            self.migration_steps.append(step)
        # The deferred FKs, as ADD CONSTRAINT steps, in table then
        # column order. They run after every CREATE TABLE, when both
        # tables exist.
        for name in sorted(deferred):
            table = by_name[name]
            for col_name in sorted(deferred[name]):
                ref = table.foreign_keys[col_name]
                step = self._add_constraint_step(
                    {
                        "table": name,
                        "constraint_type": "FOREIGN_KEY",
                        "columns": [col_name],
                        "references": ref,
                    }
                )
                step.dependencies = sorted({name, ref.split(".", 1)[0]})
                self.migration_steps.append(step)

    def _create_table_sql(self, table: Table, exclude_fks: frozenset = frozenset()) -> str:
        """The CREATE TABLE statement for one table. Every constraint
        the schema declares is emitted WITH the name the modify/drop
        steps assume (pk_table, fk_table_column, uq_table_column,
        ck_table_column): a constraint created unnamed cannot be
        dropped by name later, so a table this generator creates must
        be modifiable by this generator afterwards. A column's UNIQUE
        and CHECK are emitted as named table-level constraints, not
        as inline column modifiers — an inline UNIQUE is unnamed."""
        columns_sql = []

        for col_name, column in table.columns.items():
            columns_sql.append(self._column_definition_sql(col_name, column))

        # Primary key, named.
        if table.primary_key:
            columns_sql.append(
                f"CONSTRAINT pk_{table.name} PRIMARY KEY ({', '.join(table.primary_key)})"
            )

        # Foreign keys (stored as "table.column", SQL wants
        # "table(column)"), named fk_table_column. exclude_fks holds
        # the columns whose FK is deferred to a post-create ADD
        # CONSTRAINT step (a foreign-key cycle has no valid inline
        # order); the rollback re-creates the table with all FKs,
        # because it runs when the referenced tables exist.
        for col_name, ref in table.foreign_keys.items():
            if col_name in exclude_fks:
                continue
            columns_sql.append(
                f"CONSTRAINT fk_{table.name}_{col_name} FOREIGN KEY "
                f"({col_name}) REFERENCES {self._references_sql(ref)}"
            )

        # Column-level unique and check constraints, named.
        for col_name, column in table.columns.items():
            if column.unique:
                columns_sql.append(f"CONSTRAINT uq_{table.name}_{col_name} UNIQUE ({col_name})")
            if column.check_constraint:
                columns_sql.append(
                    f"CONSTRAINT ck_{table.name}_{col_name} CHECK ({column.check_constraint})"
                )

        # Table-level unique constraints, with the same conventional
        # names the ADD/DROP constraint steps use (uq_table_col1_col2),
        # so a later drop can find them.
        for cols in table.unique_constraints:
            name = f"uq_{table.name}_{'_'.join(cols)}"
            columns_sql.append(f"CONSTRAINT {name} UNIQUE ({', '.join(cols)})")

        # Table-level check constraints, under their schema names.
        for name, condition in table.check_constraints.items():
            columns_sql.append(f"CONSTRAINT {name} CHECK ({condition})")

        return f"CREATE TABLE {table.name} (\n    " + ",\n    ".join(columns_sql) + "\n);"

    def _create_table_step(
        self,
        table: Table,
        deferred_fks: frozenset = frozenset(),
        dependencies: Optional[List[str]] = None,
    ) -> MigrationStep:
        """Create migration step for table creation. deferred_fks
        names the columns whose FK is added later by an ADD
        CONSTRAINT step (a foreign-key cycle); dependencies names
        the tables this CREATE depends on."""
        create_sql = self._create_table_sql(table, exclude_fks=deferred_fks)
        drop_sql = f"DROP TABLE IF EXISTS {table.name};"

        return MigrationStep(
            step_id=self._generate_step_id(),
            step_type="CREATE_TABLE",
            table=table.name,
            description=f"Create table {table.name} with {len(table.columns)} columns",
            sql_forward=create_sql,
            sql_rollback=drop_sql,
            validation_sql=f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name = '{table.name}';",
            dependencies=dependencies if dependencies is not None else [],
            risk_level="LOW",
        )

    def _generate_column_addition_steps(self, columns_added: List[Dict[str, Any]]):
        """Generate steps for adding columns. A new column's UNIQUE,
        foreign key and CHECK are emitted as separate ADD_CONSTRAINT
        steps with the conventional names — not as inline column
        modifiers, which would be unnamed and undroppable later."""
        for col_info in columns_added:
            if self.zero_downtime:
                # For zero-downtime, add columns as nullable first.
                step = self._add_column_zero_downtime_step(col_info)
                self.migration_steps.append(step)
                follow_up = self._add_column_zero_downtime_follow_up(col_info)
                if follow_up is not None:
                    self.migration_steps.append(follow_up)
            else:
                step = self._add_column_step(col_info)
                self.migration_steps.append(step)
                self.migration_steps.extend(self._column_constraint_steps(col_info))

    def _add_column_step(self, col_info: Dict[str, Any]) -> MigrationStep:
        """Create step for adding a column. The column itself is type,
        NOT NULL and DEFAULT; its UNIQUE, foreign key and CHECK are
        separate ADD_CONSTRAINT steps (see _generate_column_addition_
        steps), so they get the names a later drop assumes."""
        table = col_info["table"]
        column = col_info["definition"]

        col_sql = self._column_definition_sql(column.name, column)

        add_sql = f"ALTER TABLE {table} ADD COLUMN {col_sql};"
        drop_sql = f"ALTER TABLE {table} DROP COLUMN {column.name};"

        risk_level = "HIGH" if not column.nullable and column.default_value is None else "LOW"

        return MigrationStep(
            step_id=self._generate_step_id(),
            step_type="ADD_COLUMN",
            table=table,
            description=f"Add column {column.name} to {table}",
            sql_forward=add_sql,
            sql_rollback=drop_sql,
            validation_sql=f"SELECT COUNT(*) FROM information_schema.columns WHERE table_name = '{table}' AND column_name = '{column.name}';",
            risk_level=risk_level,
        )

    def _add_column_zero_downtime_step(self, col_info: Dict[str, Any]) -> MigrationStep:
        """Create zero-downtime step for adding a column: phase 1
        adds it nullable (a NOT NULL column without a default fails
        on a populated table). The NOT NULL and constraints are
        applied by the follow-up step, after the application has
        populated the column."""
        table = col_info["table"]
        column = col_info["definition"]

        # Phase 1: add as nullable with default if needed.
        col_sql = f"{column.name} {column.data_type}"
        if column.default_value is not None:
            col_sql += f" DEFAULT {column.default_value}"

        add_sql = f"ALTER TABLE {table} ADD COLUMN {col_sql};"
        drop_sql = f"ALTER TABLE {table} DROP COLUMN {column.name};"

        return MigrationStep(
            step_id=self._generate_step_id(),
            step_type="ADD_COLUMN_ZD",
            table=table,
            description=f"Add column {column.name} to {table} (zero-downtime phase 1)",
            sql_forward=add_sql,
            sql_rollback=drop_sql,
            validation_sql=f"SELECT COUNT(*) FROM information_schema.columns WHERE table_name = '{table}' AND column_name = '{column.name}';",
            risk_level="LOW",
            zero_downtime_phase="EXPAND",
        )

    def _add_column_zero_downtime_follow_up(
        self, col_info: Dict[str, Any]
    ) -> Optional[MigrationStep]:
        """Phase 2 of a zero-downtime column addition: apply the
        target's NOT NULL, default and named constraints. Runs only
        after the application has populated the column — it fails on
        rows that are still NULL, which is the point: an incomplete
        backfill must fail loudly here, not silently pass. Returns
        None when the target needs nothing applied (nullable, no
        default, no constraints)."""
        table = col_info["table"]
        column = col_info["definition"]
        actions = []
        rollback_actions = []
        if not column.nullable:
            actions.append(f"ALTER COLUMN {column.name} SET NOT NULL")
            rollback_actions.append(f"ALTER COLUMN {column.name} DROP NOT NULL")
        if column.default_value is not None:
            actions.append(f"ALTER COLUMN {column.name} SET DEFAULT {column.default_value}")
            rollback_actions.append(f"ALTER COLUMN {column.name} DROP DEFAULT")
        actions.extend(self._column_constraint_actions(table, column.name, column))
        for action in self._column_constraint_actions(table, column.name, column):
            name = action.split(" ", 3)[2]
            rollback_actions.append(f"DROP CONSTRAINT {name}")
        if not actions:
            return None
        forward = f"ALTER TABLE {table}\n    " + ",\n    ".join(actions) + ";"
        rollback = f"ALTER TABLE {table}\n    " + ",\n    ".join(rollback_actions) + ";"
        return MigrationStep(
            step_id=self._generate_step_id(),
            step_type="APPLY_COLUMN_CONSTRAINTS",
            table=table,
            description=f"Apply NOT NULL, default and constraints to {column.name} in {table} (zero-downtime phase 2 — run only after the application has populated the column)",
            sql_forward=forward,
            sql_rollback=rollback,
            risk_level="MEDIUM",
            zero_downtime_phase="EXPAND",
        )

    @staticmethod
    def _references_sql(foreign_key: str) -> str:
        """A foreign key is stored as "table.column"; SQL wants
        "table(column)"."""
        if "." in foreign_key:
            ref_table, ref_col = foreign_key.rsplit(".", 1)
            return f"{ref_table}({ref_col})"
        return foreign_key

    def _column_definition_sql(self, name: str, column: Column) -> str:
        """The column definition: type, NOT NULL, DEFAULT. UNIQUE,
        CHECK and REFERENCES are NOT part of it — an inline UNIQUE,
        CHECK or REFERENCES creates an unnamed constraint, and a
        later DROP CONSTRAINT by the conventional name (uq_, ck_,
        fk_) would fail. Those live in _column_constraint_actions
        instead, as named ADD CONSTRAINT actions. A default of 0 is
        a real default: the test is `is not None`, not truthiness."""
        sql = f"{name} {column.data_type}"
        if not column.nullable:
            sql += " NOT NULL"
        if column.default_value is not None:
            sql += f" DEFAULT {column.default_value}"
        return sql

    def _column_constraint_actions(self, table: str, name: str, column: Column) -> List[str]:
        """The named ADD CONSTRAINT actions for one column's unique,
        foreign key and check — the names the modify/drop steps
        assume (uq_table_column, fk_table_column, ck_table_column)."""
        actions = []
        if column.unique:
            actions.append(f"ADD CONSTRAINT uq_{table}_{name} UNIQUE ({name})")
        if column.foreign_key:
            actions.append(
                f"ADD CONSTRAINT fk_{table}_{name} FOREIGN KEY ({name}) "
                f"REFERENCES {self._references_sql(column.foreign_key)}"
            )
        if column.check_constraint:
            actions.append(f"ADD CONSTRAINT ck_{table}_{name} CHECK ({column.check_constraint})")
        return actions

    def _column_constraint_steps(self, col_info: Dict[str, Any]) -> List[MigrationStep]:
        """One ADD_CONSTRAINT step per constraint a new column
        declares, using the same machinery (and names) as a
        table-level constraint addition."""
        table = col_info["table"]
        column = col_info["definition"]
        steps = []
        if column.unique:
            steps.append(
                self._add_constraint_step(
                    {"table": table, "constraint_type": "UNIQUE", "columns": [column.name]}
                )
            )
        if column.foreign_key:
            steps.append(
                self._add_constraint_step(
                    {
                        "table": table,
                        "constraint_type": "FOREIGN_KEY",
                        "columns": [column.name],
                        "references": column.foreign_key,
                    }
                )
            )
        if column.check_constraint:
            steps.append(
                self._add_constraint_step(
                    {
                        "table": table,
                        "constraint_type": "CHECK",
                        "constraint_name": f"ck_{table}_{column.name}",
                        "condition": column.check_constraint,
                    }
                )
            )
        return [s for s in steps if s is not None]

    def _recreate_column_sql(self, table: str, column: Column) -> str:
        """SQL that re-creates a column with its named constraints:
        ADD COLUMN (type, NOT NULL, DEFAULT) plus one ADD CONSTRAINT
        per unique/FK/check. The rollback of a DROP COLUMN, and of
        the zero-downtime DROP_OLD_COLUMN. The column comes back
        empty — the data is not restored (reversibility schema-only)."""
        statements = [
            f"ALTER TABLE {table} ADD COLUMN {self._column_definition_sql(column.name, column)};"
        ]
        for action in self._column_constraint_actions(table, column.name, column):
            statements.append(f"ALTER TABLE {table} {action};")
        return "\n".join(statements)

    def _generate_column_modification_steps(self, columns_modified: List[Dict[str, Any]]):
        """Generate steps for modifying columns."""
        for col_info in columns_modified:
            if self.zero_downtime:
                steps = self._modify_column_zero_downtime_steps(col_info)
                self.migration_steps.extend(steps)
            else:
                step = self._modify_column_step(col_info)
                self.migration_steps.append(step)

    def _modify_column_step(self, col_info: Dict[str, Any]) -> MigrationStep:
        """Create step for modifying a column."""
        table = col_info["table"]
        column = col_info["column"]
        current_def = col_info["current_definition"]
        target_def = col_info["target_definition"]
        changes = col_info["changes"]

        alter_statements = []
        rollback_statements = []

        # Handle different types of changes
        if current_def.data_type != target_def.data_type:
            alter_statements.append(f"ALTER COLUMN {column} TYPE {target_def.data_type}")
            rollback_statements.append(f"ALTER COLUMN {column} TYPE {current_def.data_type}")

        if current_def.nullable != target_def.nullable:
            if target_def.nullable:
                alter_statements.append(f"ALTER COLUMN {column} DROP NOT NULL")
                rollback_statements.append(f"ALTER COLUMN {column} SET NOT NULL")
            else:
                alter_statements.append(f"ALTER COLUMN {column} SET NOT NULL")
                rollback_statements.append(f"ALTER COLUMN {column} DROP NOT NULL")

        if current_def.default_value != target_def.default_value:
            # A default of 0 is a real default: `is not None`, not
            # truthiness — SET DEFAULT 0 must not become DROP DEFAULT.
            if target_def.default_value is not None:
                alter_statements.append(
                    f"ALTER COLUMN {column} SET DEFAULT {target_def.default_value}"
                )
            else:
                alter_statements.append(f"ALTER COLUMN {column} DROP DEFAULT")

            if current_def.default_value is not None:
                rollback_statements.append(
                    f"ALTER COLUMN {column} SET DEFAULT {current_def.default_value}"
                )
            else:
                rollback_statements.append(f"ALTER COLUMN {column} DROP DEFAULT")

        # Unique, foreign key and check changes are constraint changes.
        # _columns_different detects them, so this step must convert them
        # to SQL — otherwise a unique-only change produces an empty ALTER
        # (invalid SQL) that claims to do the change and does nothing.
        if current_def.unique != target_def.unique:
            constraint_name = f"uq_{table}_{column}"
            if target_def.unique:
                alter_statements.append(f"ADD CONSTRAINT {constraint_name} UNIQUE ({column})")
                rollback_statements.append(f"DROP CONSTRAINT {constraint_name}")
            else:
                alter_statements.append(f"DROP CONSTRAINT {constraint_name}")
                rollback_statements.append(f"ADD CONSTRAINT {constraint_name} UNIQUE ({column})")

        if current_def.foreign_key != target_def.foreign_key:
            constraint_name = f"fk_{table}_{column}"
            if current_def.foreign_key:
                alter_statements.append(f"DROP CONSTRAINT {constraint_name}")
                rollback_statements.append(
                    f"ADD CONSTRAINT {constraint_name} FOREIGN KEY ({column}) "
                    f"REFERENCES {self._references_sql(current_def.foreign_key)}"
                )
            if target_def.foreign_key:
                alter_statements.append(
                    f"ADD CONSTRAINT {constraint_name} FOREIGN KEY ({column}) "
                    f"REFERENCES {self._references_sql(target_def.foreign_key)}"
                )
                rollback_statements.append(f"DROP CONSTRAINT {constraint_name}")

        if current_def.check_constraint != target_def.check_constraint:
            constraint_name = f"ck_{table}_{column}"
            if current_def.check_constraint:
                alter_statements.append(f"DROP CONSTRAINT {constraint_name}")
                rollback_statements.append(
                    f"ADD CONSTRAINT {constraint_name} CHECK ({current_def.check_constraint})"
                )
            if target_def.check_constraint:
                alter_statements.append(
                    f"ADD CONSTRAINT {constraint_name} CHECK ({target_def.check_constraint})"
                )
                rollback_statements.append(f"DROP CONSTRAINT {constraint_name}")

        if not alter_statements:
            # A detected change with no SQL handler must stop here, not
            # produce an empty ALTER that pretends to do the change.
            raise ValueError(
                f"column {table}.{column}: the detected change "
                f"({', '.join(changes)}) has no SQL handler"
            )

        # Build SQL
        alter_sql = f"ALTER TABLE {table}\n    " + ",\n    ".join(alter_statements) + ";"
        rollback_sql = f"ALTER TABLE {table}\n    " + ",\n    ".join(rollback_statements) + ";"

        # Assess risk
        risk_level = self._assess_column_modification_risk(current_def, target_def)

        return MigrationStep(
            step_id=self._generate_step_id(),
            step_type="MODIFY_COLUMN",
            table=table,
            description=f"Modify column {column}: {', '.join(changes)}",
            sql_forward=alter_sql,
            sql_rollback=rollback_sql,
            validation_sql=f"SELECT data_type, is_nullable FROM information_schema.columns WHERE table_name = '{table}' AND column_name = '{column}';",
            risk_level=risk_level,
        )

    def _modify_column_zero_downtime_steps(self, col_info: Dict[str, Any]) -> List[MigrationStep]:
        """Create zero-downtime steps for column modification using the
        expand-contract pattern:

        1. ADD_TEMP_COLUMN (EXPAND) — type only, nullable. The old
           code carried the target's full definition here: a NOT NULL
           column without a default fails on a populated table before
           the copy step ever runs, so the temp column carries the
           type and nothing else.
        2. COPY_COLUMN_DATA (EXPAND) — backfill, with a validation
           query that must return 0 before the contract phase: the
           old code had no check at all here. The check is now in
           the plan (SELECT COUNT(*) ... WHERE temp IS NULL — or,
           when the target is nullable, WHERE temp IS NULL AND old
           IS NOT NULL).
        3. DROP_OLD_COLUMN (CONTRACT) — HIGH risk, schema-only
           rollback: the column comes back empty, the data is not
           restored.
        4. RENAME_COLUMN (CONTRACT) — temp becomes the column.
        5. APPLY_CONSTRAINTS (CONTRACT) — the target's NOT NULL,
           default and named constraints, applied only after the
           backfill check returns 0. Emitted only when the target
           actually needs something applied (a plain type change has
           no step 5)."""
        table = col_info["table"]
        column = col_info["column"]
        current_def = col_info["current_definition"]
        target_def = col_info["target_definition"]

        steps = []

        # For zero-downtime, use expand-contract pattern
        temp_column = f"{column}_new"

        # Step 1: Add temp column with the new type only — nullable,
        # no default, no constraints.
        step1 = MigrationStep(
            step_id=self._generate_step_id(),
            step_type="ADD_TEMP_COLUMN",
            table=table,
            description=f"Add temporary column {temp_column} in {table} (type only — constraints are applied after the rename)",
            sql_forward=f"ALTER TABLE {table} ADD COLUMN {temp_column} {target_def.data_type};",
            sql_rollback=f"ALTER TABLE {table} DROP COLUMN {temp_column};",
            risk_level="LOW",
            zero_downtime_phase="EXPAND",
        )
        steps.append(step1)

        # Step 2: Copy data, with a backfill check that must return 0
        # before the contract phase runs.
        if not target_def.nullable:
            backfill_sql = f"SELECT COUNT(*) FROM {table} WHERE {temp_column} IS NULL;"
        else:
            backfill_sql = (
                f"SELECT COUNT(*) FROM {table} "
                f"WHERE {temp_column} IS NULL "
                f"AND {column} IS NOT NULL;"
            )
        step2 = MigrationStep(
            step_id=self._generate_step_id(),
            step_type="COPY_COLUMN_DATA",
            table=table,
            description=f"Copy data from {column} to {temp_column} in {table} — the backfill check must return 0 before the contract phase",
            sql_forward=f"UPDATE {table} SET {temp_column} = {column};",
            sql_rollback=f"UPDATE {table} SET {temp_column} = NULL;",
            validation_sql=backfill_sql,
            risk_level="MEDIUM",
            zero_downtime_phase="EXPAND",
        )
        steps.append(step2)

        # Step 3: Drop old column. This destroys the original column,
        # so it is HIGH risk — it must never inherit the default LOW.
        # The rollback re-adds the column with its named constraints,
        # but empty: the data is not restored (schema-only).
        step3 = MigrationStep(
            step_id=self._generate_step_id(),
            step_type="DROP_OLD_COLUMN",
            table=table,
            description=f"Drop original column {column} in {table} — the rollback re-adds the column empty; the data is not restored. Back up before running.",
            sql_forward=f"ALTER TABLE {table} DROP COLUMN {column};",
            sql_rollback=self._recreate_column_sql(table, current_def),
            risk_level="HIGH",
            zero_downtime_phase="CONTRACT",
            reversibility="schema-only",
        )
        steps.append(step3)

        # Step 4: Rename new column
        step4 = MigrationStep(
            step_id=self._generate_step_id(),
            step_type="RENAME_COLUMN",
            table=table,
            description=f"Rename {temp_column} to {column}",
            sql_forward=f"ALTER TABLE {table} RENAME COLUMN {temp_column} TO {column};",
            sql_rollback=f"ALTER TABLE {table} RENAME COLUMN {column} TO {temp_column};",
            risk_level="MEDIUM",
            zero_downtime_phase="CONTRACT",
        )
        steps.append(step4)

        # Step 5: Apply the target's NOT NULL, default and named
        # constraints, under the final name — only when the target
        # actually needs something applied.
        apply_step = self._zero_downtime_apply_constraints(table, column, current_def, target_def)
        if apply_step is not None:
            steps.append(apply_step)

        return steps

    def _zero_downtime_apply_constraints(
        self, table: str, column: str, current_def: Column, target_def: Column
    ) -> Optional[MigrationStep]:
        """The APPLY_CONSTRAINTS step of a zero-downtime modify: the
        target's NOT NULL, default and named constraints, applied
        only after the backfill check returns 0. Only the attributes
        that actually change are emitted; a plain type change needs
        no step (returns None)."""
        actions = []
        rollback_actions = []
        if not target_def.nullable and current_def.nullable:
            actions.append(f"ALTER COLUMN {column} SET NOT NULL")
            rollback_actions.append(f"ALTER COLUMN {column} DROP NOT NULL")
        if (
            target_def.default_value != current_def.default_value
            and target_def.default_value is not None
        ):
            actions.append(f"ALTER COLUMN {column} SET DEFAULT {target_def.default_value}")
            if current_def.default_value is not None:
                rollback_actions.append(
                    f"ALTER COLUMN {column} SET DEFAULT {current_def.default_value}"
                )
            else:
                rollback_actions.append(f"ALTER COLUMN {column} DROP DEFAULT")
        if target_def.unique and not current_def.unique:
            actions.append(f"ADD CONSTRAINT uq_{table}_{column} UNIQUE ({column})")
            rollback_actions.append(f"DROP CONSTRAINT uq_{table}_{column}")
        if target_def.foreign_key and target_def.foreign_key != current_def.foreign_key:
            actions.append(
                f"ADD CONSTRAINT fk_{table}_{column} FOREIGN KEY ({column}) "
                f"REFERENCES {self._references_sql(target_def.foreign_key)}"
            )
            rollback_actions.append(f"DROP CONSTRAINT fk_{table}_{column}")
        if (
            target_def.check_constraint
            and target_def.check_constraint != current_def.check_constraint
        ):
            actions.append(
                f"ADD CONSTRAINT ck_{table}_{column} CHECK ({target_def.check_constraint})"
            )
            rollback_actions.append(f"DROP CONSTRAINT ck_{table}_{column}")
        if not actions:
            return None
        forward = f"ALTER TABLE {table}\n    " + ",\n    ".join(actions) + ";"
        rollback = f"ALTER TABLE {table}\n    " + ",\n    ".join(rollback_actions) + ";"
        return MigrationStep(
            step_id=self._generate_step_id(),
            step_type="APPLY_CONSTRAINTS",
            table=table,
            description=f"Apply the target's NOT NULL, default and constraints to {column} in {table} — run only after the backfill check returns 0",
            sql_forward=forward,
            sql_rollback=rollback,
            risk_level="MEDIUM",
            zero_downtime_phase="CONTRACT",
        )

    def _assess_column_modification_risk(self, current: Column, target: Column) -> str:
        """Assess risk level of column modification."""
        if current.data_type != target.data_type:
            conversion_key = (current.data_type, target.data_type)
            if conversion_key in self.risky_type_conversions:
                return "HIGH"
            elif conversion_key not in self.safe_type_conversions:
                return "MEDIUM"

        if current.nullable and not target.nullable:
            return "HIGH"  # Adding NOT NULL constraint

        # Adding a constraint can fail on existing data.
        if (
            current.unique != target.unique
            or current.foreign_key != target.foreign_key
            or current.check_constraint != target.check_constraint
        ):
            return "MEDIUM"

        return "LOW"

    def _generate_constraint_addition_steps(self, constraints_added: List[Dict[str, Any]]):
        """Generate steps for adding constraints."""
        for constraint_info in constraints_added:
            step = self._add_constraint_step(constraint_info)
            self.migration_steps.append(step)

    def _add_constraint_step(self, constraint_info: Dict[str, Any]) -> MigrationStep:
        """Create step for adding constraint."""
        table = constraint_info["table"]
        constraint_type = constraint_info["constraint_type"]

        if constraint_type == "PRIMARY_KEY":
            columns = constraint_info["columns"]
            constraint_name = f"pk_{table}"
            add_sql = f"ALTER TABLE {table} ADD CONSTRAINT {constraint_name} PRIMARY KEY ({', '.join(columns)});"
            drop_sql = f"ALTER TABLE {table} DROP CONSTRAINT {constraint_name};"
            description = f"Add primary key on {', '.join(columns)}"

        elif constraint_type == "UNIQUE":
            columns = constraint_info["columns"]
            constraint_name = f"uq_{table}_{'_'.join(columns)}"
            add_sql = f"ALTER TABLE {table} ADD CONSTRAINT {constraint_name} UNIQUE ({', '.join(columns)});"
            drop_sql = f"ALTER TABLE {table} DROP CONSTRAINT {constraint_name};"
            description = f"Add unique constraint on {', '.join(columns)}"

        elif constraint_type == "FOREIGN_KEY":
            columns = constraint_info["columns"]
            constraint_name = f"fk_{table}_{'_'.join(columns)}"
            references = self._references_sql(constraint_info["references"])
            add_sql = (
                f"ALTER TABLE {table} ADD CONSTRAINT {constraint_name} "
                f"FOREIGN KEY ({', '.join(columns)}) REFERENCES {references};"
            )
            drop_sql = f"ALTER TABLE {table} DROP CONSTRAINT {constraint_name};"
            description = f"Add foreign key on {', '.join(columns)} referencing {references}"

        elif constraint_type == "CHECK":
            constraint_name = constraint_info["constraint_name"]
            condition = constraint_info["condition"]
            add_sql = f"ALTER TABLE {table} ADD CONSTRAINT {constraint_name} CHECK ({condition});"
            drop_sql = f"ALTER TABLE {table} DROP CONSTRAINT {constraint_name};"
            description = f"Add check constraint: {condition}"

        else:
            # Every caller uses the returned step directly (sets
            # .dependencies, appends it to the plan), so returning
            # None here would corrupt the plan or crash later with
            # a confusing AttributeError. An unknown constraint type
            # is a programming error: fail loudly.
            raise ValueError(f"unknown constraint type: {constraint_type!r}")

        return MigrationStep(
            step_id=self._generate_step_id(),
            step_type="ADD_CONSTRAINT",
            table=table,
            description=description,
            sql_forward=add_sql,
            sql_rollback=drop_sql,
            risk_level="MEDIUM",  # Constraints can fail if data doesn't comply
        )

    def _generate_index_addition_steps(self, indexes_added: List[Dict[str, Any]]):
        """Generate steps for adding indexes."""
        for index_info in indexes_added:
            step = self._add_index_step(index_info)
            self.migration_steps.append(step)

    def _index_create_sql(self, index: Dict[str, Any], table: str) -> str:
        """The CREATE INDEX statement for one index, with everything
        the schema declares: UNIQUE, the USING method, an expression
        instead of columns, and the WHERE predicate. The old code
        emitted only the column list — a partial index, an
        expression index and a GIN index all came out as plain
        btree indexes on the same columns, silently changing the
        index. The same helper builds an index drop's rollback, so a
        dropped index comes back as itself."""
        unique_keyword = "UNIQUE " if index.get("unique", False) else ""
        method = index.get("method") or index.get("using")
        using = f" USING {method}" if method else ""
        expression = index.get("expression")
        if expression:
            columns_sql = expression
        else:
            columns_sql = ", ".join(index.get("columns") or [])
        predicate = index.get("where") or index.get("predicate")
        where = f" WHERE {predicate}" if predicate else ""
        return (
            f"CREATE {unique_keyword}INDEX {index['name']} "
            f"ON {table}{using} ({columns_sql}){where};"
        )

    def _add_index_step(self, index_info: Dict[str, Any]) -> MigrationStep:
        """Create step for adding index."""
        table = index_info["table"]
        index = index_info["index"]

        create_sql = self._index_create_sql(index, table)
        drop_sql = f"DROP INDEX {index['name']};"

        columns_sql = index.get("expression") or ", ".join(index.get("columns") or [])
        return MigrationStep(
            step_id=self._generate_step_id(),
            step_type="ADD_INDEX",
            table=table,
            description=f"Create index {index['name']} on ({columns_sql})",
            sql_forward=create_sql,
            sql_rollback=drop_sql,
            estimated_time="1-5 minutes depending on table size",
            risk_level="LOW",
        )

    def _generate_table_rename_steps(self, tables_renamed: List[Dict[str, Any]]):
        """Generate steps for renaming tables."""
        for rename_info in tables_renamed:
            step = self._rename_table_step(rename_info)
            self.migration_steps.append(step)

    def _rename_table_step(self, rename_info: Dict[str, Any]) -> MigrationStep:
        """Create step for renaming table."""
        old_name = rename_info["old_name"]
        new_name = rename_info["new_name"]

        rename_sql = f"ALTER TABLE {old_name} RENAME TO {new_name};"
        rollback_sql = f"ALTER TABLE {new_name} RENAME TO {old_name};"

        similarity = rename_info.get("similarity_score")
        similarity_note = (
            (
                f" (heuristic, column similarity {similarity:.2f} — "
                f"confirm the rename before running)"
            )
            if similarity
            else ""
        )
        return MigrationStep(
            step_id=self._generate_step_id(),
            step_type="RENAME_TABLE",
            table=old_name,
            description=f"Rename table {old_name} to {new_name}{similarity_note}",
            sql_forward=rename_sql,
            sql_rollback=rollback_sql,
            validation_sql=f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name = '{new_name}';",
            risk_level="MEDIUM",
        )

    def _generate_column_removal_steps(self, columns_dropped: List[Dict[str, Any]]):
        """Generate steps for removing columns."""
        for col_info in columns_dropped:
            step = self._drop_column_step(col_info)
            self.migration_steps.append(step)

    def _drop_column_step(self, col_info: Dict[str, Any]) -> MigrationStep:
        """Create step for dropping column. The rollback re-adds the
        column with its named constraints — but the column comes back
        empty: the data is not restored. That is reversibility
        "schema-only", and the summary marks the step as a data-loss
        step (backup_required). A rollback that claims to restore the
        column while silently losing its rows is worse than one that
        says so."""
        table = col_info["table"]
        column = col_info["definition"]

        drop_sql = f"ALTER TABLE {table} DROP COLUMN {column.name};"

        add_sql = self._recreate_column_sql(table, column)

        return MigrationStep(
            step_id=self._generate_step_id(),
            step_type="DROP_COLUMN",
            table=table,
            description=f"Drop column {column.name} from {table} — the rollback restores the column empty; the data is not restored. Back up before running.",
            sql_forward=drop_sql,
            sql_rollback=add_sql,
            risk_level="HIGH",  # Data loss risk
            reversibility="schema-only",
        )

    def _generate_constraint_removal_steps(self, constraints_dropped: List[Dict[str, Any]]):
        """Generate steps for removing constraints."""
        for constraint_info in constraints_dropped:
            step = self._drop_constraint_step(constraint_info)
            if step:
                self.migration_steps.append(step)

    def _drop_constraint_step(self, constraint_info: Dict[str, Any]) -> Optional[MigrationStep]:
        """Create step for dropping constraint."""
        table = constraint_info["table"]
        constraint_type = constraint_info["constraint_type"]

        if constraint_type == "PRIMARY_KEY":
            constraint_name = f"pk_{table}"
            drop_sql = f"ALTER TABLE {table} DROP CONSTRAINT {constraint_name};"
            columns = constraint_info["columns"]
            add_sql = f"ALTER TABLE {table} ADD CONSTRAINT {constraint_name} PRIMARY KEY ({', '.join(columns)});"
            description = "Drop primary key constraint"

        elif constraint_type == "UNIQUE":
            columns = constraint_info["columns"]
            constraint_name = f"uq_{table}_{'_'.join(columns)}"
            drop_sql = f"ALTER TABLE {table} DROP CONSTRAINT {constraint_name};"
            add_sql = f"ALTER TABLE {table} ADD CONSTRAINT {constraint_name} UNIQUE ({', '.join(columns)});"
            description = f"Drop unique constraint on {', '.join(columns)}"

        elif constraint_type == "CHECK":
            constraint_name = constraint_info["constraint_name"]
            condition = constraint_info.get("condition", "")
            drop_sql = f"ALTER TABLE {table} DROP CONSTRAINT {constraint_name};"
            add_sql = f"ALTER TABLE {table} ADD CONSTRAINT {constraint_name} CHECK ({condition});"
            description = f"Drop check constraint {constraint_name}"

        else:
            return None

        return MigrationStep(
            step_id=self._generate_step_id(),
            step_type="DROP_CONSTRAINT",
            table=table,
            description=description,
            sql_forward=drop_sql,
            sql_rollback=add_sql,
            risk_level="MEDIUM",
        )

    def _generate_index_removal_steps(self, indexes_dropped: List[Dict[str, Any]]):
        """Generate steps for removing indexes."""
        for index_info in indexes_dropped:
            step = self._drop_index_step(index_info)
            self.migration_steps.append(step)

    def _drop_index_step(self, index_info: Dict[str, Any]) -> MigrationStep:
        """Create step for dropping index. The rollback re-creates the
        index as it was — predicate, expression and method included
        (see _index_create_sql); the old rollback rebuilt a plain
        btree index on the columns, silently changing a partial,
        expression or GIN index."""
        table = index_info["table"]
        index = index_info["index"]

        drop_sql = f"DROP INDEX {index['name']};"

        # Recreate for rollback — the full definition, not just the
        # column list.
        create_sql = self._index_create_sql(index, table)

        return MigrationStep(
            step_id=self._generate_step_id(),
            step_type="DROP_INDEX",
            table=table,
            description=f"Drop index {index['name']}",
            sql_forward=drop_sql,
            sql_rollback=create_sql,
            risk_level="LOW",
        )

    def _generate_table_removal_steps(self, tables_dropped: List[Dict[str, Any]]):
        """Generate steps for removing tables, in reverse FK
        dependency order: a table that references another drops
        first, so no DROP ever breaks a FK that still exists.
        Tables in a cycle drop in reverse alphabetical order —
        dropping a table removes its FKs, so any order inside a
        cycle is safe. Each drop step names the tables (also
        dropped) that reference it: they must be gone first."""
        by_name = {info["definition"].name: info["definition"] for info in tables_dropped}
        order, cyclic = _topological_table_order(by_name)
        drop_order = sorted(cyclic, reverse=True) + list(reversed(order))
        by_info = {info["definition"].name: info for info in tables_dropped}
        for name in drop_order:
            step = self._drop_table_step(by_info[name])
            step.dependencies = sorted(
                other
                for other, table in by_name.items()
                if name in {r.split(".", 1)[0] for r in table.foreign_keys.values()}
            )
            self.migration_steps.append(step)

    def _drop_table_step(self, table_info: Dict[str, Any]) -> MigrationStep:
        """Create step for dropping table. The rollback is the real
        CREATE TABLE for the table — with its named constraints — plus
        the CREATE INDEX statements for its indexes, built by the
        same code that creates the table in the first place. The table
        comes back empty: the data is not restored (schema-only), and
        the summary marks the step as a data-loss step."""
        table = table_info["definition"]

        drop_sql = f"DROP TABLE {table.name};"

        create_statements = [self._create_table_sql(table)]
        for index in table.indexes:
            create_statements.append(self._index_create_sql(index, table.name))
        create_sql = "\n".join(create_statements)

        return MigrationStep(
            step_id=self._generate_step_id(),
            step_type="DROP_TABLE",
            table=table.name,
            description=f"Drop table {table.name} — the rollback re-creates the table empty; the data is not restored. Back up before running.",
            sql_forward=drop_sql,
            sql_rollback=create_sql,
            risk_level="HIGH",  # Data loss risk
            reversibility="schema-only",
        )

    def _generate_migration_id(self, changes: Dict[str, List[Dict[str, Any]]]) -> str:
        """Generate unique migration ID."""
        content = json.dumps(changes, sort_keys=True, default=_json_default)
        return hashlib.md5(content.encode()).hexdigest()[:8]

    def _calculate_schema_hash(self, schema: Optional[Dict[str, Any]]) -> str:
        """The SHA-256 of a schema dict (keys sorted, defaults
        serialised). Empty string when no schema was given — the
        caller did not bind the plan to a schema pair, and the
        summary says so. The old code hashed the changes dict and
        left the target hash empty, so a PASS could be carried from
        one schema pair to another."""
        if schema is None:
            return ""
        content = json.dumps(schema, sort_keys=True, default=_json_default)
        return hashlib.sha256(content.encode()).hexdigest()

    def _generate_summary(self, changes: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Generate migration summary. The summary now also says
        whether any step loses data: backup_required is True and
        data_loss_steps lists the step ids whose reversibility is
        "schema-only" (a rollback that restores the structure but not
        the data)."""
        data_loss_steps = [
            s.step_id for s in self.migration_steps if s.reversibility == "schema-only"
        ]
        summary = {
            "total_steps": len(self.migration_steps),
            "backup_required": bool(data_loss_steps),
            "data_loss_steps": data_loss_steps,
            "changes_summary": {
                "tables_added": len(changes["tables_added"]),
                "tables_dropped": len(changes["tables_dropped"]),
                "tables_renamed": len(changes["tables_renamed"]),
                "columns_added": len(changes["columns_added"]),
                "columns_dropped": len(changes["columns_dropped"]),
                "columns_modified": len(changes["columns_modified"]),
                "constraints_added": len(changes["constraints_added"]),
                "constraints_dropped": len(changes["constraints_dropped"]),
                "indexes_added": len(changes["indexes_added"]),
                "indexes_dropped": len(changes["indexes_dropped"]),
            },
            "risk_assessment": {
                "high_risk_steps": len([s for s in self.migration_steps if s.risk_level == "HIGH"]),
                "medium_risk_steps": len(
                    [s for s in self.migration_steps if s.risk_level == "MEDIUM"]
                ),
                "low_risk_steps": len([s for s in self.migration_steps if s.risk_level == "LOW"]),
            },
            "zero_downtime": self.zero_downtime,
        }
        if self.zero_downtime:
            # The expand-contract output is a DRAFT, not a verified
            # zero-downtime migration: there is no write-synchronisation
            # and no cutover in these steps. The backfill check IS in
            # the plan now (a validation query on the COPY_COLUMN_DATA
            # step, which must return 0 before CONTRACT). It still
            # needs application coordination (dual-write during EXPAND,
            # a cutover). Do not run it automatically on real data.
            summary["zero_downtime_warning"] = (
                "Expand-contract DRAFT. The backfill check is in the "
                "plan (run the COPY step's validation query — it must "
                "return 0 before the contract phase). Still requires "
                "application coordination: dual-write to both columns "
                "during EXPAND, and a cutover. Do not run "
                "automatically on real data."
            )

        return summary


class ValidationGenerator:
    """Generates validation queries for migration verification."""

    def generate_validations(self, migration_plan: MigrationPlan) -> List[ValidationCheck]:
        """Generate validation checks for migration plan."""
        validations = []

        for step in migration_plan.steps:
            if step.step_type == "CREATE_TABLE":
                validations.append(self._create_table_validation(step))
            elif step.step_type == "ADD_COLUMN":
                validations.append(self._add_column_validation(step))
            elif step.step_type == "MODIFY_COLUMN":
                validations.append(self._modify_column_validation(step))
            elif step.step_type == "ADD_INDEX":
                validations.append(self._add_index_validation(step))
            elif step.step_type == "DROP_COLUMN":
                validations.append(self._drop_column_validation(step))
            elif step.step_type == "DROP_TABLE":
                validations.append(self._drop_table_validation(step))

        return validations

    def _create_table_validation(self, step: MigrationStep) -> ValidationCheck:
        """Create validation for table creation."""
        return ValidationCheck(
            check_id=f"validate_{step.step_id}",
            check_type="TABLE_EXISTS",
            table=step.table,
            description=f"Verify table {step.table} exists",
            sql_query=f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name = '{step.table}';",
            expected_result=1,
        )

    def _add_column_validation(self, step: MigrationStep) -> ValidationCheck:
        """Create validation for column addition."""
        # Extract column name from SQL
        column_match = re.search(r"ADD COLUMN (\w+)", step.sql_forward)
        column_name = column_match.group(1) if column_match else "unknown"

        return ValidationCheck(
            check_id=f"validate_{step.step_id}",
            check_type="COLUMN_EXISTS",
            table=step.table,
            description=f"Verify column {column_name} exists in {step.table}",
            sql_query=f"SELECT COUNT(*) FROM information_schema.columns WHERE table_name = '{step.table}' AND column_name = '{column_name}';",
            expected_result=1,
        )

    def _modify_column_validation(self, step: MigrationStep) -> ValidationCheck:
        """Create validation for column modification."""
        return ValidationCheck(
            check_id=f"validate_{step.step_id}",
            check_type="COLUMN_MODIFIED",
            table=step.table,
            description=f"Verify column modification in {step.table}",
            sql_query=step.validation_sql or "SELECT 1;",  # Use provided validation or default
            expected_result=1,
        )

    def _add_index_validation(self, step: MigrationStep) -> ValidationCheck:
        """Create validation for index addition."""
        # Extract index name from SQL
        index_match = re.search(r"INDEX (\w+)", step.sql_forward)
        index_name = index_match.group(1) if index_match else "unknown"

        return ValidationCheck(
            check_id=f"validate_{step.step_id}",
            check_type="INDEX_EXISTS",
            table=step.table,
            description=f"Verify index {index_name} exists",
            sql_query=f"SELECT COUNT(*) FROM information_schema.statistics WHERE index_name = '{index_name}';",
            expected_result=1,
        )

    def _drop_column_validation(self, step: MigrationStep) -> ValidationCheck:
        """Create validation for column removal. A drop must be
        verified BEFORE it runs — that the column exists (expected 1)
        — because the step is schema-only: once it runs, the data is
        gone and the rollback restores the column empty. The old
        generator emitted no validation at all for DROP COLUMN."""
        column_match = re.search(r"DROP COLUMN (\w+)", step.sql_forward)
        column_name = column_match.group(1) if column_match else "unknown"

        return ValidationCheck(
            check_id=f"validate_{step.step_id}",
            check_type="COLUMN_EXISTS_BEFORE_DROP",
            table=step.table,
            description=f"Verify column {column_name} exists in {step.table} before dropping it",
            sql_query=f"SELECT COUNT(*) FROM information_schema.columns WHERE table_name = '{step.table}' AND column_name = '{column_name}';",
            expected_result=1,
        )

    def _drop_table_validation(self, step: MigrationStep) -> ValidationCheck:
        """Create validation for table removal — same reasoning as
        the column drop: verify the table exists before destroying
        it, because the rollback re-creates it empty."""
        return ValidationCheck(
            check_id=f"validate_{step.step_id}",
            check_type="TABLE_EXISTS_BEFORE_DROP",
            table=step.table,
            description=f"Verify table {step.table} exists before dropping it",
            sql_query=f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name = '{step.table}';",
            expected_result=1,
        )


def format_migration_plan_text(
    plan: MigrationPlan, validations: Optional[List[ValidationCheck]] = None
) -> str:
    """Format migration plan as human-readable text."""
    lines = []
    lines.append("DATABASE MIGRATION PLAN")
    lines.append("=" * 50)
    lines.append(f"Migration ID: {plan.migration_id}")
    lines.append(f"Created: {plan.created_at}")
    lines.append(f"Zero Downtime: {plan.summary['zero_downtime']}")
    lines.append("")

    # Summary
    summary = plan.summary
    lines.append("MIGRATION SUMMARY")
    lines.append("-" * 17)
    lines.append(f"Total Steps: {summary['total_steps']}")

    changes = summary["changes_summary"]
    for change_type, count in changes.items():
        if count > 0:
            lines.append(f"{change_type.replace('_', ' ').title()}: {count}")
    lines.append("")

    # Risk Assessment
    risk = summary["risk_assessment"]
    lines.append("RISK ASSESSMENT")
    lines.append("-" * 15)
    lines.append(f"High Risk Steps: {risk['high_risk_steps']}")
    lines.append(f"Medium Risk Steps: {risk['medium_risk_steps']}")
    lines.append(f"Low Risk Steps: {risk['low_risk_steps']}")
    if summary.get("backup_required"):
        lines.append(
            f"BACKUP REQUIRED: steps {', '.join(summary['data_loss_steps'])} "
            f"restore the structure but not the data."
        )
    lines.append("")

    # Migration Steps
    lines.append("MIGRATION STEPS")
    lines.append("-" * 15)
    for i, step in enumerate(plan.steps, 1):
        lines.append(f"{i}. {step.description} ({step.risk_level} risk)")
        lines.append(f"   Type: {step.step_type}")
        if step.zero_downtime_phase:
            lines.append(f"   Phase: {step.zero_downtime_phase}")
        if step.reversibility != "schema":
            lines.append(
                f"   Reversibility: {step.reversibility} "
                f"(rollback restores the structure, not the data)"
            )
        lines.append(f"   Forward SQL: {step.sql_forward}")
        lines.append(f"   Rollback SQL: {step.sql_rollback}")
        if step.estimated_time:
            lines.append(f"   Estimated Time: {step.estimated_time}")
        lines.append("")

    # Validation Checks
    if validations:
        lines.append("VALIDATION CHECKS")
        lines.append("-" * 17)
        for validation in validations:
            lines.append(f"• {validation.description}")
            lines.append(f"  SQL: {validation.sql_query}")
            lines.append(f"  Expected: {validation.expected_result}")
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate database migration scripts")
    parser.add_argument("--current", "-c", required=True, help="Current schema JSON file")
    parser.add_argument("--target", "-t", required=True, help="Target schema JSON file")
    parser.add_argument("--output", "-o", help="Output file (default: stdout)")
    parser.add_argument(
        "--format", "-f", choices=["json", "text", "sql"], default="text", help="Output format"
    )
    parser.add_argument(
        "--zero-downtime",
        "-z",
        action="store_true",
        help="Generate zero-downtime migration strategy",
    )
    parser.add_argument(
        "--validate-only", "-v", action="store_true", help="Only generate validation queries"
    )
    parser.add_argument(
        "--include-validations", action="store_true", help="Include validation queries in output"
    )

    args = parser.parse_args()

    try:
        # Load schemas
        with open(args.current, "r") as f:
            current_schema = json.load(f)

        with open(args.target, "r") as f:
            target_schema = json.load(f)

        # Compare schemas
        comparator = SchemaComparator()
        comparator.load_schemas(current_schema, target_schema)
        changes = comparator.compare_schemas()

        if not any(changes.values()):
            print("No schema changes detected.")
            return 0

        # Generate migration — the loaded schema dicts bind the plan's
        # hashes to this schema pair (see generate_migration).
        generator = MigrationGenerator(zero_downtime=args.zero_downtime)
        migration_plan = generator.generate_migration(
            changes, current_schema=current_schema, target_schema=target_schema
        )

        # Generate validations if requested
        validations = None
        if args.include_validations or args.validate_only:
            validator = ValidationGenerator()
            validations = validator.generate_validations(migration_plan)

        # Format output
        if args.validate_only:
            output = json.dumps([asdict(v) for v in validations], indent=2)
        elif args.format == "json":
            result = {"migration_plan": asdict(migration_plan)}
            if validations:
                result["validations"] = [asdict(v) for v in validations]
            output = json.dumps(result, indent=2)
        elif args.format == "sql":
            sql_lines = []
            sql_lines.append("-- Database Migration Script")
            sql_lines.append(f"-- Migration ID: {migration_plan.migration_id}")
            sql_lines.append(f"-- Created: {migration_plan.created_at}")
            sql_lines.append("")

            for step in migration_plan.steps:
                sql_lines.append(f"-- Step: {step.description}")
                sql_lines.append(step.sql_forward)
                sql_lines.append("")

            output = "\n".join(sql_lines)
        else:  # text format
            output = format_migration_plan_text(migration_plan, validations)

        # Write output
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
        else:
            print(output)

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
