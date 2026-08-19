#!/usr/bin/env python3
"""Backward-compatible CLI wrapper for gemini-webapi.

This file is kept so that ``python cli.py`` continues to work from a source
checkout. The actual implementation lives in ``gemini_webapi.cli`` and is
installed as the ``gemini-webapi`` console script via ``[project.scripts]``.
"""

import sys
from pathlib import Path

# Run straight from a source checkout, without the package having to be installed
if (_src := str(Path(__file__).resolve().parent / "src")) not in sys.path:
    sys.path.insert(0, _src)

from gemini_webapi.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
