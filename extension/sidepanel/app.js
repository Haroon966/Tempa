const DEFAULT_DAEMON = "http://localhost:8787";

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

window.addEventListener("message", (event) => {
  if (event.origin !== window.location.origin) return;
  const data = event.data;
  if (data?.type === "google_oauth") {
    void refreshConnections();
  }
});

async function getDaemonUrl() {
  const { daemonUrl } = await chrome.storage.local.get({ daemonUrl: DEFAULT_DAEMON });
  return daemonUrl || DEFAULT_DAEMON;
}

async function api(path, options = {}) {
  const daemon = await getDaemonUrl();
  const res = await fetch(`${daemon}${path}`, options);
  if (!res.ok) throw new Error(await res.text());
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  return res.text();
}

function setTab(name) {
  document.querySelectorAll(".tab").forEach((el) => el.classList.remove("active"));
  document.querySelectorAll("#tabs button").forEach((el) => el.classList.remove("active"));
  document.getElementById(name).classList.add("active");
  document.querySelector(`#tabs button[data-tab="${name}"]`).classList.add("active");
}

document.querySelectorAll("#tabs button").forEach((btn) => {
  btn.addEventListener("click", () => setTab(btn.dataset.tab));
});

function updateQrDisplay(qrCode) {
  const img = document.getElementById("qr-image");
  if (!qrCode) {
    img.style.display = "none";
    return;
  }
  img.src = qrCode.startsWith("data:") ? qrCode : `data:image/png;base64,${qrCode}`;
  img.style.display = "block";
}

async function refreshConnections() {
  try {
    const data = await api("/api/connections");
    const badges = document.getElementById("connection-badges");
    badges.innerHTML = "";
    for (const [key, val] of Object.entries(data)) {
      const span = document.createElement("span");
      span.className = `badge ${val.connected ? "ok" : "bad"}`;
      span.textContent = `${key}: ${val.status}`;
      badges.appendChild(span);
    }
    document.getElementById("google-status").textContent = `Google: ${data.google.status}`;
    document.getElementById("gmail-status").textContent = `Gmail: ${data.gmail?.status ?? "disconnected"}`;
    document.getElementById("groq-status").textContent = `Groq: ${data.groq.status}`;
    try {
      const models = await api("/api/connections/groq/models");
      document.getElementById("groq-models").textContent = `Models: ${Object.keys(models.chains || {}).join(", ")}`;
    } catch {}
  } catch (e) {
    document.getElementById("connection-badges").textContent = `Daemon offline: ${e}`;
  }
}

async function refreshWhatsAppQr() {
  try {
    const data = await api("/api/connections/whatsapp?qr=1&refresh=1");
    updateQrDisplay(data.qr_code);
    document.getElementById("wa-status").textContent = data.needs_qr_rescan
      ? "Disconnected — scan QR to reconnect"
      : JSON.stringify(data.connection_state || data.status);
  } catch (e) {
    document.getElementById("wa-status").textContent = String(e);
  }
}

document.getElementById("save-groq").addEventListener("click", async () => {
  const api_key = document.getElementById("groq-key").value;
  const result = await api("/api/connections/groq", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key }),
  });
  document.getElementById("groq-status").textContent = JSON.stringify(result);
  refreshConnections();
});

document.getElementById("connect-google").addEventListener("click", async () => {
  const result = await api("/api/connections/google", { method: "POST" });
  if (result.authorization_url) window.open(result.authorization_url, "_blank");
});

document.getElementById("connect-gmail").addEventListener("click", async () => {
  const result = await api("/api/connections/gmail", { method: "POST" });
  if (result.authorization_url) window.open(result.authorization_url, "_blank");
});

document.getElementById("refresh-qr").addEventListener("click", refreshWhatsAppQr);

document.getElementById("grant-consent").addEventListener("click", async () => {
  const result = await api("/api/meetings/consent", { method: "POST" });
  document.getElementById("consent-status").textContent = JSON.stringify(result);
});

document.getElementById("stop-daemon").addEventListener("click", async () => {
  await api("/api/daemon/shutdown", { method: "POST" });
  document.getElementById("daemon-status").textContent = "Shutdown requested";
});

document.getElementById("restart-daemon").addEventListener("click", async () => {
  await api("/api/daemon/restart", { method: "POST" });
  document.getElementById("daemon-status").textContent = "Restart requested";
});

