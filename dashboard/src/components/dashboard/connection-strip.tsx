import {
  BrainIcon,
  CalendarIcon,
  DatabaseIcon,
  HashIcon,
  MailIcon,
  MessageCircleIcon,
  ServerIcon,
  TicketIcon,
} from "lucide-react"
import { Link } from "react-router-dom"
import type { DashboardPayload } from "@/types/dashboard"
import { cn } from "@/lib/utils"
import { statusDot } from "@/components/status-badge"

const ITEMS = [
  { key: "daemon",   label: "Daemon",   icon: ServerIcon },
  { key: "groq",     label: "Groq",     icon: BrainIcon },
  { key: "google",   label: "Google",   icon: CalendarIcon },
  { key: "gmail",    label: "Gmail",    icon: MailIcon },
  { key: "whatsapp", label: "WhatsApp", icon: MessageCircleIcon },
  { key: "slack",    label: "Slack",    icon: HashIcon },
  { key: "jira",     label: "Jira",     icon: TicketIcon },
  { key: "rag",      label: "RAG",      icon: DatabaseIcon },
] as const

export function ConnectionStrip({
  connections,
  className,
}: {
  connections: DashboardPayload["connections"]
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-2",
        className,
      )}
    >
      <span className="mr-1 hidden text-[10px] font-bold uppercase tracking-[0.14em] text-muted-foreground sm:inline">
        Live
      </span>
      {ITEMS.map(({ key, label, icon: Icon }) => {
        const conn = connections[key]
        if (!conn) return null
        const connected =
          "connected" in conn ? conn.connected : "reachable" in conn ? conn.reachable : false
        const status = conn.status ?? (connected ? "connected" : "disconnected")
        const isGood = status === "connected" || status === "healthy"
        const detail =
          "last_sync_error" in conn && conn.last_sync_error
            ? String(conn.last_sync_error)
            : "detail" in conn && conn.detail
              ? String(conn.detail)
              : ""

        return (
          <Link
            key={key}
            to="/connections"
            className={cn(
              "group flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1.5 text-[11px] transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40",
              isGood
                ? "border-emerald-200/80 bg-emerald-50/80 hover:border-emerald-300 hover:bg-emerald-100/80 hover:shadow-sm"
                : "border-border bg-white/60 hover:border-primary/25 hover:bg-white hover:shadow-sm",
            )}
          >
            <span
              className={cn("size-1.5 shrink-0 rounded-full", statusDot(status))}
              aria-hidden
            />
            <Icon
              className={cn(
                "size-3 transition-colors",
                isGood ? "text-emerald-700" : "text-muted-foreground group-hover:text-primary",
              )}
              aria-hidden
            />
            <span
              className={cn(
                "font-semibold tracking-tight",
                isGood ? "text-emerald-800" : "text-foreground/80 group-hover:text-foreground",
              )}
            >
              {label}
            </span>
            {detail && !isGood && (
              <span className="max-w-[10rem] truncate text-[10px] text-destructive/80">{detail}</span>
            )}
          </Link>
        )
      })}
    </div>
  )
}
