import {
  BrainIcon,
  CalendarIcon,
  DatabaseIcon,
  MailIcon,
  MessageCircleIcon,
  ServerIcon,
} from "lucide-react"
import type { DashboardPayload } from "@/types/dashboard"
import { cn } from "@/lib/utils"
import { statusDot } from "@/components/status-badge"

const ITEMS = [
  { key: "daemon",   label: "Daemon",   icon: ServerIcon },
  { key: "groq",     label: "Groq",     icon: BrainIcon },
  { key: "google",   label: "Google",   icon: CalendarIcon },
  { key: "gmail",    label: "Gmail",    icon: MailIcon },
  { key: "whatsapp", label: "WhatsApp", icon: MessageCircleIcon },
  { key: "rag",      label: "RAG",      icon: DatabaseIcon },
] as const

export function ConnectionStrip({
  connections,
  className,
  onNavigateToConnections,
}: {
  connections: DashboardPayload["connections"]
  className?: string
  onNavigateToConnections?: () => void
}) {
  return (
    <div className={cn("flex flex-wrap items-center gap-1.5", className)}>
      {ITEMS.map(({ key, label, icon: Icon }) => {
        const conn = connections[key]
        if (!conn) return null
        const connected =
          "connected" in conn ? conn.connected : "reachable" in conn ? conn.reachable : false
        const status = conn.status ?? (connected ? "connected" : "disconnected")
        const isGood = status === "connected" || status === "healthy"

        return (
          <button
            key={key}
            type="button"
            onClick={onNavigateToConnections}
            className={cn(
              "group flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              isGood
                ? "border-green-200 bg-green-50 hover:border-green-300 hover:bg-green-100"
                : "border-border bg-card hover:border-primary/30 hover:bg-muted/60",
            )}
          >
            <span
              className={cn("size-1.5 shrink-0 rounded-full", statusDot(status))}
              aria-hidden
            />
            <Icon className="size-3 text-muted-foreground transition-colors group-hover:text-foreground" aria-hidden />
            <span className="font-medium tracking-wide text-foreground/80 group-hover:text-foreground">
              {label}
            </span>
          </button>
        )
      })}
    </div>
  )
}
