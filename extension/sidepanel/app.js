const DEFAULT_DAEMON = "http://localhost:8787";

const PROMPTS = [
  "What's on my calendar this week?",
  "Search my Gmail for unread messages",
  "Search memory for recent meeting notes",
  "Summarize my latest WhatsApp chats",
];

const state = {
  sessionId: null,
  runId: null,
  streaming: false,
  abort: null,
  messages: [],
};

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

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

function setStatus(text, kind = "") {
  const el = document.getElementById("status");
  el.textContent = text;
  el.className = `status ${kind}`.trim();
}

async function pingDaemon() {
  try {
    const daemon = await getDaemonUrl();
    const res = await fetch(`${daemon}/api/health`);
    setStatus(res.ok ? "Online" : "Unreachable", res.ok ? "ok" : "bad");
  } catch {
    setStatus("Offline", "bad");
  }
}

function setView(name) {
  document.querySelectorAll(".view").forEach((el) => el.classList.toggle("active", el.dataset.view === name));
  document.querySelectorAll(".nav-item").forEach((el) => el.classList.toggle("active", el.dataset.nav === name));
  if (name === "approvals") loadPending();
  if (name === "activity" && !document.getElementById("activity-log").children.length) {
    document.getElementById("activity-log").innerHTML = `<li><div class="what">Waiting for agent events…</div></li>`;
  }
}

document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => setView(btn.dataset.nav));
});

function updateEmpty() {
  document.getElementById("chat-empty").classList.toggle("hidden", state.messages.length > 0);
}

function renderPrompts() {
  const chips = document.getElementById("prompt-chips");
  chips.innerHTML = "";
  for (const text of PROMPTS) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip";
    btn.textContent = text;
    btn.addEventListener("click", () => {
      document.getElementById("chat-input").value = text;
      document.getElementById("chat-form").requestSubmit();
    });
    chips.appendChild(btn);
  }
}

function scrollChat() {
  const log = document.getElementById("chat-log");
  log.scrollTop = log.scrollHeight;
}

