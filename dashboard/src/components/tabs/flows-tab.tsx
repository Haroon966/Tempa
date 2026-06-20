import { CheckCircle2Icon, CircleDashedIcon, RouteIcon, XCircleIcon } from "lucide-react"
import type { DashboardPayload, HealthStatus } from "@/types/dashboard"
import { PanelCard } from "@/components/dashboard/panel-card"
import { StatusBadge } from "@/components/status-badge"
import { cn } from "@/lib/utils"

function StepIcon({ status }: { status: HealthStatus | string }) {
  const key = status.toLowerCase()
  if (key === "healthy" || key === "connected")
    return <CheckCircle2Icon className="size-4 text-green-600" />
  if (key === "degraded")
    return <CircleDashedIcon className="size-4 text-amber-600" />
  return <XCircleIcon className="size-4 text-red-600" />
}

export function FlowsTab({ data }: { data: DashboardPayload }) {
  if (data.flows.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-xl border border-border bg-muted/30 py-20 text-center">
        <RouteIcon className="size-8 text-muted-foreground/30" />
        <p className="text-sm text-muted-foreground">No end-to-end flows registered.</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      {data.flows.map((flow) => (
        <PanelCard
          key={flow.id}
          title={flow.name}
          description={flow.description}
          icon={RouteIcon}
          action={<StatusBadge status={flow.status} />}
        >
          <ol className="flex flex-col gap-0">
            {flow.steps.map((step, i) => {
              const isLast     = i === flow.steps.length - 1
              const key        = step.status.toLowerCase()
              const isGood     = key === "healthy" || key === "connected"
              const isDegraded = key === "degraded"

              return (
                <li key={step.name} className="relative flex gap-4 pb-5 last:pb-0">
                  {!isLast && (
                    <span
                      className={cn(
                        "absolute left-[11px] top-6 h-[calc(100%-12px)] w-px",
                        isGood ? "bg-green-200" : isDegraded ? "bg-amber-200" : "bg-red-200",
                      )}
                      aria-hidden
                    />
                  )}

                  <span
                    className={cn(
                      "relative z-10 mt-0.5 flex size-[22px] shrink-0 items-center justify-center rounded-full border text-[10px] font-bold",
                      isGood
                        ? "border-green-300 bg-green-50 text-green-700"
                        : isDegraded
                          ? "border-amber-300 bg-amber-50 text-amber-700"
                          : "border-red-300 bg-red-50 text-red-600",
                    )}
                    aria-label={`Step ${i + 1}`}
                  >
                    {i + 1}
                  </span>

                  <div
                    className={cn(
                      "flex min-w-0 flex-1 flex-wrap items-center justify-between gap-3 rounded-lg border p-3 transition-colors duration-200",
                      isGood
                        ? "border-green-200 bg-green-50/60 hover:border-green-300"
                        : isDegraded
                          ? "border-amber-200 bg-amber-50/60 hover:border-amber-300"
                          : "border-red-200 bg-red-50/60 hover:border-red-300",
                    )}
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <StepIcon status={step.status} />
                      <span className="text-sm font-medium text-foreground">{step.name}</span>
                    </div>
                    <StatusBadge status={step.status} />
                  </div>
                </li>
              )
            })}
          </ol>
        </PanelCard>
      ))}
    </div>
  )
}
