"""Entrada FastAPI para Vercel."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from servidor_recuperacion import app  # noqa: E402