function truncate(text, max = 72) {
  const t = String(text || "").trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max - 1)}…`;
}

function friendlyActivity(ev) {
  const d = ev.detail || "";
  if (d.startsWith("plan:")) {
    try {
      const steps = JSON.parse(d.slice(5));
      return {
        headline: "Plan",
        detail: steps.map((s) => `• ${s.agent}: ${s.task ?? ""}`).join("\n"),
      };
    } catch {
      return { headline: "Plan", detail: d.slice(5) };
    }
  }
  if (d.startsWith("understand:")) return { headline: "Understand", detail: d.slice(11) };
  if (d.startsWith("step_start:")) return { headline: "Running", detail: d.slice(11) };
  if (d.startsWith("step_done:")) return { headline: "Done", detail: d.slice(10) };
  if (d === "replan" || d === "goal_replan") return { headline: "Replanning" };
  if (d.startsWith("clarify:")) return { headline: "Clarify", detail: d.slice(8) };
  return { headline: ev.action || "event", detail: d };
}

function feedHtml(steps = [], activity = [], live = false) {
  const items = [];
  for (const step of steps) {
    const status = step.status || "start";
    items.push({
      key: `s-${step.subtask_id}-${status}`,
      agent: step.agent || "agent",
      headline: truncate(step.detail || status),
      status,
      live: live && status === "start",
    });
  }
  for (const ev of activity.slice(-12)) {
    const f = friendlyActivity(ev);
    items.push({
      key: `a-${ev.timestamp}-${ev.agent}-${ev.action}`,
      agent: ev.agent || "agent",
      headline: f.headline,
      detail: f.detail,
      status: "activity",
      live: false,
    });
  }
  if (!items.length) return "";

  const body = items
    .map((it) => {
      const cls = it.live ? "live" : it.status === "done" ? "done" : it.status === "error" ? "error" : "";
      return `<div class="feed-item">
        <span class="dot ${cls}"></span>
        <div>
          <div class="agent">${escapeHtml(it.agent)} · ${escapeHtml(it.headline)}</div>
          ${it.detail ? `<div class="detail">${escapeHtml(it.detail)}</div>` : ""}
        </div>
      </div>`;
    })
    .join("");

  return `<div class="feed">
    <button type="button" class="feed-toggle" data-feed-toggle>
      <span>${live ? "Agents working…" : "Agent steps"} · ${items.length}</span>
      <span aria-hidden="true">▾</span>
    </button>
    <div class="feed-body">${body}</div>
  </div>`;
}

function pendingCardsHtml(actions = []) {
  return actions
    .map(
      (a) => `<div class="action-card" data-action-id="${escapeHtml(a.id)}">
        <h3>${escapeHtml(a.type || "action")}</h3>
        <p class="preview">${escapeHtml(a.preview || "Needs approval")}</p>
        <div class="action-actions">
          <button type="button" class="btn primary" data-approve="${escapeHtml(a.id)}">Approve</button>
          <button type="button" class="btn ghost-danger" data-reject="${escapeHtml(a.id)}">Cancel</button>
        </div>
      </div>`,
    )
    .join("");
}

function sourcesHtml(sources = []) {
  if (!sources.length) return "";
  return `<div class="sources">${sources
    .map((s) => {
      const label = typeof s === "string" ? s : s.label || s.source || s.type || "source";
      return `<span class="source-pill">${escapeHtml(label)}</span>`;
    })
    .join("")}</div>`;
}

function planHtml(steps = []) {
  if (!steps.length) return "";
  return `<ul class="plan-list">${steps
    .map((s) => `<li><strong>${escapeHtml(s.agent || "agent")}</strong> — ${escapeHtml(s.task || "")}</li>`)
    .join("")}</ul>`;
}

function messageHtml(msg) {
  if (msg.role === "user") {
    return `<article class="msg user" data-id="${msg.id}">
      <div class="msg-meta"><span class="msg-role">You</span></div>
      <div class="bubble">${escapeHtml(msg.content)}</div>
    </article>`;
  }

  const hasActivity = Boolean(msg.steps?.length || msg.activity?.length);
  let body = "";
  if (msg.content) {
    body += `<div class="content">${escapeHtml(msg.content)}</div>`;
  } else if (msg.streaming && !hasActivity) {
    body += `<div class="thinking"><span class="dots"><span></span><span></span><span></span></span> Thinking…</div>`;
  } else if (!msg.streaming && !hasActivity) {
    body += `<div class="content muted">No response.</div>`;
  }

  body += feedHtml(msg.steps || [], msg.activity || [], Boolean(msg.streaming));
  body += planHtml(msg.planned_steps || []);
  body += sourcesHtml(msg.sources || []);
  body += pendingCardsHtml(msg.pending_actions || []);

  return `<article class="msg assistant" data-id="${msg.id}">
    <div class="msg-meta"><span class="msg-role">Tempa</span></div>
    <div class="bubble">${body}</div>
  </article>`;
}

function renderMessages() {
  const log = document.getElementById("chat-log");
  log.innerHTML = state.messages.map(messageHtml).join("");
  updateEmpty();
  scrollChat();
}

function patchMessage(id, patch) {
  const idx = state.messages.findIndex((m) => m.id === id);
  if (idx < 0) return;
  state.messages[idx] = { ...state.messages[idx], ...patch };
  const el = document.querySelector(`.msg[data-id="${id}"]`);
  if (el) {
    el.outerHTML = messageHtml(state.messages[idx]);
  } else {
    renderMessages();
  }
  scrollChat();
}

function classifySse(eventType, data) {
  let kind = eventType;
  if (!kind) {
    if ("delta" in data) kind = "token";
    else if ("agent" in data && "action" in data) kind = "activity";
    else if ("error" in data) kind = "error";
    else if ("content" in data || "session_id" in data || "sources" in data || "paused" in data) kind = "message";
    else if ("run_id" in data && "session_id" in data) kind = "run_started";
    else if ("subtask_id" in data && "status" in data) kind = "step";
    else if (Object.keys(data).length === 0) kind = "done";
  }
  return kind;
}

function mergeStep(steps, step) {
  const next = [...steps];
  if (step.status === "start") {
    next.push(step);
  } else {
    const i = next.findIndex((s) => s.subtask_id === step.subtask_id && s.status === "start");
    if (i >= 0) next[i] = { ...next[i], ...step };
    else next.push(step);
  }
  return next.slice(-50);
}

function setStreamingUi(on) {
  state.streaming = on;
  document.getElementById("btn-stop").classList.toggle("hidden", !on);
  document.getElementById("btn-send").disabled = on;
  document.getElementById("chat-input").disabled = on;
}

async function cancelRun() {
  if (state.abort) state.abort.abort();
  if (state.runId) {
    try {
      await api(`/api/chat/runs/${state.runId}/cancel`, { method: "POST" });
    } catch {}
  }
  setStreamingUi(false);
}

document.getElementById("btn-stop").addEventListener("click", cancelRun);

document.getElementById("btn-new-chat").addEventListener("click", () => {
  if (state.streaming) cancelRun();
  state.sessionId = null;
  state.runId = null;
  state.messages = [];
  renderMessages();
  document.getElementById("chat-input").focus();
  setView("chat");
});

async function sendMessage(text) {
  const trimmed = text.trim();
  if (!trimmed || state.streaming) return;

  const userId = uid();
  const assistantId = uid();
  state.messages.push({ id: userId, role: "user", content: trimmed });
  state.messages.push({
    id: assistantId,
    role: "assistant",
    content: "",
    streaming: true,
    steps: [],
    activity: [],
  });
  renderMessages();

  const controller = new AbortController();
  state.abort = controller;
  state.runId = null;
  setStreamingUi(true);

  let content = "";
  let steps = [];
  let activity = [];
  let finalized = false;

  const finalize = (patch = {}) => {
    if (finalized) return;
    finalized = true;
    patchMessage(assistantId, {
      content: patch.content ?? content,
      streaming: false,
      steps,
      activity,
      sources: patch.sources,
      pending_actions: patch.pending_actions,
      planned_steps: patch.planned_steps,
      paused: patch.paused,
    });
    setStreamingUi(false);
    if (patch.pending_actions?.length) loadPending();
  };

  try {
    const daemon = await getDaemonUrl();
    const res = await fetch(`${daemon}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({
        message: trimmed,
        session_id: state.sessionId,
        context: { channel: "extension" },
        run_id: state.runId,
      }),
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(await res.text());
    if (!res.body) throw new Error("No response body");

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";

      for (const part of parts) {
        const normalized = part.replace(/\r\n/g, "\n").trim();
        if (!normalized) continue;
        let eventType = "";
        const dataLines = [];
        for (const line of normalized.split("\n")) {
          if (line.startsWith("event:")) eventType = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
        }
        let data = {};
        try {
          data = JSON.parse(dataLines.join("\n") || "{}");
        } catch {
          continue;
        }
        const kind = classifySse(eventType, data);

        if (kind === "run_started") {
          state.runId = data.run_id || state.runId;
          if (data.session_id) state.sessionId = data.session_id;
        } else if (kind === "token") {
          content += String(data.delta ?? "");
          patchMessage(assistantId, { content, streaming: true, steps, activity });
        } else if (kind === "step") {
          steps = mergeStep(steps, data);
          patchMessage(assistantId, { content, streaming: true, steps, activity });
        } else if (kind === "activity") {
          activity = [...activity.slice(-49), {
            agent: String(data.agent || ""),
            action: String(data.action || ""),
            detail: String(data.detail || ""),
            timestamp: String(data.timestamp || ""),
          }];
          patchMessage(assistantId, { content, streaming: true, steps, activity });
          prependActivity(data);
        } else if (kind === "message") {
          if (data.session_id) state.sessionId = data.session_id;
          if (data.run_id) state.runId = data.run_id;
          content = String(data.content ?? content);
          finalize({
            content,
            sources: data.sources || [],
            pending_actions: data.pending_actions || [],
            planned_steps: data.planned_steps || [],
            paused: Boolean(data.paused),
          });
        } else if (kind === "error") {
          if (data.code === "CANCELLED") {
            finalize({ content: content ? `${content}\n\n(Stopped)` : "(Stopped)" });
          } else {
            finalize({ content: `Error: ${data.error || "Unknown error"}` });
          }
        } else if (kind === "done") {
          finalize();
        }
      }
    }
    if (!finalized) finalize();
  } catch (err) {
    if (err.name === "AbortError") {
      if (!finalized) finalize({ content: content ? `${content}\n\n(Stopped)` : "(Stopped)" });
    } else {
      finalize({ content: `Error: ${err.message || err}` });
      pingDaemon();
    }
  }
}

