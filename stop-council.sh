#!/bin/bash
# stop-council.sh — stop the LLM Council and free its RAM.
#
# The big memory is the Ollama models pinned with keep_alive=-1 (~80GB). This
# unloads them and stops the dev servers. Ollama itself stays running (idle) so
# it's quick to bring back with ./restart-council.sh.
#
#   cd ~/Ahuja-Claude/llm-council && ./stop-council.sh

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

echo "==> Stopping dev servers"
pkill -f "backend.main" 2>/dev/null && echo "  backend stopped" || echo "  backend was not running"
pkill -f "llm-council/frontend/node_modules/.bin/vite" 2>/dev/null && echo "  frontend stopped" || echo "  frontend was not running"

echo "==> Unloading Ollama models (frees the RAM held by keep_alive=-1)"
ollama ps 2>/dev/null | tail -n +2 | awk '{print $1}' | while read -r m; do
  [ -n "$m" ] && ollama stop "$m" 2>/dev/null && echo "  unloaded $m"
done

# SearXNG is light (~200MB) and auto-manages via Docker; leave it running.
# To stop it too, uncomment:
# docker compose -f "$HOME/Ahuja-Claude/llm-council/searxng/docker-compose.yml" stop >/dev/null 2>&1

echo ""
echo "  models resident now: $(ollama ps 2>/dev/null | tail -n +2 | grep -c .)  (should be 0)"
echo "==> Council stopped, RAM freed. Ollama app is still running idle."
echo "    Bring it back anytime with ./restart-council.sh"
