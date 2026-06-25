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
        isGood     && "border-emerald-200 bg-emerald-50 text-emerald-800",
        isDegraded && "border-amber-200 bg-amber-50 text-amber-800",
        isDiscon   && "border-slate-200 bg-slate-50 text-slate-600",
        !isGood && !isDegraded && !isDiscon && "border-red-200 bg-red-50 text-red-700",
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
    return "bg-emerald-500 glow-green"
  if (key === "degraded")
    return "bg-amber-500 glow-amber"
  if (key === "disconnected")
    return "bg-slate-400"
  return "bg-red-500 glow-red"
}
