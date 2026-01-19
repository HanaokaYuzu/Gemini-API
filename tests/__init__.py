from pathlib import Path
import sys

# Ensure src layout is importable in tests without an editable install.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.is_dir():
    sys.path.insert(0, str(SRC))
