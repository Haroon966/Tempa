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
        "gap-1.5 border font-medium tracking-wide uppercase",
        isGood     && "border-green-300 bg-green-50 text-green-700",
        isDegraded && "border-amber-300 bg-amber-50 text-amber-700",
        isDiscon   && "border-slate-300 bg-slate-50 text-slate-500",
        !isGood && !isDegraded && !isDiscon && "border-red-300 bg-red-50 text-red-600",
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
    return "bg-green-500 shadow-[0_0_7px_rgba(22,163,74,0.8)]"
  if (key === "degraded")
    return "bg-amber-500 shadow-[0_0_6px_rgba(217,119,6,0.7)]"
  if (key === "disconnected")
    return "bg-slate-400"
  return "bg-red-500 shadow-[0_0_6px_rgba(220,38,38,0.7)]"
}
