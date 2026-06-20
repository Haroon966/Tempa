const DEFAULT_DAEMON = "http://localhost:8787";

async function getDaemonUrl() {
  const { daemonUrl } = await chrome.storage.local.get({ daemonUrl: DEFAULT_DAEMON });
  return daemonUrl || DEFAULT_DAEMON;
}

async function refresh() {
  const daemon = await getDaemonUrl();
  const health = document.getElementById("health");
  const qrImg = document.getElementById("qr");
  try {
    const conn = await fetch(`${daemon}/api/connections`).then((r) => r.json());
    const ok = ["groq", "google", "gmail", "whatsapp", "daemon"].every((k) => conn[k]?.connected);
    health.innerHTML = ok
      ? '<span class="ok">All connections OK</span>'
      : `<span class="bad">Partial: ${Object.entries(conn).map(([k, v]) => `${k}:${v.status}`).join(", ")}</span>`;
    const wa = await fetch(`${daemon}/api/connections/whatsapp?qr=1`).then((r) => r.json());
    if (wa.qr_code) {
      qrImg.src = wa.qr_code.startsWith("data:") ? wa.qr_code : `data:image/png;base64,${wa.qr_code}`;
      qrImg.style.display = "block";
    } else {
      qrImg.style.display = "none";
    }
    if (wa.needs_qr_rescan) {
      health.innerHTML = '<span class="bad">WhatsApp disconnected — scan QR</span>';
    }
  } catch (e) {
    health.innerHTML = `<span class="bad">Daemon offline</span>`;
    qrImg.style.display = "none";
  }
}

document.getElementById("open-panel").addEventListener("click", () => {
  chrome.sidePanel.open({ windowId: chrome.windows.WINDOW_ID_CURRENT });
});

document.getElementById("refresh").addEventListener("click", refresh);
refresh();
