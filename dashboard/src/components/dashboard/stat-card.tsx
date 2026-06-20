import { ArrowRightIcon, type LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import { StatusBadge } from "@/components/status-badge"

export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  status,
  className,
  onClick,
}: {
  label: string
  value: React.ReactNode
  hint?: string
  icon: LucideIcon
  status?: string
  className?: string
  onClick?: () => void
}) {
  return (
    <div
      className={cn(
        "panel-card group relative flex flex-col gap-4 overflow-hidden p-5",
        onClick && "cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter" || e.key === " ") onClick() } : undefined}
    >
      {/* accent bar */}
      <span className="stat-accent-bar" aria-hidden />

      <div className="flex items-start justify-between gap-2">
        <div className="flex size-10 items-center justify-center rounded-lg border border-primary/20 bg-primary/8 text-primary transition-all duration-200 group-hover:border-primary/40 group-hover:bg-primary/15 group-hover:shadow-[0_0_12px_rgba(61,108,185,0.2)]">
          <Icon className="size-5" aria-hidden />
        </div>
        {status && <StatusBadge status={status} />}
      </div>

      <div className="flex-1">
        <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          {label}
        </p>
        <p className="mt-1 text-3xl font-bold tracking-wide text-foreground">{value}</p>
        {hint && (
          <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{hint}</p>
        )}
      </div>

      {onClick && (
        <div className="flex items-center gap-1 text-xs text-primary/50 transition-colors duration-200 group-hover:text-primary">
          <span>View details</span>
          <ArrowRightIcon className="size-3 transition-transform duration-200 group-hover:translate-x-0.5" />
        </div>
      )}

      {/* corner accent glow on hover */}
      <span
        className="pointer-events-none absolute -right-6 -top-6 size-24 rounded-full bg-primary/6 opacity-0 blur-2xl transition-opacity duration-300 group-hover:opacity-100"
        aria-hidden
      />
    </div>
  )
}
