import { useCallback, useEffect, useState } from "react"
import {
  deleteQaRepo,
  fetchQaAgentPlaybook,
  fetchQaBranches,
  fetchQaFindings,
  fetchQaJobs,
  fetchQaRepos,
  fetchQaSummary,
  postQaComment,
  postQaFix,
  postQaRepo,
  postQaScan,
  type QaAgentPlaybook,
  type QaBranchStatus,
  type QaFinding,
  type QaJob,
  type QaRepoEntry,
  type QaSummary,
} from "@/lib/api"

export function useQa(pollMs = 12000) {
  const [summary, setSummary] = useState<QaSummary | null>(null)
  const [repos, setRepos] = useState<QaRepoEntry[]>([])
  const [branches, setBranches] = useState<QaBranchStatus[]>([])
  const [findings, setFindings] = useState<QaFinding[]>([])
  const [jobs, setJobs] = useState<QaJob[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([
      fetchQaSummary(),
      fetchQaRepos(),
      fetchQaBranches(),
      fetchQaFindings(),
      fetchQaJobs(),
    ])
    const [s, r, b, f, j] = results
    if (s.status === "fulfilled") setSummary(s.value)
    if (r.status === "fulfilled") setRepos(r.value.repos)
    if (b.status === "fulfilled") setBranches(b.value.branches)
    if (f.status === "fulfilled") setFindings(f.value.findings)
    if (j.status === "fulfilled") setJobs(j.value.jobs)

    const failed = results.find((res) => res.status === "rejected")
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
    async (repo: string, branch?: string, prNumber?: number) => {
      await postQaScan(repo, branch, prNumber)
      await refresh()
    },
    [refresh],
  )

  const addRepo = useCallback(
    async (repo: string) => {
      await postQaRepo(repo)
      await refresh()
    },
    [refresh],
  )

  const removeRepo = useCallback(
    async (repo: string) => {
      await deleteQaRepo(repo)
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
    repos,
    branches,
    findings,
    jobs,
    loading,
    error,
    refresh,
    scanRepo,
    addRepo,
    removeRepo,
    commentFinding,
    requestFix,
    loadAgentPlaybook,
  }
}
