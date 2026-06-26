<p align="center">
<table cellpadding="8">
<tr>
<td align="center" valign="middle">

<img src="tempa.png" alt="Tempa" width="200" />
</a>
</td>
<td align="left" valign="middle">
<h1>Tempa</h1>
<p><strong>The AI that lives in your system core</strong><br />
always on · always connected</p>
<p>Gmail · Calendar · Google Meet · WhatsApp<br />
Unified memory · multi-agent · local-first</p>
</td>
</tr>
</table>
</p>

<p align="center">
https://github.com/Haroon966/Tempa/raw/main/animated_tempa.mp4
</p>

<p align="center">
<img src="overview_tab.png" alt="Tempa dashboard — system health, integrations, and active tasks" width="920" />
</p>

<p align="center">
<a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11+-3d6cb9?style=for-the-badge&amp;logo=python&amp;logoColor=white" alt="Python 3.11+" /></a>
<a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&amp;logo=fastapi&amp;logoColor=white" alt="FastAPI" /></a>
<a href="docker-compose.yml"><img src="https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&amp;logo=docker&amp;logoColor=white" alt="Docker Compose" /></a>
<a href="https://console.groq.com/"><img src="https://img.shields.io/badge/Groq-inference-f55036?style=for-the-badge" alt="Groq" /></a>
</p>

<p align="center">
<a href="http://localhost:8787"><img src="https://img.shields.io/badge/▶_Open_Dashboard-localhost:8787-3d6cb9?style=for-the-badge" alt="Open dashboard" /></a>
</p>

---

## ✦ Features

<table>
<tr>
<td width="50%" valign="top">
<ul>
<li>💬 <strong>WhatsApp</strong> — QR login once; read, reply &amp; remind with RAG context</li>
<li>📧 <strong>Gmail</strong> — OAuth inbox; compose, search &amp; manage mail</li>
<li>📅 <strong>Calendar</strong> — sync events, schedule &amp; WhatsApp reminders</li>
<li>🎥 <strong>Meet</strong> — auto-join, record, transcribe &amp; archive calls</li>
</ul>
</td>
<td width="50%" valign="top">
<ul>
<li>🧠 <strong>Unified RAG</strong> — one ChromaDB store, no memory silos</li>
<li>🤖 <strong>Varys coordinator</strong> — Claude Code CLI brain + optional LangGraph specialists</li>
<li>🧩 <strong>Extension</strong> — lightweight companion for status &amp; approvals (dashboard is primary)</li>
<li>🔒 <strong>Local-first</strong> — your data stays on your machine</li>
</ul>
</td>
</tr>
</table>

---

## ✦ Architecture

### System overview

Everything funnels through the **Tempa daemon** (`8787`). Channels ingest into unified memory; the **coordinator** decides how to reply; specialists and tools reach Gmail, Calendar, Meet, Slack, and WhatsApp.

```mermaid
flowchart TB
    subgraph clients [Clients]
        Dashboard[Dashboard]
        Extension[Extension]
        SlackIn[Slack DMs and mentions]
        WhatsAppIn[WhatsApp webhook]
    end

    Daemon["Tempa daemon :8787"]

    subgraph brain [Coordinator]
        Router{TEMPA_COORDINATOR}
        Varys[Varys coordinator]
        LangGraph[LangGraph specialists]
    end

    subgraph varysCore [Varys core]
        Harness[(harness.db)]
        Tick[Orchestrator tick 270s]
        ClaudeCLI[Claude Code CLI]
        Vault[data/vault]
    end

    subgraph memory [Unified memory]
        Chroma[(ChromaDB RAG)]
    end

    subgraph channels [Channels and workers]
        SlackOut[Slack Bolt]
        WhatsAppBridge[WhatsApp bridge :8080]
        GoogleAPIs[Gmail and Calendar]
        MeetWorker[Meet worker]
        QAWorker[QA worker]
    end

    subgraph llm [Models]
        Groq[Groq API]
        Claude[Claude via CLI]
    end

    Dashboard --> Daemon
    Extension --> Daemon
    SlackIn --> SlackOut --> Daemon
    WhatsAppIn --> WhatsAppBridge --> Daemon

    Daemon --> Router
    Router -->|varys or hybrid| Varys
    Router -->|langgraph or hybrid| LangGraph

    Varys --> ClaudeCLI --> Claude
    Varys --> Harness
    Tick --> Harness
    Tick --> ClaudeCLI
    Varys --> Vault
    Vault --> Chroma
    Varys --> Chroma

    LangGraph --> Groq
    LangGraph --> Chroma
    LangGraph --> GoogleAPIs
    LangGraph --> SlackOut
    LangGraph --> WhatsAppBridge
    LangGraph --> MeetWorker

    Daemon --> QAWorker
    SlackOut --> SlackIn
    WhatsAppBridge --> WhatsAppIn
```

### Message flow (Varys mode)

When `TEMPA_COORDINATOR=varys`, dashboard and Slack messages use the Varys coordinator. WhatsApp casual chat still uses the fast Groq path unless routed to the full coordinator.

