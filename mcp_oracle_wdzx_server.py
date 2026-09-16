#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import decimal
import os
import re
from pathlib import Path
from typing import Any

import oracledb
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP


REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPO_ROOT / ".env.local"
DEFAULT_SCHEMA_ENV = "ORACLE_DB_NAME"
MAX_SELECT_LIMIT = 100
MAX_SAMPLE_LIMIT = 20
MAX_ENUM_DISTINCT = 20
MAX_PROFILE_SAMPLE = 5

BLOCKED_SQL_PATTERNS = (
    r"\binsert\b",
    r"\bupdate\b",
    r"\bdelete\b",
    r"\bmerge\b",
    r"\bdrop\b",
    r"\balter\b",
    r"\bcreate\b",
    r"\btruncate\b",
    r"\bgrant\b",
    r"\brevoke\b",
    r"\bcall\b",
    r"\bexec(?:ute)?\b",
    r"\bbegin\b",
    r"\bcommit\b",
    r"\brollback\b",
)

IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*$")
DATE_COLUMN_RE = re.compile(r"(DATE|DT|ENDDATE|TRADEDATE|NAVDATE|REPORTDATE|截止|日期)", re.IGNORECASE)
ENUM_COLUMN_RE = re.compile(r"(TYPE|CLASS|CATEGORY|STYLE|STATUS|FLAG|NAME|TAG|SOURCE)", re.IGNORECASE)

mcp = FastMCP("oracle-wdzx-readonly")
_ORACLE_CLIENT_INITIALIZED = False


def load_config() -> dict[str, str]:
    load_dotenv(ENV_FILE, override=False)
    required = (
        "ORACLE_DB_HOST",
        "ORACLE_DB_PORT",
        "ORACLE_DB_SID",
        "ORACLE_DB_USER",
        "ORACLE_DB_PASSWORD",
        "ORACLE_CLIENT_LIB_DIR",
    )
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(f"Missing required Oracle environment variables: {', '.join(missing)}")

    config = {key: os.environ[key] for key in required}
    config[DEFAULT_SCHEMA_ENV] = os.getenv(DEFAULT_SCHEMA_ENV, config["ORACLE_DB_USER"]).upper()
    return config


def init_oracle_client(config: dict[str, str]) -> None:
    global _ORACLE_CLIENT_INITIALIZED
    if _ORACLE_CLIENT_INITIALIZED:
        return
    oracledb.init_oracle_client(lib_dir=config["ORACLE_CLIENT_LIB_DIR"])
    _ORACLE_CLIENT_INITIALIZED = True


def connect() -> oracledb.Connection:
    config = load_config()
    init_oracle_client(config)
    dsn = oracledb.makedsn(
        config["ORACLE_DB_HOST"],
        int(config["ORACLE_DB_PORT"]),
        sid=config["ORACLE_DB_SID"],
    )
    connection = oracledb.connect(
        user=config["ORACLE_DB_USER"],
        password=config["ORACLE_DB_PASSWORD"],
        dsn=dsn,
    )
    return connection


def default_schema() -> str:
    return load_config()[DEFAULT_SCHEMA_ENV]


def assert_identifier(value: str, label: str) -> str:
    normalized = (value or "").strip().upper()
    if not normalized or not IDENTIFIER_RE.match(normalized):
        raise ValueError(f"Invalid {label}: {value!r}")
    return normalized


def quote_identifier(value: str) -> str:
    return assert_identifier(value, "identifier")


def clamp_limit(value: int | None, max_limit: int) -> int:
    try:
        limit = int(value if value is not None else max_limit)
    except (TypeError, ValueError):
        limit = max_limit
    return max(1, min(limit, max_limit))


def clamp_offset(value: int | None) -> int:
    try:
        offset = int(value if value is not None else 0)
    except (TypeError, ValueError):
        offset = 0
    return max(0, offset)


def normalize_sql(query: str) -> str:
    sql = (query or "").strip()
    if not sql:
        raise ValueError("SQL query is required")
    if sql.endswith(";"):
        raise ValueError("Trailing semicolon is not allowed")

    lowered = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL).lower()
    lowered = re.sub(r"--.*?$", " ", lowered, flags=re.MULTILINE).strip()
    first_token = lowered.split(None, 1)[0] if lowered else ""
    if first_token not in {"select", "with"}:
        raise ValueError("Only SELECT or WITH queries are allowed")

    for pattern in BLOCKED_SQL_PATTERNS:
        if re.search(pattern, lowered):
            raise ValueError(f"Blocked non-read-only SQL pattern: {pattern}")
    return sql


