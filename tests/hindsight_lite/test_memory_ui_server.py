import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from hindsight_lite.memory_ui_server import create_memory_ui_server, memory_ui_server_url
from hindsight_lite.store import LocalMemoryStore

_OPENER = build_opener(ProxyHandler({}))


def test_memory_ui_server_serves_editable_ui_and_saves_existing_page(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.write_page(
        page_id="preference",
        title="Preference",
        content="I like lemon water.",
        tags=["user"],
        metadata={"source": "test"},
    )
    server = create_memory_ui_server(store)
    thread = Thread(target=server.serve_forever)
    thread.start()

    try:
        url = memory_ui_server_url(server)
        with _OPENER.open(url) as response:
            html = response.read().decode("utf-8")
        assert '"save_url": "/api/pages"' in html

        request = Request(
            f"{url}api/pages/preference",
            data=json.dumps({"content": "I like sparkling water."}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with _OPENER.open(request) as response:
            result = json.loads(response.read())

        saved = store.get_page("preference")
        assert result["id"] == "preference"
        assert saved.content == "I like sparkling water."
        assert saved.title == "Preference"
        assert saved.tags == ["user"]
        assert saved.metadata == {"source": "test"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_memory_ui_server_uses_explicit_bind_host(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    server = create_memory_ui_server(store, host="127.0.0.1")
    try:
        assert memory_ui_server_url(server).startswith("http://127.0.0.1:")
    finally:
        server.server_close()


def test_memory_ui_server_refuses_to_create_or_escape_pages(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    server = create_memory_ui_server(store)
    thread = Thread(target=server.serve_forever)
    thread.start()

    try:
        url = memory_ui_server_url(server)
        for page_id in ("missing", "%2E%2E%2Foutside"):
            request = Request(
                f"{url}api/pages/{page_id}",
                data=json.dumps({"content": "should not be written"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="PUT",
            )
            try:
                _OPENER.open(request)
            except HTTPError as exc:
                assert exc.code in (400, 404)
            else:
                raise AssertionError("unsafe page update unexpectedly succeeded")
        assert not (tmp_path / "banks" / "outside.md").exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
