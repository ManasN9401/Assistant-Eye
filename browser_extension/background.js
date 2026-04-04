/**
 * EYE Extension — Background Service Worker
 *
 * Maintains a persistent WebSocket connection to the Python EYE app
 * (ws://localhost:8765). When the Python side sends a command, this
 * worker executes it in the active tab's content script.
 *
 * Message protocol (JSON):
 *
 *   Python → Extension:
 *     { "type": "execute_js",  "code": "...",        "id": "req-123" }
 *     { "type": "navigate",    "url": "...",          "id": "req-124" }
 *     { "type": "get_content", "selector": "body",   "id": "req-125" }
 *     { "type": "ping" }
 *
 *   Extension → Python:
 *     { "type": "result",  "id": "req-123", "value": "..." }
 *     { "type": "error",   "id": "req-123", "message": "..." }
 *     { "type": "page_info", "url": "...", "title": "..." }
 *     { "type": "pong" }
 */

const WS_URL = "ws://localhost:8765";
const RECONNECT_DELAY = 3000;

let ws = null;
let reconnectTimer = null;
let currentStatus = "disconnected";  // tracked so popup can query it at any time
let currentAssistantName = "EYE";     // tracked so popup can query it at any time

function connect() {
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    console.log("[EYE] Connected to Python bridge");
    clearTimeout(reconnectTimer);
    broadcastStatus("connected");
    sendCurrentPageInfo();
  };

  ws.onmessage = async (event) => {
    let msg;
    try { msg = JSON.parse(event.data); }
    catch { return; }
    await handleMessage(msg);
  };

  ws.onclose = () => {
    console.log("[EYE] Disconnected. Reconnecting in 3s…");
    broadcastStatus("disconnected");
    ws = null;
    reconnectTimer = setTimeout(connect, RECONNECT_DELAY);
  };

  ws.onerror = (err) => {
    console.warn("[ARIA] WebSocket error:", err);
  };
}

async function handleMessage(msg) {
  const { type, id } = msg;

  if (type === "ping") {
    send({ type: "pong" });
    return;
  }

  if (type === "assistant_name") {
    currentAssistantName = msg.name || "EYE";
    console.log("[EYE] Received assistant name update:", currentAssistantName);
    broadcastToPopups({ type: "assistant_name", name: currentAssistantName });
    return;
  }

  // For all page-related operations, find a suitable tab.
  const isValidTab = (candidate) => {
    return candidate && candidate.url && !candidate.url.startsWith("chrome://") && !candidate.url.startsWith("chrome-extension://");
  };

  let [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!isValidTab(tab)) {
    const tabs = await chrome.tabs.query({ currentWindow: true });
    tab = tabs.find(isValidTab);
    if (tab) {
      console.warn("[EYE] active tab invalid, falling back to first normal tab in current window:", tab.url);
    }
  }

  if (!isValidTab(tab)) {
    const allTabs = await chrome.tabs.query({});
    tab = allTabs.find(isValidTab);
    console.warn("[EYE] no valid current-window tab, falling back to first normal tab across all windows:", tab?.url);
  }

  if (!isValidTab(tab)) {
    send({ type: "error", id, message: "No browser tab available for execution" });
    return;
  }

  if (type === "execute_js") {
    try {
      console.log("[EYE] executing JS on tab", tab.id, "URL:", tab.url, "Code:", msg.code);
      
      const usesAria = msg.code.includes("__aria");
      
      if (usesAria) {
        // Execute in the page MAIN world to access page/context helpers directly.
        const [result] = await chrome.scripting.executeScript({
          target: { tabId: tab.id },
          world: "MAIN",
          func: (code) => {
            // eslint-disable-next-line no-eval
            return eval(code);
          },
          args: [msg.code],
        });
        const returnValue = result?.result ?? null;
        console.log("[EYE] JS execution result (MAIN world):", returnValue);
        send({ type: "result", id, value: returnValue });
        return;
      }

      // For non-__aria code, use isolated world (safer)
      const [result] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (code) => {
          // eslint-disable-next-line no-eval
          const result = eval(code);
          console.log("[Isolated] Eval result:", result);
          return result;
        },
        args: [msg.code],
      });
      const returnValue = result?.result ?? null;
      console.log("[EYE] JS execution result:", returnValue);
      send({ type: "result", id, value: returnValue });
      return;
    } catch (err) {
      console.error("[EYE] JS execution error:", err.message, err.stack);
      send({ type: "error", id, message: err.message });
      return;
    }
  }


  if (type === "navigate") {
    await chrome.tabs.update(tab.id, { url: msg.url });
    // Wait for navigation and report back
    chrome.tabs.onUpdated.addListener(function listener(tabId, info) {
      if (tabId === tab.id && info.status === "complete") {
        chrome.tabs.onUpdated.removeListener(listener);
        send({ type: "result", id, value: "navigated" });
      }
    });
    return;
  }

  if (type === "get_content") {
    try {
      const selector = msg.selector || "body";
      const [result] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (sel) => document.querySelector(sel)?.innerText ?? "",
        args: [selector],
      });
      send({ type: "result", id, value: result?.result ?? "" });
    } catch (e) {
      send({ type: "error", id, message: e.message });
    }
    return;
  }

  if (type === "get_page_info") {
    send({
      type: "page_info",
      id,
      url: tab.url,
      title: tab.title,
    });
    return;
  }

  send({ type: "error", id, message: `Unknown command type: ${type}` });
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj));
  }
}

async function sendCurrentPageInfo() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab) {
    send({ type: "page_info", url: tab.url, title: tab.title });
  }
}

function broadcastStatus(status) {
  currentStatus = status;  // keep state so get_status queries always get the latest
  chrome.runtime.sendMessage({ type: "status", status }).catch(() => {});
}

function broadcastToPopups(msg) {
  // Send message to all popup pages
  chrome.runtime.sendMessage(msg).catch(() => {});
}

// ── Respond to popup's get_status query ──────────────────────────────────────
// The popup opens *after* ws.onopen may have fired, so it can't rely on the
// broadcast alone. It sends get_status on load; we reply with currentStatus.
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "get_status") {
    sendResponse({ status: currentStatus, name: currentAssistantName });
    return true;  // keep channel open for async sendResponse
  }
  if (msg.type === "user_command" && ws && ws.readyState === WebSocket.OPEN) {
    send({ type: "user_command", text: msg.text });
  }
});

// Notify Python when user navigates
chrome.tabs.onUpdated.addListener((_id, info, tab) => {
  if (info.status === "complete" && tab.active) {
    sendCurrentPageInfo();
  }
});

chrome.tabs.onActivated.addListener(() => sendCurrentPageInfo());

connect();
