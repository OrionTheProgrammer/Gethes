from __future__ import annotations

import sys
import traceback

from gethes.app import GethesApp


if __name__ == "__main__":
    try:
        app = GethesApp()
        app.run()
    except Exception as exc:
        traceback.print_exc()
        sys.stderr.write(f"[fatal] Gethes terminated with unhandled error: {type(exc).__name__}: {exc}\n")
        sys.exit(1)
