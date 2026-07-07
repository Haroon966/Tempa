import { Badge } from "@/components/ui/badge"
import type { HealthStatus } from "@/types/dashboard"
import { cn } from "@/lib/utils"

const labels: Record<string, string> = {
  healthy:      "Healthy",
  connected:    "Connected",
  degraded:     "Degraded",
  unhealthy:    "Down",
  disconnected: "Disconnected",
  error:        "Error",
}

export function StatusBadge({
  status,
  className,
  showDot = true,
}: {
  status: string
  className?: string
  showDot?: boolean
}) {
  const key = status.toLowerCase()
  const isGood     = key === "healthy" || key === "connected"
  const isDegraded = key === "degraded"
  const isDiscon   = key === "disconnected"

  return (
    <Badge
      variant="outline"
      className={cn(
        "gap-1.5 border font-semibold tracking-wide uppercase",
        isGood     && "border-success/30 bg-success/10 text-success",
        isDegraded && "border-warning/30 bg-warning/10 text-warning",
        isDiscon   && "border-border bg-muted text-muted-foreground",
        !isGood && !isDegraded && !isDiscon && "border-destructive/30 bg-destructive/10 text-destructive",
        className,
      )}
    >
      {showDot && (
        <span
          className={cn("size-1.5 shrink-0 rounded-full", statusDot(status))}
          aria-hidden
        />
      )}
      {labels[key] ?? status}
    </Badge>
  )
}

export function statusDot(status: HealthStatus | string) {
  const key = status.toLowerCase()
  if (key === "healthy" || key === "connected")
    return "bg-success glow-green"
  if (key === "degraded")
    return "bg-warning glow-amber"
  if (key === "disconnected")
    return "bg-muted-foreground/50"
  return "bg-destructive glow-red"
}
