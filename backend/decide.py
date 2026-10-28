"""Decision-model routing signals for the council (added 2026-10-27, Claude).

One call per user question asks a System One decision model three yes/no
questions: does answering it need code work, real math, or current information?
The model supplies the judgments; routing.py and web_search.py decide what to do.

Truth table per signal (see decide()):
    p >= YES  -> signal on
    p <= NO   -> signal off
    otherwise -> unsettled: defer to the original regex heuristic
    any failure (model down, timeout, bad response) -> original regex heuristic

Backends (env COUNCIL_ROUTER):
    nimble  (default) local Ollama decision model; the question never leaves the
            machine, matching the council's privacy design
    jev     TypeSafe Jev, hosted; sends every question to api.typesafe.ai
    regex   original behavior, no model call
Other env: COUNCIL_ROUTER_TIMEOUT (s, default 3), COUNCIL_ROUTER_KEEP_ALIVE
(nimble residency, default "30m").
"""

import json
import logging
import os
import shlex
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional

log = logging.getLogger(__name__)

DEFAULT_BACKEND = "nimble"
YES, NO = 0.7, 0.3
MAX_CHARS = 12000          # nimble's prompt budget is ~8K tokens

ENDPOINTS = {
    "nimble": ("http://localhost:11434/v1/systemone", "nimble"),
    "jev": ("https://api.typesafe.ai/v1/systemone", "jev-latest"),
}

# Question wording lives here, in one place, for review.
QUESTIONS = {
    "code": {
        "type": "noul",
        "instructions": "Does answering `question` require writing, reading, explaining, or fixing computer code?",
        "criteria": {
            "true": "The user wants code written, explained, reviewed, or debugged, or asks how a programming language, library, or developer tool works",
            "false": "The question is about something else, even if it uses words like function, script, program, code, or algorithm in their everyday or non-software sense",
        },
    },
    "math": {
        "type": "noul",
        "instructions": "Does answering `question` require working through math, such as a calculation, an equation, a proof, or a probability computed from numbers in the question?",
        "criteria": {
            "true": "A good answer has to calculate, solve, or prove something",
            "false": "The answer is a fact to look up, an explanation, or advice; numbers, percentages, or ranges may appear but nothing needs to be calculated",
        },
    },
    "current": {
        "type": "noul",
        "instructions": "Does a good answer to `question` depend on facts that change over time or are recent, such as news, prices, schedules, opening hours, who currently holds a role, or products and models released recently?",
        "criteria": {
            "true": "The answer could be wrong or stale without checking up-to-date information",
            "false": "The answer is stable knowledge: how something works, history, definitions, or general advice",
        },
    },
}

_cache: Dict[str, Dict[str, float]] = {}


def _jev_key() -> Optional[str]:
    key = os.environ.get("TYPESAFE_API_KEY")
    if key:
        return key
    try:
        with open(os.path.expanduser("~/.config/typesafe/env")) as fh:
            for line in fh:
                if "TYPESAFE_API_KEY=" in line:
                    return shlex.split(line.split("=", 1)[1])[0]
    except Exception:
        pass
    return None


def judge(query: str) -> Optional[Dict[str, float]]:
    """{'code': p, 'math': p, 'current': p} or None (caller falls back to regex)."""
    backend = os.environ.get("COUNCIL_ROUTER", DEFAULT_BACKEND).strip().lower()
    if backend not in ENDPOINTS or not query or not query.strip():
        return None
    ck = backend + "\x00" + query
    if ck in _cache:
        return _cache[ck]
    url, model = ENDPOINTS[backend]
    body = {"model": model, "state": {"question": query[:MAX_CHARS]}}
    headers = {"Content-Type": "application/json"}
    if backend == "jev":
        key = _jev_key()
        if not key:
            log.warning("router: jev selected but no TYPESAFE_API_KEY; using regex")
            return None
        headers["Authorization"] = "Bearer " + key
    else:
        body["keep_alive"] = os.environ.get("COUNCIL_ROUTER_KEEP_ALIVE", "30m")
    t0 = time.time()
    timeout = float(os.environ.get("COUNCIL_ROUTER_TIMEOUT", "3"))

    def post(qs):
        req = urllib.request.Request(url, data=json.dumps({**body, "questions": qs}).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)["answers"]

    try:
        if backend == "nimble":
            # nimble's answers bleed across questions sent in one request (tested
            # 2026-10-27: bundled code=0.99 on "Solve x^2-5x+6=0", alone 0.00), so
            # it gets one question per request, in parallel. Jev keeps questions
            # independent, so it gets them bundled.
            with ThreadPoolExecutor(max_workers=len(QUESTIONS)) as ex:
                parts = list(ex.map(lambda k: post({k: QUESTIONS[k]}), QUESTIONS))
            answers = {k: v for part in parts for k, v in part.items()}
        else:
            answers = post(QUESTIONS)
        result = {k: float(answers[k]["noul"]) for k in QUESTIONS}
    except Exception as e:  # never let routing break the council
        log.warning("router: %s unavailable (%s); using regex", backend, repr(e)[:160])
        return None
    log.info("router: %s %.0fms %s", backend, (time.time() - t0) * 1000,
             " ".join(f"{k}={v:.2f}" for k, v in result.items()))
    if len(_cache) > 512:
        _cache.clear()
    _cache[ck] = result
    return result


def decide(signal: str, regex_hit: bool, query: str) -> bool:
    """Final on/off for one signal: model judgment, with regex for unsettled/failed cases."""
    j = judge(query)
    if not j:
        return regex_hit
    p = j[signal]
    if p >= YES:
        return True
    if p <= NO:
        return False
    return regex_hit
