import { Outlet, useLocation } from "react-router-dom"
import { RefreshCwIcon, ZapIcon } from "lucide-react"
import { useDashboard } from "@/hooks/use-dashboard"
import { useNavigateSection } from "@/hooks/use-navigate-section"
import { ConnectionStrip } from "@/components/dashboard/connection-strip"
import { AppSidebar } from "@/components/dashboard/app-sidebar"
import { DEFAULT_SECTION, PAGE_META, sectionFromPath } from "@/components/dashboard/nav"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"
import { Separator } from "@/components/ui/separator"
import { StatusBadge } from "@/components/status-badge"
import { formatTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { DashboardPayload } from "@/types/dashboard"

export type DashboardOutletContext = {
  data: DashboardPayload
  refresh: () => Promise<void>
}

export function DashboardLayout() {
  const { data, loading, error, refresh } = useDashboard(10000)
  const location = useLocation()
  const navigateSection = useNavigateSection()
  const activeTab = sectionFromPath(location.pathname) ?? DEFAULT_SECTION
  const page = PAGE_META[activeTab]
  const pendingCount = data?.pending_actions?.length ?? 0
  const isAgentPage = activeTab === "agent"

  return (
    <SidebarProvider defaultOpen>
      <AppSidebar active={activeTab} data={data} />

      <SidebarInset
        className={cn(isAgentPage && "h-svh max-h-svh overflow-hidden")}
      >
        <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b border-border bg-background/90 px-4 backdrop-blur-xl lg:px-6">
          <SidebarTrigger className="cursor-pointer text-muted-foreground hover:text-foreground" />
          <Separator orientation="vertical" className="h-5" />

          <div className="flex min-w-0 flex-1 items-center gap-2">
            <h1 className="truncate text-sm font-semibold tracking-wide text-foreground">
              {page.title}
            </h1>
            <span className="hidden text-muted-foreground/40 sm:block">/</span>
            <p className="hidden truncate text-xs text-muted-foreground sm:block">
              {page.description}
            </p>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {data && (
              <div className="hidden items-center gap-2 rounded-full border border-border bg-muted/60 px-3 py-1 md:flex">
                <StatusBadge
                  status={data.overall.status}
                  showDot
                  className="border-none bg-transparent p-0 text-[11px] uppercase tracking-[0.12em]"
                />
                <Separator orientation="vertical" className="h-3" />
                <span className="text-[11px] text-muted-foreground">
                  {data.overall.healthy}/{data.overall.total_components}
                </span>
              </div>
            )}

            {pendingCount > 0 && (
              <button
                type="button"
                onClick={() => navigateSection("pending")}
                className="flex cursor-pointer items-center gap-1.5 rounded-full border border-primary/30 bg-primary/10 px-2.5 py-1 text-[11px] font-medium text-primary transition-colors duration-200 hover:border-primary/50 hover:bg-primary/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <ZapIcon className="size-3" />
                {pendingCount} pending
              </button>
            )}

            {data && (
              <p className="hidden text-xs text-muted-foreground/70 md:block">
                {formatTime(data.generated_at)}
              </p>
            )}

            <Button
              variant="outline"
              size="sm"
              className={cn(
                "cursor-pointer border-border bg-card text-foreground hover:border-primary/40 hover:bg-muted/50",
                loading && "opacity-60",
              )}
              onClick={() => void refresh()}
              disabled={loading}
            >
              <RefreshCwIcon
                data-icon="inline-start"
                className={cn("size-3.5", loading && "animate-spin")}
              />
              <span className="hidden sm:inline">Refresh</span>
            </Button>
          </div>
        </header>

        {data && (
          <div className="border-b border-border bg-background/80 px-4 py-2.5 lg:px-6">
            <ConnectionStrip connections={data.connections} />
          </div>
        )}

        <div
          className={cn(
            "flex min-h-0 flex-1 flex-col gap-4 p-3 sm:gap-6 sm:p-4 lg:p-6",
            isAgentPage && "overflow-hidden",
          )}
        >
          {error && (
            <Alert variant="destructive" className="border-destructive/40 bg-destructive/8">
              <AlertTitle>Daemon unreachable</AlertTitle>
              <AlertDescription>
                {error}. Start Tempa with <code>tempa start</code> or{" "}
                <code>docker compose up -d</code>.
              </AlertDescription>
            </Alert>
          )}

          {loading && !data ? (
            <div className="flex flex-col gap-4">
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-36 w-full rounded-xl bg-muted" />
                ))}
              </div>
              <Skeleton className="h-[28rem] w-full rounded-xl bg-muted" />
            </div>
          ) : data ? (
            <div
              className={cn(
                "flex min-h-0 min-w-0 flex-1 flex-col animate-in fade-in duration-200",
                isAgentPage && "overflow-hidden",
              )}
            >
              <Outlet context={{ data, refresh } satisfies DashboardOutletContext} />
            </div>
          ) : null}

          {!loading && !data && !error && (
            <div className="flex flex-col items-center justify-center gap-4 rounded-xl border border-border bg-muted/30 py-20 text-center">
              <div className="flex size-14 items-center justify-center rounded-full border border-border bg-card">
                <ZapIcon className="size-6 text-muted-foreground" />
              </div>
              <div>
                <p className="font-medium text-foreground">No data available</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Could not load the dashboard payload.
                </p>
              </div>
              <Button variant="outline" className="cursor-pointer" onClick={() => void refresh()}>
                Try again
              </Button>
            </div>
          )}
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}
