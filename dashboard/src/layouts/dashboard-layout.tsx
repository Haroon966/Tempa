import { useMemo } from "react"
import { Outlet, useLocation } from "react-router-dom"
import { RefreshCwIcon, ZapIcon } from "lucide-react"
import { useDashboard } from "@/hooks/use-dashboard"
import { useNavigateSection } from "@/hooks/use-navigate-section"
import { AppSidebar } from "@/components/dashboard/app-sidebar"
import { DEFAULT_SECTION, PAGE_META, sectionFromPath } from "@/components/dashboard/nav"
import { Button } from "@/components/ui/button"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"
import { StatusBadge } from "@/components/status-badge"
import { formatTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import { DashboardProviders } from "@/contexts/dashboard-context"

export type { DashboardOutletContext } from "@/contexts/dashboard-context"

export function DashboardLayout() {
  const location = useLocation()
  const activeTab = sectionFromPath(location.pathname) ?? DEFAULT_SECTION
  const { data, loading, error, refresh } = useDashboard({
    activeTab,
    pathname: location.pathname,
  })
  const navigateSection = useNavigateSection()
  const page = PAGE_META[activeTab]
  const pendingCount = data?.pending_actions?.length ?? 0
  const isAgentPage = activeTab === "agent"

  const sidebarProps = useMemo(
    () => ({
      pendingCount,
      overallStatus: data?.overall.status ?? ("disconnected" as const),
      overallHealthy: data?.overall.healthy,
      overallTotal: data?.overall.total_components,
      version: data?.environment.tempa_version ?? "0.1.0",
    }),
    [
      pendingCount,
      data?.overall.status,
      data?.overall.healthy,
      data?.overall.total_components,
      data?.environment.tempa_version,
    ],
  )

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
      <AppSidebar active={activeTab} {...sidebarProps} />

      <SidebarInset
        className={cn(
          "bg-background",
          isAgentPage && "h-svh max-h-svh overflow-hidden",
        )}
      >
        <div
          className={cn(
            "flex flex-col",
            isAgentPage ? "h-svh max-h-svh min-h-0 overflow-hidden" : "min-h-svh",
          )}
        >
          <header className="sticky top-0 z-30 border-b border-border bg-background/95 backdrop-blur-sm">
            <div className="flex h-14 items-center gap-3 px-4 lg:px-6">
              <SidebarTrigger className="cursor-pointer text-muted-foreground transition-colors duration-200 hover:text-primary" />

              <h1 className="min-w-0 flex-1 truncate text-base font-bold tracking-tight text-foreground">
                {page.title}
              </h1>

              <div className="flex shrink-0 items-center gap-2">
                {data && (
                  <div className="hidden items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 md:flex">
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
                    onClick={() => navigateSection("inbox")}
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
                    "cursor-pointer",
                    loading && "opacity-60",
                  )}
                  onClick={() => void refresh(true)}
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
          </header>

          <div
            className={cn(
              "flex min-h-0 flex-1 flex-col gap-4 px-4 py-5 lg:px-6 lg:py-6",
              isAgentPage && "overflow-hidden",
            )}
          >
            {data && healthIssues.length > 0 && (
              <Alert className="border-warning/30 bg-warning/5 text-foreground">
                <AlertTitle>Attention needed</AlertTitle>
                <AlertDescription className="flex flex-wrap items-center gap-2">
                  <span>{healthIssues.join(" · ")}</span>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="cursor-pointer"
                    onClick={() => navigateSection("settings")}
                  >
                    Open Settings
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

            <div
              className={cn(
                "flex min-h-0 min-w-0 flex-1 flex-col",
                isAgentPage && "h-full overflow-hidden",
              )}
            >
              <DashboardProviders data={data} refresh={refresh}>
                <Outlet />
              </DashboardProviders>
            </div>
          </div>
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}
