# CLAUDE.md - Technical Notes for LLM Council

This file contains technical details, architectural decisions, and important implementation notes for future development sessions.

## Project Overview

LLM Council is a 3-stage deliberation system where multiple LLMs collaboratively answer user questions. The key innovation is anonymized peer review in Stage 2, preventing models from playing favorites.

## Local Mode, Web Search & Fast Council (added 2026-07)

This fork runs **fully local and free** by default (Ollama), with **privacy-preserving web search** and a **per-query fast/full toggle**. The original app was OpenRouter-only.

### Run modes (`config.py`) — LOCAL vs CLOUD
`config.py` has two blocks; whichever is active (uncommented) wins (Python reads top to bottom):
- **LOCAL (active default)**: `OPENROUTER_API_URL` → `http://localhost:11434/v1/chat/completions` (Ollama's OpenAI-compatible endpoint). `openrouter.py` is unchanged — it's a plain `{model, messages}` OpenAI-style call, so Ollama works with **zero code changes**. The bearer token is ignored locally, so the `.env` key can stay a placeholder.
- **CLOUD**: comment the LOCAL block, uncomment CLOUD, put a real key in `.env`.
- Vars: `COUNCIL_MODELS`, `CHAIRMAN_MODEL`, `TITLE_MODEL`, `OPENROUTER_API_URL`.

### Web search (`backend/web_search.py` + `searxng/`)
Local, privacy-preserving. Backed by a self-hosted **SearXNG** metasearch container (no account, no API key).
- `needs_search(query)`: temporal-keyword heuristic (today/latest/current/price/news/20xx/…). Evergreen questions skip the network entirely.
- `augment_query(query, force)`: if searching, GET `SEARXNG_URL` (`/search?q=…&format=json`), take top `MAX_RESULTS` (5), truncate snippets to `SNIPPET_CHARS` (500), and **prepend** a "LIVE WEB SEARCH RESULTS" block to the query. Returns `(query_to_use, meta)`.
  - `force`: `True`=always search, `False`=never, `None`=heuristic (driven by the `🌐 Web: Auto/On/Off` UI toggle).
  - **Degrades gracefully**: SearXNG down or 0 results → returns the plain query. It NEVER falls back to a cloud search API — the only thing that leaves the box is the search terms reaching SearXNG's upstream engines (no account/key linkage).
- Injection happens once at the top of the flow; storage keeps the ORIGINAL question (UI shows clean text). The augmented query feeds all 3 stages.
- **SearXNG setup** (`searxng/docker-compose.yml` + `settings.yml`): `docker compose -f searxng/docker-compose.yml up -d`. JSON output is OFF by default (403) — `settings.yml` enables it via `search.formats: [html, json]` and sets `limiter: false` + a `secret_key`. Needs Docker Desktop running.

### Per-seat routing + Fast/Full council (`config.py` + `routing.py:route_council`)
Two orthogonal controls assemble the council per query:
- **Fast/Full toggle** picks the generalist *pool* + chairman + speed:
  - **Full** (default): `ROUTE_GENERALISTS_FULL` = `COUNCIL_MODELS` (5, incl. `gpt-oss:120b`), chairman `gpt-oss:120b`. Deepest; ~2.7 min/query locally.
  - **Fast**: `ROUTE_GENERALISTS_FAST` (4 small + `llama3.1:8b`), chairman `qwen3.6`. All-resident → much faster.
- **Per-seat routing** (`routing.py`): `route_council(query, searched, fast)` detects *signals* on the original question and lets **specialist** models claim seats; generalists fill the rest up to `COUNCIL_SIZE` (5). Signals → `SPECIALISTS_FULL` / `SPECIALISTS_FAST` (mode-specific):
  - `websearch` (a search fired) → Cohere `command-r7b` (RAG) · `code` (regex) → `qwen3-coder:30b` · `math` (regex) → `deepseek-r1:70b` (Full) or `qwen3.5:35b-a3b-coding-nvfp4` (Fast MoE, so "fast" stays fast).
  - Multiple signals seat multiple specialists (a code question that also searched seats *both* Cohere and Qwen-Coder). No signals → the plain generalist roster (pre-routing behavior). This **generalizes the old dynamic 5th seat** — `websearch → Cohere` is now just one routing rule.
  - Returns `(models, chairman, signals)`; `signals` is surfaced in the response metadata.
- `stage1/2/3` take optional `models=`/`chairman=` (default to the full-council globals). `run_full_council(query, fast, force_search)` and the streaming path both call `route_council` and thread the roster through.

### Request/response wiring
- `SendMessageRequest` gained `fast: bool = False` and `force_search: Optional[bool] = None`.
- The `stage2_complete` SSE event's `metadata` now also carries `search` (augment meta), `council` (actual roster used), `chairman`, and `fast`.
- Frontend: `ChatInterface.jsx` holds `webMode` (`'auto'|'on'|'off'`) + `fast` as sticky pills above the input; passes `{fast, forceSearch}` via `onSendMessage` → `App.jsx` → `api.sendMessageStream(..., options)`.

## Architecture

### Backend Structure (`backend/`)

**`config.py`**
- Two run-mode blocks: LOCAL (Ollama, active default) / CLOUD (OpenRouter, commented) — see "Local Mode, Web Search & Fast Council" above
- `COUNCIL_MODELS`, `CHAIRMAN_MODEL`, `TITLE_MODEL` (conversation titles), `OPENROUTER_API_URL` (repointed to Ollama in LOCAL mode)
- `WEB_SEARCH_ENABLED`, `SEARXNG_URL` — local web search
- `FAST_COUNCIL_BASE`, `FAST_SEAT_REASONING` (Meta), `FAST_SEAT_WEBSEARCH` (Cohere), `FAST_CHAIRMAN_MODEL` — fast council pool + chairman
- `SPECIALISTS_FULL`/`SPECIALISTS_FAST` (signal→model), `ROUTE_GENERALISTS_FULL`/`ROUTE_GENERALISTS_FAST`, `COUNCIL_SIZE` — per-seat routing
- Uses environment variable `OPENROUTER_API_KEY` from `.env` (ignored in LOCAL mode)
- Backend runs on **port 8001** (NOT 8000 - user had another app on 8000)

**`web_search.py`** (local, privacy-preserving web search)
- `needs_search()` temporal heuristic + `augment_query(query, force)` → SearXNG → prepend results. Degrades to plain query; never uses a cloud search API. Full detail in the dedicated section above.

**`routing.py`** (per-seat council routing)
- `detect_signals(query, searched)` (regex) + `route_council(query, searched, fast)` → assembles the council: specialist seats by signal (web/code/math) + generalists filling the rest. See section above.

**`warmup.py`** (keep local models resident)
- `warm_council()` runs at FastAPI startup (`@app.on_event("startup")`, non-blocking). In LOCAL mode it POSTs to Ollama's NATIVE `/api/generate` for each `WARM_MODELS` (the fast council) with `keep_alive=-1` + `options.num_ctx=OLLAMA_NUM_CTX` (32768). The explicit `num_ctx` overrides the Ollama app's large default context per-request so all 5 fit in RAM.
- Requires the Ollama **server** env `OLLAMA_MAX_LOADED_MODELS >= len(WARM_MODELS)` (Apple-Silicon default is 3) — set via `launchctl setenv` before Ollama starts. The app overrides `OLLAMA_CONTEXT_LENGTH` (so we set context per-request instead), but respects `OLLAMA_MAX_LOADED_MODELS` and `OLLAMA_KEEP_ALIVE`.

**`openrouter.py`**
- `query_model()`: Single async model query
- `query_models_parallel()`: Parallel queries using `asyncio.gather()`
- Returns dict with 'content' and optional 'reasoning_details'
- Graceful degradation: returns None on failure, continues with successful responses

**`council.py`** - The Core Logic
- `stage1_collect_responses()`: Parallel queries to all council models
- `stage2_collect_rankings()`:
  - Anonymizes responses as "Response A, B, C, etc."
  - Creates `label_to_model` mapping for de-anonymization
  - Prompts models to evaluate and rank (with strict format requirements)
  - Returns tuple: (rankings_list, label_to_model_dict)
  - Each ranking includes both raw text and `parsed_ranking` list
- `stage3_synthesize_final()`: Chairman synthesizes from all responses + rankings
- `parse_ranking_from_text()`: Extracts "FINAL RANKING:" section, handles both numbered lists and plain format
- `calculate_aggregate_rankings()`: Computes average rank position across all peer evaluations
- council assembly is delegated to `routing.py:route_council(query, searched, fast)` → `(models, chairman, signals)` (see section above)
- `stage1/2/3` accept optional `models=`/`chairman=`; `run_full_council(query, fast, force_search)` threads the chosen roster through all stages

**`storage.py`**
- JSON-based conversation storage in `data/conversations/`
- Each conversation: `{id, created_at, messages[]}`
- Assistant messages contain: `{role, stage1, stage2, stage3}`
- Note: assistant messages now persist a `metadata` field (label_to_model, aggregate_rankings, search, council, chairman, fast, signals) so the routing/search indicator + Stage 2 de-anon survive reloads

**`main.py`**
- FastAPI app with CORS enabled for localhost:5173 and localhost:3000
- POST `/api/conversations/{id}/message` returns metadata in addition to stages
- Metadata includes: label_to_model mapping and aggregate_rankings

### Frontend Structure (`frontend/src/`)

**`App.jsx`**
- Main orchestration: manages conversations list and current conversation
- Handles message sending and metadata storage
- Important: metadata is stored in the UI state for display but not persisted to backend JSON

**`components/ChatInterface.jsx`**
- Multiline textarea (3 rows, resizable)
- Enter to send, Shift+Enter for new line
- User messages wrapped in markdown-content class for padding

**`components/Stage1.jsx`**
- Tab view of individual model responses
- ReactMarkdown rendering with markdown-content wrapper

**`components/Stage2.jsx`**
- **Critical Feature**: Tab view showing RAW evaluation text from each model
- De-anonymization happens CLIENT-SIDE for display (models receive anonymous labels)
- Shows "Extracted Ranking" below each evaluation so users can validate parsing
- Aggregate rankings shown with average position and vote count
- Explanatory text clarifies that boldface model names are for readability only

**`components/Stage3.jsx`**
- Final synthesized answer from chairman
- Green-tinted background (#f0fff0) to highlight conclusion

**Styling (`*.css`)**
- Light mode theme (not dark mode)
- Primary color: #4a90e2 (blue)
- Global markdown styling in `index.css` with `.markdown-content` class
- 12px padding on all markdown content to prevent cluttered appearance

## Key Design Decisions

### Stage 2 Prompt Format
The Stage 2 prompt is very specific to ensure parseable output:
```
1. Evaluate each response individually first
2. Provide "FINAL RANKING:" header
3. Numbered list format: "1. Response C", "2. Response A", etc.
4. No additional text after ranking section
```

This strict format allows reliable parsing while still getting thoughtful evaluations.

### De-anonymization Strategy
- Models receive: "Response A", "Response B", etc.
- Backend creates mapping: `{"Response A": "openai/gpt-5.1", ...}`
- Frontend displays model names in **bold** for readability
- Users see explanation that original evaluation used anonymous labels
- This prevents bias while maintaining transparency

### Error Handling Philosophy
- Continue with successful responses if some models fail (graceful degradation)
- Never fail the entire request due to single model failure
- Log errors but don't expose to user unless all models fail

### UI/UX Transparency
- All raw outputs are inspectable via tabs
- Parsed rankings shown below raw text for validation
- Users can verify system's interpretation of model outputs
- This builds trust and allows debugging of edge cases

## Important Implementation Details

### Relative Imports
All backend modules use relative imports (e.g., `from .config import ...`) not absolute imports. This is critical for Python's module system to work correctly when running as `python -m backend.main`.

### Port Configuration
- Backend: 8001 (changed from 8000 to avoid conflict)
- Frontend: 5173 (Vite default)
- Update both `backend/main.py` and `frontend/src/api.js` if changing

### Markdown Rendering
All ReactMarkdown components must be wrapped in `<div className="markdown-content">` for proper spacing. This class is defined globally in `index.css`.

### Model Configuration
Models are configured in `backend/config.py`. Default run mode is **LOCAL (Ollama)** with a 5-seat council; chairman is `gpt-oss:120b` (`qwen3.6` in fast mode). The council is assembled per query by `routing.py`: a `⚡ Fast` toggle picks the generalist pool/speed, and specialist seats are routed in by signal (web→Cohere, code→Qwen-Coder, math→DeepSeek-R1). See "Local Mode, Web Search & Fast Council" for the full picture.

## Common Gotchas

1. **Module Import Errors**: Always run backend as `python -m backend.main` from project root, not from backend directory
2. **CORS Issues**: Frontend must match allowed origins in `main.py` CORS middleware
3. **Ranking Parse Failures**: If models don't follow format, fallback regex extracts any "Response X" patterns in order
4. **Metadata**: now persisted on assistant messages (was previously ephemeral) — powers the routing/search indicator and Stage 2 de-anonymization on reload
5. **Web search silently off**: If Docker/SearXNG isn't running, search degrades to no-search (by design). Bring it up: `docker compose -f searxng/docker-compose.yml up -d` (needs Docker Desktop running).
6. **SearXNG 403 on JSON**: `settings.yml` must include `json` under `search.formats` (off by default).
7. **TITLE_MODEL must match run mode**: in LOCAL mode it must be a local model (e.g. `phi4:latest`); a cloud model id fails silently → titles become "New Conversation".

## Future Enhancement Ideas

- ✅ DONE: Streaming responses (SSE via `/message/stream`)
- ✅ DONE: Per-query council control (`⚡ Fast` toggle + per-seat routing: web/code/math specialists)
- ✅ DONE: Local/offline operation (Ollama) + private web search (SearXNG)
- Configurable council/chairman rosters via UI (currently `config.py` + fast toggle only)
- Surface search activity + 5th-seat choice in the UI (currently only in SSE metadata / backend logs)
- Export conversations to markdown/PDF
- Model performance analytics over time
- Custom ranking criteria (not just accuracy/insight)

## Testing Notes

Use `test_openrouter.py` to verify API connectivity and test different model identifiers before adding to council. The script tests both streaming and non-streaming modes.

## Data Flow Summary

```
User Query
    ↓
Web search (gated): needs_search / force → SearXNG → prepend results to query
    ↓
route_council(query, searched, fast) → [specialist + generalist roster + chairman + signals]
    ↓
Stage 1: Parallel queries → [individual responses]
    ↓
Stage 2: Anonymize → Parallel ranking queries → [evaluations + parsed rankings]
    ↓
Aggregate Rankings Calculation → [sorted by avg position]
    ↓
Stage 3: Chairman synthesis with full context
    ↓
Return: {stage1, stage2, stage3, metadata:{label_to_model, aggregate_rankings, search, council, chairman, fast}}
    ↓
Frontend: Display with tabs + validation UI
```

The entire flow is async/parallel where possible to minimize latency.
