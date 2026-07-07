import {
  DatabaseIcon,
  HashIcon,
  MessageCircleIcon,
  ServerIcon,
  type LucideIcon,
} from "lucide-react"
import type { DashboardPayload } from "@/types/dashboard"
import { StatusBadge } from "@/components/status-badge"
import { cn } from "@/lib/utils"

function InfraCard({
  title,
  conn,
  icon: Icon,
}: {
  title: string
  conn: DashboardPayload["connections"][string] | undefined
  icon: LucideIcon
}) {
  if (!conn) return null
  const connected = "connected" in conn ? conn.connected : "reachable" in conn ? conn.reachable : false
  const status = conn.status ?? (connected ? "connected" : "disconnected")
  const isGood = status === "connected" || status === "healthy"

  return (
    <div
      className={cn(
        "surface-card p-4 transition-colors duration-200",
        isGood ? "border-success/30 bg-success/5" : "",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div
            className={cn(
              "flex size-8 items-center justify-center rounded-lg border",
              isGood
                ? "border-success/30 bg-success/10 text-success"
                : "border-border bg-muted text-muted-foreground",
            )}
          >
            <Icon className="size-4" aria-hidden />
          </div>
          <span className="text-sm font-medium text-foreground">{title}</span>
        </div>
        <StatusBadge status={status} />
      </div>
      {"detail" in conn && typeof conn.detail === "string" && conn.detail && (
        <p className="mt-2 text-xs text-muted-foreground">{conn.detail}</p>
      )}
      {"chunks" in conn && conn.chunks !== undefined && (
        <p className="mt-2 text-xs text-muted-foreground">Chunks: {conn.chunks}</p>
      )}
      {"port" in conn && typeof conn.port === "number" && (
        <p className="mt-2 text-xs text-muted-foreground">Port: {conn.port}</p>
      )}
    </div>
  )
}

export function InfraStrip({ data }: { data: DashboardPayload }) {
  const bridge = data.connections.whatsapp_bridge ?? data.connections.evolution_api
  return (
    <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <InfraCard title="Tempa Daemon" conn={data.connections.daemon} icon={ServerIcon} />
      <InfraCard title="Unified RAG" conn={data.connections.rag} icon={DatabaseIcon} />
      <InfraCard title="WhatsApp Bridge" conn={bridge} icon={MessageCircleIcon} />
      <InfraCard title="Slack" conn={data.connections.slack} icon={HashIcon} />
    </section>
  )
}
