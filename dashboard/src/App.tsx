import { useState } from "react"
import { RefreshCwIcon, ZapIcon } from "lucide-react"
import { useDashboard } from "@/hooks/use-dashboard"
import { ConnectionStrip } from "@/components/dashboard/connection-strip"
import { AppSidebar } from "@/components/dashboard/app-sidebar"
import { PAGE_META, type NavSection } from "@/components/dashboard/nav"
import { AgentTab } from "@/components/tabs/agent-tab"
import { OverviewTab } from "@/components/tabs/overview-tab"
import { ConnectionsTab } from "@/components/tabs/connections-tab"
import { ComponentsTab } from "@/components/tabs/components-tab"
import { FlowsTab } from "@/components/tabs/flows-tab"
import { DataTab } from "@/components/tabs/data-tab"
import { ActivityTab } from "@/components/tabs/activity-tab"
import { PendingTab } from "@/components/tabs/pending-tab"
import { MailTab } from "@/components/tabs/mail-tab"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"
import { Separator } from "@/components/ui/separator"
import { StatusBadge } from "@/components/status-badge"
import { formatTime } from "@/lib/format"
import { cn } from "@/lib/utils"

export default function App() {
  const { data, loading, error, refresh } = useDashboard(10000)
  const [activeTab, setActiveTab] = useState<NavSection>("overview")
  const page = PAGE_META[activeTab]
  const pendingCount = data?.pending_actions?.length ?? 0

  return (
    <SidebarProvider defaultOpen>
      <AppSidebar active={activeTab} onNavigate={setActiveTab} data={data} />

      <SidebarInset>
        {/* ── Header ──────────────────────────────────────── */}
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
            {/* system health pill */}
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

            {/* pending badge */}
            {pendingCount > 0 && (
              <button
                type="button"
                onClick={() => setActiveTab("pending")}
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

        {/* ── Connection strip ────────────────────────────── */}
        {data && (
          <div className="border-b border-border bg-background/80 px-4 py-2.5 lg:px-6">
            <ConnectionStrip
              connections={data.connections}
              onNavigateToConnections={() => setActiveTab("connections")}
            />
          </div>
        )}

        {/* ── Content ─────────────────────────────────────── */}
        <div className="flex flex-1 flex-col gap-6 p-4 lg:p-6">
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
            <div className="min-w-0 animate-in fade-in duration-200">
              {activeTab === "agent"        && <AgentTab data={data} onNavigate={setActiveTab} />}
              {activeTab === "overview"     && <OverviewTab data={data} onNavigate={setActiveTab} />}
              {activeTab === "connections"  && <ConnectionsTab data={data} onRefresh={refresh} />}
              {activeTab === "components"   && <ComponentsTab data={data} />}
              {activeTab === "flows"        && <FlowsTab data={data} />}
              {activeTab === "data"         && <DataTab data={data} onNavigate={setActiveTab} />}
              {activeTab === "activity"     && <ActivityTab data={data} />}
              {activeTab === "pending"      && <PendingTab />}
              {activeTab === "mail"         && <MailTab />}
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
