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
    "gemma4:26b-mlx",        # Google (MLX build — Apple-Silicon optimized)
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
# Reranking (local cross-encoder): a self-hosted llama.cpp server running
# bge-reranker-v2-m3 (Ollama has no rerank endpoint). When web search fires we
# pull a LARGER candidate pool from SearXNG (RERANK_CANDIDATES), rerank by true
# query-relevance, and keep only the best MAX_RESULTS for the council's context —
# so the seats get the most on-point sources, not just SearXNG's own ordering.
# If the rerank server is down we fall back to that ordering: nothing breaks and
# nothing leaves the box (localhost only). Server: ~/llama-models/rerank-server.sh
# (restart-council.sh starts it automatically).
# ─────────────────────────────────────────────────────────────────────────────
RERANK_ENABLED = True
RERANK_URL = "http://127.0.0.1:8090/v1/rerank"
RERANK_TIMEOUT = 10.0     # seconds; on timeout we keep SearXNG's order
RERANK_CANDIDATES = 15    # results pulled from SearXNG before reranking down to MAX_RESULTS

# The same reranker also trims large uploaded attachments: at message time each
# file's text is chunked (~RERANK_DOC_CHUNK_CHARS) and only the RERANK_DOC_TOP_CHUNKS
# chunks most relevant to the user's question are injected (in original document
# order). Files small enough to fit in TOP_CHUNKS chunks are injected whole; if the
# reranker is down we fall back to the whole (truncated) text — never worse. See
# backend/extract.py:build_attachment_context.
RERANK_DOC_CHUNK_CHARS = 1200   # target size of each attachment chunk
RERANK_DOC_TOP_CHUNKS = 6       # most-relevant chunks kept per attachment
RERANK_DOC_MAX_CHUNKS = 300     # ceiling on chunks reranked in one pass (bounds the rerank request)
RERANK_DOC_TIMEOUT = 60.0       # seconds; whole-document reranking is many chunks, so allow longer

# ─────────────────────────────────────────────────────────────────────────────
# FAST MODE (per-query ⚡ toggle): a lighter, all-resident local council for
# quick single answers — nothing swaps in/out of the 128 GB. The 5th seat is
# chosen per query: Cohere command-r7b (RAG) when the query hit web search,
# else Meta llama3.1:8b (generalist reasoner). Assumes LOCAL (Ollama) models.
# ─────────────────────────────────────────────────────────────────────────────
FAST_COUNCIL_BASE = [
    "qwen3.6:latest",        # Alibaba
    "gemma4:26b-mlx",        # Google (MLX build — Apple-Silicon optimized)
    "mistral-small:latest",  # Mistral
    "phi4:latest",           # Microsoft
]
FAST_SEAT_REASONING = "llama3.1:8b"   # Meta — generalist reasoner (default fast seat)
FAST_SEAT_WEBSEARCH = "command-r7b"   # Cohere — web-search specialist (RAG-tuned)
FAST_CHAIRMAN_MODEL = "qwen3.6:latest"

# ─────────────────────────────────────────────────────────────────────────────
# PER-SEAT ROUTING: assemble the council per query. Each detected signal claims a
# seat with a specialist model; generalists fill the rest (up to COUNCIL_SIZE).
# Generalizes the fast 5th-seat swap — "websearch -> Cohere" is now just one rule
# alongside code -> Qwen Coder and math -> DeepSeek R1. Detection (regex on the
# original question) lives in routing.py. With no signals you get the generalist
# roster, i.e. the pre-routing behavior.
# ─────────────────────────────────────────────────────────────────────────────
COUNCIL_SIZE = 5
# Specialist rosters differ by mode only for MATH: Full uses the heavyweight
# reasoner (DeepSeek R1 70B); Fast uses a fast MoE (~3B active) so "fast" stays fast.
SPECIALISTS_FULL = {
    "websearch": FAST_SEAT_WEBSEARCH,            # Cohere command-r7b — RAG/grounding
    "code":      "qwen3-coder:30b",              # Qwen Coder — programming / debugging
    "math":      "deepseek-r1:70b",              # DeepSeek R1 — deep quantitative reasoning
}
SPECIALISTS_FAST = {
    "websearch": FAST_SEAT_WEBSEARCH,            # Cohere command-r7b — RAG/grounding
    "code":      "qwen3-coder:30b",              # Qwen Coder — programming / debugging
    "math":      "qwen3.5:35b-a3b-coding-nvfp4", # Qwen MoE (~3B active) — fast quantitative
}
# Generalist pools, filled in after specialists (list order = fill priority).
ROUTE_GENERALISTS_FULL = COUNCIL_MODELS                             # gpt-oss:120b + 4
ROUTE_GENERALISTS_FAST = FAST_COUNCIL_BASE + [FAST_SEAT_REASONING]  # 4 small + llama3.1:8b

# Stage 2 speed-up: for these signals the rankers get a terse "ranking only" prompt
# (no verbose per-response critique) — a big generation-time cut on long answers.
# All models still rank (votes preserved); they just write far less. Math answers
# are objective, so the prose critique adds little there.
STAGE2_CONCISE_SIGNALS = {"math"}

# ─────────────────────────────────────────────────────────────────────────────
# Keep-warm (LOCAL mode): on startup, pin the fast-council models resident in
# Ollama with keep_alive=-1 and a bounded context, so queries skip cold-loading
# and Stage 1/2 run all seats truly in parallel. Needs the Ollama server started
# with OLLAMA_MAX_LOADED_MODELS >= len(WARM_MODELS) (see README / LaunchAgent).
# ─────────────────────────────────────────────────────────────────────────────
WARM_ON_STARTUP = True
OLLAMA_NUM_CTX = 32768                 # context to load warmed models with (bounds KV-cache RAM)
WARM_MODELS = ROUTE_GENERALISTS_FAST   # the all-resident fast council (4 small + llama3.1:8b)

# ─────────────────────────────────────────────────────────────────────────────
# File uploads: every file is turned into text and injected into the council's
# prompt. Images are described/OCR'd by a local Ollama vision model; audio is
# transcribed locally by Whisper (faster-whisper). See backend/extract.py.
# ─────────────────────────────────────────────────────────────────────────────
VISION_MODEL = "qwen2.5vl:72b"   # Ollama vision model used to describe/OCR images
WHISPER_MODEL = "base"           # faster-whisper model size for audio transcription

# Data directory for conversation storage
DATA_DIR = "data/conversations"
