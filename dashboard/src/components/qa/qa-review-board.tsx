import {
  ArrowUpIcon,
  BotIcon,
  CalendarClockIcon,
  CheckCircle2Icon,
  CircleDashedIcon,
  ExternalLinkIcon,
  GitPullRequestIcon,
  HashIcon,
  LoaderCircleIcon,
  MessageCircleIcon,
  MonitorIcon,
  XCircleIcon,
} from "lucide-react"
import { useEffect, useState } from "react"
import { Badge } from "@/components/ui/badge"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { fetchQaJobFindings, type QaFinding, type QaJob } from "@/lib/api"
import { cn } from "@/lib/utils"

const SEVERITY_CLASS: Record<string, string> = {
  critical: "border-red-300 bg-red-50 text-red-700",
  high: "border-orange-300 bg-orange-50 text-orange-700",
  medium: "border-amber-300 bg-amber-50 text-amber-700",
  low: "border-blue-200 bg-blue-50 text-blue-700",
  info: "border-border bg-muted text-muted-foreground",
}

const JOB_TYPE_LABEL: Record<string, string> = {
  deep_review: "Deep review",
  branch_scan: "Branch scan",
  repo_scan: "Repo scan",
}

function channelIcon(sourceChannel?: string) {
  const s = (sourceChannel ?? "").toLowerCase()
  if (s.includes("slack")) return HashIcon
  if (s.includes("whatsapp")) return MessageCircleIcon
  if (s.includes("github")) return GitPullRequestIcon
  if (s.includes("scheduler") || s.includes("followup")) return CalendarClockIcon
  if (s.includes("dashboard") || s.includes("api")) return MonitorIcon
  return BotIcon
}

