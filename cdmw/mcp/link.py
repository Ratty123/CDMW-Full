"""The app's end of AI connections: on while "Allow AI connections" is on (P13 stage C).

``start`` writes a new per-session token to ``workspace\\ai-connection.token``
(readable by the current user only) and starts listening on the pipe;
``stop`` stops listening, ends the connected app's connection and deletes the
token file. Nothing listens and no token file exists while it is stopped.

No Qt here; the Qt side (``cdmw.ui.ai_connections``) owns one link per app
and calls ``start`` and ``stop`` when the setting changes.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from cdmw.mcp import transport


class AiConnectionLink:
    def __init__(self, serve: Callable[[object], None], *, on_refused: Callable[[str], None] | None = None) -> None:
        self._serve = serve
        self._on_refused = on_refused or (lambda _reason: None)
        self._lock = threading.Lock()
        self._pipe: transport.McpPipeServer | None = None
        self.address = ""
        self.token_file = transport.token_path()

    @property
    def listening(self) -> bool:
        return self._pipe is not None

    @property
    def connected(self) -> bool:
        pipe = self._pipe
        return pipe is not None and pipe.connected > 0

    def start(self) -> None:
        with self._lock:
            if self._pipe is not None:
                return
            token = transport.new_token()
            self.address = transport.pipe_address()
            # Listen first: a token without a pipe would only send a client to a closed door.
            pipe = transport.McpPipeServer(self.address, token, self._serve, refused=self._on_refused)
            try:
                transport.write_token_file(self.token_file, token)
            except Exception:
                pipe.stop()
                raise
            pipe.start()
            self._pipe = pipe

    def stop(self) -> None:
        with self._lock:
            pipe, self._pipe = self._pipe, None
            try:
                if pipe is not None:
                    pipe.stop()
            finally:
                transport.remove_token_file(self.token_file)
