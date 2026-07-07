import { useCallback, useEffect, useRef, useState } from "react"
import type { NavSection } from "@/components/dashboard/nav"
import type { DashboardPayload, DashboardSummary } from "@/types/dashboard"
import { fetchDashboard } from "@/lib/api"
import { isAgentStreaming } from "@/lib/dashboard-streaming"

const NORMAL_POLL_MS = 20_000
const SLOW_POLL_MS = 60_000
const FULL_POLL_MS = 60_000

function pollMsForRoute(activeTab: NavSection | null, pathname: string) {
  if (activeTab === "settings" || activeTab === "diagnostics") return SLOW_POLL_MS
  if (activeTab === "meetings" && pathname.includes("/archive")) return SLOW_POLL_MS
  return NORMAL_POLL_MS
}

function dashboardPayloadEqual(a: DashboardPayload | null, b: DashboardPayload): boolean {
  if (!a) return false
  const { generated_at: _a, ...restA } = a
  const { generated_at: _b, ...restB } = b
  return JSON.stringify(restA) === JSON.stringify(restB)
}

function mergeConnections(
  base: DashboardPayload["connections"],
  patch: DashboardPayload["connections"],
): DashboardPayload["connections"] {
  const next = { ...base }
  for (const [key, patchConn] of Object.entries(patch)) {
    if (!patchConn || typeof patchConn !== "object") {
      next[key] = patchConn
      continue
    }
    next[key] = { ...(base[key] ?? {}), ...patchConn }
  }
  return next
}

function applySummary(data: DashboardPayload, summary: DashboardSummary): DashboardPayload {
  return {
    ...data,
    generated_at: summary.generated_at,
    overall: summary.overall,
    connections: mergeConnections(data.connections, summary.connections),
    pending_actions: summary.pending_actions,
  }
}

export type UseDashboardOptions = {
  activeTab?: NavSection | null
  pathname?: string
}

export function useDashboard(options: UseDashboardOptions = {}) {
  const { activeTab = null, pathname = "" } = options
  const pollMs = pollMsForRoute(activeTab, pathname)

  const [data, setData] = useState<DashboardPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const summaryInFlight = useRef(false)
  const fullInFlight = useRef(false)

  const refreshFull = useCallback(async (force = false) => {
    if (fullInFlight.current) return
    fullInFlight.current = true
    try {
      const json = (await fetchDashboard(true, force)) as DashboardPayload
      setData((prev) => (dashboardPayloadEqual(prev, json) ? prev : json))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load dashboard")
    } finally {
      setLoading(false)
      fullInFlight.current = false
    }
  }, [])

  const refreshSummary = useCallback(async (force = false) => {
    if (summaryInFlight.current) return
    summaryInFlight.current = true
    try {
      const summary = (await fetchDashboard(false, force)) as DashboardSummary
      setData((prev) => {
        if (!prev) return prev
        const merged = applySummary(prev, summary)
        return dashboardPayloadEqual(prev, merged) ? prev : merged
      })
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load dashboard")
    } finally {
      setLoading(false)
      summaryInFlight.current = false
    }
  }, [])

  const refresh = useCallback(
    async (force = false) => refreshFull(force),
    [refreshFull],
  )

  useEffect(() => {
    void refreshFull()

    const shouldTick = () =>
      document.visibilityState === "visible" && !isAgentStreaming()

    const onSummary = () => {
      if (!shouldTick()) return
      void refreshSummary()
    }

    const onFull = () => {
      if (!shouldTick()) return
      void refreshFull()
    }

    const summaryId = setInterval(onSummary, pollMs)
    const fullId = setInterval(onFull, FULL_POLL_MS)

    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        void refreshSummary()
      }
    }
    document.addEventListener("visibilitychange", onVisibility)

    return () => {
      clearInterval(summaryId)
      clearInterval(fullId)
      document.removeEventListener("visibilitychange", onVisibility)
    }
  }, [pollMs, refreshFull, refreshSummary])

  return { data, loading, error, refresh }
}
