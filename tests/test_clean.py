import pandas as pd
import pytest

from pipeline.clean import MIN_TEXT_CHARS, clean_reviews, is_english, scrub_pii
from pipeline.ingest import AppSource, ingest

LONG_TEXT = "The app keeps crashing whenever I open a playlist"


def always_english(_text: str) -> bool:
    return True


def make_reviews(**overrides) -> pd.DataFrame:
    row = {
        "review_id": "r1",
        "app_id": "spotify",
        "rating": 2,
        "text": LONG_TEXT,
        "review_date": pd.Timestamp("2024-01-01"),
        "app_version": "8.9.1",
        "thumbs_up": 0,
    }
    return pd.DataFrame([{**row, **overrides}])


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("mail me at jane.doe+x@example.co.uk please", "mail me at [EMAIL] please"),
        ("see https://example.org/a?b=1 now", "see [URL] now"),
        ("see www.example.org now", "see [URL] now"),
        ("go to mysite.com/profile now", "go to [URL] now"),
        ("call 555-123-4567.", "call [PHONE]."),
        ("call (555) 123-4567 today", "call [PHONE] today"),
        ("call 5551234567 today", "call [PHONE] today"),
        ("call +44 20 7946 0958 today", "call [PHONE] today"),
    ],
)
def test_scrub_pii_replaces_personal_details(text, expected):
    assert scrub_pii(text)[0] == expected


@pytest.mark.parametrize(
    "text",
    [
        "broken since version 8.9.36.616 came out",
        "started on 2023-12-15 and is still bad",
        "I have 1200 songs and paid 9.99 for 12 months",
        "rated this 5 stars in 2019",
        "It was good.App works fine now",
        "nothing else to say.Me and my friends left",
    ],
)
def test_scrub_pii_leaves_ordinary_numbers_alone(text):
    assert scrub_pii(text)[0] == text


def test_scrub_pii_counts_each_kind():
    _, counts = scrub_pii("a@b.com and c@d.com at https://x.org")
    assert counts == {"url": 1, "email": 2, "phone": 0}


def test_too_short_is_removed():
    cleaned, report = clean_reviews(make_reviews(text="x" * (MIN_TEXT_CHARS - 1)), always_english)
    assert cleaned.empty
    assert report["removed"]["too_short"] == 1


def test_review_that_is_only_a_link_counts_as_too_short():
    text = "https://example.org/a-very-long-link-that-passes-the-length-rule"
    _, report = clean_reviews(make_reviews(text=text), always_english)
    assert report["removed"]["too_short"] == 1


def test_duplicate_text_keeps_the_earliest_and_ignores_case():
    df = pd.concat(
        [
            make_reviews(review_id="late", review_date=pd.Timestamp("2024-02-01")),
            make_reviews(
                review_id="early", review_date=pd.Timestamp("2024-01-01"), text=LONG_TEXT.upper()
            ),
        ]
    )
    cleaned, report = clean_reviews(df, always_english)
    assert cleaned["review_id"].tolist() == ["early"]
    assert report["removed"]["duplicate_text"] == 1


def test_duplicate_review_id_is_removed():
    df = pd.concat([make_reviews(), make_reviews(text=LONG_TEXT + " again and again")])
    _, report = clean_reviews(df, always_english)
    assert report["removed"]["duplicate_review_id"] == 1


@pytest.mark.parametrize(
    "bad",
    [{"rating": 0}, {"rating": 6}, {"text": pd.NA}, {"review_date": pd.NaT}, {"review_id": pd.NA}],
)
def test_invalid_rows_are_removed(bad):
    cleaned, report = clean_reviews(make_reviews(**bad), always_english)
    assert cleaned.empty
    assert report["removed"]["missing_or_invalid_fields"] == 1


def test_not_english_is_removed():
    cleaned, report = clean_reviews(make_reviews(), lambda _text: False)
    assert cleaned.empty
    assert report["removed"]["not_english"] == 1


def test_is_english_uses_real_detection():
    assert is_english("This app keeps crashing every time I try to play my favorite songs")
    assert not is_english("Esta aplicación se cierra cada vez que intento escuchar mis canciones")
    assert not is_english("12345 67890")


def test_report_adds_up_and_text_is_normalized():
    df = pd.concat(
        [
            make_reviews(text=f"  {LONG_TEXT}\n\nreally   bad "),
            make_reviews(review_id="r2", text="short"),
        ]
    )
    cleaned, report = clean_reviews(df, always_english)
    assert cleaned["text"].tolist() == [f"{LONG_TEXT} really bad"]
    assert cleaned["text_len"].tolist() == [len(cleaned["text"][0])]
    assert report["rows_in"] - sum(report["removed"].values()) == report["rows_out"] == len(cleaned)


def test_stylized_unicode_letters_become_plain_text():
    styled = "𝑻𝒉𝒆 𝒏𝒆𝒘 𝒖𝒑𝒅𝒂𝒕𝒆𝒅 𝒗𝒆𝒓𝒔𝒊𝒐𝒏 𝒊𝒔 𝒕𝒉𝒆 𝒘𝒐𝒓𝒔𝒕"
    cleaned, _ = clean_reviews(make_reviews(text=styled), always_english)
    assert cleaned["text"].tolist() == ["The new updated version is the worst"]


def test_is_english_keeps_short_english_the_top_guess_gets_wrong():
    assert is_english("Spotify is not working well.")


def test_cleaning_twice_gives_the_same_result():
    once, _ = clean_reviews(make_reviews(text=f"{LONG_TEXT} a@b.com"), always_english)
    twice, _ = clean_reviews(once, always_english)
    pd.testing.assert_frame_equal(once, twice)


def test_ingest_renames_columns_and_never_loads_usernames(tmp_path):
    path = tmp_path / "raw.csv"
    path.write_text(
        "reviewId,userName,content,score,thumbsUpCount,reviewCreatedVersion,at,appVersion\n"
        "r1,Secret Person,Great app,5,3,8.10,2024-01-01 10:00:00,8.10\n"
    )
    df = ingest(AppSource(app_id="demo", name="Demo", category="Test", path=path))
    assert "userName" not in df.columns
    assert "Secret Person" not in df.to_string()
    row = df.iloc[0]
    assert (row["review_id"], row["app_id"], row["rating"], row["thumbs_up"]) == (
        "r1",
        "demo",
        5,
        3,
    )
    assert row["app_version"] == "8.10"  # Must stay a string, not the number 8.1.
