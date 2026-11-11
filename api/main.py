"""FastAPI app: a health check and the streaming /ask endpoint."""

import json
import logging
import sys
import time
from collections.abc import Iterator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import iterate_in_threadpool

from api.cache import AnswerCache, RateLimiter
from api.router import GeminiLLM, QuotaExceededError, Trace, default_tools, run_ask, to_sse
from api.schemas import AskRequest

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
log = logging.getLogger("api")

ALLOWED_APPS = {"spotify"}
app = FastAPI(title="FeedbackPulse API")
cache = AnswerCache()
limiter = RateLimiter(max_requests=20, window_seconds=60)
# The API is public, so this caps what any mix of callers can spend from the Gemini quota.
daily_limiter = RateLimiter(max_requests=200, window_seconds=86_400)


def client_ip(request: Request) -> str:
    # Cloud Run appends the real caller last. Earlier entries can be forged by the client.
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[-1].strip() or (request.client.host if request.client else "?")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def answer_events(question: str, app_id: str) -> Iterator[dict]:
    cached = cache.get(app_id, question)
    if cached is not None:
        log.info(json.dumps({"event": "ask", "cached": True}))
        yield from cached
        return

    started = time.perf_counter()
    trace = Trace()
    events = []
    status = "ok"
    try:
        for name, data in run_ask(question, GeminiLLM(app_id), default_tools(app_id), trace):
            event = to_sse(name, data)
            events.append(event)
            yield event
        cache.put(app_id, question, events)
    except QuotaExceededError:
        status = "quota"
        message = "The free-tier AI quota is used up for now. Please try again in a minute."
        yield to_sse("error", {"message": message})
    except Exception as error:
        status = type(error).__name__
        yield to_sse("error", {"message": "Something went wrong answering that question."})
    finally:
        log.info(
            json.dumps(
                {
                    "event": "ask",
                    "cached": False,
                    "status": status,
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                    "tools": trace.tools,
                    "tokens": trace.tokens,
                }
            )
        )


@app.post("/ask")
async def ask(body: AskRequest, request: Request) -> EventSourceResponse:
    if body.app_id not in ALLOWED_APPS:
        raise HTTPException(status_code=404, detail="Unknown app")
    if not limiter.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many questions. Please wait a minute.")
    if not daily_limiter.allow("all"):
        raise HTTPException(status_code=429, detail="The demo's daily limit has been reached.")
    return EventSourceResponse(iterate_in_threadpool(answer_events(body.question, body.app_id)))
