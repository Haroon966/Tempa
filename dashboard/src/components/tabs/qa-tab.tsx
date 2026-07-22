import {
  ArrowRightIcon,
  CheckCircle2Icon,
  CircleDashedIcon,
  GitBranchIcon,
  LayersIcon,
  ListTodoIcon,
  LoaderCircleIcon,
  MessageSquareIcon,
  PlusIcon,
  ScanSearchIcon,
  TerminalIcon,
  Trash2Icon,
  WrenchIcon,
} from "lucide-react"
import { useMemo, useState } from "react"
import { QaAgentPlaybookSheet } from "@/components/qa/qa-agent-playbook-sheet"
import { CursorJobsBoard } from "@/components/qa/cursor-jobs-board"
import { QaReviewBoard } from "@/components/qa/qa-review-board"
import { PageHeader } from "@/components/dashboard/page-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useQa } from "@/hooks/use-qa"
import type { QaAgentPlaybook, QaBranchStatus, QaFinding } from "@/lib/api"
import { cn } from "@/lib/utils"

const SEVERITY_CLASS: Record<string, string> = {
  critical: "border-red-300 bg-red-50 text-red-700",
  high: "border-orange-300 bg-orange-50 text-orange-700",
  medium: "border-amber-300 bg-amber-50 text-amber-700",
  low: "border-blue-200 bg-blue-50 text-blue-700",
  info: "border-border bg-muted text-muted-foreground",
}

const STATUS_CLASS: Record<string, string> = {
  success: "text-green-700",
  failure: "text-red-700",
  pending: "text-amber-700",
  skipped: "text-muted-foreground",
  unknown: "text-muted-foreground",
}

function StatusDot({ status }: { status?: string }) {
  const s = status ?? "unknown"
  return (
    <span className={cn("text-xs font-medium capitalize", STATUS_CLASS[s] ?? STATUS_CLASS.unknown)}>
      {s}
    </span>
  )
}

function FlowStep({
  label,
  count,
  active,
  icon: Icon,
  last,
}: {
  label: string
  count: number
  active?: boolean
  icon: typeof CircleDashedIcon
  last?: boolean
}) {
  return (
    <div className="flex min-w-0 flex-1 items-center gap-2 sm:gap-3">
      <div
        className={cn(
          "flex min-w-0 flex-1 items-center gap-3 rounded-xl border px-3 py-3 transition-colors duration-200",
          active
            ? "border-foreground/20 bg-foreground text-background"
            : "border-border/70 bg-card text-foreground",
        )}
      >
        <Icon
          className={cn(
            "size-4 shrink-0",
            active ? "text-background" : "text-muted-foreground",
            label === "Scanning" && count > 0 && "animate-spin",
          )}
        />
        <div className="min-w-0">
          <p className={cn("text-[11px] font-medium uppercase tracking-wide", active ? "text-background/70" : "text-muted-foreground")}>
            {label}
          </p>
          <p className="text-xl font-bold tabular-nums tracking-tight">{count}</p>
        </div>
      </div>
      {!last && (
        <ArrowRightIcon className="hidden size-4 shrink-0 text-muted-foreground/50 sm:block" aria-hidden />
      )}
    </div>
  )
}

function FindingRow({
  finding,
  busy,
  onComment,
  onFix,
  onPlaybook,
}: {
  finding: QaFinding
  busy: string | null
  onComment: () => void
  onFix: () => void
  onPlaybook: (target: "claude" | "cursor") => void
}) {
  const sev = finding.severity ?? "medium"
  return (
    <li className="rounded-xl border border-border/70 bg-card p-4 transition-colors duration-200 hover:border-foreground/20">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-foreground">{finding.title}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {finding.repo}
            {finding.branch ? ` · ${finding.branch}` : ""}
          </p>
        </div>
        <Badge variant="outline" className={cn("text-xs capitalize", SEVERITY_CLASS[sev])}>
          {sev}
        </Badge>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant="outline" disabled={busy === `comment-${finding.id}`} onClick={onComment}>
          <MessageSquareIcon className="mr-1.5 size-3.5" />
          Comment
        </Button>
        {finding.file && (
          <Button size="sm" variant="outline" disabled={busy === `fix-${finding.id}`} onClick={onFix}>
            <WrenchIcon className="mr-1.5 size-3.5" />
            Request fix
          </Button>
        )}
        <Button
          size="sm"
          variant="secondary"
          disabled={busy === `playbook-claude-${finding.id}`}
          onClick={() => onPlaybook("claude")}
        >
          <TerminalIcon className="mr-1.5 size-3.5" />
          Claude
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={busy === `playbook-cursor-${finding.id}`}
          onClick={() => onPlaybook("cursor")}
        >
          Cursor
        </Button>
      </div>
    </li>
  )
}

