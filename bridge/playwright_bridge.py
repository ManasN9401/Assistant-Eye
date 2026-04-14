"""
Playwright Bridge — full implementation for Phase 2.
Controls a headless or headed Chromium browser for automated testing.
Also contains the unified ActionExecutor.
"""
from __future__ import annotations
import asyncio
import json
import logging
import re
from typing import Any, Optional


log = logging.getLogger(__name__)

class PlaywrightBridge:
    def __init__(self, settings, engine=None):
        self.settings = settings
        self.engine = engine
        self._browser = None
        self._page = None
        self._playwright = None

    async def launch(self, headless: bool = False, url: str = ""):
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=headless)
        ctx = await self._browser.new_context()
        self._page = await ctx.new_page()
        target = url or self.settings.get("active_site_url", "")
        if target:
            await self._page.goto(target)

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._page = None

    async def navigate(self, url: str):
        if self._page:
            await self._page.goto(url)

    async def evaluate(self, code: str) -> Any:
        if not self._page:
            raise RuntimeError("Browser not launched")
        return await self._page.evaluate(code)

    async def get_text(self, selector: str = "body") -> str:
        if not self._page:
            return ""
        try:
            return await self._page.inner_text(selector)
        except Exception:
            return ""

    async def screenshot(self, path: str = "/tmp/aria-screenshot.png"):
        if self._page:
            await self._page.screenshot(path=path)

    @property
    def is_running(self) -> bool:
        return bool(self._browser and self._browser.is_connected())


class ActionExecutor:
    """
    Executes registry actions using whichever browser backend is available.
      1. Extension bridge (ws_server.BrowserBridgeThread) - preferred for live browsing
      2. Playwright - preferred for automated testing / headless
    """

    def __init__(self, settings, engine, playwright: PlaywrightBridge, browser_bridge=None):
        self.settings = settings
        self.engine = engine
        self.playwright = playwright
        self.browser_bridge = browser_bridge

    def execute_action(self, fn_def: dict, params: dict) -> str:
        try:
            return asyncio.run(self._execute_async(fn_def, params))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self._execute_async(fn_def, params))
            finally:
                loop.close()

    async def _execute_async(self, fn_def: dict, params: dict) -> str:
        action_type = fn_def.get("action_type", "js")
        action      = fn_def.get("action", "")
        for k, v in params.items():
            action = action.replace(f"{{{{{k}}}}}", str(v))

        if action_type == "js":
            return await self._run_js(action)
        if action_type == "navigate":
            return await self._run_navigate(action)
        if action_type == "ai_reason":
            return await self._run_ai_reason(action, params)
        if action_type == "native":
            return self._run_native(action)
        return f"Unknown action type: {action_type}"

    async def _run_js(self, code: str) -> str:
        bridge_connected = bool(self.browser_bridge and self.browser_bridge.server.is_connected)
        log.debug("_run_js called; browser_bridge_connected=%s, playwright_running=%s", bridge_connected, self.playwright.is_running)
        if bridge_connected:
            log.debug("Sending JS to browser bridge: %s", code)
            fut = self.browser_bridge.run_coro(self.browser_bridge.server.execute_js(code))
            try:
                result = await asyncio.wrap_future(fut)
                log.debug("Browser bridge JS result: %s", result)
                return f"Done: {result}"
            except Exception as exc:
                log.exception("Browser bridge JS execution failed")
                return f"Browser bridge error: {exc}"
        if self.playwright.is_running:
            result = await self.playwright.evaluate(code)
            log.debug("Playwright JS result: %s", result)
            return f"Done: {result}"
        log.warning("No browser connected; cannot execute JS action")
        return "No browser connected"

    async def _run_navigate(self, path: str) -> str:
        base = self.settings.get("active_site_url", "").rstrip("/")
        url  = base + path if path.startswith("/") else path
        if self.browser_bridge and self.browser_bridge.server.is_connected:
            fut = self.browser_bridge.run_coro(self.browser_bridge.server.navigate(url))
            await asyncio.wrap_future(fut)
            return f"Navigated to {url}"
        if self.playwright.is_running:
            await self.playwright.navigate(url)
            return f"Navigated to {url}"
        return "No browser connected"

    async def _run_ai_reason(self, action_hint: str, params: dict) -> str:
        if not self.engine:
            return "AI engine not available"
        scrape_url = None
        base = self.settings.get("active_site_url", "").rstrip("/")
        if "pricing" in action_hint.lower():
            scrape_url = base + "/pages/pricing.html"
        elif "doc" in action_hint.lower():
            scrape_url = base + "/pages/docs.html"
        content = ""
        if scrape_url:
            if self.playwright.is_running:
                await self.playwright.navigate(scrape_url)
                await asyncio.sleep(1)
                content = await self.playwright.get_text("body")
            elif self.browser_bridge and self.browser_bridge.server.is_connected:
                fut = self.browser_bridge.run_coro(self.browser_bridge.server.navigate(scrape_url))
                await asyncio.wrap_future(fut)
                await asyncio.sleep(1)
                fut2 = self.browser_bridge.run_coro(self.browser_bridge.server.get_content("body"))
                content = await asyncio.wrap_future(fut2)
        if not content:
            return "Could not retrieve page content"
        content = content[:5000]
        prompt = (
            f"Page content:\n\n{content}\n\n"
            f"User question/params: {json.dumps(params)}\n\n"
            "Give a helpful, concise answer based on the page content."
        )
        return self.engine.chat(prompt)

    def _run_native(self, cmd: str) -> str:
        try:
            import os
            # On Windows, os.startfile opens URLs, Protocols (spotify:), or EXE paths
            os.startfile(cmd)
            return f"Launched native target: {cmd}"
        except Exception as e:
            log.exception("Native launch failed")
            return f"Error launching native app: {e}"


def parse_action_from_ai(text: str):
    pattern = r'\{[^{}]*"action"[^{}]*\}'
    m = re.search(pattern, text)
    if not m:
        return None, text
    try:
        action = json.loads(m.group())
        rest = (text[:m.start()] + text[m.end():]).strip()
        return action, rest
    except json.JSONDecodeError:
        return None, text
