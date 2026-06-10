from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from hindsight_lite.memory_ui import render_memory_ui
from hindsight_lite.store import LocalMemoryStore, PageNotFoundError, UnsafePageIdError

_MAX_REQUEST_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class PageUpdate:
    content: str


@dataclass(frozen=True)
class PageUpdateResponse:
    id: str
    updated_at: str | None


def create_memory_ui_server(store: LocalMemoryStore, port: int = 0) -> ThreadingHTTPServer:
    handler = _handler_for_store(store)
    # The UI can rewrite memory pages, so it must never listen beyond the local machine.
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def memory_ui_server_url(server: ThreadingHTTPServer) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}/"


def _handler_for_store(store: LocalMemoryStore) -> type[BaseHTTPRequestHandler]:
    class MemoryUiHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if urlparse(self.path).path != "/":
                self._write_text(HTTPStatus.NOT_FOUND, "not found")
                return
            html = render_memory_ui(store, save_url="/api/pages")
            self._write_bytes(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8")

        def do_PUT(self) -> None:
            path = urlparse(self.path).path
            prefix = "/api/pages/"
            if not path.startswith(prefix):
                self._write_text(HTTPStatus.NOT_FOUND, "not found")
                return

            page_id = unquote(path.removeprefix(prefix))
            try:
                update = self._read_page_update()
                page = store.get_page(page_id)
                saved = store.write_page(
                    page_id=page.id,
                    title=page.title,
                    content=update.content,
                    tags=page.tags,
                    metadata=page.metadata,
                )
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                self._write_text(HTTPStatus.BAD_REQUEST, "invalid page update")
                return
            except (PageNotFoundError, UnsafePageIdError):
                self._write_text(HTTPStatus.NOT_FOUND, "page not found")
                return

            response = PageUpdateResponse(id=saved.id, updated_at=saved.updated_at)
            body = json.dumps(asdict(response)).encode("utf-8")
            self._write_bytes(HTTPStatus.OK, body, "application/json; charset=utf-8")

        def log_message(self, format: str, *args: object) -> None:
            return

        def _read_page_update(self) -> PageUpdate:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > _MAX_REQUEST_BYTES:
                raise ValueError("invalid content length")
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            if not isinstance(payload, Mapping) or not isinstance(payload.get("content"), str):
                raise ValueError("content must be a string")
            return PageUpdate(content=payload["content"])

        def _write_text(self, status: HTTPStatus, text: str) -> None:
            self._write_bytes(status, text.encode("utf-8"), "text/plain; charset=utf-8")

        def _write_bytes(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return MemoryUiHandler
