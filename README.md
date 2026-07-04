# LLM Council

![llmcouncil](header.jpg)

The idea of this repo is that instead of asking a question to your favorite LLM provider (e.g. OpenAI GPT 5.1, Google Gemini 3.0 Pro, Anthropic Claude Sonnet 4.5, xAI Grok 4, eg.c), you can group them into your "LLM Council". This repo is a simple, local web app that essentially looks like ChatGPT except it uses OpenRouter to send your query to multiple LLMs, it then asks them to review and rank each other's work, and finally a Chairman LLM produces the final response.

In a bit more detail, here is what happens when you submit a query:

1. **Stage 1: First opinions**. The user query is given to all LLMs individually, and the responses are collected. The individual responses are shown in a "tab view", so that the user can inspect them all one by one.
2. **Stage 2: Review**. Each individual LLM is given the responses of the other LLMs. Under the hood, the LLM identities are anonymized so that the LLM can't play favorites when judging their outputs. The LLM is asked to rank them in accuracy and insight.
3. **Stage 3: Final response**. The designated Chairman of the LLM Council takes all of the model's responses and compiles them into a single final answer that is presented to the user.

## Vibe Code Alert

This project was 99% vibe coded as a fun Saturday hack because I wanted to explore and evaluate a number of LLMs side by side in the process of [reading books together with LLMs](https://x.com/karpathy/status/1990577951671509438). It's nice and useful to see multiple responses side by side, and also the cross-opinions of all LLMs on each other's outputs. I'm not going to support it in any way, it's provided here as is for other people's inspiration and I don't intend to improve it. Code is ephemeral now and libraries are over, ask your LLM to change it in whatever way you like.

## Local Mode, Web Search & Fast Council (this fork)

This fork adds three things on top of the original: it runs **fully local and free** by default (via [Ollama](https://ollama.com/) — no OpenRouter key or credits), it can **search the web privately**, and it has a **per-query speed toggle**. The OpenRouter setup in the sections below is now *optional* — only needed if you switch to cloud mode.

### Run it locally (free, private, offline)

1. Install [Ollama](https://ollama.com/) and pull the council models named in `backend/config.py`, e.g.:
   ```bash
   ollama pull gpt-oss:120b qwen3.6 gemma4:26b mistral-small phi4
   ollama pull llama3.1:8b command-r7b        # fast-mode 5th-seat models
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

### ⚡ Fast mode

The **⚡ Fast** toggle swaps the deep default council (led by a large 120B model) for a lighter, all-in-memory council that answers much faster. In fast mode the 5th seat auto-selects to fit the question — a web-savvy model (Cohere) when the query searched, or a generalist reasoner (Meta) otherwise.

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
