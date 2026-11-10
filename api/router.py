"""The Analyst loop: the model picks tools, code runs them, and events stream out."""

import json
import os
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from google import genai
from google.genai import errors, types

from api.prompts import FINAL_INSTRUCTION, SYSTEM_PROMPT
from api.schemas import FinalAnswer
from api.sql_guard import UnsafeQueryError
from api.tools.analytics import get_theme_trends, run_sql
from api.tools.search import search_reviews

MAX_TOOL_ROUNDS = 5
LLM_TIMEOUT_MS = 45_000
MAX_LLM_ATTEMPTS = 4
RETRYABLE_CODES = {429, 500, 503}
BRACKET_RE = re.compile(r"\[([^\[\]]+)\]")
ID_LIKE_RE = re.compile(r"[\w-]{8,64}")

_STRING = {"type": "STRING"}
TOOL_DECLARATIONS = [
    {
        "name": "run_sql",
        "description": "Run one read-only BigQuery SELECT on the analytics tables.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"query": _STRING},
            "required": ["query"],
        },
    },
    {
        "name": "search_reviews",
        "description": "Find reviews similar in meaning to a query, with optional filters.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": _STRING,
                "version": _STRING,
                "rating_max": {"type": "INTEGER"},
                "date_from": {"type": "STRING", "description": "YYYY-MM-DD"},
                "date_to": {"type": "STRING", "description": "YYYY-MM-DD, exclusive"},
                "k": {"type": "INTEGER"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_theme_trends",
        "description": "Compare theme shares between two versions. Omit versions for latest two.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"version_a": _STRING, "version_b": _STRING},
        },
    },
]


class QuotaExceededError(RuntimeError):
    """The free-tier Gemini quota ran out, even after retries."""


@dataclass
class Step:
    calls: list[tuple[str, dict]]
    message: object = None
    tokens: int = 0


@dataclass
class Final:
    answer: FinalAnswer
    tokens: int = 0