function timeAgo(iso?: string): string {
  if (!iso) return ""
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return "just now"
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

function jobTitle(job: QaJob) {
  if (job.pr_number) return `${job.repo} · PR #${job.pr_number}`
  if (job.branch) return `${job.repo} · ${job.branch}`
  return job.repo
}

function githubLink(job: QaJob) {
  if (job.pr_url) return job.pr_url
  if (job.pr_number) return `https://github.com/${job.repo}/pull/${job.pr_number}`
  return `https://github.com/${job.repo}`
}

const COLUMNS = [
  { key: "queued", label: "Queued", icon: CircleDashedIcon, match: (s: string) => s === "queued" },
  { key: "running", label: "In progress", icon: LoaderCircleIcon, match: (s: string) => s === "running" },
  {
    key: "done",
    label: "Done",
    icon: CheckCircle2Icon,
    match: (s: string) => s === "completed" || s === "failed",
  },
] as const

function RequestCard({ job, onOpen }: { job: QaJob; onOpen: (job: QaJob) => void }) {
  const ChannelIcon = channelIcon(job.source_channel)
  const failed = job.status === "failed"
  const requester =
    job.requested_by || (job.source_channel ? job.source_channel.replace(/_/g, " ") : "system")
  return (
    <button
      type="button"
      onClick={() => onOpen(job)}
      className={cn(
        "w-full cursor-pointer rounded-lg border bg-card p-3 text-left shadow-sm",
        "transition-colors duration-200 hover:border-primary/40 hover:bg-muted/40",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        failed ? "border-red-300" : "border-border/70",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 truncate text-sm font-semibold text-foreground">{jobTitle(job)}</p>
        {job.priority && (
          <Badge variant="outline" className="shrink-0 gap-1 border-purple-300 bg-purple-50 text-[10px] text-purple-700">
            <ArrowUpIcon className="size-3" />
            Priority
          </Badge>
        )}
      </div>
      <div className="mt-1.5 flex items-center gap-1.5 text-xs text-slate-600">
        <ChannelIcon className="size-3.5 shrink-0" />
        <span className="truncate capitalize">{requester}</span>
      </div>
      {job.request_message ? (
        <p className="mt-1.5 line-clamp-2 border-l-2 border-border pl-2 text-xs italic text-slate-600">
          “{job.request_message}”
        </p>
      ) : null}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <Badge variant="outline" className="text-[10px]">
          {JOB_TYPE_LABEL[job.job_type ?? ""] ?? job.job_type ?? "scan"}
        </Badge>
        {failed && (
          <Badge variant="outline" className="gap-1 border-red-300 bg-red-50 text-[10px] text-red-700">
            <XCircleIcon className="size-3" />
            Failed
          </Badge>
        )}
        <span className="ml-auto text-[11px] text-slate-500">{timeAgo(job.enqueued_at)}</span>
      </div>
    </button>
  )
}


function TimelineRow({ label, at }: { label: string; at?: string }) {
  return (
    <div className="flex items-center justify-between gap-2 text-xs">
      <span className="text-slate-600">{label}</span>
      <span className="font-medium text-foreground">
        {at ? `${new Date(at).toLocaleString()} (${timeAgo(at)})` : "—"}
      </span>
    </div>
  )
}

function JobDetailSheet({
  job,
  open,
  onOpenChange,
}: {
  job: QaJob | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [findings, setFindings] = useState<QaFinding[]>([])
  const [findingsLoading, setFindingsLoading] = useState(false)

  useEffect(() => {
    if (!open || !job) return
    let cancelled = false
    setFindingsLoading(true)
    fetchQaJobFindings(job.id)
      .then((res) => {
        if (!cancelled) setFindings(res.findings)
      })
      .catch(() => {
        if (!cancelled) setFindings([])
      })
      .finally(() => {
        if (!cancelled) setFindingsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, job])

  if (!job) return null
  const ChannelIcon = channelIcon(job.source_channel)

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader className="text-left">
          <SheetTitle className="flex flex-wrap items-center gap-2">
            {jobTitle(job)}
            {job.priority && (
              <Badge variant="outline" className="gap-1 border-purple-300 bg-purple-50 text-[10px] text-purple-700">
                <ArrowUpIcon className="size-3" />
                Priority
              </Badge>
            )}
          </SheetTitle>
          <SheetDescription className="flex items-center gap-1.5">
            <ChannelIcon className="size-3.5" />
            Requested by {job.requested_by || (job.source_channel ? job.source_channel.replace(/_/g, " ") : "system")}
            {job.source_channel && job.requested_by ? ` via ${job.source_channel.replace(/_/g, " ")}` : ""}
          </SheetDescription>
        </SheetHeader>

        <div className="mt-6 flex flex-col gap-5 px-4 pb-8">
          {job.request_message && (
            <section>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Request</p>
              <blockquote className="mt-2 rounded-lg border border-border bg-muted/30 p-3 text-sm italic text-foreground/90">
                “{job.request_message}”
              </blockquote>
            </section>
          )}

          <section>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Timeline</p>
            <div className="mt-2 flex flex-col gap-1.5 rounded-lg border border-border p-3">
              <TimelineRow label="Enqueued" at={job.enqueued_at} />
              <TimelineRow label="Started" at={job.started_at} />
              <TimelineRow label="Completed" at={job.completed_at} />
            </div>
          </section>

          <section className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="capitalize">
              {job.status}
            </Badge>
            <Badge variant="outline">{JOB_TYPE_LABEL[job.job_type ?? ""] ?? job.job_type ?? "scan"}</Badge>
            {job.result?.provider && (
              <Badge variant="outline" className="capitalize">
                Reviewed by {job.result.provider}
              </Badge>
            )}
            <a
              href={githubLink(job)}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs font-medium text-primary underline-offset-2 hover:underline"
            >
              <ExternalLinkIcon className="size-3.5" />
              {job.pr_number ? `PR #${job.pr_number} on GitHub` : "Repo on GitHub"}
            </a>
            {typeof job.result?.comment_url === "string" && job.result.comment_url && (
              <a
                href={job.result.comment_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-xs font-medium text-primary underline-offset-2 hover:underline"
              >
                <ExternalLinkIcon className="size-3.5" />
                Posted review comment
              </a>
            )}
          </section>

          {job.error && (
            <section className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700">
              {job.error}
            </section>
          )}

          <section>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Findings {findingsLoading ? "" : `(${findings.length})`}
            </p>
            {findingsLoading ? (
              <p className="mt-2 text-sm text-slate-600">Loading findings…</p>
            ) : findings.length === 0 ? (
              <p className="mt-2 text-sm text-slate-600">
                {job.status === "completed" ? "No findings from this run." : "No findings yet."}
              </p>
            ) : (
              <ul className="mt-2 flex flex-col gap-2">
                {findings.map((f) => (
                  <li key={f.id} className="rounded-lg border border-border/70 p-3">
                    <div className="flex items-start justify-between gap-2">
                      <p className="min-w-0 text-sm font-medium text-foreground">{f.title}</p>
                      <Badge
                        variant="outline"
                        className={cn("shrink-0 text-[10px]", SEVERITY_CLASS[f.severity] ?? SEVERITY_CLASS.info)}
                      >
                        {f.severity}
                      </Badge>
                    </div>
                    {f.file && (
                      <p className="mt-1 font-mono text-[11px] text-slate-600">
                        {f.file}
                        {f.line ? `:${f.line}` : ""}
                      </p>
                    )}
                    {f.body && <p className="mt-1 line-clamp-3 text-xs text-slate-600">{f.body}</p>}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </SheetContent>
    </Sheet>
  )
}

export function QaReviewBoard({ jobs }: { jobs: QaJob[] }) {
  const [selected, setSelected] = useState<QaJob | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)

  function openJob(job: QaJob) {
    setSelected(job)
    setDetailOpen(true)
  }

  if (jobs.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border/70 px-6 py-10 text-center">
        <p className="font-medium text-foreground">No reviews in flight</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Ask Tempa with a PR link, or start a scan.
        </p>
      </div>
    )
  }

  // Keep Done lean — recent finishes only; Queued/Running stay complete.
  const recentDone = jobs
    .filter((j) => j.status === "completed" || j.status === "failed")
    .slice(0, 12)
  const boardJobs = [
    ...jobs.filter((j) => j.status === "queued" || j.status === "running"),
    ...recentDone,
  ]

  return (
    <>
      <div className="grid gap-3 md:grid-cols-3">
        {COLUMNS.map((col) => {
          const items = boardJobs.filter((j) => col.match(j.status))
          const Icon = col.icon
          return (
            <div key={col.key} className="flex min-w-0 flex-col rounded-xl border border-border/60 bg-muted/20">
              <div className="flex items-center gap-2 border-b border-border/60 px-3 py-2">
                <Icon
                  className={cn(
                    "size-4 text-muted-foreground",
                    col.key === "running" && items.length > 0 && "animate-spin",
                  )}
                />
                <span className="text-sm font-semibold text-foreground">{col.label}</span>
                <Badge variant="outline" className="ml-auto text-[10px]">
                  {items.length}
                </Badge>
              </div>
              <div className="flex max-h-[28rem] flex-col gap-2 overflow-y-auto p-2">
                {items.length === 0 ? (
                  <p className="px-1 py-6 text-center text-xs text-muted-foreground">Nothing here</p>
                ) : (
                  items.map((job) => <RequestCard key={job.id} job={job} onOpen={openJob} />)
                )}
              </div>
            </div>
          )
        })}
      </div>
      <JobDetailSheet job={selected} open={detailOpen} onOpenChange={setDetailOpen} />
    </>
  )
}
