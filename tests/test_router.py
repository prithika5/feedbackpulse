from fastapi.testclient import TestClient

import api.main as main
from api.cache import AnswerCache, RateLimiter
from api.router import Final, Step, Trace, call_tool, link_citations, run_ask
from api.schemas import FinalAnswer
from api.sql_guard import UnsafeQueryError

REVIEW_ID = "437314fe-1b1d-4352-abea-12fec30fce58"
REVIEW = {"review_id": REVIEW_ID, "rating": 1, "date": "2024-01-01", "snippet": "too many ads"}


class FakeLLM:
    """Asks for one search, then answers with a citation."""

    def __init__(self, answer: str = f"Users dislike ads [{REVIEW_ID}]."):
        self.answer = answer
        self.steps = 0

    def start(self, question):
        return [question]

    def step(self, contents):
        self.steps += 1
        if self.steps == 1:
            return Step(calls=[("search_reviews", {"query": "ads"})], message="call", tokens=10)
        return Step(calls=[], tokens=5)

    def tool_message(self, results):
        return results

    def final(self, contents):
        return Final(FinalAnswer(answer=self.answer, insufficient_data=False), tokens=20)


def fake_tools():
    return {"search_reviews": lambda **_: {"reviews": [REVIEW]}}


def test_events_arrive_in_order_with_citations():
    events = list(run_ask("why?", FakeLLM(), fake_tools(), Trace()))
    names = [name for name, _ in events]
    assert names[:2] == ["tool_call", "tool_result"]
    assert "citation" in names
    assert names[-1] == "done"
    text = "".join(data["text"] for name, data in events if name == "answer_delta")
    assert text == "Users dislike ads [1]."
    assert events[-1][1]["tokens"] == 35
    assert events[-1][1]["tools"] == ["search_reviews"]


def test_invented_citations_are_removed():
    llm = FakeLLM("Users dislike ads [00000000-aaaa-bbbb-cccc-000000000000].")
    events = list(run_ask("why?", llm, fake_tools(), Trace()))
    assert not [name for name, _ in events if name == "citation"]
    assert "".join(d["text"] for n, d in events if n == "answer_delta") == "Users dislike ads."


def test_link_citations_numbers_repeats_consistently():
    text, citations = link_citations(f"A [{REVIEW_ID}]. B [{REVIEW_ID}].", {REVIEW_ID: REVIEW})
    assert text == "A [1]. B [1]."
    assert len(citations) == 1


def test_several_ids_in_one_bracket_become_separate_citations():
    other_id = "932e85a6-2d43-4989-91b9-6697334d5383"
    fake_id = "00000000-aaaa-bbbb-cccc-000000000000"
    retrieved = {REVIEW_ID: REVIEW, other_id: {**REVIEW, "review_id": other_id}}
    text, citations = link_citations(f"Ads [{REVIEW_ID}, {other_id}, {fake_id}].", retrieved)
    assert text == "Ads [1][2]."
    assert [citation["review_id"] for citation in citations] == [REVIEW_ID, other_id]


def test_ordinary_bracketed_text_is_left_alone():
    assert link_citations("A link [URL] here.", {})[0] == "A link [URL] here."


def test_rejected_sql_goes_back_to_the_model_as_data():
    def reject(**_):
        raise UnsafeQueryError("Only SELECT queries are allowed")

    assert "Query rejected" in call_tool({"run_sql": reject}, "run_sql", {"query": "x"})["error"]


def test_unknown_tool_and_bad_arguments_return_errors():
    assert "Unknown tool" in call_tool({}, "drop_everything", {})["error"]

    def needs_query(query):
        return {"query": query}

    assert "Invalid arguments" in call_tool({"t": needs_query}, "t", {"wrong": 1})["error"]


def test_rate_limiter_blocks_then_recovers():
    now = [0.0]
    limiter = RateLimiter(max_requests=2, window_seconds=60, clock=lambda: now[0])
    assert limiter.allow("ip") and limiter.allow("ip")
    assert not limiter.allow("ip")
    assert limiter.allow("other-ip")
    now[0] = 61
    assert limiter.allow("ip")


def test_cache_ignores_case_and_spacing():
    cache = AnswerCache()
    cache.put("spotify", "Why  did it DROP?", ["event"])
    assert cache.get("spotify", "why did it drop?") == ["event"]
    assert cache.get("other", "why did it drop?") is None


def make_client(monkeypatch):
    monkeypatch.setattr(main, "cache", AnswerCache())
    monkeypatch.setattr(main, "limiter", RateLimiter(100, 60))
    monkeypatch.setattr(main, "GeminiLLM", lambda app_id: FakeLLM())
    monkeypatch.setattr(main, "default_tools", lambda app_id: fake_tools())
    return TestClient(main.app)


def test_health(monkeypatch):
    assert make_client(monkeypatch).get("/health").json() == {"status": "ok"}


def test_ask_streams_events(monkeypatch):
    response = make_client(monkeypatch).post("/ask", json={"question": "why did it drop?"})
    assert response.status_code == 200
    assert "event: tool_call" in response.text
    assert "event: done" in response.text


def test_ask_rejects_unknown_app_and_bad_input(monkeypatch):
    client = make_client(monkeypatch)
    assert client.post("/ask", json={"question": "hello", "app_id": "x"}).status_code == 404
    assert client.post("/ask", json={"question": ""}).status_code == 422


def test_ask_is_rate_limited(monkeypatch):
    client = make_client(monkeypatch)
    monkeypatch.setattr(main, "limiter", RateLimiter(1, 60))
    assert client.post("/ask", json={"question": "first question"}).status_code == 200
    assert client.post("/ask", json={"question": "second question"}).status_code == 429
