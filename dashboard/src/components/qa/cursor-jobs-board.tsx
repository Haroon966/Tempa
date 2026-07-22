import { ExternalLinkIcon, LoaderCircleIcon } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import type { CursorAgentJob } from "@/lib/api"
import { cn } from "@/lib/utils"

const STATUS_CLASS: Record<string, string> = {
  queued: "border-border bg-muted text-muted-foreground",
  running: "border-blue-200 bg-blue-50 text-blue-700",
  waiting_ci: "border-amber-200 bg-amber-50 text-amber-800",
  fixing_ci: "border-orange-200 bg-orange-50 text-orange-800",
  running_tests: "border-violet-200 bg-violet-50 text-violet-800",
  completed: "border-green-200 bg-green-50 text-green-700",
  failed: "border-red-200 bg-red-50 text-red-700",
  interrupted: "border-border bg-muted text-muted-foreground",
  needs_help: "border-red-300 bg-red-50 text-red-800",
}

function slackThreadHref(job: CursorAgentJob): string | null {
  if (!job.channel_id || !job.thread_ts) return null
  const ts = job.thread_ts.replace(".", "")
  return `https://app.slack.com/archives/${job.channel_id}/p${ts}`
}

export function CursorJobsBoard({ jobs }: { jobs: CursorAgentJob[] }) {
  if (jobs.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No Tempa Cursor jobs yet. Allowlisted Slack coding asks show up here.
      </p>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-left text-sm">
        <thead>
          <tr className="border-b border-border/60 text-[11px] uppercase tracking-wide text-muted-foreground">
            <th className="pb-2 pr-3 font-semibold">User</th>
            <th className="pb-2 pr-3 font-semibold">Phase</th>
            <th className="pb-2 pr-3 font-semibold">PR</th>
            <th className="pb-2 pr-3 font-semibold">Thread</th>
            <th className="pb-2 font-semibold">Updated</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => {
            const status = job.status || job.phase || "unknown"
            const thread = slackThreadHref(job)
            const active = ["queued", "running", "waiting_ci", "fixing_ci", "running_tests"].includes(
              status,
            )
            return (
              <tr key={job.id} className="border-b border-border/40 align-top">
                <td className="py-2.5 pr-3">
                  <div className="font-medium">{job.user_id || "—"}</div>
                  <div className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                    {job.label || job.ask_text || job.repo || "—"}
                  </div>
                </td>
                <td className="py-2.5 pr-3">
                  <Badge
                    variant="outline"
                    className={cn("gap-1 font-normal", STATUS_CLASS[status] ?? STATUS_CLASS.queued)}
                  >
                    {active ? <LoaderCircleIcon className="size-3 animate-spin" /> : null}
                    {status}
                    {typeof job.ci_fix_count === "number" && job.ci_fix_count > 0
                      ? ` · fix ${job.ci_fix_count}`
                      : ""}
                  </Badge>
                </td>
                <td className="py-2.5 pr-3">
                  {job.pr_url ? (
                    <a
                      href={job.pr_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-xs text-foreground underline-offset-2 hover:underline"
                    >
                      #{job.pr_number || "PR"}
                      <ExternalLinkIcon className="size-3" />
                    </a>
                  ) : (
                    <span className="text-xs text-muted-foreground">—</span>
                  )}
                </td>
                <td className="py-2.5 pr-3">
                  {thread ? (
                    <a
                      href={thread}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs underline-offset-2 hover:underline"
                    >
                      open
                    </a>
                  ) : (
                    <span className="text-xs text-muted-foreground">—</span>
                  )}
                </td>
                <td className="py-2.5 text-xs text-muted-foreground">
                  {(job.updated_at || job.enqueued_at || "").replace("T", " ").slice(0, 19) || "—"}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
