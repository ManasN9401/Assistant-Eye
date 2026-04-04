"""
Browser WebSocket Server
Runs a WebSocket server on ws://localhost:8765.
The Chrome extension connects here; this server relays commands
and receives results.

Usage:
    server = BrowserWSServer(settings)
    await server.start()
    result = await server.execute_js("document.title")
    await server.navigate("https://example.com")
    text = await server.get_content("body")
    await server.stop()
"""
from __future__ import annotations
import asyncio
import json
import logging
import uuid
from typing import Any, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

log = logging.getLogger(__name__)

PORT = 8765


class BrowserWSServer:
    """
    Async WebSocket server.  Wraps websockets library.
    One client (the Chrome extension) is expected at a time.
    """

    def __init__(self, settings=None):
        self.settings = settings
        self._websocket = None          # active extension connection
        self._pending: dict[str, asyncio.Future] = {}
        self._page_info: dict = {}
        self._server = None
        self._on_page_change_cb = None  # callable(url, title)
        self._on_user_command_cb = None # callable(text)

    def on_page_change(self, cb):
        self._on_page_change_cb = cb

    def on_user_command(self, cb):
        self._on_user_command_cb = cb

    async def start(self):
        import websockets
        self._server = await websockets.serve(
            self._handler, "localhost", PORT
        )
        log.info(f"[ARIA Bridge] Listening on ws://localhost:{PORT}")

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    @property
    def is_connected(self) -> bool:
        return self._websocket is not None

    # ── WebSocket handler ─────────────────────────────────────────────────────

    async def _handler(self, websocket):
        self._websocket = websocket
        log.info("[ARIA Bridge] Extension connected")
        # Send current assistant name on connection
        if self.settings:
            await self.send_assistant_name(self.settings.assistant_name)
        try:
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                await self._dispatch(msg)
        except Exception:
            pass
        finally:
            self._websocket = None
            log.info("[ARIA Bridge] Extension disconnected")

    async def _dispatch(self, msg: dict):
        t = msg.get("type")
        log.debug("BrowserWS received: %s", msg)

        if t == "pong":
            return

        if t == "result" or t == "error":
            req_id = msg.get("id")
            if req_id and req_id in self._pending:
                fut = self._pending.pop(req_id)
                if t == "error":
                    fut.set_exception(RuntimeError(msg.get("message", "unknown")))
                else:
                    fut.set_result(msg.get("value"))
            return

        if t == "page_info":
            self._page_info = {"url": msg.get("url", ""), "title": msg.get("title", "")}
            log.debug("Page info updated: %s", self._page_info)
            if self._on_page_change_cb:
                self._on_page_change_cb(self._page_info["url"], self._page_info["title"])
            return

        if t == "user_command":
            text = msg.get("text", "")
            log.debug("User command received from extension: %s", text)
            if text and self._on_user_command_cb:
                self._on_user_command_cb(text)
            return

    # ── Request helpers ───────────────────────────────────────────────────────

    async def _request(self, payload: dict, timeout: float = 10.0) -> Any:
        if not self._websocket:
            raise RuntimeError("Browser extension not connected")
        req_id = str(uuid.uuid4())[:8]
        payload["id"] = req_id
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut
        await self._websocket.send(json.dumps(payload))
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise TimeoutError(f"Browser did not respond within {timeout}s")

    async def execute_js(self, code: str) -> Any:
        return await self._request({"type": "execute_js", "code": code})

    async def navigate(self, url: str) -> str:
        return await self._request({"type": "navigate", "url": url}, timeout=20.0)

    async def get_content(self, selector: str = "body") -> str:
        return await self._request({"type": "get_content", "selector": selector})

    async def get_page_info(self) -> dict:
        return self._page_info

    async def ping(self):
        if self._websocket:
            await self._websocket.send(json.dumps({"type": "ping"}))

    async def send_assistant_name(self, name: str):
        """Send the assistant name to the extension for display."""
        if self._websocket:
            await self._websocket.send(json.dumps({"type": "assistant_name", "name": name}))


# ── Qt thread wrapper ─────────────────────────────────────────────────────────

class BrowserBridgeThread(QThread):
    """
    Runs the asyncio event loop + WebSocket server in a background thread.
    Provides a synchronous-friendly interface via run_coro().
    """
    connected    = pyqtSignal()
    disconnected = pyqtSignal()
    page_changed = pyqtSignal(str, str)   # url, title
    user_command = pyqtSignal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.server = BrowserWSServer(settings)

    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self.server.on_page_change(
            lambda url, title: self.page_changed.emit(url, title)
        )
        self.server.on_user_command(
            lambda text: self.user_command.emit(text)
        )

        self._loop.run_until_complete(self.server.start())
        self._loop.run_forever()

    def stop(self):
        if self._loop:
            self._loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(self._shutdown())
            )

    async def _shutdown(self):
        await self.server.stop()
        asyncio.get_event_loop().stop()

    def run_coro(self, coro) -> asyncio.Future:
        """Schedule a coroutine on the bridge event loop from any thread."""
        if self._loop:
            return asyncio.run_coroutine_threadsafe(coro, self._loop)
        raise RuntimeError("Bridge not running")

    # ── Convenience sync wrappers (call from Qt main thread) ─────────────────

    def execute_js(self, code: str, callback=None):
        """Fire-and-forget JS execution. callback(result_or_exception) if given."""
        fut = self.run_coro(self.server.execute_js(code))
        if callback:
            fut.add_done_callback(
                lambda f: callback(f.exception() or f.result())
            )

    def navigate(self, url: str, callback=None):
        fut = self.run_coro(self.server.navigate(url))
        if callback:
            fut.add_done_callback(
                lambda f: callback(f.exception() or f.result())
            )

    def get_content(self, selector: str = "body", callback=None):
        fut = self.run_coro(self.server.get_content(selector))
        if callback:
            fut.add_done_callback(
                lambda f: callback(f.exception() or f.result())
            )

    def send_assistant_name(self, name: str):
        """Send the assistant name to the extension."""
        self.run_coro(self.server.send_assistant_name(name))
