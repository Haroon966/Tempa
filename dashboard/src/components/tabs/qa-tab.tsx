import {
  BrainIcon,
  GitBranchIcon,
  LayersIcon,
  ListTodoIcon,
  MessageSquareIcon,
  PlusIcon,
  TerminalIcon,
  Trash2Icon,
  WrenchIcon,
} from "lucide-react"
import { useMemo, useState } from "react"
import { QaAgentPlaybookSheet } from "@/components/qa/qa-agent-playbook-sheet"
import { PanelCard } from "@/components/dashboard/panel-card"
import { StatCard } from "@/components/dashboard/stat-card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { useQa } from "@/hooks/use-qa"
import type { QaAgentPlaybook } from "@/lib/api"
import { cn } from "@/lib/utils"

const SEVERITY_CLASS: Record<string, string> = {
  critical: "border-red-300 bg-red-50 text-red-700",
  high: "border-orange-300 bg-orange-50 text-orange-700",
  medium: "border-amber-300 bg-amber-50 text-amber-700",
  low: "border-blue-200 bg-blue-50 text-blue-700",
  info: "border-border bg-muted text-muted-foreground",
}

const STATUS_CLASS: Record<string, string> = {
  success: "text-green-600",
  failure: "text-red-600",
  pending: "text-amber-600",
  skipped: "text-muted-foreground",
  unknown: "text-muted-foreground",
}

function StatusDot({ status }: { status?: string }) {
  const s = status ?? "unknown"
  return <span className={cn("text-xs font-medium capitalize", STATUS_CLASS[s] ?? STATUS_CLASS.unknown)}>{s}</span>
}

const SOURCE_LABEL: Record<string, string> = {
  env: "env",
  config: "config",
  dashboard: "dashboard",
  github_app: "app",
}

