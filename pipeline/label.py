"""Stage 6: ask Gemini to name each cluster. Answers are validated and cached on disk."""

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Literal

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field, field_validator

CACHE_DIR = Path(".llm_cache")
TIMEOUT_MS = 60_000
MAX_ATTEMPTS = 12  # Generous because this is a batch job and 503 spikes can last minutes.
MAX_BACKOFF_SECONDS = 30
RETRYABLE_CODES = {429, 500, 503}
REPRESENTATIVE_REVIEWS = 20
MAX_REVIEW_CHARS = 400


class ThemeLabel(BaseModel):
    name: str
    description: str
    sentiment: Literal["neg", "neutral", "pos"]
    keywords: list[str] = Field(min_length=1, max_length=10)

    @field_validator("name")
    @classmethod
    def name_is_two_to_four_words(cls, value: str) -> str:
        if not 2 <= len(value.split()) <= 4:
            raise ValueError("name must be 2 to 4 words")
        return value.strip()


def build_prompt(reviews: list[str]) -> str:
    quoted = "\n".join(f"- {review[:MAX_REVIEW_CHARS]}" for review in reviews)
    return (
        "These app-store reviews were grouped together because they are about the same topic.\n"
        "Describe the topic they share. Use only what the reviews say.\n"
        "name: 2 to 4 words, specific enough to tell this theme apart from others about the "
        'same app. Prefer "Too Many Ads" over "User Complaints".\n'
        "description: one sentence.\n"
        'sentiment: "neg", "neutral", or "pos", for how these reviewers feel overall.\n'
        "keywords: 3 to 8 lowercase words or short phrases.\n\n"
        f"Reviews:\n{quoted}"
    )


def label_cluster(reviews: list[str], cache_dir: Path = CACHE_DIR) -> ThemeLabel:
    """Return a validated label, using the cache when the same prompt has been answered."""
    model = os.environ["GEMINI_MODEL"]
    prompt = build_prompt(reviews)
    cache_key = hashlib.sha256(f"{model}\n{prompt}".encode()).hexdigest()
    cache_file = cache_dir / f"{cache_key}.json"
    if cache_file.exists():
        return ThemeLabel.model_validate_json(cache_file.read_text())

    label = _request_label(model, prompt)
    cache_dir.mkdir(exist_ok=True)
    cache_file.write_text(json.dumps(label.model_dump()))
    return label


def _request_label(model: str, prompt: str) -> ThemeLabel:
    client = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"], http_options=types.HttpOptions(timeout=TIMEOUT_MS)
    )
    config = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=ThemeLabel, temperature=0
    )
    contents = prompt
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.models.generate_content(model=model, contents=contents, config=config)
            return ThemeLabel.model_validate_json(response.text)
        except errors.APIError as error:
            if error.code not in RETRYABLE_CODES or attempt == MAX_ATTEMPTS:
                raise
        except ValueError as error:  # The model broke a rule, such as a 5-word name.
            if attempt == MAX_ATTEMPTS:
                raise
            # At temperature 0 the same prompt returns the same answer, so say what was wrong.
            contents = f"{prompt}\n\nYour previous answer was rejected: {error}\nFix that."
        # Back off so free-tier rate limits have time to reset.
        time.sleep(min(2**attempt, MAX_BACKOFF_SECONDS))
    raise RuntimeError("unreachable")
