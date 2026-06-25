import { Outlet, useLocation } from "react-router-dom"
import { RefreshCwIcon, SparklesIcon, ZapIcon } from "lucide-react"
import { useDashboard } from "@/hooks/use-dashboard"
import { useNavigateSection } from "@/hooks/use-navigate-section"
import { ConnectionStrip } from "@/components/dashboard/connection-strip"
import { AppSidebar } from "@/components/dashboard/app-sidebar"
import { DEFAULT_SECTION, PAGE_META, sectionFromPath } from "@/components/dashboard/nav"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"
import { StatusBadge } from "@/components/status-badge"
import { formatTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { DashboardPayload } from "@/types/dashboard"

export type DashboardOutletContext = {
  data: DashboardPayload | null
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

  const healthIssues: string[] = []
  if (data) {
    if (!data.connections.groq?.connected) healthIssues.push("Groq not connected")
    if (!data.connections.google?.connected) healthIssues.push("Google not connected")
    if (data.connections.gmail?.last_sync_error) healthIssues.push("Gmail sync failed")
    if (data.connections.google?.calendar_sync?.last_sync_error) {
      healthIssues.push("Calendar sync failed")
    }
    if (data.connections.whatsapp?.needs_qr_rescan) healthIssues.push("WhatsApp needs QR rescan")
    if (data.connections.rag?.error) healthIssues.push("RAG store error")
  }

  return (
    <SidebarProvider defaultOpen>
      <AppSidebar active={activeTab} data={data} />

      <SidebarInset
        className={cn(
          "bg-transparent",
          isAgentPage && "h-svh max-h-svh overflow-hidden",
        )}
      >
        <div
          className={cn(
            "flex flex-col",
            isAgentPage ? "h-svh max-h-svh min-h-0 overflow-hidden" : "min-h-svh",
          )}
        >
          {/* Floating header */}
          <header className="sticky top-0 z-30 px-3 pt-3 sm:px-4 sm:pt-4 lg:px-6">
            <div className="glass-surface-strong flex flex-col gap-3 rounded-2xl px-3 py-2.5 sm:px-4 lg:px-5">
              <div className="flex h-11 items-center gap-3">
                <SidebarTrigger className="cursor-pointer text-muted-foreground transition-colors duration-200 hover:text-primary" />

                <div className="flex min-w-0 flex-1 flex-col gap-0.5 sm:flex-row sm:items-center sm:gap-3">
                  <div className="flex min-w-0 items-center gap-2">
                    <SparklesIcon className="hidden size-4 shrink-0 text-primary sm:block" aria-hidden />
                    <h1 className="truncate text-base font-bold tracking-tight text-foreground">
                      {page.title}
                    </h1>
                  </div>
                  <p className="hidden truncate text-xs text-muted-foreground md:block">
                    {page.description}
                  </p>
                </div>

                <div className="flex shrink-0 items-center gap-2">
                  {data && (
                    <div className="hidden items-center gap-2 rounded-full border border-border bg-muted px-3 py-1.5 md:flex">
                      <StatusBadge
                        status={data.overall.status}
                        showDot
                        className="border-none bg-transparent p-0 text-[10px] uppercase tracking-[0.12em]"
                      />
                      <span className="text-[10px] font-medium text-muted-foreground">
                        {data.overall.healthy}/{data.overall.total_components}
                      </span>
                    </div>
                  )}

                  {pendingCount > 0 && (
                    <button
                      type="button"
                      onClick={() => navigateSection("pending")}
                      className="flex cursor-pointer items-center gap-1.5 rounded-full border border-cta/30 bg-cta/10 px-2.5 py-1.5 text-[11px] font-semibold text-cta transition-colors duration-200 hover:border-cta/50 hover:bg-cta/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cta/40"
                    >
                      <ZapIcon className="size-3" />
                      <span className="hidden sm:inline">{pendingCount} pending</span>
                      <span className="sm:hidden">{pendingCount}</span>
                    </button>
                  )}

                  {data && (
                    <p className="hidden text-[11px] text-muted-foreground lg:block">
                      {formatTime(data.generated_at)}
                    </p>
                  )}

                  <Button
                    variant="outline"
                    size="sm"
                    className={cn(
                      "cursor-pointer border-primary/15 bg-white/60 text-foreground shadow-none hover:border-primary/30 hover:bg-white",
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
              </div>

              {data && (
                <div className="border-t border-primary/8 pt-2.5">
                  <ConnectionStrip connections={data.connections} />
                </div>
              )}
            </div>
          </header>

          {/* Main content */}
          <div
            className={cn(
              "flex min-h-0 flex-1 flex-col gap-4 px-3 py-4 sm:gap-5 sm:px-4 sm:py-5 lg:px-6 lg:py-6",
              isAgentPage && "overflow-hidden",
            )}
          >
            {data && healthIssues.length > 0 && (
              <Alert className="glass-surface border-amber-200/60 bg-amber-50/90 text-amber-900">
                <AlertTitle className="text-amber-900">Attention needed</AlertTitle>
                <AlertDescription className="flex flex-wrap items-center gap-2 text-amber-800/90">
                  <span>{healthIssues.join(" · ")}</span>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="cursor-pointer border-amber-300/60 bg-white/70 hover:bg-white"
                    onClick={() => navigateSection("connections")}
                  >
                    Fix in Connections
                  </Button>
                </AlertDescription>
              </Alert>
            )}

            {error && (
              <Alert variant="destructive" className="border-destructive/30 bg-destructive/5">
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
                    <Skeleton key={i} className="h-36 w-full rounded-2xl bg-white/50" />
                  ))}
                </div>
                <Skeleton className="h-[28rem] w-full rounded-2xl bg-white/50" />
              </div>
            ) : (
              <div
                className={cn(
                  "flex min-h-0 min-w-0 flex-1 flex-col animate-in fade-in duration-300",
                  isAgentPage && "h-full overflow-hidden",
                )}
              >
                <Outlet context={{ data, refresh } satisfies DashboardOutletContext} />
              </div>
            )}

            {!loading && !data && !error && (
              <div className="glass-surface flex flex-col items-center justify-center gap-4 rounded-2xl py-20 text-center">
                <div className="flex size-16 items-center justify-center rounded-2xl border border-border bg-muted">
                  <ZapIcon className="size-7 text-primary" />
                </div>
                <div>
                  <p className="text-lg font-semibold text-foreground">No data available</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Could not load the dashboard payload.
                  </p>
                </div>
                <Button
                  variant="outline"
                  className="cursor-pointer border-primary/20 bg-white/70 hover:bg-white"
                  onClick={() => void refresh()}
                >
                  Try again
                </Button>
              </div>
            )}
          </div>
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}