function branchNeedsAttention(row: QaBranchStatus) {
  return (
    row.ci_status === "failure" ||
    row.lint_status === "failure" ||
    row.test_status === "failure" ||
    (row.grade && ["D", "F"].includes(row.grade))
  )
}

export function QaTab() {
  const {
    summary,
    repos: managedRepos,
    branches,
    findings,
    jobs,
    cursorJobs,
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
  const [scanOpen, setScanOpen] = useState(false)
  const [newRepo, setNewRepo] = useState("")
  const [scanRepoInput, setScanRepoInput] = useState("")
  const [scanBranchInput, setScanBranchInput] = useState("")
  const [scanPrInput, setScanPrInput] = useState("")
  const [branchFilter, setBranchFilter] = useState("")
  const [view, setView] = useState("flow")

  const flowCounts = useMemo(() => {
    const queued = jobs.filter((j) => j.status === "queued").length
    const scanning = jobs.filter((j) => j.status === "running").length
    const done = jobs.filter((j) => j.status === "completed" || j.status === "failed").length
    const fix = findings.filter((f) => f.severity === "critical" || f.severity === "high").length
    return { queued, scanning, done, fix }
  }, [jobs, findings])

  const frontFindings = useMemo(
    () =>
      findings
        .filter((f) => f.severity === "critical" || f.severity === "high")
        .slice(0, 5),
    [findings],
  )

  const attentionBranches = useMemo(() => {
    const q = branchFilter.trim().toLowerCase()
    const sorted = [...branches].sort((a, b) => {
      const aHit = branchNeedsAttention(a) ? 0 : 1
      const bHit = branchNeedsAttention(b) ? 0 : 1
      if (aHit !== bHit) return aHit - bHit
      return `${a.repo}/${a.branch}`.localeCompare(`${b.repo}/${b.branch}`)
    })
    const filtered = q
      ? sorted.filter(
          (b) =>
            b.repo.toLowerCase().includes(q) ||
            (b.branch || "").toLowerCase().includes(q),
        )
      : sorted
    return filtered.slice(0, 25)
  }, [branches, branchFilter])

  const activeCursor = useMemo(
    () =>
      cursorJobs.filter((j) =>
        ["queued", "running", "waiting_ci", "fixing_ci", "running_tests"].includes(
          j.status || j.phase || "",
        ),
      ).length,
    [cursorJobs],
  )

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
        <Skeleton className="h-20 w-full rounded-xl" />
        <Skeleton className="h-24 w-full rounded-xl" />
        <Skeleton className="h-72 w-full rounded-xl" />
      </div>
    )
  }

  if (summary && !summary.enabled) {
    return (
      <div className="rounded-xl border border-border bg-muted/30 p-10 text-center">
        <p className="font-semibold">QA is off</p>
        <p className="mt-2 text-sm text-muted-foreground">Enable TEMPA_QA_ENABLED to start scanning.</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="QA"
        description="Request → scan → review → fix"
        actions={
          <Button className="cursor-pointer" onClick={() => setScanOpen(true)}>
            <ScanSearchIcon className="mr-1.5 size-4" />
            New scan
          </Button>
        }
      />

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      {!summary?.configured && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Connect GitHub under Manage to run scans.
        </div>
      )}

      <div className="flex flex-col gap-2 sm:flex-row sm:items-stretch">
        <FlowStep label="Queued" count={flowCounts.queued} icon={CircleDashedIcon} active={flowCounts.queued > 0} />
        <FlowStep
          label="Scanning"
          count={flowCounts.scanning}
          icon={LoaderCircleIcon}
          active={flowCounts.scanning > 0}
        />
        <FlowStep label="Reviewed" count={flowCounts.done} icon={CheckCircle2Icon} />
        <FlowStep label="Needs fix" count={flowCounts.fix} icon={WrenchIcon} last active={flowCounts.fix > 0} />
      </div>

      <Tabs
        value={view}
        onValueChange={(next) => {
          if (typeof next === "string") setView(next)
        }}
        className="gap-4"
      >
        <TabsList variant="line" className="w-full justify-start overflow-x-auto">
          <TabsTrigger value="flow" className="cursor-pointer px-3">
            <ListTodoIcon className="size-3.5" />
            Flow
            {flowCounts.queued + flowCounts.scanning > 0 && (
              <Badge variant="outline" className="ml-1 text-[10px]">
                {flowCounts.queued + flowCounts.scanning}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="problems" className="cursor-pointer px-3">
            <MessageSquareIcon className="size-3.5" />
            Problems
            {findings.length > 0 && (
              <Badge variant="outline" className="ml-1 text-[10px]">
                {findings.length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="manage" className="cursor-pointer px-3">
            <LayersIcon className="size-3.5" />
            Manage
            {activeCursor > 0 && (
              <Badge variant="outline" className="ml-1 text-[10px]">
                {activeCursor} coding
              </Badge>
            )}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="flow" className="flex flex-col gap-6 outline-none">
          <section className="flex flex-col gap-3">
            <div className="flex items-end justify-between gap-2">
              <div>
                <h3 className="text-sm font-semibold text-foreground">Active reviews</h3>
                <p className="text-xs text-muted-foreground">Who asked, what’s running, what’s done</p>
              </div>
            </div>
            <QaReviewBoard jobs={jobs} />
          </section>

          {frontFindings.length > 0 && (
            <section className="flex flex-col gap-3">
              <div className="flex items-end justify-between gap-2">
                <div>
                  <h3 className="text-sm font-semibold text-foreground">Needs attention</h3>
                  <p className="text-xs text-muted-foreground">Critical and high findings only</p>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="cursor-pointer text-xs"
                  onClick={() => setView("problems")}
                >
                  All problems
                  <ArrowRightIcon className="ml-1 size-3.5" />
                </Button>
              </div>
              <ul className="flex flex-col gap-3">
                {frontFindings.map((f) => (
                  <FindingRow
                    key={f.id}
                    finding={f}
                    busy={busy}
                    onComment={() => runAction(`comment-${f.id}`, () => commentFinding(f.id))}
                    onFix={() => runAction(`fix-${f.id}`, () => requestFix(f.id))}
                    onPlaybook={(target) =>
                      openPlaybook(f.id, target, `Fix in ${target === "claude" ? "Claude" : "Cursor"} — ${f.title}`)
                    }
                  />
                ))}
              </ul>
            </section>
          )}
        </TabsContent>

        <TabsContent value="problems" className="outline-none">
          {findings.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border/70 px-6 py-12 text-center">
              <p className="font-medium text-foreground">No open problems</p>
              <p className="mt-1 text-sm text-muted-foreground">Scans look clean. Run a new scan if you need a fresh pass.</p>
              <Button className="mt-4 cursor-pointer" size="sm" onClick={() => setScanOpen(true)}>
                New scan
              </Button>
            </div>
          ) : (
            <ul className="flex flex-col gap-3">
              {findings.map((f) => (
                <FindingRow
                  key={f.id}
                  finding={f}
                  busy={busy}
                  onComment={() => runAction(`comment-${f.id}`, () => commentFinding(f.id))}
                  onFix={() => runAction(`fix-${f.id}`, () => requestFix(f.id))}
                  onPlaybook={(target) =>
                    openPlaybook(f.id, target, `Fix in ${target === "claude" ? "Claude" : "Cursor"} — ${f.title}`)
                  }
                />
              ))}
            </ul>
          )}
        </TabsContent>

        <TabsContent value="manage" className="flex flex-col gap-8 outline-none">
          <section className="flex flex-col gap-3">
            <div>
              <h3 className="text-sm font-semibold text-foreground">Repositories</h3>
              <p className="text-xs text-muted-foreground">What Tempa is allowed to scan</p>
            </div>
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
              <Button type="submit" size="sm" className="cursor-pointer" disabled={busy === "add-repo" || !newRepo.trim()}>
                <PlusIcon className="mr-1.5 size-3.5" />
                Add
              </Button>
            </form>
            {managedRepos.length === 0 ? (
              <p className="text-sm text-muted-foreground">No repos yet. Add one above.</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {managedRepos.map((entry) => (
                  <li
                    key={entry.repo}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/60 px-3 py-2"
                  >
                    <span className="truncate font-medium">{entry.repo}</span>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        className="cursor-pointer"
                        disabled={busy === `repo-${entry.repo}`}
                        onClick={() => runAction(`repo-${entry.repo}`, () => scanRepo(entry.repo))}
                      >
                        Scan all
                      </Button>
                      {entry.removable && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="cursor-pointer border-red-200 text-red-600 hover:bg-red-50"
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
          </section>

          <section className="flex flex-col gap-3">
            <div className="flex flex-wrap items-end justify-between gap-2">
              <div>
                <h3 className="text-sm font-semibold text-foreground">Branch health</h3>
                <p className="text-xs text-muted-foreground">
                  Attention first · showing {attentionBranches.length}
                  {branches.length > attentionBranches.length ? ` of ${branches.length}` : ""}
                </p>
              </div>
              <Input
                placeholder="Filter repo or branch"
                value={branchFilter}
                onChange={(e) => setBranchFilter(e.target.value)}
                className="max-w-xs"
              />
            </div>
            {attentionBranches.length === 0 ? (
              <p className="text-sm text-muted-foreground">No branch scans yet.</p>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-border/60">
                <table className="w-full min-w-[560px] text-left text-sm">
                  <thead>
                    <tr className="border-b border-border/60 bg-muted/30 text-[11px] uppercase tracking-wide text-muted-foreground">
                      <th className="px-3 py-2 font-semibold">Branch</th>
                      <th className="px-3 py-2 font-semibold">CI</th>
                      <th className="px-3 py-2 font-semibold">Lint</th>
                      <th className="px-3 py-2 font-semibold">Tests</th>
                      <th className="px-3 py-2 font-semibold">Grade</th>
                      <th className="px-3 py-2 font-semibold" />
                    </tr>
                  </thead>
                  <tbody>
                    {attentionBranches.map((row) => {
                      const key = `${row.repo}#${row.branch}`
                      const hot = branchNeedsAttention(row)
                      return (
                        <tr
                          key={key}
                          className={cn(
                            "border-b border-border/40 last:border-0",
                            hot && "bg-red-50/40",
                          )}
                        >
                          <td className="px-3 py-2.5">
                            <p className="font-medium text-foreground">{row.branch}</p>
                            <p className="text-xs text-muted-foreground">{row.repo}</p>
                          </td>
                          <td className="px-3 py-2.5">
                            <StatusDot status={row.ci_status} />
                          </td>
                          <td className="px-3 py-2.5">
                            <StatusDot status={row.lint_status} />
                          </td>
                          <td className="px-3 py-2.5">
                            <StatusDot status={row.test_status} />
                          </td>
                          <td className="px-3 py-2.5">
                            <Badge variant="outline">{row.grade ?? "—"}</Badge>
                          </td>
                          <td className="px-3 py-2.5 text-right">
                            <Button
                              size="sm"
                              variant="outline"
                              className="cursor-pointer"
                              disabled={busy === key}
                              onClick={() => runAction(key, () => scanRepo(row.repo, row.branch))}
                            >
                              Rescan
                            </Button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="flex flex-col gap-3">
            <div>
              <h3 className="text-sm font-semibold text-foreground">Cursor coding jobs</h3>
              <p className="text-xs text-muted-foreground">Slack write jobs — separate from QA scans</p>
            </div>
            <CursorJobsBoard jobs={cursorJobs} />
          </section>
        </TabsContent>
      </Tabs>

      <Sheet open={scanOpen} onOpenChange={setScanOpen}>
        <SheetContent side="right" className="w-full sm:max-w-md">
          <SheetHeader className="text-left">
            <SheetTitle>New scan</SheetTitle>
            <SheetDescription>Queue a repo, branch, or PR for review.</SheetDescription>
          </SheetHeader>
          <form
            className="mt-6 flex flex-col gap-4 px-4 pb-8"
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
                setScanOpen(false)
                setView("flow")
              })
            }}
          >
            <div className="flex flex-col gap-1.5">
              <label htmlFor="qa-scan-repo" className="text-xs font-medium text-muted-foreground">
                Repository
              </label>
              <Input
                id="qa-scan-repo"
                placeholder="owner/repo"
                value={scanRepoInput}
                onChange={(e) => setScanRepoInput(e.target.value)}
                required
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="qa-scan-branch" className="text-xs font-medium text-muted-foreground">
                Branch <span className="font-normal">(optional)</span>
              </label>
              <Input
                id="qa-scan-branch"
                placeholder="main"
                value={scanBranchInput}
                onChange={(e) => setScanBranchInput(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="qa-scan-pr" className="text-xs font-medium text-muted-foreground">
                PR number <span className="font-normal">(optional)</span>
              </label>
              <Input
                id="qa-scan-pr"
                placeholder="42"
                value={scanPrInput}
                onChange={(e) => setScanPrInput(e.target.value)}
              />
            </div>
            <Button
              type="submit"
              className="cursor-pointer"
              disabled={busy === "custom-scan" || !scanRepoInput.trim()}
            >
              {busy === "custom-scan" ? (
                <LoaderCircleIcon className="mr-1.5 size-4 animate-spin" />
              ) : (
                <GitBranchIcon className="mr-1.5 size-4" />
              )}
              Queue scan
            </Button>
          </form>
        </SheetContent>
      </Sheet>

      <QaAgentPlaybookSheet
        open={playbookOpen}
        onOpenChange={setPlaybookOpen}
        playbook={playbook}
        title={playbookTitle}
      />
    </div>
  )
}