def to_jsonable(value: Any) -> Any:
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat(sep=" ") if isinstance(value, dt.datetime) else value.isoformat()
    if isinstance(value, decimal.Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def rows_from_cursor(cursor: oracledb.Cursor) -> list[dict[str, Any]]:
    columns = [col[0] for col in cursor.description or []]
    return [
        {columns[index]: to_jsonable(value) for index, value in enumerate(row)}
        for row in cursor.fetchall()
    ]


def fetch_all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params or {})
            return rows_from_cursor(cursor)


def table_exists(connection: oracledb.Connection, schema_name: str, table_name: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1
            FROM ALL_OBJECTS
            WHERE OWNER = :schema_name
              AND OBJECT_NAME = :table_name
              AND OBJECT_TYPE IN ('TABLE', 'VIEW', 'MATERIALIZED VIEW')
              AND ROWNUM = 1
            """,
            {"schema_name": schema_name, "table_name": table_name},
        )
        return cursor.fetchone() is not None


def get_columns(connection: oracledb.Connection, schema_name: str, table_name: str) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              c.COLUMN_NAME,
              c.DATA_TYPE,
              c.DATA_LENGTH,
              c.DATA_PRECISION,
              c.DATA_SCALE,
              c.NULLABLE,
              cc.COMMENTS AS COLUMN_COMMENT,
              CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 'Y' ELSE 'N' END AS IS_PRIMARY_KEY
            FROM ALL_TAB_COLUMNS c
            LEFT JOIN ALL_COL_COMMENTS cc
              ON cc.OWNER = c.OWNER
             AND cc.TABLE_NAME = c.TABLE_NAME
             AND cc.COLUMN_NAME = c.COLUMN_NAME
            LEFT JOIN (
              SELECT acc.OWNER, acc.TABLE_NAME, acc.COLUMN_NAME
              FROM ALL_CONSTRAINTS ac
              JOIN ALL_CONS_COLUMNS acc
                ON acc.OWNER = ac.OWNER
               AND acc.CONSTRAINT_NAME = ac.CONSTRAINT_NAME
               AND acc.TABLE_NAME = ac.TABLE_NAME
              WHERE ac.CONSTRAINT_TYPE = 'P'
            ) pk
              ON pk.OWNER = c.OWNER
             AND pk.TABLE_NAME = c.TABLE_NAME
             AND pk.COLUMN_NAME = c.COLUMN_NAME
            WHERE c.OWNER = :schema_name
              AND c.TABLE_NAME = :table_name
            ORDER BY c.COLUMN_ID
            """,
            {"schema_name": schema_name, "table_name": table_name},
        )
        return rows_from_cursor(cursor)


def paginated_select_sql(query: str) -> str:
    return f"""
    SELECT *
    FROM (
      SELECT mcp_inner_query.*, ROWNUM AS MCP_RN
      FROM (
        {query}
      ) mcp_inner_query
      WHERE ROWNUM <= :mcp_end_row
    )
    WHERE MCP_RN > :mcp_offset
    """


