import { Navigate, Route, Routes, useOutletContext } from "react-router-dom"
import { DashboardLayout } from "@/layouts/dashboard-layout"
import { AgentTab } from "@/components/tabs/agent-tab"
import { OverviewTab } from "@/components/tabs/overview-tab"
import { ConnectionsTab } from "@/components/tabs/connections-tab"
import { ComponentsTab } from "@/components/tabs/components-tab"
import { FlowsTab } from "@/components/tabs/flows-tab"
import { DataTab } from "@/components/tabs/data-tab"
import { ActivityTab } from "@/components/tabs/activity-tab"
import { PendingTab } from "@/components/tabs/pending-tab"
import { LiveMeetingTab } from "@/components/tabs/live-meeting-tab"
import { MailTab } from "@/components/tabs/mail-tab"
import type { DashboardOutletContext } from "@/layouts/dashboard-layout"

function useDashboardContext() {
  return useOutletContext<DashboardOutletContext>()
}

function AgentRoute() {
  const { data } = useDashboardContext()
  return <AgentTab data={data} />
}

function OverviewRoute() {
  const { data } = useDashboardContext()
  return <OverviewTab data={data} />
}

function ConnectionsRoute() {
  const { data, refresh } = useDashboardContext()
  return <ConnectionsTab data={data} onRefresh={refresh} />
}

function ComponentsRoute() {
  const { data } = useDashboardContext()
  return <ComponentsTab data={data} />
}

function FlowsRoute() {
  const { data } = useDashboardContext()
  return <FlowsTab data={data} />
}

function DataRoute() {
  const { data } = useDashboardContext()
  return <DataTab data={data} />
}

function LiveMeetingRoute() {
  return <LiveMeetingTab />
}

function ActivityRoute() {
  const { data } = useDashboardContext()
  return <ActivityTab data={data} />
}

export default function App() {
  return (
    <Routes>
      <Route element={<DashboardLayout />}>
        <Route index element={<Navigate to="/overview" replace />} />
        <Route path="agent" element={<AgentRoute />} />
        <Route path="agent/:sessionId" element={<AgentRoute />} />
        <Route path="overview" element={<OverviewRoute />} />
        <Route path="live-meeting" element={<LiveMeetingRoute />} />
        <Route path="activity" element={<ActivityRoute />} />
        <Route path="pending" element={<PendingTab />} />
        <Route path="mail" element={<MailTab />} />
        <Route path="connections" element={<ConnectionsRoute />} />
        <Route path="components" element={<ComponentsRoute />} />
        <Route path="flows" element={<FlowsRoute />} />
        <Route path="data" element={<DataRoute />} />
      </Route>
      <Route path="*" element={<Navigate to="/overview" replace />} />
    </Routes>
  )
}