```mermaid
sequenceDiagram
    participant User
    participant Channel as Slack or Dashboard
    participant Daemon as Tempa daemon
    participant Coord as Varys coordinator
    participant Ctx as Context builder
    participant Vault as data/vault
    participant RAG as ChromaDB
    participant Harness as harness.db
    participant Claude as Claude Code CLI

    User->>Channel: message
    Channel->>Daemon: inbound event
    Daemon->>Coord: run_coordinator_full

    alt work request e.g. fix X in repo
        Coord->>Harness: create ticket + event
        Coord-->>User: ticket created, reply go to approve
    else owner replies go
        Coord->>Harness: message.go_signal event
        Coord-->>User: approved, tick will dispatch
    else conversational
        Coord->>Ctx: build prompt
        Ctx->>Vault: read wing and rules
        Ctx->>RAG: search_memory
        Ctx->>Claude: system + user prompt
        Claude-->>Coord: reply
        Coord-->>User: response
    end

    Note over Harness,Claude: Orchestrator tick polls tickets,<br/>dispatches pending events via Claude CLI
```

### Memory and vault

Varys vault files and all channel ingest share **one** Chroma collection — no memory silos.

```mermaid
flowchart LR
    subgraph sources [Memory sources]
        VaultFiles["data/vault/*.md"]
        GmailSync[Gmail sync]
        SlackSync[Slack sync]
        CalendarSync[Calendar sync]
        MeetArchive[Meet transcripts]
        WhatsAppIdx[WhatsApp ingest]
    end

    subgraph ingest [Ingest pipeline]
        VaultSync[vault-sync / tempa vault-sync]
        IngestFn[ingest_text]
    end

    Chroma[(ChromaDB tempa_unified)]

    subgraph meta [Metadata tags]
        Wing[wing e.g. tempa]
        Room[room e.g. memory]
        Tool[tool e.g. vault, gmail]
    end

    VaultFiles --> VaultSync --> IngestFn
    GmailSync --> IngestFn
    SlackSync --> IngestFn
    CalendarSync --> IngestFn
    MeetArchive --> IngestFn
    WhatsAppIdx --> IngestFn
    IngestFn --> Chroma
    IngestFn --> meta
    meta --> Chroma

    Chroma --> VarysCtx[Varys context builder]
    Chroma --> LangGraphRAG[LangGraph RAG agent]
```

### Docker layout

```mermaid
flowchart LR
    subgraph host [Your machine]
        ClaudeBin[Claude Code CLI]
        ClaudeCfg["~/.claude auth"]
    end

    subgraph compose [docker compose]
        DaemonC[tempa-daemon :8787]
        BridgeC[whatsapp-bridge :8080]
        MeetC[meet-worker]
        PgC[postgres :5432]
    end

    Data["./data volume<br/>vector, vault, harness, sessions"]

    ClaudeBin -.->|mounted binary| DaemonC
    ClaudeCfg -.->|mounted config| DaemonC
    DaemonC --> Data
    DaemonC --> BridgeC
    DaemonC --> MeetC
    BridgeC --> PgC
```

<table>
<tr>
<td align="center"><code>8787</code><br /><sub>Tempa daemon</sub></td>
<td align="center">→</td>
<td align="center"><code>8080</code><br /><sub>WhatsApp bridge</sub></td>
<td align="center">→</td>
<td align="center"><code>5432</code><br /><sub>Postgres</sub></td>
</tr>
</table>

| Service | Port | Role |
|:--|:--:|:--|
| **Tempa daemon** | `8787` | API · dashboard · coordinator · webhooks · Varys tick |
| **WhatsApp bridge** | `8080` | Baileys sidecar · Evolution-compatible REST |
| **Meet worker** | — | Playwright join / record / transcribe |
| **Postgres** | `5432` | WhatsApp session storage |

---

## ✦ Varys coordinator

