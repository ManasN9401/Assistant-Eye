// popup.js — EYE Extension popup controller

const dot  = document.getElementById("status-dot");
const text = document.getElementById("status-text");
const nameElement = document.getElementById("assistant-name");
const cmdInput = document.getElementById("cmd-input");
const cmdButton = document.getElementById("cmd-send");

let currentAssistantName = "EYE";

// Get current status and name from background
chrome.runtime.sendMessage({ type: "get_status" }, (resp) => {
  if (chrome.runtime.lastError) return;
  updateStatus(resp?.status ?? "disconnected");
  if (resp?.name) {
    currentAssistantName = resp.name;
    updateAssistantName(resp.name);
  }
});

// Listen for status updates pushed from background
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "status") updateStatus(msg.status);
  if (msg.type === "assistant_name") {
    currentAssistantName = msg.name;
    updateAssistantName(msg.name);
  }
  if (msg.type === "page_info") {
    document.getElementById("page-title").textContent = msg.title || "—";
    document.getElementById("page-url").textContent =
      msg.url?.replace(/^https?:\/\//, "").substring(0, 45) || "—";
  }
});

function updateStatus(status) {
  dot.className = "dot " + (status === "connected" ? "connected" : status === "error" ? "error" : "");
  text.textContent =
    status === "connected"    ? `Connected to ${currentAssistantName} app` :
    status === "disconnected" ? `${currentAssistantName} app not running` :
    status === "error"        ? "Connection error" : "—";
}

function updateAssistantName(name) {
  currentAssistantName = name;
  nameElement.textContent = name.toUpperCase();
  cmdInput.placeholder = `Ask ${name}…`;
  cmdButton.textContent = `Send to ${name} →`;
  // Re-render status text with updated name
  chrome.runtime.sendMessage({ type: "get_status" }, (resp) => {
    if (!chrome.runtime.lastError) {
      updateStatus(resp?.status ?? "disconnected");
    }
  });
}


// Send command to background → Python bridge
document.getElementById("cmd-send").addEventListener("click", () => {
  const val = document.getElementById("cmd-input").value.trim();
  if (!val) return;
  chrome.runtime.sendMessage({ type: "user_command", text: val });
  document.getElementById("cmd-input").value = "";
  window.close();
});

document.getElementById("cmd-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") document.getElementById("cmd-send").click();
});

document.getElementById("open-panel").addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "open_panel" });
  window.close();
});

document.getElementById("toggle-dark").addEventListener("click", () => {
  chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
    if (tab) {
      chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => window.__aria?.toggleDark(),
      });
    }
  });
  window.close();
});