document.getElementById("chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = document.getElementById("chat-input");
  const text = input.value;
  input.value = "";
  input.style.height = "";
  sendMessage(text);
});

const chatInput = document.getElementById("chat-input");
chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    document.getElementById("chat-form").requestSubmit();
  }
});
chatInput.addEventListener("input", () => {
  chatInput.style.height = "auto";
  chatInput.style.height = `${Math.min(chatInput.scrollHeight, 120)}px`;
});

document.getElementById("chat-log").addEventListener("click", async (e) => {
  const approve = e.target.closest("[data-approve]");
  const reject = e.target.closest("[data-reject]");
  const toggle = e.target.closest("[data-feed-toggle]");
  if (toggle) {
    const body = toggle.parentElement.querySelector(".feed-body");
    if (body) body.hidden = !body.hidden;
    return;
  }
  if (approve) {
    const id = approve.dataset.approve;
    approve.disabled = true;
    try {
      await api(`/api/pending-actions/${id}/approve`, { method: "POST" });
      approve.closest(".action-card")?.remove();
      loadPending();
    } catch (err) {
      approve.disabled = false;
      alert(String(err.message || err));
    }
  }
  if (reject) {
    const id = reject.dataset.reject;
    reject.disabled = true;
    try {
      await api(`/api/pending-actions/${id}/reject`, { method: "POST" });
      reject.closest(".action-card")?.remove();
      loadPending();
    } catch (err) {
      reject.disabled = false;
      alert(String(err.message || err));
    }
  }
});

