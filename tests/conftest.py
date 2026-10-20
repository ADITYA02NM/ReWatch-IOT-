import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
for p in ("common", "pi4-core", "pi3-sentinel", "pi3-herald"):
    sys.path.insert(0, str(ROOT / p))
