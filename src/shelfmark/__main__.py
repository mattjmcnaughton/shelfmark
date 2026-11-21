"""Production entry point: ``python -m shelfmark`` serves on $PORT."""

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "shelfmark.app:build_app",
        factory=True,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )


if __name__ == "__main__":
    main()
