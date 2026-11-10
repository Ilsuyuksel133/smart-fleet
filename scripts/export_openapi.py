"""Write the fleet API's OpenAPI schema to web/openapi/fleet-api.json.

The web frontend generates its TypeScript types from this file, and CI checks
that it is up to date, so a backend change cannot silently break the frontend.

    python scripts/export_openapi.py      (or: make openapi)
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "web" / "openapi" / "fleet-api.json"


def main() -> None:
    # Importing the app creates its database engine; an in-memory one leaves no file behind
    os.environ.setdefault("DATABASE_URL", "sqlite://")
    sys.path.insert(0, str(ROOT / "api"))
    from main import app

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
