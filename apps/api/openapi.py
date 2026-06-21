"""Deterministic OpenAPI export — `python -m apps.api.openapi`.

Outputs the OpenAPI spec to stdout. CI diffs it against web/openapi.json
to detect drift between backend schema and the generated TS client.
"""

from __future__ import annotations

import json
import sys

from apps.api.app import create_app


def main() -> None:
    app = create_app()
    schema = app.openapi()
    json.dump(schema, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
