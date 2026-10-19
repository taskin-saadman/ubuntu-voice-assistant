"""Start the authenticated local conversation backend for desktop development."""

import secrets
import socket

import uvicorn

from voice_assistant.api import create_app
from voice_assistant.readiness import ComponentName, ReadinessService
from voice_assistant.runtime import VoiceRuntime
from voice_assistant.transport import DesktopTransport


def main() -> None:
    # Bind before displaying a key, so a port conflict cannot pair it with another service.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 8765))
        listener.listen(128)
        token = secrets.token_urlsafe(32)
        runtime = VoiceRuntime()
        app = create_app(
            desktop=DesktopTransport(runtime, token),
            readiness=ReadinessService({ComponentName.LLM: runtime.llm.available}),
        )
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=8765,
            access_log=False,
            proxy_headers=False,
            ws="websockets-sansio",
            ws_max_size=4096,
            ws_max_queue=8,
            ws_ping_interval=5,
            ws_ping_timeout=5,
            ws_per_message_deflate=False,
        )
        print("Local desktop connection key (valid until this backend stops):", flush=True)
        print(token, flush=True)
        uvicorn.Server(config).run(sockets=[listener])


if __name__ == "__main__":
    main()
