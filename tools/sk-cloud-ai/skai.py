#!/usr/bin/env python3
"""Launch the Cloud AI source tool without installing a package."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sk_cloud_ai.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
