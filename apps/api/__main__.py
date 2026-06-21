"""Run the API: `python -m apps.api` (dev convenience)."""
from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run(
        "apps.api.app:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104  — explicit bind for container/uvicorn
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
