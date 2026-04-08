"""Root pytest fixtures.

Adds the project root to sys.path so tests can `from engine import ...` etc.
without needing the project to be installed.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
