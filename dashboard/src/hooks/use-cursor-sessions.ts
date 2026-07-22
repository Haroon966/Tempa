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
  const detailInFlight = useRef(false)

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
    if (!jobId || detailInFlight.current) return
    detailInFlight.current = true
    setDetailLoading(true)
    try {
      const payload = await fetchCursorSessionDetail(jobId)
      setDetail((prev) => (equal(prev, payload) ? prev : payload))
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setDetailLoading(false)
      detailInFlight.current = false
    }
  }, [])

  useEffect(() => {
    void refreshList()
    const id = window.setInterval(() => void refreshList(), pollMs)
    return () => window.clearInterval(id)
  }, [pollMs, refreshList])

  useEffect(() => {
    if (!selectedId) {
      setDetail(null)
      return
    }
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
