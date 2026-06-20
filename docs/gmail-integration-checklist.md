# Gmail integration manual test checklist

Prerequisites:
- Tempa daemon running (`tempa start` or docker-compose)
- Google OAuth client ID/secret configured (same app as Calendar)
- Authorized redirect URI: `http://localhost:8787/api/connections/gmail/callback`
- Gmail API enabled in Google Cloud Console for the OAuth project

## 1. Connection

- [ ] Open dashboard Connections tab (or extension side panel)
- [ ] Save Google OAuth credentials if not already saved
- [ ] Click **Connect Gmail** and complete OAuth in popup
- [ ] Verify `GET /api/connections` shows `gmail.connected: true`
- [ ] Verify `gmail.email_address` matches your Google account
- [ ] Restart daemon; confirm token decrypts and Gmail stays connected

## 2. Read / search (on-demand)

- [ ] In chat, ask: "Show my recent inbox emails"
- [ ] Confirm agent activity shows `gmail` specialist
- [ ] Confirm response lists message subjects/snippets
- [ ] Search memory with query related to an email subject; confirm `tool=gmail` chunks exist

## 3. Send

- [ ] In chat, ask: "Send an email to yourself with subject Test from Tempa and body Hello"
- [ ] Confirm safety screen runs (check agent activity / logs)
- [ ] Confirm email arrives in recipient inbox
- [ ] Confirm outbound message ingested into RAG (`tags` includes `outbound`)

## 4. Disconnect

- [ ] Click **Disconnect** on Gmail panel
- [ ] Verify `gmail.connected: false`
- [ ] Chat request for email should return "Gmail not connected"

## 5. Security

- [ ] Confirm `data/sessions/gmail/token.json.enc` exists after daemon shutdown (encrypted at rest)
- [ ] Plain `token.json` should not remain after shutdown when encryption is active
