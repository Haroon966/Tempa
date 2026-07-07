import { NavLink, Outlet, useLocation, Navigate } from "react-router-dom"
import { MailIcon, ShieldCheckIcon } from "lucide-react"
import { useDashboardData } from "@/contexts/dashboard-context"
import { cn } from "@/lib/utils"

const SUB_TABS = [
  { path: "/inbox/mail", label: "Mail", icon: MailIcon },
  { path: "/inbox/approvals", label: "Approvals", icon: ShieldCheckIcon },
] as const

export function InboxTab() {
  const { pathname } = useLocation()
  const { pendingCount } = useDashboardData()
  const isSubRoute = SUB_TABS.some((t) => t.path === pathname)
  if (!isSubRoute) return <Navigate to="/inbox/mail" replace />

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-5">
      <nav className="flex gap-1 rounded-lg border border-border bg-muted p-1 w-fit" aria-label="Inbox sections">
        {SUB_TABS.map(({ path, label, icon: Icon }) => {
          const active = pathname === path
          const showBadge = path === "/inbox/approvals" && pendingCount > 0
          return (
            <NavLink
              key={path}
              to={path}
              className={cn(
                "flex cursor-pointer items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors duration-200",
                active
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className="size-4" aria-hidden />
              {label}
              {showBadge && (
                <span className="ml-0.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-cta px-1.5 text-[10px] font-bold text-cta-foreground">
                  {pendingCount > 9 ? "9+" : pendingCount}
                </span>
              )}
            </NavLink>
          )
        })}
      </nav>
      <Outlet />
    </div>
  )
}
