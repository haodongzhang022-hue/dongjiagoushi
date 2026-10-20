# -*- coding: utf-8 -*-
"""`python -m intent` 入口 → 承接侧 CLI。"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from intent.take_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
