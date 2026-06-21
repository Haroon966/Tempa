import { useState } from "react"
import { CheckIcon, PencilIcon, ShieldCheckIcon, XIcon } from "lucide-react"
import {
  approvePendingAction,
  fetchPendingActions,
  rejectPendingAction,
  updatePendingAction,
  type PendingActionPreview,
} from "@/lib/api"
import { EmailPreview } from "@/components/pending/email-preview"
import { WhatsAppPreview } from "@/components/pending/whatsapp-preview"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { toast } from "sonner"

type PendingActionCardProps = {
  preview: PendingActionPreview
  onResolved?: () => void
  onContinuePlan?: () => void
  streaming?: boolean
}

export function PendingActionCard({
  preview,
  onResolved,
  onContinuePlan,
  streaming = false,
}: PendingActionCardProps) {
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState(false)
  const [fullAction, setFullAction] = useState<Record<string, unknown> | null>(null)
  const [editBody, setEditBody] = useState("")

  const loadFullAction = async () => {
    if (fullAction) return fullAction
    const data = await fetchPendingActions()
    const action = data.actions.find((a) => a.id === preview.id)
    if (action) {
      setFullAction(action.payload)
      setEditBody(String(action.payload.body ?? action.payload.body_html ?? action.payload.message ?? ""))
      return action.payload
    }
    return null
  }

  const handleApprove = async () => {
    setLoading(true)
    try {
      await approvePendingAction(preview.id)
      toast.success("Approved and executed")
      onResolved?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Approval failed")
    } finally {
      setLoading(false)
    }
  }

  const handleReject = async () => {
    setLoading(true)
    try {
      await rejectPendingAction(preview.id)
      toast.message("Action rejected")
      onResolved?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Reject failed")
    } finally {
      setLoading(false)
    }
  }

  const handleSaveEdit = async () => {
    setLoading(true)
    try {
      const payload = await loadFullAction()
      if (!payload) throw new Error("Action not found")
      const patch =
        preview.type === "email_send"
          ? { ...payload, body: editBody }
          : { ...payload, message: editBody }
      await updatePendingAction(preview.id, patch)
      setFullAction(patch)
      setEditing(false)
      toast.success("Draft updated")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Update failed")
    } finally {
      setLoading(false)
    }
  }

  const handleStartEdit = async () => {
    await loadFullAction()
    setEditing(true)
  }

  const isPlan = preview.type === "plan_preview"

  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50/80 p-3 text-left sm:p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <ShieldCheckIcon className="size-4 shrink-0 text-amber-700" />
          <div>
            <p className="text-sm font-medium text-amber-900">
              {isPlan ? "Plan awaiting approval" : "Action awaiting approval"}
            </p>
            <Badge variant="outline" className="mt-1 text-[10px] text-amber-800">
              {preview.type}
            </Badge>
          </div>
        </div>
      </div>

      {preview.preview && !editing && (
        <pre className="mt-3 max-h-40 overflow-auto rounded-lg border border-amber-200/80 bg-white/70 p-3 text-xs whitespace-pre-wrap text-foreground">
          {preview.preview}
        </pre>
      )}

      {fullAction && preview.type === "email_send" && !editing && (
        <div className="mt-3 rounded-lg border border-amber-200/80 bg-white/70 p-3">
          <EmailPreview payload={fullAction} />
        </div>
      )}

      {fullAction && preview.type === "whatsapp_send" && !editing && (
        <div className="mt-3 rounded-lg border border-amber-200/80 bg-white/70 p-3">
          <WhatsAppPreview payload={fullAction} />
        </div>
      )}

      {editing && (
        <textarea
          value={editBody}
          onChange={(e) => setEditBody(e.target.value)}
          className="mt-3 min-h-24 w-full rounded-lg border border-amber-200 bg-white p-3 text-sm"
        />
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {isPlan ? (
          <Button
            size="sm"
            className="h-9 cursor-pointer"
            onClick={onContinuePlan}
            disabled={streaming || loading}
          >
            Continue plan
          </Button>
        ) : (
          <>
            {!fullAction && !isPlan && (
              <Button
                size="sm"
                variant="outline"
                className="h-9 cursor-pointer"
                onClick={() => void loadFullAction()}
                disabled={loading}
              >
                Load preview
              </Button>
            )}
            {editing ? (
              <Button
                size="sm"
                className="h-9 cursor-pointer gap-1"
                onClick={() => void handleSaveEdit()}
                disabled={loading}
              >
                <CheckIcon className="size-3.5" />
                Save draft
              </Button>
            ) : (
              !isPlan && (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-9 cursor-pointer gap-1"
                  onClick={() => void handleStartEdit()}
                  disabled={loading}
                >
                  <PencilIcon className="size-3.5" />
                  Edit
                </Button>
              )
            )}
            <Button
              size="sm"
              className="h-9 cursor-pointer gap-1"
              onClick={() => void handleApprove()}
              disabled={loading || streaming}
            >
              <CheckIcon className="size-3.5" />
              Approve
            </Button>
          </>
        )}
        <Button
          size="sm"
          variant="outline"
          className="h-9 cursor-pointer gap-1"
          onClick={() => void handleReject()}
          disabled={loading || streaming}
        >
          <XIcon className="size-3.5" />
          Reject
        </Button>
      </div>
    </div>
  )
}
