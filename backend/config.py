"""Configuration for the LLM Council."""

import os
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# API key: only used by CLOUD mode. LOCAL mode ignores it (Ollama doesn't check
# the bearer token), so the placeholder in .env is fine while running locally.
# ─────────────────────────────────────────────────────────────────────────────
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# ═════════════════════════════════════════════════════════════════════════════
# ACTIVE: LOCAL MODE (Ollama) — FREE, private, offline. No API credits.
# Council of 5 built from models already on this Mac; 5 distinct labs for
# viewpoint diversity. Runs against Ollama's OpenAI-compatible endpoint.
# ═════════════════════════════════════════════════════════════════════════════
COUNCIL_MODELS = [
    "gpt-oss:120b",          # OpenAI (open-weight)
    "qwen3.6:latest",        # Alibaba
    "gemma4:26b",            # Google
    "mistral-small:latest",  # Mistral
    "phi4:latest",           # Microsoft
]
CHAIRMAN_MODEL = "gpt-oss:120b"   # strongest generalist synthesizes the final answer
TITLE_MODEL = "phi4:latest"       # small/fast local model for conversation titles
OPENROUTER_API_URL = "http://localhost:11434/v1/chat/completions"  # Ollama OpenAI-compatible endpoint

# ═════════════════════════════════════════════════════════════════════════════
# ALTERNATE: CLOUD MODE (OpenRouter) — costs credits, real frontier models.
# To switch: comment the LOCAL block above, uncomment this block, and put a real
# key in .env. (Whichever block is LAST/active wins — Python reads top to bottom.)
# ═════════════════════════════════════════════════════════════════════════════
# COUNCIL_MODELS = [
#     "openai/gpt-5.1",
#     "google/gemini-3-pro-preview",
#     "anthropic/claude-sonnet-4.5",
#     "x-ai/grok-4",
#     "deepseek/deepseek-chat",   # 5th seat — confirm exact slug at openrouter.ai/models
# ]
# CHAIRMAN_MODEL = "google/gemini-3-pro-preview"
# TITLE_MODEL = "google/gemini-2.5-flash"
# OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# ─────────────────────────────────────────────────────────────────────────────
# Web search (local, privacy-preserving): a self-hosted SearXNG metasearch
# instance. The council searches ONLY on time-sensitive queries and injects
# results into context. If SearXNG is down, it degrades to no-search — nothing
# is sent to any third-party API. Container config lives in ../searxng/.
# ─────────────────────────────────────────────────────────────────────────────
WEB_SEARCH_ENABLED = True
SEARXNG_URL = "http://localhost:8080/search"

# ─────────────────────────────────────────────────────────────────────────────
# FAST MODE (per-query ⚡ toggle): a lighter, all-resident local council for
# quick single answers — nothing swaps in/out of the 128 GB. The 5th seat is
# chosen per query: Cohere command-r7b (RAG) when the query hit web search,
# else Meta llama3.1:8b (generalist reasoner). Assumes LOCAL (Ollama) models.
# ─────────────────────────────────────────────────────────────────────────────
FAST_COUNCIL_BASE = [
    "qwen3.6:latest",        # Alibaba
    "gemma4:26b",            # Google
    "mistral-small:latest",  # Mistral
    "phi4:latest",           # Microsoft
]
FAST_SEAT_REASONING = "llama3.1:8b"   # Meta — 5th seat for reasoning / evergreen queries
FAST_SEAT_WEBSEARCH = "command-r7b"   # Cohere — 5th seat for web-search queries (RAG-tuned)
FAST_CHAIRMAN_MODEL = "qwen3.6:latest"

# Data directory for conversation storage
DATA_DIR = "data/conversations"
