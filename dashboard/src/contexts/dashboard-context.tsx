import { createContext, useContext, useMemo, type ReactNode } from "react"
import type { DashboardPayload } from "@/types/dashboard"

export type DashboardDataContextValue = {
  data: DashboardPayload | null
  pendingCount: number
}

export type DashboardActionsContextValue = {
  refresh: (force?: boolean) => Promise<void>
}

export type DashboardOutletContext = DashboardDataContextValue & DashboardActionsContextValue

const DashboardDataContext = createContext<DashboardDataContextValue | null>(null)
const DashboardActionsContext = createContext<DashboardActionsContextValue | null>(null)

export function DashboardProviders({
  data,
  refresh,
  children,
}: {
  data: DashboardPayload | null
  refresh: (force?: boolean) => Promise<void>
  children: ReactNode
}) {
  const pendingCount = data?.pending_actions?.length ?? 0
  const dataValue = useMemo(
    () => ({ data, pendingCount }),
    [data, pendingCount],
  )
  const actionsValue = useMemo(() => ({ refresh }), [refresh])

  return (
    <DashboardActionsContext.Provider value={actionsValue}>
      <DashboardDataContext.Provider value={dataValue}>{children}</DashboardDataContext.Provider>
    </DashboardActionsContext.Provider>
  )
}

export function useDashboardData() {
  const ctx = useContext(DashboardDataContext)
  if (!ctx) throw new Error("useDashboardData outside DashboardProviders")
  return ctx
}

export function useDashboardActions() {
  const ctx = useContext(DashboardActionsContext)
  if (!ctx) throw new Error("useDashboardActions outside DashboardProviders")
  return ctx
}

export function useDashboardContext(): DashboardOutletContext {
  const { data, pendingCount } = useDashboardData()
  const { refresh } = useDashboardActions()
  return { data, pendingCount, refresh }
}