export function QaTab() {
  const {
    summary,
    repos: managedRepos,
    branches,
    findings,
    jobs,
    loading,
    error,
    scanRepo,
    addRepo,
    removeRepo,
    commentFinding,
    requestFix,
    loadAgentPlaybook,
  } = useQa()
  const [busy, setBusy] = useState<string | null>(null)
  const [playbookOpen, setPlaybookOpen] = useState(false)
  const [playbook, setPlaybook] = useState<QaAgentPlaybook | null>(null)
  const [playbookTitle, setPlaybookTitle] = useState("")
  const [newRepo, setNewRepo] = useState("")
  const [scanRepoInput, setScanRepoInput] = useState("")
  const [scanBranchInput, setScanBranchInput] = useState("")
  const [scanPrInput, setScanPrInput] = useState("")

  const repos = useMemo(() => {
    const set = new Set(managedRepos.map((r) => r.repo))
    for (const b of branches) set.add(b.repo)
    return Array.from(set).sort()
  }, [managedRepos, branches])

  async function runAction(key: string, fn: () => Promise<void>) {
    setBusy(key)
    try {
      await fn()
    } finally {
      setBusy(null)
    }
  }

  async function openPlaybook(findingId: string, target: "claude" | "cursor", title: string) {
    setBusy(`playbook-${target}-${findingId}`)
    try {
      const pb = await loadAgentPlaybook(findingId, target)
      setPlaybook(pb)
      setPlaybookTitle(title)
      setPlaybookOpen(true)
    } finally {
      setBusy(null)
    }
  }

  if (loading && !summary && branches.length === 0 && findings.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    )
  }

  if (summary && !summary.enabled) {
    return (
      <div className="rounded-xl border border-border bg-muted/30 p-10 text-center">
        <p className="font-semibold">QA agent is disabled</p>
        <p className="mt-2 text-sm text-muted-foreground">Set TEMPA_QA_ENABLED=true in your environment.</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-5">
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      {!summary?.configured && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          GitHub not configured. Set <code className="text-xs">GITHUB_TOKEN</code> in your environment, then add
          repos in the <strong>Repositories</strong> panel below (or set <code className="text-xs">GITHUB_REPOS</code>
          ). For webhooks, use <code className="text-xs">GITHUB_APP_ID</code>,{" "}
          <code className="text-xs">GITHUB_PRIVATE_KEY</code>, and <code className="text-xs">GITHUB_WEBHOOK_SECRET</code>.
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Badge
          variant="outline"
          className={cn(
            "gap-1.5",
            summary?.groq_configured
              ? "border-green-300 bg-green-50 text-green-800"
              : "border-amber-300 bg-amber-50 text-amber-800",
          )}
        >
          <BrainIcon className="size-3.5" />
          Groq API {summary?.groq_configured ? "configured" : "not configured"}
        </Badge>
        {summary?.github_auth_mode === "pat" && (
          <Badge variant="outline" className="gap-1.5 border-green-300 bg-green-50 text-green-800">
            GitHub PAT configured
          </Badge>
        )}
        {summary?.github_auth_mode === "app" && (
          <Badge variant="outline" className="gap-1.5 border-green-300 bg-green-50 text-green-800">
            GitHub App configured
          </Badge>
        )}
        <span className="text-sm text-muted-foreground">
          Automated scans and autofix use Groq. Deep fixes run in Claude Code or Cursor — not the Claude API.
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Repos" value={summary?.repos_monitored ?? managedRepos.length} icon={LayersIcon} />
        <StatCard label="Branches" value={summary?.branches_scanned ?? 0} icon={GitBranchIcon} />
        <StatCard label="Open findings" value={summary?.open_findings ?? 0} icon={MessageSquareIcon} accent="orange" />
        <StatCard label="Queue" value={summary?.queue_depth ?? 0} icon={ListTodoIcon} accent="sky" />
      </div>

      <PanelCard
        title="Repositories"
        description="Manage which repos Tempa can scan (also configurable via GITHUB_REPOS)"
        icon={LayersIcon}
      >
        <div className="flex flex-col gap-4">
          <form
            className="flex flex-wrap gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              const value = newRepo.trim()
              if (!value) return
              void runAction("add-repo", async () => {
                await addRepo(value)
                setNewRepo("")
              })
            }}
          >
            <Input
              placeholder="owner/repo"
              value={newRepo}
              onChange={(e) => setNewRepo(e.target.value)}
              className="max-w-xs"
            />
            <Button type="submit" size="sm" disabled={busy === "add-repo" || !newRepo.trim()}>
              <PlusIcon className="mr-1.5 size-3.5" />
              Add repo
            </Button>
          </form>

          {managedRepos.length === 0 ? (
            <p className="text-sm text-muted-foreground">No repos yet. Add one above or set GITHUB_REPOS in .env.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {managedRepos.map((entry) => (
                <li
                  key={entry.repo}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/60 px-3 py-2"
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="truncate font-medium">{entry.repo}</span>
                    <Badge variant="outline" className="text-xs capitalize">
                      {SOURCE_LABEL[entry.source] ?? entry.source}
                    </Badge>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy === `repo-${entry.repo}`}
                      onClick={() => runAction(`repo-${entry.repo}`, () => scanRepo(entry.repo))}
                    >
                      Scan all
                    </Button>
                    {entry.removable && (
                      <Button
                        size="sm"
                        variant="outline"
                        className="border-red-200 text-red-600 hover:bg-red-50"
                        disabled={busy === `remove-${entry.repo}`}
                        onClick={() => runAction(`remove-${entry.repo}`, () => removeRepo(entry.repo))}
                      >
                        <Trash2Icon className="size-3.5" />
                      </Button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}

          <form
            className="flex flex-wrap items-end gap-2 border-t border-border/60 pt-4"
            onSubmit={(e) => {
              e.preventDefault()
              const repo = scanRepoInput.trim()
              if (!repo) return
              const pr = scanPrInput.trim() ? Number(scanPrInput) : undefined
              void runAction("custom-scan", async () => {
                await scanRepo(repo, scanBranchInput.trim() || undefined, pr)
                setScanRepoInput("")
                setScanBranchInput("")
                setScanPrInput("")
              })
            }}
          >
            <div className="flex flex-col gap-1">
              <label className="text-xs text-muted-foreground">Quick scan</label>
              <Input
                placeholder="owner/repo"
                value={scanRepoInput}
                onChange={(e) => setScanRepoInput(e.target.value)}
                className="w-44"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-muted-foreground">Branch (optional)</label>
              <Input
                placeholder="main"
                value={scanBranchInput}
                onChange={(e) => setScanBranchInput(e.target.value)}
                className="w-36"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-muted-foreground">PR # (optional)</label>
              <Input
                placeholder="42"
                value={scanPrInput}
                onChange={(e) => setScanPrInput(e.target.value)}
                className="w-20"
              />
            </div>
            <Button type="submit" size="sm" disabled={busy === "custom-scan" || !scanRepoInput.trim()}>
              Run scan
            </Button>
          </form>
        </div>
      </PanelCard>

      <div className="grid gap-4 xl:grid-cols-3">
        <PanelCard
          title="Branches"
          description="CI, lint, tests, and security grade per branch"
          icon={GitBranchIcon}
          className="xl:col-span-2"
        >
          {branches.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No branch scans yet. Configure GitHub (PAT or App) and trigger a scan.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-sm">
                <thead>
                  <tr className="border-b border-border/60 text-[11px] uppercase tracking-wide text-muted-foreground">
                    <th className="pb-2 pr-3 font-semibold">Repo / Branch</th>
                    <th className="pb-2 pr-3 font-semibold">CI</th>
                    <th className="pb-2 pr-3 font-semibold">Lint</th>
                    <th className="pb-2 pr-3 font-semibold">Tests</th>
                    <th className="pb-2 pr-3 font-semibold">Grade</th>
                    <th className="pb-2 font-semibold">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {branches.map((row) => {
                    const key = `${row.repo}#${row.branch}`
                    return (
                      <tr key={key} className="border-b border-border/40 last:border-0">
                        <td className="py-2.5 pr-3">
                          <p className="font-medium text-foreground">{row.repo}</p>
                          <p className="text-xs text-muted-foreground">{row.branch}</p>
                        </td>
                        <td className="py-2.5 pr-3">
                          <StatusDot status={row.ci_status} />
                        </td>
                        <td className="py-2.5 pr-3">
                          <StatusDot status={row.lint_status} />
                        </td>
                        <td className="py-2.5 pr-3">
                          <StatusDot status={row.test_status} />
                        </td>
                        <td className="py-2.5 pr-3">
                          <Badge variant="outline">{row.grade ?? "—"}</Badge>
                        </td>
                        <td className="py-2.5">
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={busy === key}
                            onClick={() => runAction(key, () => scanRepo(row.repo, row.branch))}
                          >
                            Scan
                          </Button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          {repos.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-2 border-t border-border/60 pt-4">
              {repos.map((repo) => (
                <Button
                  key={repo}
                  size="sm"
                  variant="secondary"
                  disabled={busy === `repo-${repo}`}
                  onClick={() => runAction(`repo-${repo}`, () => scanRepo(repo))}
                >
                  Scan all — {repo}
                </Button>
              ))}
            </div>
          )}
        </PanelCard>

        <PanelCard title="Scan queue" description="Queued and running jobs" icon={GitBranchIcon}>
          {jobs.length === 0 ? (
            <p className="text-sm text-muted-foreground">Queue is empty.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {jobs.slice(0, 12).map((job) => (
                <li key={job.id} className="rounded-lg border border-border/60 px-3 py-2 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-medium">{job.repo}</span>
                    <Badge variant="outline" className="shrink-0 text-xs capitalize">
                      {job.status}
                    </Badge>
                  </div>
                  <p className="mt-0.5 truncate text-xs text-muted-foreground">
                    {job.job_type}
                    {job.branch ? ` · ${job.branch}` : ""}
                  </p>
                  {job.error && <p className="mt-1 text-xs text-red-600">{job.error}</p>}
                </li>
              ))}
            </ul>
          )}
        </PanelCard>
      </div>

      <PanelCard title="Problems" description="Open findings across all branches" icon={MessageSquareIcon}>
        {findings.length === 0 ? (
          <p className="text-sm text-muted-foreground">No open problems. All branches look healthy.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {findings.map((f) => {
              const sev = f.severity ?? "medium"
              return (
                <li key={f.id} className="rounded-xl border border-border/70 bg-card p-4 shadow-sm">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold text-foreground">{f.title}</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {f.repo} · {f.branch || "—"} · {f.category}
                      </p>
                      {f.body && (
                        <pre className="mt-2 max-h-32 overflow-auto rounded-md bg-muted/50 p-2 text-xs text-muted-foreground">
                          {f.body.slice(0, 600)}
                        </pre>
                      )}
                      {f.suggestion && (
                        <p className="mt-2 text-sm text-foreground/80">
                          <span className="font-medium">Suggestion: </span>
                          {f.suggestion}
                        </p>
                      )}
                    </div>
                    <Badge variant="outline" className={cn("text-xs", SEVERITY_CLASS[sev])}>
                      {sev}
                    </Badge>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy === `comment-${f.id}`}
                      onClick={() => runAction(`comment-${f.id}`, () => commentFinding(f.id))}
                    >
                      <MessageSquareIcon className="mr-1.5 size-3.5" />
                      Comment
                    </Button>
                    {f.file && (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy === `fix-${f.id}`}
                        onClick={() => runAction(`fix-${f.id}`, () => requestFix(f.id))}
                      >
                        <WrenchIcon className="mr-1.5 size-3.5" />
                        Request fix
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={busy === `playbook-claude-${f.id}`}
                      onClick={() => openPlaybook(f.id, "claude", `Fix in Claude — ${f.title}`)}
                    >
                      <TerminalIcon className="mr-1.5 size-3.5" />
                      Fix in Claude
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={busy === `playbook-cursor-${f.id}`}
                      onClick={() => openPlaybook(f.id, "cursor", `Fix in Cursor — ${f.title}`)}
                    >
                      Fix in Cursor
                    </Button>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </PanelCard>

      <QaAgentPlaybookSheet
        open={playbookOpen}
        onOpenChange={setPlaybookOpen}
        playbook={playbook}
        title={playbookTitle}
      />
    </div>
  )
}
