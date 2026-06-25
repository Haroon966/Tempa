import { useCallback, useEffect, useState } from "react"
import {
  fetchQaAgentPlaybook,
  fetchQaBranches,
  fetchQaFindings,
  fetchQaJobs,
  fetchQaSummary,
  postQaComment,
  postQaFix,
  postQaScan,
  type QaAgentPlaybook,
  type QaBranchStatus,
  type QaFinding,
  type QaJob,
  type QaSummary,
} from "@/lib/api"

export function useQa(pollMs = 12000) {
  const [summary, setSummary] = useState<QaSummary | null>(null)
  const [branches, setBranches] = useState<QaBranchStatus[]>([])
  const [findings, setFindings] = useState<QaFinding[]>([])
  const [jobs, setJobs] = useState<QaJob[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([
      fetchQaSummary(),
      fetchQaBranches(),
      fetchQaFindings(),
      fetchQaJobs(),
    ])
    const [s, b, f, j] = results
    if (s.status === "fulfilled") setSummary(s.value)
    if (b.status === "fulfilled") setBranches(b.value.branches)
    if (f.status === "fulfilled") setFindings(f.value.findings)
    if (j.status === "fulfilled") setJobs(j.value.jobs)

    const failed = results.find((r) => r.status === "rejected")
    if (failed && failed.status === "rejected") {
      setError(failed.reason instanceof Error ? failed.reason.message : String(failed.reason))
    } else {
      setError(null)
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, pollMs)
    return () => clearInterval(id)
  }, [refresh, pollMs])

  const scanRepo = useCallback(
    async (repo: string, branch?: string) => {
      await postQaScan(repo, branch)
      await refresh()
    },
    [refresh],
  )

  const commentFinding = useCallback(
    async (findingId: string) => {
      await postQaComment(findingId)
      await refresh()
    },
    [refresh],
  )

  const requestFix = useCallback(
    async (findingId: string) => {
      await postQaFix(findingId)
      await refresh()
    },
    [refresh],
  )

  const loadAgentPlaybook = useCallback(
    async (findingId: string, target: "claude" | "cursor"): Promise<QaAgentPlaybook> => {
      return fetchQaAgentPlaybook(findingId, target)
    },
    [],
  )

  return {
    summary,
    branches,
    findings,
    jobs,
    loading,
    error,
    refresh,
    scanRepo,
    commentFinding,
    requestFix,
    loadAgentPlaybook,
  }
}