function prependActivity(ev) {
  const list = document.getElementById("activity-log");
  if (list.firstElementChild?.textContent?.includes("Waiting for")) list.innerHTML = "";
  const f = friendlyActivity(ev);
  const li = document.createElement("li");
  li.innerHTML = `
    <div class="when">${escapeHtml(ev.timestamp || new Date().toISOString())}</div>
    <div class="what">${escapeHtml(ev.agent || "agent")} · ${escapeHtml(f.headline)}</div>
    ${f.detail ? `<div class="detail">${escapeHtml(f.detail)}</div>` : ""}`;
  list.prepend(li);
  while (list.children.length > 80) list.lastElementChild.remove();
}

async function connectActivityWs() {
  try {
    const daemon = await getDaemonUrl();
    const ws = new WebSocket(daemon.replace(/^http/, "ws") + "/api/agents/activity");
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        prependActivity(data);
        if (data.notification_type === "pending_action" || data.action === "pending_action") {
          chrome.runtime.sendMessage({
            type: "notify",
            title: data.title || "Approval needed",
            body: data.body || data.detail,
          });
          loadPending();
        }
      } catch {}
    };
    ws.onclose = () => setTimeout(connectActivityWs, 3000);
  } catch {
    setTimeout(connectActivityWs, 5000);
  }
}

async function loadPending() {
  const list = document.getElementById("pending-list");
  const badge = document.getElementById("pending-badge");
  try {
    const data = await api("/api/pending-actions");
    const actions = data.actions || [];
    badge.textContent = String(actions.length);
    badge.classList.toggle("hidden", actions.length === 0);
    if (!actions.length) {
      list.innerHTML = `<p class="muted">No pending approvals</p>`;
      return;
    }
    list.innerHTML = actions
      .map(
        (a) => `<div class="action-card" data-action-id="${escapeHtml(a.id)}">
          <h3>${escapeHtml(a.title || a.type)}</h3>
          <p class="preview">${escapeHtml(typeof a.payload === "object" ? JSON.stringify(a.payload, null, 2).slice(0, 400) : a.preview || "")}</p>
          <div class="action-actions">
            <button type="button" class="btn primary" data-approve="${escapeHtml(a.id)}">Approve</button>
            <button type="button" class="btn ghost-danger" data-reject="${escapeHtml(a.id)}">Cancel</button>
          </div>
        </div>`,
      )
      .join("");
  } catch (e) {
    list.innerHTML = `<p class="muted">${escapeHtml(String(e))}</p>`;
  }
}

document.getElementById("pending-list").addEventListener("click", async (e) => {
  const approve = e.target.closest("[data-approve]");
  const reject = e.target.closest("[data-reject]");
  if (!approve && !reject) return;
  const id = (approve || reject).dataset.approve || (approve || reject).dataset.reject;
  try {
    if (approve) await api(`/api/pending-actions/${id}/approve`, { method: "POST" });
    else await api(`/api/pending-actions/${id}/reject`, { method: "POST" });
    loadPending();
  } catch (err) {
    alert(String(err.message || err));
  }
});

document.getElementById("memory-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const query = document.getElementById("memory-query").value.trim();
  if (!query) return;
  const out = document.getElementById("memory-results");
  out.innerHTML = `<p class="muted">Searching…</p>`;
  try {
    const data = await api("/api/memory/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, top_k: 8 }),
    });
    const hits = data.results || [];
    out.innerHTML = hits.length
      ? hits
          .map(
            (r) => `<div class="memory-hit"><div class="score">${escapeHtml(String(r.score?.toFixed?.(2) ?? ""))}</div>${escapeHtml(r.content)}</div>`,
          )
          .join("")
      : `<p class="muted">No results</p>`;
  } catch (err) {
    out.innerHTML = `<p class="muted">${escapeHtml(String(err.message || err))}</p>`;
  }
});

renderPrompts();
updateEmpty();
pingDaemon();
loadPending();
connectActivityWs();
setInterval(pingDaemon, 30000);
setInterval(loadPending, 15000);
