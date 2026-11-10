"""Check model-written SQL before it reaches BigQuery. Parsing it is safer than keyword matching."""

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

ALLOWED_TABLES = {
    "apps",
    "reviews",
    "releases",
    "themes",
    "review_themes",
    "daily_metrics",
    "theme_daily",
}
MAX_ROWS = 1000
FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Merge,
    exp.TruncateTable,
    exp.Command,
    exp.Set,
)


class UnsafeQueryError(ValueError):
    """The query broke a rule. The message goes back to the model so it can correct itself."""


def guard_sql(query: str, dataset: str, project: str) -> str:
    """Return a safe, LIMIT-capped version of the query, or raise UnsafeQueryError."""
    try:
        statements = [s for s in sqlglot.parse(query, read="bigquery") if s is not None]
    except SqlglotError as error:
        raise UnsafeQueryError("Query could not be parsed as BigQuery SQL") from error

    if len(statements) != 1:
        raise UnsafeQueryError("Only a single statement is allowed")
    statement = statements[0]
    if not isinstance(statement, exp.Select | exp.SetOperation):
        raise UnsafeQueryError("Only SELECT queries are allowed")
    if any(statement.find(node) for node in FORBIDDEN_NODES):
        raise UnsafeQueryError("Only read-only SELECT queries are allowed")

    cte_names = {cte.alias.lower() for cte in statement.find_all(exp.CTE)}
    for table in statement.find_all(exp.Table):
        _check_table(table, cte_names, dataset, project)
    return _cap_rows(statement).sql(dialect="bigquery")


def _check_table(table: exp.Table, cte_names: set[str], dataset: str, project: str) -> None:
    # Anything other than a plain name is a table function, such as EXTERNAL_QUERY(...).
    if not isinstance(table.this, exp.Identifier):
        raise UnsafeQueryError("Table functions are not allowed")
    name, db, catalog = table.name.lower(), table.db, table.catalog
    if not db and not catalog and name in cte_names:
        return
    if name not in ALLOWED_TABLES:
        raise UnsafeQueryError(f"Table not allowed: {table.name}")
    if db and db != dataset:
        raise UnsafeQueryError(f"Dataset not allowed: {db}")
    if catalog and catalog != project:
        raise UnsafeQueryError(f"Project not allowed: {catalog}")


def _cap_rows(statement: exp.Expression) -> exp.Expression:
    limit = statement.args.get("limit")
    if limit is not None:
        value = limit.expression
        if isinstance(value, exp.Literal) and value.is_int and int(value.this) <= MAX_ROWS:
            return statement
    return statement.limit(MAX_ROWS, copy=True)
