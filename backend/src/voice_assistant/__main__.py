"""Run the Phase 2 health server, with a fixed loopback bind and no model loading."""

import uvicorn


def main() -> None:
    uvicorn.run(
        "voice_assistant.api:create_app",
        factory=True,
        host="127.0.0.1",
        port=8765,
        access_log=False,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
