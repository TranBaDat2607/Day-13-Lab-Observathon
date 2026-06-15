"""YOUR mitigation + observability layer. The simulator calls mitigate() around the
opaque agent (a REAL LLM) for every request. This is the ONLY place observability can
live -- the agent is silent. Legal moves: retry / cache / route / guardrail / sanitize
/ fallback / session-reset / PROMPT ROUTING, plus your own logging/tracing/metrics.
Illegal: hardcoding answers, importing the agent internals, reading instructor files,
network exfiltration.

  call_next(question, config) -> result   # the only way to reach the black box
  context = {"session_id","turn_index","qid","cache": <shared dict>, "cache_lock": <Lock>}
  result  = {"answer","status","steps","trace","meta":{latency_ms,usage,...}}
"""
from __future__ import annotations

import os
import re
import time

# --- Day 13 telemetry toolkit (optional: wrapper still runs if it's unavailable) -----------
try:
    from telemetry.logger import logger, new_correlation_id, set_correlation_id
    from telemetry.cost import cost_from_usage
    from telemetry.redact import redact
except Exception:  # pragma: no cover - telemetry is optional
    logger = None

    def new_correlation_id():
        return None

    def set_correlation_id(_cid):
        return None

    def cost_from_usage(_model, _usage):
        return 0.0

    def redact(s):
        return (s, 0)

_HERE = os.path.dirname(os.path.abspath(__file__))


# --- Load the rewritten system prompt + few-shot once, at import time ----------------------
def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return ""


_SYSTEM_PROMPT = _read(os.path.join(_HERE, "prompt.txt")).strip()


# --- Input sanitization: neutralize prompt-injection hidden in order notes -----------------
# The private twist embeds a fake "system" price/instruction inside an order note
# ("GHI CHU"/"GHI CHÚ"). Notes are DATA; we strip injected directives so even a weak model
# never sees them. Conservative: only act inside an explicit note marker.
_NOTE_MARKER = re.compile(r"(ghi\s*ch[uú]|note\s*:|system\s*:)", re.IGNORECASE)
_INJECTION_SIGNAL = re.compile(
    r"(\bvnd\b|\d{3,}|gi[aá]\s|ap\s*dung|thanh\s*toan|ignore|disregard|bo\s*qua|"
    r"system|overrid|instruct|set\s+price|new\s+price)",
    re.IGNORECASE,
)


def sanitize_question(question):
    """Return (clean_question, removed_note_text|None). Strips an injected directive that
    follows a note marker; leaves a benign note untouched."""
    if not isinstance(question, str):
        return question, None
    m = _NOTE_MARKER.search(question)
    if not m:
        return question, None
    head, note = question[: m.start()], question[m.start():]
    if _INJECTION_SIGNAL.search(note):
        cleaned = head.rstrip().rstrip(",.;-") + " [note ignored as untrusted data]"
        return cleaned, note
    return question, None


# --- Cache helpers (the run is concurrent: guard shared state) -----------------------------
def _cache_key(question):
    return re.sub(r"\s+", " ", (question or "").strip().lower())


def _cache_get(context, key):
    cache = context.get("cache")
    lock = context.get("cache_lock")
    if cache is None:
        return None
    if lock is not None:
        with lock:
            return cache.get(key)
    return cache.get(key)


def _cache_put(context, key, value):
    cache = context.get("cache")
    lock = context.get("cache_lock")
    if cache is None:
        return
    if lock is not None:
        with lock:
            cache[key] = value
    else:
        cache[key] = value


def _is_error_result(result):
    if not isinstance(result, dict):
        return True
    if result.get("status") in ("wrapper_error", "loop", "max_steps", "no_action"):
        return True
    if not (result.get("answer") or "").strip():
        return True
    return False


def _log(event, data):
    if logger:
        try:
            logger.log_event(event, data)
        except Exception:
            pass  # observability must never crash the agent


# --- The mitigation entry point ------------------------------------------------------------
def mitigate(call_next, question, config, context):
    context = context or {}
    qid = context.get("qid")
    session_id = context.get("session_id")
    turn_index = context.get("turn_index")

    # One correlation id per request ties all telemetry of this call together.
    try:
        set_correlation_id(new_correlation_id())
    except Exception:
        pass

    # 1) Sanitize injected order notes before the model ever sees them.
    clean_q, removed_note = sanitize_question(question)

    # 2) Cache: serve repeats (latency + cost win). Only "ok" answers are cached.
    key = _cache_key(clean_q)
    cached = _cache_get(context, key)
    if cached is not None:
        _log("CACHE_HIT", {"qid": qid, "session": session_id, "turn": turn_index})
        return cached

    # 3) Prompt routing: guarantee the rewritten system prompt is used this request.
    conf = dict(config)
    if _SYSTEM_PROMPT:
        conf["system_prompt"] = _SYSTEM_PROMPT

    # 4) Retry with backoff on transient tool/agent errors.
    attempts = 0
    max_attempts = 3
    backoff_ms = 200
    t0 = time.time()
    result = None
    last_exc = None
    while attempts < max_attempts:
        attempts += 1
        try:
            result = call_next(clean_q, conf)
        except Exception as exc:  # the agent raised — count it, back off, retry
            last_exc = exc
            result = None
        if result is not None and not _is_error_result(result):
            break
        if attempts < max_attempts:
            time.sleep((backoff_ms * attempts) / 1000.0)

    wall_ms = int((time.time() - t0) * 1000)

    # Fallback shape if every attempt failed/raised.
    if not isinstance(result, dict):
        result = {"answer": None, "status": "wrapper_error", "steps": 0,
                  "trace": [], "meta": {}}

    meta = result.get("meta", {}) or {}
    usage = meta.get("usage", {}) or {}

    # 5) Output PII redaction (net for pii_leak; the prompt also forbids echoing PII).
    answer = result.get("answer")
    pii_hits = 0
    if isinstance(answer, str) and answer:
        red, pii_hits = redact(answer)
        if pii_hits:
            result["answer"] = red

    # 6) Observability — THE telemetry. The only place these signals exist.
    _log("AGENT_CALL", {
        "qid": qid,
        "session": session_id,
        "turn": turn_index,
        "status": result.get("status"),
        "steps": result.get("steps"),
        "attempts": attempts,
        "agent_error": repr(last_exc) if last_exc else None,
        "wall_ms": wall_ms,
        "reported_latency_ms": meta.get("latency_ms"),
        "tokens": usage,
        "cost_usd": cost_from_usage(meta.get("model", conf.get("model", "")), usage),
        "tools_used": meta.get("tools_used", []),
        "n_tools": len(meta.get("tools_used", []) or []),
        "pii_in_answer": pii_hits,
        "note_injection_stripped": bool(removed_note),
    })

    # 7) Cache only clean, successful results.
    if not _is_error_result(result):
        _cache_put(context, key, result)

    return result
