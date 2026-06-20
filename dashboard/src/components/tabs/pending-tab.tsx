import { CheckIcon, ShieldCheckIcon, XIcon } from "lucide-react"
import { usePendingActions } from "@/hooks/use-pending-actions"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { EmailPreview } from "@/components/pending/email-preview"
import { WhatsAppPreview } from "@/components/pending/whatsapp-preview"
import { FileOpPreview } from "@/components/pending/file-op-preview"
import { TransferPreview } from "@/components/pending/transfer-preview"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

const TYPE_COLORS: Record<string, string> = {
  email_send:    "border-blue-200 bg-blue-50 text-blue-700",
  whatsapp_send: "border-green-200 bg-green-50 text-green-700",
  pc_write:      "border-amber-200 bg-amber-50 text-amber-700",
  pc_delete:     "border-red-200 bg-red-50 text-red-600",
  pc_mkdir:      "border-amber-200 bg-amber-50 text-amber-700",
  file_transfer: "border-purple-200 bg-purple-50 text-purple-700",
}

export function PendingTab() {
  const { actions, loading, approve, reject } = usePendingActions()

  if (loading && actions.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        {Array.from({ length: 2 }).map((_, i) => (
          <Skeleton key={i} className="h-48 w-full rounded-xl bg-muted" />
        ))}
      </div>
    )
  }

  if (actions.length === 0) {
    return (
      <div className="flex flex-col items-center gap-4 rounded-xl border border-border bg-muted/30 py-20 text-center">
        <div className="flex size-14 items-center justify-center rounded-full border border-green-200 bg-green-50">
          <ShieldCheckIcon className="size-6 text-green-600" />
        </div>
        <div>
          <p className="font-semibold text-foreground">All clear</p>
          <p className="mt-1 max-w-sm text-sm text-muted-foreground">
            When the agent prepares an email, WhatsApp message, or PC action, it will appear here
            for your confirmation.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/70">
          Pending approvals
        </p>
        <Badge variant="outline" className="border-primary/25 bg-primary/8 text-xs text-primary">
          {actions.length}
        </Badge>
      </div>

      {actions.map((action) => {
        const typeClass  = TYPE_COLORS[action.type] ?? "border-border bg-muted text-muted-foreground"
        const isHighRisk = action.risk_level === "high"

        return (
          <div
            key={action.id}
            className={cn(
              "rounded-xl border bg-card shadow-sm transition-all duration-200",
              isHighRisk
                ? "border-red-200 shadow-red-100"
                : "border-border hover:border-primary/30",
            )}
          >
            {/* header */}
            <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border/60 p-4">
              <div className="min-w-0 flex-1">
                <p className="font-semibold text-foreground">{action.title ?? action.type}</p>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  <Badge variant="outline" className={cn("text-xs", typeClass)}>
                    {action.type}
                  </Badge>
                  {action.risk_level && (
                    <Badge
                      variant="outline"
                      className={cn(
                        "text-xs",
                        isHighRisk
                          ? "border-red-300 bg-red-50 text-red-600"
                          : "border-amber-300 bg-amber-50 text-amber-700",
                      )}
                    >
                      {action.risk_level} risk
                    </Badge>
                  )}
                </div>
              </div>
              <div className="flex shrink-0 gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  className="cursor-pointer border-red-200 bg-red-50 text-red-600 hover:border-red-300 hover:bg-red-100"
                  onClick={() => void reject(action.id)}
                >
                  <XIcon className="size-3.5" />
                  Cancel
                </Button>
                <Button
                  size="sm"
                  className="cursor-pointer"
                  onClick={() => void approve(action.id)}
                >
                  <CheckIcon className="size-3.5" />
                  Approve
                </Button>
              </div>
            </div>
            <div className="p-4">
              {action.type === "email_send" && <EmailPreview payload={action.payload} />}
              {action.type === "whatsapp_send" && <WhatsAppPreview payload={action.payload} />}
              {(action.type === "pc_write" || action.type === "pc_delete" || action.type === "pc_mkdir") && (
                <FileOpPreview type={action.type} payload={action.payload} />
              )}
              {action.type === "file_transfer" && <TransferPreview payload={action.payload} />}
            </div>
          </div>
        )
      })}
    </div>
  )
}
