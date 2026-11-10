"""Stage 2: scrub PII, then remove rows that can't support analysis, counting every removal."""

import re
import unicodedata
from collections import Counter
from collections.abc import Callable

import pandas as pd
from langdetect import DetectorFactory, LangDetectException, detect_langs

# langdetect is randomized by default. A fixed seed keeps re-runs identical.
DetectorFactory.seed = 0

# Very short reviews ("good app") say nothing a theme could be built from.
MIN_TEXT_CHARS = 20

OUTPUT_COLUMNS = [
    "review_id",
    "app_id",
    "rating",
    "text",
    "review_date",
    "app_version",
    "thumbs_up",
    "text_len",
]

URL_RE = re.compile(
    # Bare domains are limited to endings that rarely appear when reviewers skip the space
    # after a period. Endings like .app and .me turned "good.App works" into a fake link.
    r"\b(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|net|org|co\.uk)(?:/\S*)?\b",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
# The lookarounds stop this from matching inside longer numbers or app versions like 8.9.36.616.
PHONE_RE = re.compile(
    r"(?<![\w.])"
    r"(?:\+\d{1,3}(?:[\s.-]?\d{2,4}){2,5}"
    r"|(?:\d{1,3}[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-]?)\d{3}[\s.-]?\d{4})"
    r"(?!\w|\.\d)"
)
# Order matters: emails go first, or the URL rule would match the "example.com" inside them.
PII_PATTERNS = {
    "email": (EMAIL_RE, "[EMAIL]"),
    "url": (URL_RE, "[URL]"),
    "phone": (PHONE_RE, "[PHONE]"),
}


def scrub_pii(text: str) -> tuple[str, dict[str, int]]:
    """Replace URLs, emails, and phone numbers with placeholders. Returns the text and counts."""
    counts = {}
    for kind, (pattern, placeholder) in PII_PATTERNS.items():
        text, counts[kind] = pattern.subn(placeholder, text)
    return text, counts


def is_english(text: str) -> bool:
    """True if English is among the likely languages, not only the single top guess.

    The top guess is unreliable on short text: audited on real reviews, it labeled
    "Spotify is not working well." as Afrikaans.
    """
    try:
        return any(candidate.lang == "en" for candidate in detect_langs(text))
    except LangDetectException:  # Raised when the text has no letters to judge from.
        return False


def clean_reviews(
    df: pd.DataFrame, english_check: Callable[[str], bool] = is_english
) -> tuple[pd.DataFrame, dict]:
    """Apply every cleaning rule in order. Returns the cleaned rows and a removal report."""
    report: dict = {"rows_in": len(df), "removed": {}}

    def keep(frame: pd.DataFrame, mask: pd.Series, rule: str) -> pd.DataFrame:
        report["removed"][rule] = int((~mask).sum())
        return frame[mask]

    valid = (
        df["review_id"].notna()
        & df["review_date"].notna()
        & df["rating"].isin([1, 2, 3, 4, 5])
        & df["text"].notna()
    )
    df = keep(df, valid, "missing_or_invalid_fields")

    # Sorting first means "keep the first" always keeps the earliest copy, on every run.
    df = df.sort_values(["review_date", "review_id"]).copy()
    df = keep(df, ~df["review_id"].duplicated(), "duplicate_review_id")

    # Scrub before the length check, so a review that was only a link counts as too short.
    pii_replaced = Counter(dict.fromkeys(PII_PATTERNS, 0))
    scrubbed_texts = []
    for text in df["text"]:
        # NFKC turns stylized letters (𝑺𝒐𝒏𝒈) into plain ones, so every later step can read them.
        scrubbed, counts = scrub_pii(unicodedata.normalize("NFKC", text))
        scrubbed_texts.append(scrubbed)
        pii_replaced.update(counts)
    report["pii_replaced"] = dict(pii_replaced)
    df["text"] = pd.Series(scrubbed_texts, index=df.index, dtype="string")
    df["text"] = df["text"].str.replace(r"\s+", " ", regex=True).str.strip()

    df = keep(df, df["text"].str.len() >= MIN_TEXT_CHARS, "too_short")
    df = keep(df, ~df["text"].str.casefold().duplicated(), "duplicate_text")

    # Last because it's by far the slowest rule, so it should see as few rows as possible.
    df = keep(df, df["text"].map(english_check).astype(bool), "not_english")

    df = df.copy()
    df["rating"] = df["rating"].astype(int)
    df["app_version"] = df["app_version"].str.strip().replace("", pd.NA)
    df["text_len"] = df["text"].str.len().astype(int)
    report["rows_out"] = len(df)
    return df[OUTPUT_COLUMNS].reset_index(drop=True), report
