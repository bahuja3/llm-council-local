"""Local cross-encoder reranking for the LLM Council.

Backed by a self-hosted llama.cpp server running bge-reranker-v2-m3, exposing an
OpenAI-style POST /v1/rerank. Ollama has no rerank endpoint, so this is a separate
local service (started by restart-council.sh, model at ~/llama-models/).

Like web search, this NEVER calls the cloud and degrades gracefully: if the server
is down or errors, callers get None and keep their original ordering. The only
thing that ever happens here is a localhost request to :8090.
"""

import httpx
from typing import List, Optional

from .config import RERANK_ENABLED, RERANK_URL, RERANK_TIMEOUT


async def rerank(query: str, documents: List[str], top_k: Optional[int] = None,
                 timeout: Optional[float] = None) -> Optional[List[int]]:
    """Return indices of `documents` ordered most→least relevant to `query`.

    Returns None (so the caller falls back to the original order) if reranking is
    disabled, there's nothing to rank, or the rerank server is unavailable.
    `top_k`, if given, truncates the returned indices. `timeout` overrides
    RERANK_TIMEOUT (document reranking passes a longer one for large chunk counts).
    """
    if not RERANK_ENABLED or len(documents) < 2:
        return None

    try:
        async with httpx.AsyncClient(timeout=timeout if timeout is not None else RERANK_TIMEOUT) as client:
            resp = await client.post(RERANK_URL, json={"query": query, "documents": documents})
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:  # server down, timeout, bad JSON — never break the caller
        print(f"[rerank] unavailable ({e}); keeping original order.")
        return None

    results = data.get("results") or []
    ordered = sorted(results, key=lambda r: r.get("relevance_score", float("-inf")), reverse=True)
    indices = [r["index"] for r in ordered if isinstance(r.get("index"), int) and 0 <= r["index"] < len(documents)]
    if not indices:
        return None
    return indices[:top_k] if top_k is not None else indices
