import { useCallback, useEffect, useRef, useState } from "react"
import {
  fetchCursorSessionDetail,
  fetchCursorSessions,
  type CursorAgentJob,
  type CursorSessionDetail,
} from "@/lib/api"

const POLL_MS = 12_000

function equal<T>(a: T, b: T) {
  return JSON.stringify(a) === JSON.stringify(b)
}

export function useCursorSessions(pollMs = POLL_MS) {
  const [sessions, setSessions] = useState<CursorAgentJob[]>([])
  const [activeCount, setActiveCount] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<CursorSessionDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const listInFlight = useRef(false)
  const selectedIdRef = useRef<string | null>(null)
  const detailSeq = useRef(0)

  selectedIdRef.current = selectedId

  const refreshList = useCallback(async () => {
    if (listInFlight.current) return
    listInFlight.current = true
    try {
      const payload = await fetchCursorSessions(150)
      setSessions((prev) => (equal(prev, payload.sessions) ? prev : payload.sessions))
      setActiveCount(payload.counts?.active ?? 0)
      setError(null)
      setSelectedId((cur) => {
        if (cur) return cur
        return payload.sessions[0]?.id ?? null
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
      listInFlight.current = false
    }
  }, [])

  const refreshDetail = useCallback(async (jobId: string) => {
    if (!jobId) return
    const seq = ++detailSeq.current
    setDetailLoading(true)
    try {
      const payload = await fetchCursorSessionDetail(jobId)
      // Ignore stale responses from a previous selection or superseded poll.
      if (seq !== detailSeq.current || selectedIdRef.current !== jobId) return
      setDetail((prev) => (equal(prev, payload) ? prev : payload))
      setError(null)
    } catch (err) {
      if (seq !== detailSeq.current || selectedIdRef.current !== jobId) return
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      if (seq === detailSeq.current) setDetailLoading(false)
    }
  }, [])

  useEffect(() => {
    void refreshList()
    const id = window.setInterval(() => void refreshList(), pollMs)
    return () => window.clearInterval(id)
  }, [pollMs, refreshList])

  useEffect(() => {
    if (!selectedId) {
      detailSeq.current += 1
      setDetail(null)
      setDetailLoading(false)
      return
    }
    // Drop pane content that belongs to another job immediately on switch.
    setDetail((prev) => (prev?.job.id === selectedId ? prev : null))
    void refreshDetail(selectedId)
    const id = window.setInterval(() => void refreshDetail(selectedId), pollMs)
    return () => window.clearInterval(id)
  }, [selectedId, pollMs, refreshDetail])

  return {
    sessions,
    activeCount,
    selectedId,
    setSelectedId,
    detail,
    loading,
    detailLoading,
    error,
    refresh: refreshList,
  }
}
