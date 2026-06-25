import {
  ActivityIcon,
  BotIcon,
  DatabaseIcon,
  GitBranchIcon,
  LayoutDashboardIcon,
  MailIcon,
  MessageSquareIcon,
  NetworkIcon,
  RadioIcon,
  RouteIcon,
  ShieldCheckIcon,
} from "lucide-react"

export const NAV_ITEMS = [
  { value: "agent", path: "/agent", label: "Agent", icon: MessageSquareIcon, group: "monitor" },
  { value: "overview", path: "/overview", label: "Overview", icon: LayoutDashboardIcon, group: "monitor" },
  { value: "qa", path: "/qa", label: "QA", icon: GitBranchIcon, group: "monitor" },
  { value: "live-meeting", path: "/live-meeting", label: "Live Meeting", icon: RadioIcon, group: "monitor" },
  { value: "activity", path: "/activity", label: "Activity", icon: ActivityIcon, group: "monitor" },
  { value: "pending", path: "/pending", label: "Approvals", icon: ShieldCheckIcon, group: "monitor" },
  { value: "mail", path: "/mail", label: "Mail", icon: MailIcon, group: "monitor" },
  { value: "connections", path: "/connections", label: "Connections", icon: NetworkIcon, group: "system" },
  { value: "components", path: "/components", label: "Components", icon: BotIcon, group: "system" },
  { value: "flows", path: "/flows", label: "E2E Flows", icon: RouteIcon, group: "system" },
  { value: "data", path: "/data", label: "Data", icon: DatabaseIcon, group: "system" },
] as const

export type NavSection = (typeof NAV_ITEMS)[number]["value"]

export const DEFAULT_SECTION: NavSection = "overview"

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
  qa: {
    title: "QA",
    description: "Branch health, scan queue, vulnerabilities, and test failures across repos",
  },
  "live-meeting": {
    title: "Live Meeting",
    description: "Active Meet sessions — transcript, notes, and chat copilot",
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

export function sectionPath(section: NavSection): string {
  return getNavItem(section).path
}

export function sectionFromPath(pathname: string): NavSection | null {
  const item = NAV_ITEMS.find((entry) => entry.path === pathname)
  return item?.value ?? null
}
