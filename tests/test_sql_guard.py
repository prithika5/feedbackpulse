import pytest

from api.sql_guard import MAX_ROWS, UnsafeQueryError, guard_sql

PROJECT = "demo-project"
DATASET = "feedbackpulse"


def guard(query: str) -> str:
    return guard_sql(query, dataset=DATASET, project=PROJECT)


@pytest.mark.parametrize(
    "query",
    [
        "DROP TABLE reviews",
        "DELETE FROM reviews WHERE TRUE",
        "UPDATE reviews SET rating = 5 WHERE TRUE",
        "INSERT INTO reviews (rating) VALUES (5)",
        "CREATE TABLE x AS SELECT 1",
        "TRUNCATE TABLE reviews",
        "SELECT 1; DROP TABLE reviews",
        "SELECT 1; SELECT 2",
        "SELECT * FROM secrets",
        "SELECT * FROM other_dataset.reviews",
        "SELECT * FROM `other-project.feedbackpulse.reviews`",
        "SELECT * FROM feedbackpulse.INFORMATION_SCHEMA.TABLES",
        "SELECT * FROM EXTERNAL_QUERY('conn', 'select 1')",
        "WITH r AS (SELECT * FROM secrets) SELECT * FROM r",
        "SELECT * FROM reviews WHERE review_id IN (SELECT id FROM secrets)",
        "SELECT * FROM reviews UNION ALL SELECT * FROM secrets",
        "this is not sql",
        "",
    ],
)
def test_unsafe_queries_are_rejected(query):
    with pytest.raises(UnsafeQueryError):
        guard(query)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT AVG(rating) FROM reviews",
        "SELECT * FROM feedbackpulse.daily_metrics",
        f"SELECT * FROM `{PROJECT}.feedbackpulse.reviews`",
        "WITH r AS (SELECT rating FROM reviews) SELECT AVG(rating) FROM r",
        "SELECT t.name FROM themes AS t JOIN review_themes AS rt USING (theme_id)",
        "SELECT rating FROM reviews UNION ALL SELECT rating FROM reviews",
    ],
)
def test_safe_queries_are_allowed_and_capped(query):
    assert f"LIMIT {MAX_ROWS}" in guard(query)


def test_small_limit_is_kept():
    assert guard("SELECT rating FROM reviews LIMIT 5").endswith("LIMIT 5")


def test_large_limit_is_reduced():
    result = guard("SELECT rating FROM reviews LIMIT 999999")
    assert f"LIMIT {MAX_ROWS}" in result
    assert "999999" not in result
