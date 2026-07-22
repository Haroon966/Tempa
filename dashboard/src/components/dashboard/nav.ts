import {
  ActivityIcon,
  BotIcon,
  GitBranchIcon,
  InboxIcon,
  LayoutDashboardIcon,
  MapPinIcon,
  MessageSquareIcon,
  SettingsIcon,
  StethoscopeIcon,
  VideoIcon,
} from "lucide-react"

export const NAV_ITEMS = [
  { value: "overview", path: "/overview", label: "Overview", icon: LayoutDashboardIcon, group: "work" },
  { value: "agent", path: "/agent", label: "Agent", icon: MessageSquareIcon, group: "work" },
  { value: "meetings", path: "/meetings/live", label: "Meetings", icon: VideoIcon, group: "work" },
  { value: "inbox", path: "/inbox/mail", label: "Inbox", icon: InboxIcon, group: "work" },
  { value: "presence", path: "/presence", label: "Presence", icon: MapPinIcon, group: "work" },
  { value: "activity", path: "/activity", label: "Activity", icon: ActivityIcon, group: "monitor" },
  { value: "sessions", path: "/sessions", label: "Sessions", icon: BotIcon, group: "monitor" },
  { value: "qa", path: "/qa", label: "QA", icon: GitBranchIcon, group: "monitor" },
  { value: "settings", path: "/settings", label: "Settings", icon: SettingsIcon, group: "system" },
  {
    value: "diagnostics",
    path: "/diagnostics/components",
    label: "Diagnostics",
    icon: StethoscopeIcon,
    group: "system",
  },
] as const

export type NavSection = (typeof NAV_ITEMS)[number]["value"]

export const DEFAULT_SECTION: NavSection = "overview"

export const NAV_GROUPS = [
  { id: "work", label: "Work" },
  { id: "monitor", label: "Monitor" },
  { id: "system", label: "System" },
] as const

export const PAGE_META: Record<NavSection, { title: string; description: string }> = {
  overview: {
    title: "Overview",
    description: "System health, stats, and quick status at a glance",
  },
  agent: {
    title: "Agent",
    description: "Chat with the coordinator — memory, Gmail, calendar, Meet, WhatsApp, and PC",
  },
  meetings: {
    title: "Meetings",
    description: "Live Meet sessions and archived recordings",
  },
  inbox: {
    title: "Inbox",
    description: "Synced mail and actions awaiting your approval",
  },
  presence: {
    title: "Presence",
    description: "Who is on leave, remote, in office, or on a field visit — from Slack #presence",
  },
  activity: {
    title: "Activity",
    description: "Recent events, logs, and live operations",
  },
  sessions: {
    title: "Sessions",
    description: "Tempa Slack conversations and Cursor background jobs — running, done, failed",
  },
  qa: {
    title: "QA",
    description: "Branch health, scan queue, vulnerabilities, and test failures across repos",
  },
  settings: {
    title: "Settings",
    description: "Integrations, API keys, and connection status",
  },
  diagnostics: {
    title: "Diagnostics",
    description: "Runtime components and end-to-end pipeline health",
  },
}

export function getNavItem(value: NavSection) {
  return NAV_ITEMS.find((item) => item.value === value)!
}

export function sectionPath(section: NavSection): string {
  return getNavItem(section).path
}

export function sectionFromPath(pathname: string): NavSection | null {
  if (pathname.startsWith("/agent")) return "agent"
  if (pathname.startsWith("/meetings")) return "meetings"
  if (pathname.startsWith("/inbox")) return "inbox"
  if (pathname.startsWith("/diagnostics")) return "diagnostics"
  const item = NAV_ITEMS.find((entry) => entry.path === pathname)
  return item?.value ?? null
}
