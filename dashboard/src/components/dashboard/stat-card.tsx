import { ArrowRightIcon, type LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import { StatusBadge } from "@/components/status-badge"

const ACCENT_STYLES = {
  teal: {
    icon: "border-border bg-muted text-primary",
    glow: "bg-primary/5",
  },
  orange: {
    icon: "border-cta/25 bg-cta/10 text-cta",
    glow: "bg-cta/5",
  },
  sky: {
    icon: "border-primary/20 bg-primary/5 text-primary",
    glow: "bg-primary/5",
  },
} as const

export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  status,
  className,
  onClick,
  accent = "teal",
}: {
  label: string
  value: React.ReactNode
  hint?: string
  icon: LucideIcon
  status?: string
  className?: string
  onClick?: () => void
  accent?: keyof typeof ACCENT_STYLES
}) {
  const styles = ACCENT_STYLES[accent]

  return (
    <div
      className={cn(
        "surface-card group relative flex flex-col gap-4 p-5",
        onClick && "surface-card-interactive",
        className,
      )}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter" || e.key === " ") onClick() } : undefined}
    >
      <span className="stat-accent-bar" aria-hidden />

      <div className="flex items-start justify-between gap-2">
        <div
          className={cn(
            "flex size-11 items-center justify-center rounded-xl border transition-colors duration-200",
            styles.icon,
          )}
        >
          <Icon className="size-5" aria-hidden />
        </div>
        {status && <StatusBadge status={status} />}
      </div>

      <div className="flex-1">
        <p className="section-label">{label}</p>
        <p className="mt-1.5 text-3xl font-extrabold tracking-tight text-foreground">{value}</p>
        {hint && (
          <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{hint}</p>
        )}
      </div>

      {onClick && (
        <div className="flex items-center gap-1 text-xs font-medium text-primary/60 transition-colors duration-200 group-hover:text-primary">
          <span>View details</span>
          <ArrowRightIcon className="size-3 transition-transform duration-200 group-hover:translate-x-0.5" />
        </div>
      )}

      <span
        className={cn(
          "pointer-events-none absolute -right-8 -top-8 size-28 rounded-full opacity-0 blur-2xl transition-opacity duration-200 group-hover:opacity-100",
          styles.glow,
        )}
        aria-hidden
      />
    </div>
  )
}
