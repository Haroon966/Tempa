export type QaJobFinishFields = {
  status: string
  completed_at?: string
  updated_at?: string
  enqueued_at?: string
}

function jobFinishMs(job: QaJobFinishFields): number {
  const raw = job.completed_at || job.updated_at || job.enqueued_at
  if (!raw) return 0
  const t = Date.parse(raw)
  return Number.isFinite(t) ? t : 0
}

/** Most recently finished completed/failed jobs (newest first). */
export function recentDoneJobs<T extends QaJobFinishFields>(jobs: T[], limit = 12): T[] {
  return jobs
    .filter((j) => j.status === "completed" || j.status === "failed")
    .sort((a, b) => jobFinishMs(b) - jobFinishMs(a))
    .slice(0, limit)
}