@mcp.tool()
def ping_oracle() -> dict[str, Any]:
    """Test Oracle connectivity and return current user, schema, and version info."""
    version_error = None
    version: list[dict[str, Any]] = []
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  USER AS CURRENT_USER,
                  SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') AS CURRENT_SCHEMA
                FROM DUAL
                """
            )
            identity = rows_from_cursor(cursor)[0]

            try:
                cursor.execute(
                    """
                    SELECT BANNER
                    FROM V$VERSION
                    WHERE ROWNUM <= 5
                    """
                )
                version = rows_from_cursor(cursor)
            except Exception as exc:
                version_error = f"V$VERSION failed: {type(exc).__name__}: {exc}"
                try:
                    cursor.execute(
                        """
                        SELECT PRODUCT, VERSION, STATUS
                        FROM (
                          SELECT PRODUCT, VERSION, STATUS
                          FROM PRODUCT_COMPONENT_VERSION
                        )
                        WHERE ROWNUM <= 20
                        """
                    )
                    version = rows_from_cursor(cursor)
                except Exception as fallback_exc:
                    version_error = (
                        f"{version_error}; PRODUCT_COMPONENT_VERSION failed: "
                        f"{type(fallback_exc).__name__}: {fallback_exc}"
                    )

    result: dict[str, Any] = {"ok": True, "identity": identity, "version": version}
    if version_error:
        result["version_error"] = version_error
    return result


@mcp.tool()
def list_schemas() -> dict[str, Any]:
    """List visible schemas, prioritizing the configured WDZX/current schema."""
    configured_schema = default_schema()
    rows = fetch_all(
        """
        SELECT *
        FROM (
          SELECT USERNAME AS SCHEMA_NAME, CREATED
          FROM ALL_USERS
          WHERE USERNAME = :configured_schema
             OR USERNAME = USER
             OR USERNAME LIKE '%WDZX%'
             OR EXISTS (
               SELECT 1
               FROM ALL_OBJECTS ao
               WHERE ao.OWNER = ALL_USERS.USERNAME
                 AND ao.OBJECT_TYPE IN ('TABLE', 'VIEW', 'MATERIALIZED VIEW')
                 AND ROWNUM = 1
             )
          ORDER BY
            CASE WHEN USERNAME = :configured_schema THEN 0 WHEN USERNAME = USER THEN 1 ELSE 2 END,
            USERNAME
        )
        WHERE ROWNUM <= 100
        """,
        {"configured_schema": configured_schema},
    )
    return {"default_schema": configured_schema, "schemas": rows}


@mcp.tool()
def list_tables(schema_name: str | None = None) -> dict[str, Any]:
    """List tables/views for a schema with comments and estimated row counts when available."""
    schema = assert_identifier(schema_name or default_schema(), "schema_name")
    rows = fetch_all(
        """
        SELECT *
        FROM (
          SELECT
            o.OBJECT_NAME AS TABLE_NAME,
            o.OBJECT_TYPE AS TABLE_TYPE,
            tc.COMMENTS AS COMMENTS,
            t.NUM_ROWS AS ESTIMATED_ROWS
          FROM ALL_OBJECTS o
          LEFT JOIN ALL_TAB_COMMENTS tc
            ON tc.OWNER = o.OWNER
           AND tc.TABLE_NAME = o.OBJECT_NAME
          LEFT JOIN ALL_TABLES t
            ON t.OWNER = o.OWNER
           AND t.TABLE_NAME = o.OBJECT_NAME
          WHERE o.OWNER = :schema_name
            AND o.OBJECT_TYPE IN ('TABLE', 'VIEW', 'MATERIALIZED VIEW')
          ORDER BY o.OBJECT_TYPE, o.OBJECT_NAME
        )
        WHERE ROWNUM <= 500
        """,
        {"schema_name": schema},
    )
    return {"schema_name": schema, "tables": rows, "returned": len(rows)}


@mcp.tool()
def search_tables(keywords: list[str], schema_name: str | None = None, limit: int = 200) -> dict[str, Any]:
    """Search visible tables/views by keywords in object names and comments."""
    schema = assert_identifier(schema_name or default_schema(), "schema_name")
    safe_limit = clamp_limit(limit, 500)
    cleaned_keywords = [str(keyword).strip().upper() for keyword in (keywords or []) if str(keyword).strip()]
    if not cleaned_keywords:
        return {
            "schema_name": schema,
            "error": "keywords is required; refusing to search without keywords",
            "tables": [],
            "returned": 0,
        }

    clauses = []
    params: dict[str, Any] = {"schema_name": schema, "mcp_limit": safe_limit}
    for index, keyword in enumerate(cleaned_keywords[:20]):
        param_name = f"kw_{index}"
        params[param_name] = f"%{keyword}%"
        clauses.append(f"(UPPER(o.OBJECT_NAME) LIKE :{param_name} OR UPPER(NVL(tc.COMMENTS, '')) LIKE :{param_name})")

    sql = f"""
        SELECT *
        FROM (
          SELECT
            o.OBJECT_NAME AS TABLE_NAME,
            o.OBJECT_TYPE AS TABLE_TYPE,
            tc.COMMENTS AS COMMENTS,
            t.NUM_ROWS AS ESTIMATED_ROWS
          FROM ALL_OBJECTS o
          LEFT JOIN ALL_TAB_COMMENTS tc
            ON tc.OWNER = o.OWNER
           AND tc.TABLE_NAME = o.OBJECT_NAME
          LEFT JOIN ALL_TABLES t
            ON t.OWNER = o.OWNER
           AND t.TABLE_NAME = o.OBJECT_NAME
          WHERE o.OWNER = :schema_name
            AND o.OBJECT_TYPE IN ('TABLE', 'VIEW', 'MATERIALIZED VIEW')
            AND ({' OR '.join(clauses)})
          ORDER BY o.OBJECT_TYPE, o.OBJECT_NAME
        )
        WHERE ROWNUM <= :mcp_limit
    """
    rows = fetch_all(sql, params)
    return {"schema_name": schema, "keywords": cleaned_keywords, "limit": safe_limit, "tables": rows, "returned": len(rows)}


@mcp.tool()
def describe_table(table_name: str, schema_name: str | None = None) -> dict[str, Any]:
    """Describe columns, comments, and primary-key flags for a table."""
    schema = assert_identifier(schema_name or default_schema(), "schema_name")
    table = assert_identifier(table_name, "table_name")
    with connect() as connection:
        exists = table_exists(connection, schema, table)
        if not exists:
            return {"schema_name": schema, "table_name": table, "exists": False, "columns": []}
        columns = get_columns(connection, schema, table)
    return {"schema_name": schema, "table_name": table, "exists": True, "columns": columns}


@mcp.tool()
def sample_table(table_name: str, limit: int = 5, schema_name: str | None = None) -> dict[str, Any]:
    """Return a small read-only sample from a table."""
    schema = assert_identifier(schema_name or default_schema(), "schema_name")
    table = assert_identifier(table_name, "table_name")
    safe_limit = clamp_limit(limit, MAX_SAMPLE_LIMIT)
    sql = f"""
        SELECT *
        FROM (
          SELECT *
          FROM {quote_identifier(schema)}.{quote_identifier(table)}
        )
        WHERE ROWNUM <= :mcp_limit
    """
    with connect() as connection:
        if not table_exists(connection, schema, table):
            return {"schema_name": schema, "table_name": table, "exists": False, "rows": []}
        with connection.cursor() as cursor:
            cursor.execute(sql, {"mcp_limit": safe_limit})
            rows = rows_from_cursor(cursor)
    return {"schema_name": schema, "table_name": table, "limit": safe_limit, "rows": rows}


@mcp.tool()
def execute_select(query: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Execute a read-only SELECT/WITH query with enforced pagination."""
    sql = normalize_sql(query)
    safe_limit = clamp_limit(limit, MAX_SELECT_LIMIT)
    safe_offset = clamp_offset(offset)
    end_row = safe_offset + safe_limit
    wrapped = paginated_select_sql(sql)
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(wrapped, {"mcp_offset": safe_offset, "mcp_end_row": end_row})
            rows = rows_from_cursor(cursor)
    return {"limit": safe_limit, "offset": safe_offset, "rows": rows, "returned": len(rows)}


