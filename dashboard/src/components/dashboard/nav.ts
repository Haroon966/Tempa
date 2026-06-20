import {
  ActivityIcon,
  BotIcon,
  DatabaseIcon,
  LayoutDashboardIcon,
  MailIcon,
  MessageSquareIcon,
  NetworkIcon,
  RouteIcon,
  ShieldCheckIcon,
} from "lucide-react"

export const NAV_ITEMS = [
  { value: "agent", label: "Agent", icon: MessageSquareIcon, group: "monitor" },
  { value: "overview", label: "Overview", icon: LayoutDashboardIcon, group: "monitor" },
  { value: "activity", label: "Activity", icon: ActivityIcon, group: "monitor" },
  { value: "pending", label: "Approvals", icon: ShieldCheckIcon, group: "monitor" },
  { value: "mail", label: "Mail", icon: MailIcon, group: "monitor" },
  { value: "connections", label: "Connections", icon: NetworkIcon, group: "system" },
  { value: "components", label: "Components", icon: BotIcon, group: "system" },
  { value: "flows", label: "E2E Flows", icon: RouteIcon, group: "system" },
  { value: "data", label: "Data", icon: DatabaseIcon, group: "system" },
] as const

export type NavSection = (typeof NAV_ITEMS)[number]["value"]

export const NAV_GROUPS = [
  { id: "monitor", label: "Monitor" },
  { id: "system", label: "System" },
] as const

export const PAGE_META: Record<NavSection, { title: string; description: string }> = {
  agent: {
    title: "Agent",
    description: "Chat with the coordinator — memory, Gmail, calendar, Meet, WhatsApp, and PC",
  },
  overview: {
    title: "Overview",
    description: "System health, stats, and quick status at a glance",
  },
  connections: {
    title: "Connections",
    description: "External services, APIs, and integration status",
  },
  components: {
    title: "Components",
    description: "Agents, tools, and runtime modules",
  },
  flows: {
    title: "E2E Flows",
    description: "End-to-end pipeline traces and flow health",
  },
  data: {
    title: "Data",
    description: "Memory, RAG indexes, and stored context",
  },
  activity: {
    title: "Activity",
    description: "Recent events, logs, and live operations",
  },
  pending: {
    title: "Approvals",
    description: "Review and confirm emails, messages, and PC actions",
  },
  mail: {
    title: "Mail",
    description: "Synced inbox and Gmail status",
  },
}

export function getNavItem(value: NavSection) {
  return NAV_ITEMS.find((item) => item.value === value)!
}