class GeminiLLM:
    def __init__(self, app_id: str):
        self.client = genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(timeout=LLM_TIMEOUT_MS),
        )
        self.model = os.environ["GEMINI_MODEL"]
        self.system = SYSTEM_PROMPT.format(app_id=app_id)

    def _generate(self, contents: list, config: types.GenerateContentConfig):
        for attempt in range(1, MAX_LLM_ATTEMPTS + 1):
            try:
                return self.client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
            except errors.APIError as error:
                if error.code not in RETRYABLE_CODES:
                    raise
                if attempt == MAX_LLM_ATTEMPTS:
                    raise QuotaExceededError from error
                time.sleep(2**attempt)
        raise RuntimeError("unreachable")

    @staticmethod
    def _tokens(response) -> int:
        usage = response.usage_metadata
        return (usage.total_token_count or 0) if usage else 0

    def start(self, question: str) -> list:
        return [types.Content(role="user", parts=[types.Part.from_text(text=question)])]

    def step(self, contents: list) -> Step:
        config = types.GenerateContentConfig(
            system_instruction=self.system,
            temperature=0,
            tools=[types.Tool(function_declarations=TOOL_DECLARATIONS)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = self._generate(contents, config)
        calls = [(call.name, dict(call.args or {})) for call in response.function_calls or []]
        message = response.candidates[0].content if response.candidates else None
        return Step(calls=calls, message=message, tokens=self._tokens(response))

    def tool_message(self, results: list[tuple[str, dict]]):
        parts = [
            types.Part.from_function_response(name=name, response={"result": result})
            for name, result in results
        ]
        return types.Content(role="user", parts=parts)

    def final(self, contents: list) -> Final:
        config = types.GenerateContentConfig(
            system_instruction=self.system,
            temperature=0,
            response_mime_type="application/json",
            response_schema=FinalAnswer,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        instruction = types.Content(
            role="user", parts=[types.Part.from_text(text=FINAL_INSTRUCTION)]
        )
        response = self._generate([*contents, instruction], config)
        return Final(
            answer=FinalAnswer.model_validate_json(response.text), tokens=self._tokens(response)
        )


@dataclass
class Trace:
    tools: list[str] = field(default_factory=list)
    tokens: int = 0


def link_citations(answer: str, retrieved: dict[str, dict]) -> tuple[str, list[dict]]:
    """Turn [review_id] into [1], and strip IDs the search never returned."""
    numbers: dict[str, int] = {}

    def replace(match: re.Match) -> str:
        # The model sometimes puts several IDs in one bracket: [id1, id2].
        parts = [part.strip() for part in match.group(1).split(",")]
        if not all(ID_LIKE_RE.fullmatch(part) for part in parts):
            return match.group(0)  # Ordinary bracketed text, like [URL], stays as it is.
        known = [part for part in parts if part in retrieved]
        return "".join(f"[{numbers.setdefault(part, len(numbers) + 1)}]" for part in known)

    linked = re.sub(r"\s+([.,;:!?])", r"\1", BRACKET_RE.sub(replace, answer)).strip()
    citations = [
        {"number": number, **retrieved[review_id]} for review_id, number in numbers.items()
    ]
    return linked, citations


def _summarize(name: str, result: dict) -> dict:
    """What the UI's trace shows: the exact SQL or the reviews that were retrieved."""
    if "error" in result:
        return {"tool": name, "error": result["error"]}
    if name == "run_sql":
        return {"tool": name, "sql": result["sql"], "row_count": result["row_count"]}
    if name == "search_reviews":
        return {"tool": name, "review_count": len(result["reviews"]), "reviews": result["reviews"]}
    return {"tool": name, **{k: result[k] for k in ("version_a", "version_b")}}


def default_tools(app_id: str) -> dict[str, Callable[..., dict]]:
    """The model never chooses app_id. Code fixes it, so a question can't reach other apps."""
    return {
        "run_sql": run_sql,
        "search_reviews": lambda **args: search_reviews(app_id=app_id, **args),
        "get_theme_trends": lambda **args: get_theme_trends(app_id=app_id, **args),
    }


def call_tool(tools: dict[str, Callable[..., dict]], name: str, args: dict) -> dict:
    """Failures go back to the model as data, so it can fix its query or say it can't answer."""
    if name not in tools:
        return {"error": f"Unknown tool: {name}"}
    try:
        return tools[name](**args)
    except UnsafeQueryError as error:
        return {"error": f"Query rejected: {error}"}
    except TypeError:
        return {"error": f"Invalid arguments for {name}"}
    except Exception as error:  # A failed tool shouldn't end the whole answer.
        return {"error": f"{name} failed: {type(error).__name__}"}


def run_ask(question: str, llm, tools: dict, trace: Trace) -> Iterator[tuple[str, dict]]:
    """Yield (event name, data) pairs as the answer is built."""
    contents = llm.start(question)
    retrieved: dict[str, dict] = {}

    for _ in range(MAX_TOOL_ROUNDS):
        step = llm.step(contents)
        trace.tokens += step.tokens
        if not step.calls:
            break
        contents.append(step.message)
        results = []
        for name, args in step.calls:
            trace.tools.append(name)
            yield "tool_call", {"tool": name, "args": args}
            result = call_tool(tools, name, args)
            for review in result.get("reviews", []):
                retrieved[review["review_id"]] = review
            yield "tool_result", _summarize(name, result)
            results.append((name, result))
        contents.append(llm.tool_message(results))

    final = llm.final(contents)
    trace.tokens += final.tokens
    text, citations = link_citations(final.answer.answer, retrieved)
    if final.answer.chart:
        yield "chart", final.answer.chart.model_dump()
    for citation in citations:
        yield "citation", citation
    for chunk in re.findall(r"\S+\s*", text):
        yield "answer_delta", {"text": chunk}
    yield (
        "done",
        {
            "tools": trace.tools,
            "tokens": trace.tokens,
            "insufficient_data": final.answer.insufficient_data,
        },
    )


def to_sse(name: str, data: dict) -> dict:
    return {"event": name, "data": json.dumps(data, ensure_ascii=False)}
