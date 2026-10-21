"""Make the engine importable without Home Assistant: it is a standalone module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "custom_components" / "sports_replay"))
