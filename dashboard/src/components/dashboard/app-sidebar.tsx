import type { DashboardPayload } from "@/types/dashboard"
import tempaLogo from "@/assets/tempa.png"
import { StatusBadge, statusDot } from "@/components/status-badge"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar"
import { NAV_GROUPS, NAV_ITEMS, type NavSection } from "@/components/dashboard/nav"

type AppSidebarProps = {
  active: NavSection
  onNavigate: (section: NavSection) => void
  data: DashboardPayload | null
}

export function AppSidebar({ active, onNavigate, data }: AppSidebarProps) {
  const pendingCount  = data?.pending_actions?.length ?? 0
  const overallStatus = data?.overall.status ?? "disconnected"

  return (
    <Sidebar collapsible="icon" className="border-sidebar-border">
      {/* ── Brand ─────────────────────────────────────────── */}
      <SidebarHeader className="border-b border-sidebar-border px-3 py-4 group-data-[collapsible=icon]:px-2">
        <div className="flex items-center gap-3 group-data-[collapsible=icon]:justify-center">
          <div className="flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-primary/25 bg-primary/8 shadow-[0_0_12px_rgba(61,108,185,0.15)] transition-shadow duration-300 hover:shadow-[0_0_18px_rgba(61,108,185,0.25)]">
            <img
              src={tempaLogo}
              alt="Tempa logo"
              className="size-full object-cover"
              draggable={false}
            />
          </div>
          <div className="flex min-w-0 flex-col gap-0.5 group-data-[collapsible=icon]:hidden">
            <div className="flex items-center gap-2">
              <span className="truncate text-sm font-bold tracking-[0.16em] uppercase text-foreground">
                Tempa
              </span>
              <Badge
                variant="outline"
                className="h-5 shrink-0 border-primary/25 bg-primary/8 px-1.5 text-[10px] font-medium text-primary"
              >
                v{data?.environment.tempa_version ?? "0.1.0"}
              </Badge>
            </div>
            <span className="truncate text-[11px] text-muted-foreground">Personal AI core</span>
          </div>
        </div>
      </SidebarHeader>

      {/* ── Nav ───────────────────────────────────────────── */}
      <SidebarContent className="gap-1 px-1 py-3">
        {NAV_GROUPS.map((group) => (
          <SidebarGroup key={group.id} className="py-0">
            <SidebarGroupLabel className="px-3 text-[10px] font-semibold tracking-[0.14em] uppercase text-muted-foreground/60">
              {group.label}
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {NAV_ITEMS.filter((item) => item.group === group.id).map(
                  ({ value, label, icon: Icon }) => {
                    const isActive   = active === value
                    const showBadge  = value === "pending" && pendingCount > 0

                    return (
                      <SidebarMenuItem key={value}>
                        <SidebarMenuButton
                          isActive={isActive}
                          tooltip={label}
                          onClick={() => onNavigate(value)}
                          className={cn(
                            "cursor-pointer transition-all duration-200",
                            isActive
                              ? "border border-primary/25 bg-primary/10 text-primary shadow-[inset_3px_0_0_0_var(--primary)]"
                              : "hover:bg-muted/80 hover:text-foreground",
                          )}
                        >
                          <Icon className="size-4 shrink-0" aria-hidden />
                          <span className="flex-1 truncate">{label}</span>

                          {showBadge && !isActive && (
                            <Badge className="ml-auto h-5 min-w-5 justify-center rounded-full bg-primary px-1.5 text-[10px] font-bold text-white">
                              {pendingCount > 9 ? "9+" : pendingCount}
                            </Badge>
                          )}

                          {value === "connections" && data && (
                            <span
                              className={cn("ml-auto size-1.5 shrink-0 rounded-full", statusDot(overallStatus))}
                              aria-hidden
                            />
                          )}
                        </SidebarMenuButton>
                      </SidebarMenuItem>
                    )
                  },
                )}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>

      {/* ── Footer ────────────────────────────────────────── */}
      <SidebarFooter className="border-t border-sidebar-border p-3">
        {data ? (
          <div className="flex flex-col gap-2 group-data-[collapsible=icon]:items-center">
            <StatusBadge
              status={data.overall.status}
              className="w-fit group-data-[collapsible=icon]:px-1.5"
            />
            <p className="text-[11px] text-muted-foreground group-data-[collapsible=icon]:sr-only">
              {data.overall.healthy}/{data.overall.total_components} healthy
            </p>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground group-data-[collapsible=icon]:sr-only">
            Waiting for daemon…
          </p>
        )}
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  )
}