@mcp.tool()
def profile_tables(table_names: list[str], schema_name: str | None = None) -> dict[str, Any]:
    """Profile specified whitelist tables only: columns, sample rows, date ranges, enum samples."""
    if not table_names:
        return {"schema_name": schema_name or default_schema(), "profiles": []}

    schema = assert_identifier(schema_name or default_schema(), "schema_name")
    safe_tables = [assert_identifier(table, "table_name") for table in table_names[:50]]
    profiles: list[dict[str, Any]] = []

    with connect() as connection:
        for table in safe_tables:
            profile: dict[str, Any] = {"schema_name": schema, "table_name": table}
            if not table_exists(connection, schema, table):
                profile.update({"exists": False})
                profiles.append(profile)
                continue

            columns = get_columns(connection, schema, table)
            profile.update({"exists": True, "columns": columns})

            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT *
                    FROM (
                      SELECT *
                      FROM {quote_identifier(schema)}.{quote_identifier(table)}
                    )
                    WHERE ROWNUM <= :limit
                    """,
                    {"limit": MAX_PROFILE_SAMPLE},
                )
                profile["sample_rows"] = rows_from_cursor(cursor)

            date_profiles = []
            for column in columns:
                column_name = column["COLUMN_NAME"]
                if not DATE_COLUMN_RE.search(column_name):
                    continue
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            f"""
                            SELECT MIN({quote_identifier(column_name)}) AS MIN_VALUE,
                                   MAX({quote_identifier(column_name)}) AS MAX_VALUE
                            FROM {quote_identifier(schema)}.{quote_identifier(table)}
                            """
                        )
                        date_profiles.append({"column_name": column_name, "range": rows_from_cursor(cursor)})
                except Exception as exc:
                    date_profiles.append({"column_name": column_name, "error": f"{type(exc).__name__}: {exc}"})
            profile["date_profiles"] = date_profiles

            enum_profiles = []
            enum_columns = [col["COLUMN_NAME"] for col in columns if ENUM_COLUMN_RE.search(col["COLUMN_NAME"])][:5]
            for column_name in enum_columns:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            f"""
                            SELECT *
                            FROM (
                              SELECT DISTINCT {quote_identifier(column_name)} AS VALUE
                              FROM {quote_identifier(schema)}.{quote_identifier(table)}
                              WHERE {quote_identifier(column_name)} IS NOT NULL
                            )
                            WHERE ROWNUM <= :limit
                            """,
                            {"limit": MAX_ENUM_DISTINCT},
                        )
                        enum_profiles.append({"column_name": column_name, "values": rows_from_cursor(cursor)})
                except Exception as exc:
                    enum_profiles.append({"column_name": column_name, "error": f"{type(exc).__name__}: {exc}"})
            profile["enum_profiles"] = enum_profiles
            profiles.append(profile)

    return {"schema_name": schema, "profiles": profiles}


if __name__ == "__main__":
    mcp.run()