[Varys](https://github.com/codebyshoaib/varys) is vendored under `vendor/varys` (reference only). Runtime code lives in `src/tempa/varys/`.

| Setting | Purpose |
|:--|:--|
| `TEMPA_COORDINATOR` | `varys` · `langgraph` · `hybrid` |
| `VARYS_ORCHESTRATOR_ENABLED` | Background 270s tick loop |
| `VARYS_CLAUDE_CLI_ONLY` | Use Claude Code CLI only (no API fallback) |
| `CLAUDE_CODE_PATH` | Path to `claude` binary |
| `VARYS_VAULT_DIR` | Persistent vault memory (`data/vault`) |

```bash
tempa varys status    # harness DB summary
tempa varys tick      # run one orchestrator tick
tempa vault-sync      # index vault into Chroma RAG
./scripts/vendor-varys.sh   # refresh vendored upstream
```

---

## ✦ Quick start

<table>
<tr>
<td width="50%" valign="top">
<h3>🐳 Docker</h3>
<p><sub>recommended</sub></p>
<p><strong>①</strong> Copy env &amp; add keys</p>
<pre><code>cp .env.example .env</code></pre>
<p><strong>②</strong> Launch stack</p>
<pre><code>docker compose up -d</code></pre>
<p><strong>③</strong> Complete setup at <strong>Setup</strong> (dashboard is the primary UI; extension is optional)</p>
</td>
<td width="50%" valign="top">
<h3>🛠 Native</h3>
<p><strong>①</strong> Install</p>
<pre><code>python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env</code></pre>
<p><strong>②</strong> Run</p>
<pre><code>./scripts/run-native.sh</code></pre>
<p><strong>③</strong> Dev UI <em>(optional)</em></p>
<pre><code>cd dashboard &amp;&amp; npm i &amp;&amp; npm run dev</code></pre>
</td>
</tr>
</table>

> **Prerequisites** — Python 3.11+ · Docker · [Groq API key](https://console.groq.com/) · Google OAuth

---

## ✦ Configuration

| Variable | Purpose |
|:--|:--|
| `GROQ_API_KEY` | LLM, STT & safety inference |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Calendar, Gmail, Meet OAuth |
| `WHATSAPP_OWNER_NUMBER` | Auto-reply & reminders target |
| `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` | Slack Socket Mode (bot + app-level token) |
| `SLACK_OWNER_USER_ID` | Slack user ID for DM auto-reply |
| `EVOLUTION_API_URL` | WhatsApp bridge · default `http://localhost:8080` |
| `EVOLUTION_API_KEY` | Bridge auth key |
| `TEMPA_INSTANCE_NAME` | WhatsApp instance name |
| `TEMPA_COORDINATOR` | `varys` · `langgraph` · `hybrid` |
| `VARYS_ORCHESTRATOR_ENABLED` | Enable Varys background tick loop |
| `VARYS_CLAUDE_CLI_ONLY` | Claude Code CLI only (no Anthropic API fallback) |
| `CLAUDE_CODE_PATH` | Path to Claude Code CLI (`claude`) |
| `VARYS_VAULT_DIR` | Vault memory directory (default `data/vault`) |
| `NOTION_API_KEY` | Optional Notion brain for Varys harness |
| `JIRA_BASE_URL` / `JIRA_EMAIL` / `JIRA_API_TOKEN` | Jira Cloud (Connections tab or env) |
| `JIRA_ENABLED` | Enable Jira poller + chat tools |
| `JIRA_DEFAULT_PROJECT` | Default Jira project key (e.g. `ENG`) |

📄 [`.env.example`](.env.example) · [`services/whatsapp-bridge/.env.example`](services/whatsapp-bridge/.env.example)

---

## ✦ CLI

```bash
tempa start          # start daemon
tempa setup          # first-run wizard (initializes vault)
tempa chat           # terminal chat
tempa whatsapp-qr    # show WhatsApp QR
tempa meet-auth      # Meet browser auth
tempa varys status   # Varys harness summary
tempa varys tick     # manual orchestrator tick
tempa vault-sync     # index vault into RAG
```

---

## ✦ WhatsApp bridge

In-repo **Baileys bridge** at [`services/whatsapp-bridge/`](services/whatsapp-bridge/) — Evolution-compatible API on port **8080**, zero external vendor deps.

```bash
./scripts/test-whatsapp-qr.sh
```

<details>
<summary><strong>Migrating from Evolution API</strong></summary>
<p>Compatible session data if you used <code>evoapicloud/evolution-api</code> with Postgres <code>evolution</code> / <code>evolution:evolution</code>.</p>
<p>Rename volume <code>evolution_instances</code> → <code>whatsapp_instances</code>, or remount at <code>/app/instances</code>.</p>
<p>Env vars unchanged: <code>EVOLUTION_API_URL</code> · <code>EVOLUTION_API_KEY</code> · <code>TEMPA_INSTANCE_NAME</code></p>
</details>

---

## ✦ Slack (Socket Mode)

**Bot events** (Event Subscriptions): `message.im`, `app_mention`, and **`assistant_thread_started`** (if using Slack's Assistant chat UI).

- `SLACK_BOT_TOKEN` (`xoxb-…`)
- `SLACK_APP_TOKEN` (`xapp-…` with `connections:write`)
- `SLACK_OWNER_USER_ID` (your Slack member ID for DM auto-reply)

**Bot token scopes** (OAuth & Permissions) — your app currently needs at least:

- `app_mentions:read`
- `chat:write`
- `im:history`
- `im:read` ← **missing on many setups; required for DMs**
- `users:read`
- `channels:history`, `channels:read` (for @mentions in public channels)

**Required for DMs:** App Home → **Messages Tab** ON + allow user messages. **Event Subscriptions** → bot events **`message.im`** and **`app_mention`**. After changing scopes/events, **reinstall the app** to the workspace.

DM the bot or `@mention` it in a channel. Outbound sends from the coordinator go through pending-action approval.

---

## ✦ Development

```bash
.venv/bin/pip install -e ".[dev]"    # install dev deps
.venv/bin/pytest                     # run tests
.venv/bin/ruff check src tests       # lint
```

---

<p align="center"><strong>Tempa</strong> v0.1.0 · self-hosted AI personal core agent</p>
