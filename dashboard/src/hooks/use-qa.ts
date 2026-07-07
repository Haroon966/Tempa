import { useCallback, useEffect, useRef, useState } from "react"
import {
  deleteQaRepo,
  fetchQaAgentPlaybook,
  fetchQaBranches,
  fetchQaFindings,
  fetchQaJobs,
  fetchQaRepos,
  fetchQaSummary,
  invalidateJsonCache,
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

const QA_POLL_MS = 30_000

function qaResultsEqual<T>(a: T, b: T) {
  return JSON.stringify(a) === JSON.stringify(b)
}

export function useQa(pollMs = QA_POLL_MS) {
  const [summary, setSummary] = useState<QaSummary | null>(null)
  const [repos, setRepos] = useState<QaRepoEntry[]>([])
  const [branches, setBranches] = useState<QaBranchStatus[]>([])
  const [findings, setFindings] = useState<QaFinding[]>([])
  const [jobs, setJobs] = useState<QaJob[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const inFlight = useRef(false)

  const refresh = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    try {
      const results = await Promise.allSettled([
        fetchQaSummary(),
        fetchQaRepos(),
        fetchQaBranches(),
        fetchQaFindings(),
        fetchQaJobs(),
      ])
      const [s, r, b, f, j] = results
      if (s.status === "fulfilled") {
        setSummary((prev) => (qaResultsEqual(prev, s.value) ? prev : s.value))
      }
      if (r.status === "fulfilled") {
        setRepos((prev) => (qaResultsEqual(prev, r.value.repos) ? prev : r.value.repos))
      }
      if (b.status === "fulfilled") {
        setBranches((prev) => (qaResultsEqual(prev, b.value.branches) ? prev : b.value.branches))
      }
      if (f.status === "fulfilled") {
        setFindings((prev) => (qaResultsEqual(prev, f.value.findings) ? prev : f.value.findings))
      }
      if (j.status === "fulfilled") {
        setJobs((prev) => (qaResultsEqual(prev, j.value.jobs) ? prev : j.value.jobs))
      }

      const failed = results.find((res) => res.status === "rejected")
      if (failed && failed.status === "rejected") {
        setError(failed.reason instanceof Error ? failed.reason.message : String(failed.reason))
      } else {
        setError(null)
      }
    } finally {
      setLoading(false)
      inFlight.current = false
    }
  }, [])

  useEffect(() => {
    const tick = () => {
      if (document.visibilityState === "hidden") return
      void refresh()
    }
    void refresh()
    const id = setInterval(tick, pollMs)
    const onVisibility = () => {
      if (document.visibilityState === "visible") void refresh()
    }
    document.addEventListener("visibilitychange", onVisibility)
    return () => {
      clearInterval(id)
      document.removeEventListener("visibilitychange", onVisibility)
    }
  }, [refresh, pollMs])

  const invalidateAndRefresh = useCallback(async () => {
    invalidateJsonCache()
    await refresh()
  }, [refresh])

  const scanRepo = useCallback(
    async (repo: string, branch?: string, prNumber?: number) => {
      await postQaScan(repo, branch, prNumber)
      await invalidateAndRefresh()
    },
    [invalidateAndRefresh],
  )

  const addRepo = useCallback(
    async (repo: string) => {
      await postQaRepo(repo)
      await invalidateAndRefresh()
    },
    [invalidateAndRefresh],
  )

  const removeRepo = useCallback(
    async (repo: string) => {
      await deleteQaRepo(repo)
      await invalidateAndRefresh()
    },
    [invalidateAndRefresh],
  )

  const commentFinding = useCallback(
    async (findingId: string) => {
      await postQaComment(findingId)
      await invalidateAndRefresh()
    },
    [invalidateAndRefresh],
  )

  const requestFix = useCallback(
    async (findingId: string) => {
      await postQaFix(findingId)
      await invalidateAndRefresh()
    },
    [invalidateAndRefresh],
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
