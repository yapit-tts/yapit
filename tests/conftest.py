from pathlib import Path

from dotenv import load_dotenv

_root = Path(__file__).resolve().parent.parent
load_dotenv(_root / ".env")  # secrets (takes precedence)
load_dotenv(_root / ".env.dev")  # non-secret config (fills gaps)
