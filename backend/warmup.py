"""Keep local council models warm and resident in Ollama.

On startup (LOCAL/Ollama mode) each fast-council model is pinned with keep_alive=-1
and an explicit bounded context via Ollama's NATIVE /api/generate endpoint. That
sidesteps the Ollama app's large default context (which would balloon each model's
KV cache and prevent all of them fitting), so the council's requests reuse the
already-loaded models instead of paying cold-load + swap cost on every query.

Requires the Ollama server running with OLLAMA_MAX_LOADED_MODELS >= len(WARM_MODELS).
"""

import httpx

from .config import OPENROUTER_API_URL, WARM_ON_STARTUP, WARM_MODELS, OLLAMA_NUM_CTX


def _is_local() -> bool:
    return "11434" in OPENROUTER_API_URL  # Ollama's default port


def _native_generate_url() -> str:
    # LOCAL OPENROUTER_API_URL is http://localhost:11434/v1/chat/completions
    return OPENROUTER_API_URL.replace("/v1/chat/completions", "/api/generate")


async def warm_council() -> None:
    """Best-effort: load each warm model with keep_alive=-1 + a bounded context."""
    if not (WARM_ON_STARTUP and _is_local()):
        return
    url = _native_generate_url()
    async with httpx.AsyncClient(timeout=600.0) as client:
        for model in WARM_MODELS:
            try:
                await client.post(url, json={
                    "model": model,
                    "keep_alive": -1,
                    "options": {"num_ctx": OLLAMA_NUM_CTX},
                })
                print(f"[warmup] pinned {model} (num_ctx={OLLAMA_NUM_CTX})", flush=True)
            except Exception as e:
                print(f"[warmup] {model} failed: {e}", flush=True)
