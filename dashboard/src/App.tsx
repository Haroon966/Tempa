import { lazy, Suspense, type ReactNode } from "react"
import { Navigate, Route, Routes } from "react-router-dom"
import { DashboardLayout } from "@/layouts/dashboard-layout"
import { MeetingsTab } from "@/components/tabs/meetings-tab"
import { InboxTab } from "@/components/tabs/inbox-tab"
import { DiagnosticsTab } from "@/components/tabs/diagnostics-tab"
import { Skeleton } from "@/components/ui/skeleton"
import { useDashboardContext } from "@/contexts/dashboard-context"

const AgentTab = lazy(() =>
  import("@/components/tabs/agent-tab").then((m) => ({ default: m.AgentTab })),
)
const OverviewTab = lazy(() =>
  import("@/components/tabs/overview-tab").then((m) => ({ default: m.OverviewTab })),
)
const SettingsTab = lazy(() =>
  import("@/components/tabs/settings-tab").then((m) => ({ default: m.SettingsTab })),
)
const ComponentsTab = lazy(() =>
  import("@/components/tabs/components-tab").then((m) => ({ default: m.ComponentsTab })),
)
const FlowsTab = lazy(() =>
  import("@/components/tabs/flows-tab").then((m) => ({ default: m.FlowsTab })),
)
const DataTab = lazy(() =>
  import("@/components/tabs/data-tab").then((m) => ({ default: m.DataTab })),
)
const ActivityTab = lazy(() =>
  import("@/components/tabs/activity-tab").then((m) => ({ default: m.ActivityTab })),
)
const PendingTab = lazy(() =>
  import("@/components/tabs/pending-tab").then((m) => ({ default: m.PendingTab })),
)
const LiveMeetingTab = lazy(() =>
  import("@/components/tabs/live-meeting-tab").then((m) => ({ default: m.LiveMeetingTab })),
)
const MailTab = lazy(() =>
  import("@/components/tabs/mail-tab").then((m) => ({ default: m.MailTab })),
)
const QaTab = lazy(() =>
  import("@/components/tabs/qa-tab").then((m) => ({ default: m.QaTab })),
)
const SessionsTab = lazy(() =>
  import("@/components/tabs/sessions-tab").then((m) => ({ default: m.SessionsTab })),
)

function TabFallback() {
  return <Skeleton className="h-64 w-full rounded-2xl bg-muted" />
}

function DataRoute() {
  const { data } = useDashboardContext()
  if (!data) return <TabFallback />
  return <DataTab data={data} />
}

function AgentRoute() {
  const { data } = useDashboardContext()
  if (!data) return <TabFallback />
  return <AgentTab />
}

function OverviewRoute() {
  const { data } = useDashboardContext()
  if (!data) return <TabFallback />
  return <OverviewTab data={data} />
}

function SettingsRoute() {
  const { data, refresh } = useDashboardContext()
  if (!data) return <TabFallback />
  return <SettingsTab data={data} onRefresh={refresh} />
}

function ComponentsRoute() {
  const { data } = useDashboardContext()
  if (!data) return <TabFallback />
  return <ComponentsTab data={data} />
}

function FlowsRoute() {
  const { data } = useDashboardContext()
  if (!data) return <TabFallback />
  return <FlowsTab data={data} />
}

function ActivityRoute() {
  const { data } = useDashboardContext()
  if (!data) return <TabFallback />
  return <ActivityTab data={data} />
}

function LazyRoute({ children }: { children: ReactNode }) {
  return <Suspense fallback={<TabFallback />}>{children}</Suspense>
}

export default function App() {
  return (
    <Routes>
      <Route element={<DashboardLayout />}>
        <Route index element={<Navigate to="/overview" replace />} />

        <Route
          path="agent"
          element={
            <LazyRoute>
              <AgentRoute />
            </LazyRoute>
          }
        />
        <Route
          path="agent/:sessionId"
          element={
            <LazyRoute>
              <AgentRoute />
            </LazyRoute>
          }
        />
        <Route
          path="overview"
          element={
            <LazyRoute>
              <OverviewRoute />
            </LazyRoute>
          }
        />
        <Route
          path="activity"
          element={
            <LazyRoute>
              <ActivityRoute />
            </LazyRoute>
          }
        />
        <Route
          path="qa"
          element={
            <LazyRoute>
              <QaTab />
            </LazyRoute>
          }
        />
        <Route
          path="sessions"
          element={
            <LazyRoute>
              <SessionsTab />
            </LazyRoute>
          }
        />

        <Route path="meetings" element={<MeetingsTab />}>
          <Route
            path="live"
            element={
              <LazyRoute>
                <LiveMeetingTab />
              </LazyRoute>
            }
          />
          <Route
            path="archive"
            element={
              <LazyRoute>
                <DataRoute />
              </LazyRoute>
            }
          />
        </Route>

        <Route path="inbox" element={<InboxTab />}>
          <Route
            path="mail"
            element={
              <LazyRoute>
                <MailTab />
              </LazyRoute>
            }
          />
          <Route
            path="approvals"
            element={
              <LazyRoute>
                <PendingTab />
              </LazyRoute>
            }
          />
        </Route>

        <Route path="diagnostics" element={<DiagnosticsTab />}>
          <Route
            path="components"
            element={
              <LazyRoute>
                <ComponentsRoute />
              </LazyRoute>
            }
          />
          <Route
            path="flows"
            element={
              <LazyRoute>
                <FlowsRoute />
              </LazyRoute>
            }
          />
        </Route>

        <Route
          path="settings"
          element={
            <LazyRoute>
              <SettingsRoute />
            </LazyRoute>
          }
        />

        {/* Legacy redirects */}
        <Route path="live-meeting" element={<Navigate to="/meetings/live" replace />} />
        <Route path="data" element={<Navigate to="/meetings/archive" replace />} />
        <Route path="mail" element={<Navigate to="/inbox/mail" replace />} />
        <Route path="pending" element={<Navigate to="/inbox/approvals" replace />} />
        <Route path="connections" element={<Navigate to="/settings" replace />} />
        <Route path="components" element={<Navigate to="/diagnostics/components" replace />} />
        <Route path="flows" element={<Navigate to="/diagnostics/flows" replace />} />
      </Route>
      <Route path="*" element={<Navigate to="/overview" replace />} />
    </Routes>
  )
}
