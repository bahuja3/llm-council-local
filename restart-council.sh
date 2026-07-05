#!/bin/bash
# restart-council.sh — bring the local LLM Council fully up (after a reboot, or anytime).
#
# Ensures Ollama has the right env (restarts it ONLY if the login ordering race left
# it with the default 3-model limit), makes sure SearXNG is up, then (re)starts the
# backend + frontend dev servers. Safe to run repeatedly.
#
#   cd ~/Ahuja-Claude/llm-council && ./restart-council.sh

set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

echo "==> Ensuring Ollama env (keep-alive + loaded-model limit)"
launchctl setenv OLLAMA_MAX_LOADED_MODELS 6
launchctl setenv OLLAMA_KEEP_ALIVE -1

# Make sure the Ollama server is running
if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "==> Starting Ollama"
  open -a Ollama
  for i in $(seq 1 60); do curl -s http://localhost:11434/api/tags >/dev/null 2>&1 && break; sleep 1; done
fi

# Fix the login-ordering race: if the running server didn't inherit MAX_LOADED>=5,
# restart it so all 5 fast-council models can stay resident.
PID=$(lsof -nP -iTCP:11434 -sTCP:LISTEN 2>/dev/null | awk 'NR==2{print $2}')
MAXL=$(ps eww -p "$PID" 2>/dev/null | tr ' ' '\n' | grep -E '^OLLAMA_MAX_LOADED_MODELS=' | cut -d= -f2)
if ! [ "${MAXL:-0}" -ge 5 ] 2>/dev/null; then
  echo "==> Ollama has MAX_LOADED=${MAXL:-unset}; restarting so it picks up 6"
  osascript -e 'tell application "Ollama" to quit' 2>/dev/null; sleep 2
  pkill -f "Ollama.app" 2>/dev/null; pkill -x ollama 2>/dev/null; pkill -f "llama-server" 2>/dev/null; sleep 3
  open -a Ollama
  for i in $(seq 1 60); do curl -s http://localhost:11434/api/tags >/dev/null 2>&1 && break; sleep 1; done
fi

# SearXNG (web search): start the container if Docker is running and it's down
if docker info >/dev/null 2>&1; then
  if ! curl -s http://localhost:8080/ >/dev/null 2>&1; then
    echo "==> Starting SearXNG container"
    docker compose -f "$REPO/searxng/docker-compose.yml" up -d >/dev/null 2>&1
  fi
else
  echo "==> Docker not running — web search stays off until you open Docker Desktop"
fi

# (Re)start the dev servers
echo "==> (Re)starting backend (:8001) and frontend (:5173)"
pkill -f "backend.main" 2>/dev/null
pkill -f "$REPO/frontend/node_modules/.bin/vite" 2>/dev/null
sleep 1
( cd "$REPO" && nohup uv run python -m backend.main > /tmp/llmcouncil_backend.log 2>&1 & )
( cd "$REPO" && nohup npm --prefix frontend run dev > /tmp/llmcouncil_frontend.log 2>&1 & )

echo "==> Waiting for servers to come up..."
for i in $(seq 1 45); do
  B=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8001/ 2>/dev/null)
  F=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:5173/ 2>/dev/null)
  [ "$B" = "200" ] && [ "$F" = "200" ] && break
  sleep 1
done

echo ""
echo "  Ollama   : $(curl -s -o /dev/null -w '%{http_code}' http://localhost:11434/api/tags 2>/dev/null)   (models: $(ollama ps 2>/dev/null | tail -n +2 | grep -c .) resident)"
echo "  SearXNG  : $(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/ 2>/dev/null)"
echo "  Backend  : $(curl -s -o /dev/null -w '%{http_code}' http://localhost:8001/ 2>/dev/null)"
echo "  Frontend : $(curl -s -o /dev/null -w '%{http_code}' http://localhost:5173/ 2>/dev/null)"
echo ""
echo "==> Open http://localhost:5173  (the backend is warming the 5 fast models in the background)"
