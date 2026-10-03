"""
schema_parser.py
================================================================================
Parses SQL Server schema definition files (.schema) into structured Python objects.

Usage:
    from utilities.schema_parser import parse_schema_file, to_spark_schema_hints

    columns = parse_schema_file("ddmast.schema")
    hints_str = to_spark_schema_hints(columns)
================================================================================
"""

import os
import re
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# SQL Server → Spark type mapping
# ─────────────────────────────────────────────────────────────────────────────

_SQL_SERVER_TO_SPARK = {
    "bigint": "LONG",
    "int": "INT",
    "smallint": "SHORT",
    "tinyint": "BYTE",
    "bit": "SHORT",
    "float": "DOUBLE",
    "real": "FLOAT",
    "date": "DATE",
    "datetime": "TIMESTAMP",
    "datetime2": "TIMESTAMP",
    "smalldatetime": "TIMESTAMP",
    "time": "STRING",
    "uniqueidentifier": "STRING",
    "xml": "STRING",
    "text": "STRING",
    "ntext": "STRING",
    "image": "BINARY",
    "binary": "BINARY",
    "varbinary": "BINARY",
    "money": "DECIMAL(19,4)",
    "smallmoney": "DECIMAL(10,4)",
}


def _map_sql_type_to_spark(sql_type: str) -> str:
    """Convert a SQL Server column type to the equivalent Spark SQL type string."""
    sql_lower = sql_type.lower().strip()

    if sql_lower in _SQL_SERVER_TO_SPARK:
        return _SQL_SERVER_TO_SPARK[sql_lower]

    if sql_lower.startswith(("char", "varchar", "nchar", "nvarchar")):
        return "STRING"

    match = re.match(r"(decimal|numeric)\((\d+),\s*(\d+)\)", sql_lower)
    if match:
        precision, scale = match.group(2), match.group(3)
        return f"DECIMAL({precision},{scale})"

    if sql_lower in ("decimal", "numeric"):
        return "DECIMAL(38,0)"

    match = re.match(r"datetime2\(\d+\)", sql_lower)
    if match:
        return "TIMESTAMP"

    return "STRING"


# ─────────────────────────────────────────────────────────────────────────────
# Parser
# ─────────────────────────────────────────────────────────────────────────────

_LINE_PATTERN = re.compile(
    r"\[(?P<name>[^\]]+)\]\s+"
    r"\[(?P<type>[^\]]+)\]"
    r"(?:\((?P<params>[^)]*)\))?"
    r"\s+(?P<nullable>NULL|NOT NULL)"
)

_NEEDS_QUOTING = re.compile(r"[^a-zA-Z0-9_]")


def parse_schema_file(
    filename: str,
    schema_dir: Optional[str] = None,
) -> list[dict]:
    """Parse a SQL Server schema definition file into a list of column definitions."""
    if schema_dir is None:
        schema_dir = os.path.dirname(os.path.abspath(__file__))

    filepath = os.path.join(schema_dir, filename)
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Schema file not found: {filepath}")

    columns = []
    with open(filepath, "r") as f:
        for line in f:
            stripped = re.sub(r"^\d+:\s*", "", line).strip()
            if not stripped:
                continue

            match = _LINE_PATTERN.search(stripped)
            if not match:
                continue

            col_name = match.group("name")
            base_type = match.group("type")
            params = match.group("params")
            nullable = match.group("nullable") == "NULL"

            sql_type = f"{base_type}({params})" if params else base_type
            spark_type = _map_sql_type_to_spark(sql_type)

            columns.append({
                "name": col_name,
                "sql_type": sql_type,
                "nullable": nullable,
                "spark_type": spark_type,
            })

    return columns


# ─────────────────────────────────────────────────────────────────────────────
# Output helpers
# ─────────────────────────────────────────────────────────────────────────────

def _quote_identifier(name: str) -> str:
    """Backtick-quote a column name if it contains special characters."""
    if _NEEDS_QUOTING.search(name):
        return f"`{name}`"
    return name


def to_spark_schema_hints(columns: list[dict]) -> str:
    parts = [f"{_quote_identifier(col['name'])} {col['spark_type']}" for col in columns]
    return ", ".join(parts)


def to_column_names(columns: list[dict]) -> list[str]:
    return [col["name"] for col in columns]


def get_bit_column_names(
    source_table: str,
    schema_dir: Optional[str] = None,
) -> list[str]:
    if schema_dir is None:
        schema_dir = os.path.dirname(os.path.abspath(__file__))

    schema_file = f"{source_table}.schema"
    schema_path = os.path.join(schema_dir, schema_file)
    if not os.path.isfile(schema_path):
        return []

    columns = parse_schema_file(schema_file, schema_dir=schema_dir)
    return [col["name"] for col in columns if col["sql_type"].lower() == "bit"]


def to_struct_type(columns: list[dict]):
    from pyspark.sql.types import (
        StructType, StructField, StringType, IntegerType, LongType,
        ShortType, ByteType, BooleanType, DoubleType, FloatType,
        DateType, TimestampType, BinaryType, DecimalType,
    )

    def _resolve_type(spark_type_str: str):
        s = spark_type_str.upper()
        if s == "STRING":
            return StringType()
        if s == "INT":
            return IntegerType()
        if s == "LONG":
            return LongType()
        if s == "SHORT":
            return ShortType()
        if s == "BYTE":
            return ByteType()
        if s == "BOOLEAN":
            return BooleanType()
        if s == "DOUBLE":
            return DoubleType()
        if s == "FLOAT":
            return FloatType()
        if s == "DATE":
            return DateType()
        if s == "TIMESTAMP":
            return TimestampType()
        if s == "BINARY":
            return BinaryType()
        m = re.match(r"DECIMAL\((\d+),(\d+)\)", s)
        if m:
            return DecimalType(int(m.group(1)), int(m.group(2)))
        return StringType()

    fields = [
        StructField(col["name"], _resolve_type(col["spark_type"]), col["nullable"])
        for col in columns
    ]
    return StructType(fields)


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "ddmast.schema"
    cols = parse_schema_file(target)
    print(f"Parsed {len(cols)} columns from {target}\n")
    print("First 10 columns:")
    for c in cols[:10]:
        print(f"  {c['name']:20s} {c['sql_type']:20s} → {c['spark_type']}")
    print(f"\nSchema hints (first 200 chars):\n  {to_spark_schema_hints(cols)[:200]}...")
