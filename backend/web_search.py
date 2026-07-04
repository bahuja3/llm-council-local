"""Local, privacy-preserving web search for the LLM Council.

Backed by a self-hosted SearXNG metasearch instance (no third-party account, no
API key). Search fires ONLY on time-sensitive queries; results are injected into
the council's context so every model AND the chairman see the same fresh facts.

If SearXNG is unreachable or returns nothing, we degrade gracefully to the plain
query. We never fall back to a cloud search API, so the only thing that ever
leaves the machine is the search terms reaching SearXNG's upstream engines —
never tied to an account or key.
"""

import re
import httpx
from typing import Tuple, Dict, Any, Optional

from .config import WEB_SEARCH_ENABLED, SEARXNG_URL

MAX_RESULTS = 5
SNIPPET_CHARS = 500  # keep snippets short so smaller models' context isn't blown

# Fire search only when the question looks time-sensitive / current-factual.
_TEMPORAL = re.compile(
    r"\b("
    r"today|todays|tonight|now|current|currently|latest|recent|recently|"
    r"yesterday|breaking|news|headline|headlines|price|prices|stock|stocks|market|"
    r"weather|forecast|who won|winner|score|standings|release[ds]?|"
    r"released|launch(?:ed|es)?|update[ds]?|as of|right now|"
    r"this (?:week|month|year)|"
    r"20(?:2[4-9]|3\d)"  # years 2024-2039
    r")\b",
    re.IGNORECASE,
)


def needs_search(query: str) -> bool:
    """Heuristic: does this question likely need fresh web data?"""
    return bool(_TEMPORAL.search(query))


async def _query_searxng(query: str) -> list:
    params = {"q": query, "format": "json"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(SEARXNG_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    return data.get("results", [])[:MAX_RESULTS]


def _format_results(results: list) -> str:
    blocks = []
    for i, r in enumerate(results, start=1):
        title = (r.get("title") or "").strip()
        url = (r.get("url") or "").strip()
        content = (r.get("content") or "").strip()
        if len(content) > SNIPPET_CHARS:
            content = content[:SNIPPET_CHARS].rstrip() + "…"
        blocks.append(f"[{i}] {title}\n{url}\n{content}".strip())
    return "\n\n".join(blocks)


async def augment_query(user_query: str, force: Optional[bool] = None) -> Tuple[str, Dict[str, Any]]:
    """
    Return (query_to_use, meta).

    query_to_use == user_query unless we search AND get results — in which case
    fresh web context is prepended. `force` overrides the auto heuristic:
    True = always search, False = never search, None = time-sensitivity heuristic.
    meta records what happened (surfaced in the API response / backend logs).
    """
    if force is False:
        return user_query, {"searched": False, "reason": "forced_off"}
    should_search = True if force is True else needs_search(user_query)
    if not WEB_SEARCH_ENABLED or not should_search:
        reason = "search_disabled" if not WEB_SEARCH_ENABLED else "not_time_sensitive"
        return user_query, {"searched": False, "reason": reason}

    try:
        results = await _query_searxng(user_query)
    except Exception as e:
        # SearXNG down / not running — degrade to plain query, never leak to cloud.
        print(f"[web_search] SearXNG unavailable ({e}); proceeding without search.")
        return user_query, {"searched": False, "reason": f"searxng_unavailable: {e}"}

    if not results:
        return user_query, {"searched": True, "results": 0}

    context = _format_results(results)
    augmented = (
        "You have access to the following up-to-date web search results. Use them "
        "to ground your answer in current facts, and cite a source as [n] when you "
        "rely on it. If they are irrelevant, ignore them.\n\n"
        "=== LIVE WEB SEARCH RESULTS ===\n"
        f"{context}\n"
        "=== END WEB SEARCH RESULTS ===\n\n"
        f"Question: {user_query}"
    )
    meta = {
        "searched": True,
        "results": len(results),
        "sources": [r.get("url") for r in results],
    }
    print(f"[web_search] injected {len(results)} results for: {user_query[:80]!r}")
    return augmented, meta
