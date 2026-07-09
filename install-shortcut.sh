#!/bin/bash
# install-shortcut.sh — add a `council` shell shortcut (up / down / status) so you
# can run the app from anywhere without cd-ing into the repo.
#
#   ./install-shortcut.sh      # appends a `council` function to your shell profile
#   source ~/.zshrc            # activate it (or just open a new terminal)
#   council up | council down | council status

set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

# Pick the shell profile (macOS defaults to zsh)
case "${SHELL##*/}" in
  bash) PROFILE="$HOME/.bashrc" ;;
  *)    PROFILE="$HOME/.zshrc" ;;
esac

if grep -q "^council()" "$PROFILE" 2>/dev/null; then
  echo "A 'council' function already exists in $PROFILE — leaving it as-is."
  echo "Remove that block first if you want to re-point it at $REPO."
  exit 0
fi

cat >> "$PROFILE" <<EOF

# LLM Council — quick controls (added by install-shortcut.sh)
council() {
  case "\$1" in
    up|start|restart) "$REPO/restart-council.sh" ;;
    down|stop)        "$REPO/stop-council.sh" ;;
    status) curl -s -o /dev/null -w "backend %{http_code} " http://localhost:8001/ ; curl -s -o /dev/null -w "frontend %{http_code}\n" http://localhost:5173/ ;;
    *) echo "usage: council {up|down|status}" ;;
  esac
}
EOF

echo "Added 'council' to $PROFILE  (repo: $REPO)"
echo "Activate it:  source $PROFILE   (or open a new terminal)"
echo "Then use:     council up | council down | council status"
