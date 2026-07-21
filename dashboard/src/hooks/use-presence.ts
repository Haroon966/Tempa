import { useCallback, useEffect, useRef, useState } from "react"
import {
  fetchPresence,
  invalidateJsonCache,
  postPresenceSync,
  type PresencePayload,
} from "@/lib/api"

const PRESENCE_POLL_MS = 30_000

function equal<T>(a: T, b: T) {
  return JSON.stringify(a) === JSON.stringify(b)
}

export function usePresence(date?: string, pollMs = PRESENCE_POLL_MS) {
  const [data, setData] = useState<PresencePayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [syncing, setSyncing] = useState(false)
  const inFlight = useRef(false)

  const refresh = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    try {
      const payload = await fetchPresence(date)
      setData((prev) => (equal(prev, payload) ? prev : payload))
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
      inFlight.current = false
    }
  }, [date])

  const sync = useCallback(async () => {
    setSyncing(true)
    try {
      const result = await postPresenceSync()
      invalidateJsonCache()
      setData(result.presence)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSyncing(false)
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

  return { data, loading, error, syncing, refresh, sync }
}
