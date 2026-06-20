const DEFAULT_DAEMON = "http://localhost:8787";

chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: false });
});

async function getDaemonUrl() {
  const { daemonUrl } = await chrome.storage.local.get({ daemonUrl: DEFAULT_DAEMON });
  return daemonUrl || DEFAULT_DAEMON;
}

async function updateBadge() {
  const daemon = await getDaemonUrl();
  try {
    const res = await fetch(`${daemon}/api/connections`, { signal: AbortSignal.timeout(5000) });
    const data = await res.json();
    const connected = ["groq", "google", "gmail", "whatsapp", "daemon", "rag"].filter((k) => data[k]?.connected).length;
    const total = 6;
    let pendingCount = 0;
    try {
      const pendingRes = await fetch(`${daemon}/api/pending-actions`, { signal: AbortSignal.timeout(3000) });
      const pendingData = await pendingRes.json();
      pendingCount = (pendingData.actions || []).length;
    } catch {}
    if (pendingCount > 0) {
      chrome.action.setBadgeText({ text: String(pendingCount) });
      chrome.action.setBadgeBackgroundColor({ color: "#3d6cb9" });
    } else if (connected === total) {
      chrome.action.setBadgeText({ text: "" });
      chrome.action.setBadgeBackgroundColor({ color: "#0a0" });
    } else if (connected > 0) {
      chrome.action.setBadgeText({ text: String(total - connected) });
      chrome.action.setBadgeBackgroundColor({ color: "#fa0" });
    } else {
      chrome.action.setBadgeText({ text: "!" });
      chrome.action.setBadgeBackgroundColor({ color: "#c00" });
    }
  } catch {
    chrome.action.setBadgeText({ text: "X" });
    chrome.action.setBadgeBackgroundColor({ color: "#c00" });
  }
}

function showNotification(title, body) {
  chrome.notifications.create({
    type: "basic",
    title: title || "Tempa",
    message: (body || "").slice(0, 240),
    priority: 2,
  });
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "api") {
    getDaemonUrl().then((daemon) =>
      fetch(`${daemon}${msg.path}`, msg.options)
        .then((r) => r.json())
        .then(sendResponse)
        .catch((e) => sendResponse({ error: String(e) }))
    );
    return true;
  }
  if (msg.type === "notify") {
    showNotification(msg.title, msg.body);
  }
});

chrome.notifications.onClicked.addListener(() => {
  chrome.sidePanel.open({ windowId: chrome.windows.WINDOW_ID_CURRENT });
});

setInterval(updateBadge, 20000);
updateBadge();
