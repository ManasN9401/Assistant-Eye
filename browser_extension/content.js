/**
 * EYE Content Script
 * Injected into every page. Exposes __aria on window so registry
 * action scripts can call helper functions.
 * Also observes DOM changes to keep the extension background aware
 * of SPA navigations.
 */

(function () {
  "use strict";

  if (window.__ariaInjected) return;
  window.__ariaInjected = true;

  // ── Helper utilities exposed to registry JS actions ──────────────────────

  window.__aria = window.__aria || {};

  /**
   * Toggle dark mode using common patterns found on most sites.
   * Registry JS can call window.__aria.toggleDark() or define its own.
   */
  window.__aria.toggleDark = function () {
    const html = document.documentElement;
    // Pattern 1: data-theme attribute
    if (html.dataset.theme) {
      html.dataset.theme = html.dataset.theme === "dark" ? "light" : "dark";
      return;
    }
    // Pattern 2: class on html or body
    for (const el of [html, document.body]) {
      if (el.classList.contains("dark")) {
        el.classList.remove("dark");
        return;
      }
    }
    html.classList.add("dark");
  };

  /**
   * Smooth-scroll the page by a relative amount in pixels.
   */
  window.__aria.scroll = function (dy) {
    window.scrollBy({ top: dy, behavior: "smooth" });
  };

  /**
   * Click the first element matching a CSS selector.
   */
  window.__aria.click = function (selector) {
    const el = document.querySelector(selector);
    if (el) el.click();
    return !!el;
  };

  /**
   * Fill a form field.
   */
  window.__aria.fill = function (selector, value) {
    const el = document.querySelector(selector);
    if (!el) return false;
    el.focus();
    el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  };

  /**
   * Return text content of a selector (for AI scraping).
   */
  window.__aria.getText = function (selector) {
    return document.querySelector(selector)?.innerText ?? "";
  };

  /**
   * Highlight an element briefly so the user can see what ARIA acted on.
   */
  window.__aria.highlight = function (selector, durationMs = 1200) {
    const el = document.querySelector(selector);
    if (!el) return;
    const prev = el.style.outline;
    el.style.outline = "2px solid #e8a020";
    el.style.outlineOffset = "2px";
    setTimeout(() => {
      el.style.outline = prev;
      el.style.outlineOffset = "";
    }, durationMs);
  };

  // ── SPA navigation observer ───────────────────────────────────────────────
  // Many modern sites update the URL without a full page load.
  // We observe pushState / popstate to keep the background informed.

  let _lastUrl = location.href;

  const _sendNav = () => {
    if (location.href !== _lastUrl) {
      _lastUrl = location.href;
      // Content → background doesn't use WebSocket directly;
      // the background already listens to tabs.onUpdated.
      // This is just a local hook for any page-level listeners.
      window.dispatchEvent(new CustomEvent("aria:navigation", {
        detail: { url: location.href, title: document.title },
      }));
    }
  };

  const _origPush = history.pushState.bind(history);
  history.pushState = function (...args) {
    _origPush(...args);
    _sendNav();
  };
  window.addEventListener("popstate", _sendNav);

  console.debug("[EYE] Content script loaded on", location.hostname);
})();