document.getElementById("chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("chat-input");
  const message = input.value.trim();
  if (!message) return;
  const log = document.getElementById("chat-log");
  log.innerHTML += `<div><b>You:</b> ${escapeHtml(message)}</div>`;
  input.value = "";

  const daemon = await getDaemonUrl();
  try {
    const health = await fetch(`${daemon}/api/health`);
    if (!health.ok) throw new Error("Daemon offline");
  } catch (err) {
    log.innerHTML += `<div><b>Tempa:</b> ${escapeHtml(String(err.message || err))}</div>`;
    return;
  }

  const res = await fetch(`${daemon}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop();
    for (const part of parts) {
      const dataLine = part.split("\n").find((l) => l.startsWith("data:"));
      if (!dataLine) continue;
      try {
        const payload = JSON.parse(dataLine.slice(5).trim());
        if (payload.content) log.innerHTML += `<div><b>Tempa:</b> ${escapeHtml(payload.content)}</div>`;
        if (payload.error) log.innerHTML += `<div><b>Error:</b> ${escapeHtml(payload.error)}</div>`;
      } catch {}
    }
  }
});

async function loadMeetings() {
  try {
    const data = await api("/api/meetings");
    const list = document.getElementById("meetings-list");
    list.innerHTML = "";
    for (const m of data.meetings || []) {
      const li = document.createElement("li");
      li.innerHTML = `<button class="meeting-btn" data-id="${m.id}">${m.title || m.id}</button>`;
      list.appendChild(li);
    }
    if (!list.children.length) list.innerHTML = "<li>No meetings yet</li>";
    list.querySelectorAll(".meeting-btn").forEach((btn) => {
      btn.addEventListener("click", () => showMeeting(btn.dataset.id));
    });
  } catch (e) {
    document.getElementById("meetings-list").textContent = String(e);
  }
}

async function showMeeting(id) {
  const detail = document.getElementById("meeting-detail");
  const daemon = await getDaemonUrl();
  const data = await api(`/api/meetings/${id}`);
  const m = data.meeting;
  const minutes = m.minutes || {};
  const audioUrl = `${daemon}/api/meetings/${id}/audio`;
  detail.innerHTML = `
    <h3>${m.title || m.id}</h3>
    <p>${m.meet_link || ""}</p>
    <h4>Summary</h4>
    <pre>${minutes.tldr || minutes.summary || "No minutes yet"}</pre>
    <h4>Audio</h4>
    <audio controls src="${audioUrl}"></audio>
    <h4>Transcript</h4>
    <pre class="transcript">${escapeHtml(data.transcript_raw || "")}</pre>
    <button id="delete-meeting" data-id="${id}">Delete meeting</button>
  `;
  document.getElementById("delete-meeting")?.addEventListener("click", async () => {
    await api(`/api/meetings/${id}`, { method: "DELETE" });
    detail.innerHTML = "";
    loadMeetings();
  });
}

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

document.getElementById("memory-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const query = document.getElementById("memory-query").value.trim();
  if (!query) return;
  const data = await api("/api/memory/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_k: 8 }),
  });
  const out = document.getElementById("memory-results");
  out.innerHTML = (data.results || [])
    .map((r) => `<div class="memory-hit"><small>${r.score?.toFixed(2)}</small> ${escapeHtml(r.content)}</div>`)
    .join("") || "No results";
});

async function loadPendingActions() {
  const list = document.getElementById("pending-list");
  if (!list) return;
  try {
    const data = await api("/api/pending-actions");
    list.innerHTML = "";
    for (const action of data.actions || []) {
      const div = document.createElement("div");
      div.className = "card";
      div.innerHTML = `<h3>${escapeHtml(action.title || action.type)}</h3><pre>${escapeHtml(JSON.stringify(action.payload, null, 2))}</pre>`;
      const approve = document.createElement("button");
      approve.textContent = "Approve";
      approve.onclick = async () => {
        await api(`/api/pending-actions/${action.id}/approve`, { method: "POST" });
        loadPendingActions();
      };
      const reject = document.createElement("button");
      reject.textContent = "Cancel";
      reject.onclick = async () => {
        await api(`/api/pending-actions/${action.id}/reject`, { method: "POST" });
        loadPendingActions();
      };
      div.appendChild(approve);
      div.appendChild(reject);
      list.appendChild(div);
    }
    if (!list.children.length) list.innerHTML = "<p>No pending approvals</p>";
  } catch (e) {
    list.textContent = String(e);
  }
}

async function connectActivityWs() {
  const daemon = await getDaemonUrl();
  const wsUrl = daemon.replace(/^http/, "ws") + "/api/agents/activity";
  const ws = new WebSocket(wsUrl);
  ws.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    const li = document.createElement("li");
    li.textContent = `[${data.timestamp}] ${data.agent}: ${data.action} ${data.detail || ""}`;
    document.getElementById("agents-log").prepend(li);
    if (data.notification_type === "pending_action" || data.action === "pending_action") {
      chrome.runtime.sendMessage({ type: "notify", title: data.title || "Approval needed", body: data.body || data.detail });
      loadPendingActions();
    }
    if (data.notification_type === "new_email") {
      chrome.runtime.sendMessage({ type: "notify", title: data.title || "New email", body: data.body || data.detail });
    }
  };
  ws.onclose = () => setTimeout(connectActivityWs, 3000);
}

refreshConnections();
refreshWhatsAppQr();
loadMeetings();
loadPendingActions();
connectActivityWs();
setInterval(refreshWhatsAppQr, 15000);
setInterval(refreshConnections, 30000);
setInterval(loadPendingActions, 10000);

api("/api/meetings/consent").then((d) => {
  document.getElementById("consent-status").textContent = d.consented ? "Consent granted" : "Consent required for Meet bot";
});
