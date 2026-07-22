const DEFAULT_DAEMON = "http://localhost:8787";

async function getDaemonUrl() {
  const { daemonUrl } = await chrome.storage.local.get({ daemonUrl: DEFAULT_DAEMON });
  return daemonUrl || DEFAULT_DAEMON;
}

async function refresh() {
  const health = document.getElementById("health");
  try {
    const daemon = await getDaemonUrl();
    const res = await fetch(`${daemon}/api/health`);
    health.innerHTML = res.ok
      ? '<span class="ok">Daemon online</span>'
      : '<span class="bad">Daemon unreachable</span>';
  } catch {
    health.innerHTML = '<span class="bad">Daemon offline</span>';
  }
}

document.getElementById("open-panel").addEventListener("click", () => {
  chrome.sidePanel.open({ windowId: chrome.windows.WINDOW_ID_CURRENT });
});

refresh();
