# LLM Council

[![Fork of karpathy/llm-council](https://img.shields.io/badge/fork%20of-karpathy%2Fllm--council-181717?logo=github)](https://github.com/karpathy/llm-council)

> A local-first fork of [karpathy/llm-council](https://github.com/karpathy/llm-council) — runs on Ollama with private web search and a fast/full council toggle.

![llmcouncil](header.jpg)

The idea of this repo is that instead of asking a question to your favorite LLM provider (e.g. OpenAI GPT 5.1, Google Gemini 3.0 Pro, Anthropic Claude Sonnet 4.5, xAI Grok 4, eg.c), you can group them into your "LLM Council". This repo is a simple, local web app that essentially looks like ChatGPT except it uses OpenRouter to send your query to multiple LLMs, it then asks them to review and rank each other's work, and finally a Chairman LLM produces the final response.

In a bit more detail, here is what happens when you submit a query:

1. **Stage 1: First opinions**. The user query is given to all LLMs individually, and the responses are collected. The individual responses are shown in a "tab view", so that the user can inspect them all one by one.
2. **Stage 2: Review**. Each individual LLM is given the responses of the other LLMs. Under the hood, the LLM identities are anonymized so that the LLM can't play favorites when judging their outputs. The LLM is asked to rank them in accuracy and insight.
3. **Stage 3: Final response**. The designated Chairman of the LLM Council takes all of the model's responses and compiles them into a single final answer that is presented to the user.

## Vibe Code Alert

Like the [original](https://github.com/karpathy/llm-council), this was ~99% vibe-coded — a fun hack for looking at several LLMs' answers side by side, plus their cross-opinions on each other's work. I've since extended it into a local-first setup (Ollama, no API keys or costs), with private web search and a fast/full council toggle. It's an experiment, provided as-is — but in the spirit of the original: code is ephemeral now, so point your own LLM at it and change it however you like.

## Local Mode, Web Search & Fast Council (this fork)

This fork adds four things on top of the original: it runs **fully local and free** by default (via [Ollama](https://ollama.com/) — no OpenRouter key or credits), it can **search the web privately** (self-hosted SearXNG), it has a **Fast/Full speed toggle**, and it **routes specialist models into council seats per question** (see [What's genuinely novel here](#whats-genuinely-novel-here)). The OpenRouter setup in the sections below is now *optional* — only needed if you switch to cloud mode.

### Run it locally (free, private, offline)

1. Install [Ollama](https://ollama.com/) and pull the council models named in `backend/config.py`, e.g.:
   ```bash
   ollama pull gpt-oss:120b qwen3.6 gemma4:26b mistral-small phi4   # generalist seats
   ollama pull llama3.1:8b                                          # fast-mode generalist
   # specialist seats routed in by question type (web / code / math):
   ollama pull command-r7b qwen3-coder:30b deepseek-r1:70b qwen3.5:35b-a3b-coding-nvfp4
   ```
2. `uv sync` and `cd frontend && npm install` (see Setup below).
3. `./start.sh`, then open http://localhost:5173.

No API key required — `config.py` points the app at Ollama's local endpoint by default (leave the placeholder in `.env`; it's ignored locally). To use real cloud models instead, do the OpenRouter Setup below and flip to the CLOUD block in `config.py`.

### 🌐 Web search (private, local)

By default the council answers from model knowledge only (no internet). Optionally give it **live web search** backed by a self-hosted [SearXNG](https://docs.searxng.org/) — no account, no API key, nothing tied to your identity:

```bash
cp searxng/settings.yml.example searxng/settings.yml   # first time only, then set a secret_key
docker compose -f searxng/docker-compose.yml up -d     # needs Docker running
```

Then use the **🌐 Web** toggle above the input box:
- **Auto** — searches only time-sensitive questions (default) · **On** — always · **Off** — never

Results are injected so every council member + the chairman see the same fresh, cited sources. If SearXNG isn't running, the app simply skips search — it never sends your query to any third-party API.

### ⚡ Fast/Full toggle + per-seat routing

Two controls decide *which* models sit on the council for each question:

- **⚡ Fast toggle** — Full (default) fields a deep council led by a large 120B model; **Fast** swaps to a lighter, all-in-memory council that answers much quicker.
- **Per-seat routing** — the app inspects your question and seats **specialist** models automatically, filling the remaining seats with generalists:

  | If your question… | …a specialist seat is filled by |
  |---|---|
  | triggered a web search | **Cohere Command-R** (RAG / grounding) |
  | is about code | **Qwen Coder** |
  | is quantitative / math | **DeepSeek R1** (Full) or a **fast Qwen MoE** (Fast) |

  Multiple signals stack — a coding question that *also* searched seats **both** Cohere and Qwen-Coder. Plain questions just use the generalists.

### Keep it fast (models stay warm)

Local models are slow to *cold-load* — the first query after an idle spell can take minutes as each seat loads from disk. This fork keeps the fast council resident:

- On startup the backend **pins the 5 fast-council models** in Ollama (`keep_alive=-1`) with a bounded **32K** context (via `num_ctx`), so queries reuse warm models instead of cold-loading, and Stage 1 runs all seats truly in parallel.
- For all 5 to stay resident at once, the Ollama **server** needs its loaded-model limit raised above the Apple-Silicon default of 3. Set it *before* Ollama starts:
  ```bash
  launchctl setenv OLLAMA_MAX_LOADED_MODELS 6
  launchctl setenv OLLAMA_KEEP_ALIVE -1
  # then restart Ollama (quit the app and reopen)
  ```
  These reset on reboot — add a `~/Library/LaunchAgents` plist that runs them at login to persist. (The app's own 256K default context is overridden per-request by the warm-up's `num_ctx`, so all five fit in memory.)

Measured effect: a fast query dropped from ~140s to ~104s warm, and the ~9-minute cold-start on the first query disappears.

### What changed vs the original

| | Original `karpathy/llm-council` | This fork |
|---|---|---|
| **Inference** | OpenRouter (cloud, paid) | **Ollama (local, free)** by default; OpenRouter still supported |
| **Web access** | none (model knowledge only) | **private SearXNG** metasearch — gated, injected, no third-party API |
| **Council roster** | fixed 4-model list | **routed per query** — Fast/Full pool + specialist seats |
| **Speed control** | none | **Fast/Full toggle** (all-resident lightweight vs deep) |
| **Search control** | n/a | **🌐 Auto/On/Off** toggle |
| **Conversation titles** | `gemini-2.5-flash` (cloud) | local model (`TITLE_MODEL`) |
| **New backend files** | — | `web_search.py`, `routing.py`, `searxng/` |

### What's genuinely novel here

To be candid: running Karpathy's council **locally on Ollama**, and even **adding web search**, is *not* unique — several forks did both within days of the original's release (see the community [awesome-list](https://github.com/danielrosehill/Awesome-LLM-Council-Projects)). What I couldn't find in any other fork is the **per-seat routing** here — and specifically that **the same signal deciding whether to search the web also decides which model fills that seat** (a RAG model when the query searched, a code model when it's code, a math reasoner when it's quantitative). Other forks use fixed rosters, manual per-request model picks, or swap by pipeline *phase* — none condition a seat's model identity on the *content of the question*. So the distinctive contribution is small but real: **query-conditioned specialist routing** layered on the council pattern, not the local/search plumbing itself.

## Security & scope

This is a **personal, local** app — meant to run on your own machine, not as a shared service:

- **Loopback only.** The backend (`:8001`) binds to `127.0.0.1`, and the SearXNG container publishes `:8080` on `127.0.0.1`; Vite (`:5173`) defaults to localhost. Nothing is exposed to your LAN — don't port-forward these.
- **No authentication.** Anything that can reach the backend can read/create/delete conversations. The loopback binding is the mitigation; keep it that way.
- **Plaintext storage.** Conversations save as JSON under `data/conversations/` (gitignored). Don't paste secrets you wouldn't keep in a local plaintext file.
- **Cloud mode is opt-in.** Local Ollama is the default; the OpenRouter block in `config.py` is commented out. Only if you enable it do prompts leave your machine.
- **Web search reaches the open web.** SearXNG avoids an account/API key, but your search *terms* still go to upstream engines from your IP (see the web-search section).
- **License:** this is a fork of [karpathy/llm-council](https://github.com/karpathy/llm-council), which currently declares **no license** — i.e. "all rights reserved" upstream. Fine for personal use; check with the upstream author before redistributing.

## Setup

### 1. Install Dependencies

The project uses [uv](https://docs.astral.sh/uv/) for project management.

**Backend:**
```bash
uv sync
```

**Frontend:**
```bash
cd frontend
npm install
cd ..
```

### 2. Configure API Key

Create a `.env` file in the project root:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
```

Get your API key at [openrouter.ai](https://openrouter.ai/). Make sure to purchase the credits you need, or sign up for automatic top up.

### 3. Configure Models (Optional)

Edit `backend/config.py` to customize the council:

```python
COUNCIL_MODELS = [
    "openai/gpt-5.1",
    "google/gemini-3-pro-preview",
    "anthropic/claude-sonnet-4.5",
    "x-ai/grok-4",
]

CHAIRMAN_MODEL = "google/gemini-3-pro-preview"
```

## Running the Application

**Option 1: Use the start script**
```bash
./start.sh
```

**Option 2: Run manually**

Terminal 1 (Backend):
```bash
uv run python -m backend.main
```

Terminal 2 (Frontend):
```bash
cd frontend
npm run dev
```

Then open http://localhost:5173 in your browser.

## Tech Stack

- **Backend:** FastAPI (Python 3.10+), async httpx; talks to **Ollama** (local, default) or **OpenRouter** (cloud) via the same OpenAI-style API
- **Web search (optional):** self-hosted SearXNG metasearch (`searxng/`)
- **Frontend:** React + Vite, react-markdown for rendering
- **Storage:** JSON files in `data/conversations/`
- **Package Management:** uv for Python, npm for JavaScript
