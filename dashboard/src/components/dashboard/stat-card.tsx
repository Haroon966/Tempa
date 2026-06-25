import { ArrowRightIcon, type LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import { StatusBadge } from "@/components/status-badge"

const ACCENT_STYLES = {
  teal: {
    icon: "border-border bg-muted text-primary group-hover:shadow-[0_4px_20px_rgba(15,23,42,0.08)]",
    glow: "bg-muted",
  },
  orange: {
    icon: "border-cta/25 bg-gradient-to-br from-cta/15 to-cta/5 text-cta group-hover:shadow-[0_4px_20px_rgba(249,115,22,0.18)]",
    glow: "bg-cta/8",
  },
  sky: {
    icon: "border-sky-200 bg-gradient-to-br from-sky-100 to-sky-50 text-sky-700 group-hover:shadow-[0_4px_20px_rgba(14,165,233,0.15)]",
    glow: "bg-sky-400/8",
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
        "bento-tile group relative flex flex-col gap-4 p-5",
        onClick && "cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40",
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
            "flex size-11 items-center justify-center rounded-xl border transition-all duration-200",
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
          "pointer-events-none absolute -right-8 -top-8 size-28 rounded-full opacity-0 blur-2xl transition-opacity duration-300 group-hover:opacity-100",
          styles.glow,
        )}
        aria-hidden
      />
    </div>
  )
}
