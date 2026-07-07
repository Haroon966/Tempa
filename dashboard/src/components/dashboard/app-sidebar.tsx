import { NavLink } from "react-router-dom"
import type { HealthStatus } from "@/types/dashboard"
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
  pendingCount: number
  overallStatus: HealthStatus | "disconnected"
  overallHealthy?: number
  overallTotal?: number
  version: string
}

export function AppSidebar({
  active,
  pendingCount,
  overallStatus,
  overallHealthy,
  overallTotal,
  version,
}: AppSidebarProps) {

  return (
    <Sidebar collapsible="icon" className="border-sidebar-border bg-sidebar">
      <SidebarHeader className="border-b border-sidebar-border px-3 py-4 group-data-[collapsible=icon]:px-2">
        <div className="flex items-center gap-3 group-data-[collapsible=icon]:justify-center">
          <div className="relative flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-border bg-muted">
            <img
              src="/favicon.svg"
              alt="Tempa logo"
              className="size-6"
              draggable={false}
            />
            <span
              className={cn(
                "absolute -bottom-0.5 -right-0.5 size-2.5 rounded-full border-2 border-card",
                statusDot(overallStatus),
              )}
              aria-hidden
            />
          </div>
          <div className="flex min-w-0 flex-col gap-0.5 group-data-[collapsible=icon]:hidden">
            <div className="flex items-center gap-2">
              <span className="truncate text-base font-bold tracking-tight text-foreground">
                Tempa
              </span>
              <Badge
                variant="outline"
                className="h-5 shrink-0 border-border bg-muted px-1.5 text-[10px] font-semibold text-primary"
              >
                v{version}
              </Badge>
            </div>
            <span className="truncate text-[11px] text-muted-foreground">
              Personal AI core
            </span>
          </div>
        </div>
      </SidebarHeader>

      <SidebarContent className="gap-0.5 px-2 py-3">
        {NAV_GROUPS.map((group) => (
          <SidebarGroup key={group.id} className="py-0">
            <SidebarGroupLabel
              className={cn(
                "px-3 text-[10px] font-bold tracking-[0.14em] uppercase text-muted-foreground",
                group.id === "system" && "text-muted-foreground/70",
              )}
            >
              {group.label}
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu className="gap-0.5">
                {NAV_ITEMS.filter((item) => item.group === group.id).map(
                  ({ value, path, label, icon: Icon }) => {
                    const isActive = active === value
                    const showBadge = value === "inbox" && pendingCount > 0
                    const deemphasized = value === "diagnostics"

                    return (
                      <SidebarMenuItem key={value}>
                        <SidebarMenuButton
                          render={<NavLink to={path} />}
                          isActive={isActive}
                          tooltip={label}
                          className={cn(
                            "cursor-pointer rounded-xl transition-colors duration-200",
                            isActive
                              ? "nav-active-pill font-semibold"
                              : "text-muted-foreground hover:bg-sidebar-accent hover:text-foreground",
                            deemphasized && !isActive && "text-muted-foreground/80",
                          )}
                        >
                          <Icon
                            className={cn(
                              "size-4 shrink-0",
                              isActive ? "text-primary" : "text-muted-foreground",
                            )}
                            aria-hidden
                          />
                          <span className={cn("flex-1 truncate", deemphasized && "text-xs")}>
                            {label}
                          </span>

                          {showBadge && !isActive && (
                            <Badge className="ml-auto h-5 min-w-5 justify-center rounded-full bg-cta px-1.5 text-[10px] font-bold text-cta-foreground">
                              {pendingCount > 9 ? "9+" : pendingCount}
                            </Badge>
                          )}

                          {value === "settings" && overallStatus !== "disconnected" && (
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

      <SidebarFooter className="border-t border-sidebar-border p-3">
        {overallTotal != null ? (
          <div className="surface-card rounded-xl p-3 group-data-[collapsible=icon]:p-2">
            <div className="flex flex-col gap-2 group-data-[collapsible=icon]:items-center">
              <StatusBadge
                status={overallStatus}
                className="w-fit group-data-[collapsible=icon]:px-1.5"
              />
              <p className="text-[11px] text-muted-foreground group-data-[collapsible=icon]:sr-only">
                {overallHealthy}/{overallTotal} components healthy
              </p>
            </div>
          </div>
        ) : (
          <p className="px-1 text-xs text-muted-foreground group-data-[collapsible=icon]:sr-only">
            Waiting for daemon…
          </p>
        )}
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  )
}
