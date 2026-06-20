const DEFAULT_DAEMON = "http://localhost:8787";

async function getDaemonUrl() {
  const { daemonUrl } = await chrome.storage.local.get({ daemonUrl: DEFAULT_DAEMON });
  return daemonUrl || DEFAULT_DAEMON;
}

async function load() {
  const saved = await chrome.storage.local.get({ daemonUrl: DEFAULT_DAEMON, reminderMinutes: 10, meetAutoJoin: true });
  document.getElementById("daemon-url").value = saved.daemonUrl;
  document.getElementById("reminder-min").value = saved.reminderMinutes;
  document.getElementById("auto-join").checked = saved.meetAutoJoin;
  const daemon = saved.daemonUrl || DEFAULT_DAEMON;
  try {
    const res = await fetch(`${daemon}/api/meetings/consent`);
    const data = await res.json();
    document.getElementById("consent").checked = !!data.consented;
    const settings = await fetch(`${daemon}/api/settings`).then((r) => r.json());
    document.getElementById("reminder-min").value = settings.reminder_minutes_before ?? 10;
    document.getElementById("auto-join").checked = settings.meet_auto_join_on_reminder ?? true;
  } catch {}
}

document.getElementById("save").addEventListener("click", async () => {
  const daemonUrl = document.getElementById("daemon-url").value.trim() || DEFAULT_DAEMON;
  const reminderMinutes = parseInt(document.getElementById("reminder-min").value, 10) || 10;
  const meetAutoJoin = document.getElementById("auto-join").checked;
  await chrome.storage.local.set({ daemonUrl, reminderMinutes, meetAutoJoin });
  const consent = document.getElementById("consent").checked;
  try {
    await fetch(`${daemonUrl}/api/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reminder_minutes_before: reminderMinutes,
        meet_auto_join_on_reminder: meetAutoJoin,
      }),
    });
    await fetch(`${daemonUrl}/api/meetings/consent`, { method: consent ? "POST" : "DELETE" });
    document.getElementById("status").textContent = "Saved.";
  } catch (e) {
    document.getElementById("status").textContent = `Saved locally; daemon unreachable: ${e}`;
  }
});

document.getElementById("stop-daemon").addEventListener("click", async () => {
  const daemon = await getDaemonUrl();
  try {
    await fetch(`${daemon}/api/daemon/shutdown`, { method: "POST" });
    document.getElementById("status").textContent = "Shutdown requested.";
  } catch (e) {
    document.getElementById("status").textContent = String(e);
  }
});

load();
