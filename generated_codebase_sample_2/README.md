# AI Studio Web-UI Agent

Three PoCs that turn Google AI Studio / Gemini web into an agent backend via
browser automation — no API key required.

See `download/README.md` for full docs.

## Quick start

From the repository root (`../`):

```bash
source venv/bin/activate
cd scripts
pip install -r ../requirements.txt   # install dependencies once
playwright install chromium
./run.sh                             # → http://localhost:8000
```

First time? Click "Login to Google" in the web UI, or run `./run.sh --login`.
