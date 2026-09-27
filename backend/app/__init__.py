"""Load shared repository settings before any backend modules read them."""

from pathlib import Path

from dotenv import load_dotenv

# Resolve from this file so uvicorn, scripts and tests work from any directory.
# Explicit shell/deployment variables retain priority over the local file.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
