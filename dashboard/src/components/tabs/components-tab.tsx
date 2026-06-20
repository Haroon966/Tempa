import { useState } from "react"
import { LayersIcon } from "lucide-react"
import type { DashboardPayload } from "@/types/dashboard"
import { PanelCard } from "@/components/dashboard/panel-card"
import { StatusBadge } from "@/components/status-badge"
import { cn } from "@/lib/utils"

type Filter = "all" | "healthy" | "degraded" | "unhealthy"

const FILTER_OPTIONS: { value: Filter; label: string }[] = [
  { value: "all",       label: "All" },
  { value: "healthy",   label: "Healthy" },
  { value: "degraded",  label: "Degraded" },
  { value: "unhealthy", label: "Down" },
]

export function ComponentsTab({ data }: { data: DashboardPayload }) {
  const [filter, setFilter] = useState<Filter>("all")

  const categories = [...new Set(data.components.map((c) => c.category))]

  const visible = data.components.filter((c) =>
    filter === "all" ? true : c.status === filter,
  )

  const counts = {
    all:       data.components.length,
    healthy:   data.components.filter((c) => c.status === "healthy").length,
    degraded:  data.components.filter((c) => c.status === "degraded").length,
    unhealthy: data.components.filter((c) => c.status === "unhealthy").length,
  }

  return (
    <div className="flex flex-col gap-6">
      {/* filter bar */}
      <div className="flex flex-wrap gap-1.5">
        {FILTER_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => setFilter(opt.value)}
            className={cn(
              "inline-flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              filter === opt.value
                ? "border-primary/35 bg-primary/10 text-primary"
                : "border-border bg-card text-muted-foreground hover:border-primary/25 hover:text-foreground",
            )}
          >
            {opt.label}
            <span
              className={cn(
                "rounded-full px-1.5 py-0.5 text-[10px] font-bold",
                filter === opt.value ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground",
              )}
            >
              {counts[opt.value]}
            </span>
          </button>
        ))}
      </div>

      {/* cards */}
      {categories.map((category) => {
        const items = visible.filter((c) => c.category === category)
        if (items.length === 0) return null
        return (
          <PanelCard
            key={category}
            title={category}
            description={`${items.length} component${items.length !== 1 ? "s" : ""}`}
            icon={LayersIcon}
          >
            <div className="flex flex-col gap-2">
              {items.map((component) => (
                <div
                  key={component.id}
                  className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-border bg-muted/30 p-3 transition-colors duration-200 hover:border-primary/25 hover:bg-muted/60"
                >
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-foreground">{component.name}</p>
                    {component.message && (
                      <p className="mt-0.5 text-xs text-muted-foreground">{component.message}</p>
                    )}
                  </div>
                  <StatusBadge status={component.status} />
                </div>
              ))}
            </div>
          </PanelCard>
        )
      })}

      {visible.length === 0 && (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-border bg-muted/30 py-16 text-center">
          <LayersIcon className="size-8 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">No components match the selected filter.</p>
        </div>
      )}
    </div>
  )
}
