#!/usr/bin/env bash
# run.sh — one-command launcher for the AI Studio Web-UI Agent.
#
# Usage:
#   ./run.sh              # install deps + launch web UI on port 8000
#   ./run.sh --port 9000  # custom port
#   ./run.sh --login      # just run the manual Google login flow
#   ./run.sh --test       # just run the E2E test suite

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# 1. Activate the shared repo-level virtualenv (created at repo root).
if [ ! -d "$PROJECT_ROOT/venv" ]; then
    echo "[setup] creating shared virtualenv at repo root..."
    python3 -m venv "$PROJECT_ROOT/venv"
fi
source "$PROJECT_ROOT/venv/bin/activate"

# 2. Install deps if not present.
if ! python -c "import playwright, fastapi, uvicorn" 2>/dev/null; then
    echo "[setup] installing dependencies (root requirements.txt)..."
    pip install --upgrade pip
    pip install -r "$PROJECT_ROOT/requirements.txt"
fi

# 3. Install Playwright browsers if not present.
if [ ! -d "$HOME/.cache/ms-playwright/chromium-1228" ] && \
   [ ! -d "$HOME/.cache/ms-playwright/chromium-1200" ]; then
    echo "[setup] installing Playwright Chromium..."
    playwright install chromium
    playwright install-deps chromium 2>/dev/null || true
fi

# 4. Route to the requested action.
case "${1:-serve}" in
    --login)
        python login.py "${@:2}"
        ;;
    --test)
        python test_all.py "${@:2}"
        ;;
    serve|--port|*)
        # Default: launch the web UI.
        PORT=8000
        if [ "$1" = "--port" ] && [ -n "$2" ]; then
            PORT="$2"
        fi
        echo ""
        echo "=============================================="
        echo "  AI Studio Agent — Local Web UI"
        echo "  Open: http://localhost:$PORT"
        echo "=============================================="
        echo ""
        echo "First time? Click 'Login to Google' in the UI,"
        echo "or run: ./run.sh --login"
        echo ""
        python web_ui.py --port "$PORT"
        ;;
esac
