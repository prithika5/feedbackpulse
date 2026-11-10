import datetime as dt

import pandas as pd

from pipeline.load import build_tables
from pipeline.releases import MIN_RELEASE_REVIEWS, derive_releases


def make_reviews(rows: list[tuple[str, str | None, str]], app_id: str = "spotify") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "review_id": f"{app_id}-{index}",
                "app_id": app_id,
                "app_version": version,
                "review_date": pd.Timestamp(date),
            }
            for index, (_, version, date) in enumerate(rows)
        ]
    )


def test_first_seen_date_is_the_earliest_review_of_each_version():
    reviews = make_reviews(
        [
            ("a", "1.0", "2024-03-05 10:00"),
            ("b", "1.0", "2024-03-01 23:59"),
            ("c", "2.0", "2024-04-01"),
        ]
    )
    releases = derive_releases(reviews)
    assert releases["version"].tolist() == ["1.0", "2.0"]
    assert releases["first_seen_date"].tolist() == [dt.date(2024, 3, 1), dt.date(2024, 4, 1)]
    assert releases["review_count"].tolist() == [2, 1]


def test_reviews_without_a_version_are_not_a_release():
    releases = derive_releases(
        make_reviews([("a", None, "2024-03-05"), ("b", "1.0", "2024-03-06")])
    )
    assert releases["version"].tolist() == ["1.0"]


def test_low_volume_flag_uses_the_threshold():
    enough = [("x", "1.0", "2024-01-01")] * MIN_RELEASE_REVIEWS
    too_few = [("x", "2.0", "2024-02-01")] * (MIN_RELEASE_REVIEWS - 1)
    releases = derive_releases(make_reviews(enough + too_few))
    assert releases["low_volume"].tolist() == [False, True]


def test_same_version_in_two_apps_stays_separate():
    first = make_reviews([("a", "1.0", "2024-01-01")], app_id="spotify")
    second = make_reviews([("a", "1.0", "2024-02-01")], app_id="spotify")
    second["app_id"] = "other"
    releases = derive_releases(pd.concat([first, second]))
    assert sorted(releases["app_id"]) == ["other", "spotify"]


def test_build_tables_counts_reviews_per_app():
    reviews = make_reviews([("a", "1.0", "2024-01-01"), ("b", "1.1", "2024-02-01")])
    tables = build_tables({"spotify": reviews})
    assert tables["apps"].to_dict("records") == [
        {"app_id": "spotify", "name": "Spotify", "category": "Music & Audio", "review_count": 2}
    ]
    assert len(tables["reviews"]) == 2
    assert len(tables["releases"]) == 2
