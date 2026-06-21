import { useEffect, useState } from "react"
import { CheckIcon, XIcon } from "lucide-react"
import { toast } from "sonner"
import type { MeetingRecord } from "@/types/dashboard"
import { approvePendingAction, fetchMeetingDetail, rejectPendingAction } from "@/lib/api"
import { PanelCard } from "@/components/dashboard/panel-card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"

interface MeetingDetailPanelProps {
  meeting: MeetingRecord
  onClose?: () => void
}

export function MeetingDetailPanel({ meeting, onClose }: MeetingDetailPanelProps) {
  const [detail, setDetail] = useState<Awaited<ReturnType<typeof fetchMeetingDetail>> | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  useEffect(() => {
    void fetchMeetingDetail(meeting.id)
      .then(setDetail)
      .catch(() => toast.error("Failed to load meeting detail"))
  }, [meeting.id])

  const m = detail?.meeting ?? meeting
  const minutes = (m.minutes ?? {}) as Record<string, unknown>
  const actionItems = (minutes.action_items ?? []) as Array<{ owner?: string; task?: string; due?: string }>
  const decisions = (minutes.decisions ?? []) as Array<{ summary?: string; made_by?: string }>
  const pending = detail?.pending_followups ?? []

  async function handleApprove(id: string) {
    setBusy(id)
    try {
      await approvePendingAction(id)
      toast.success("Follow-up approved")
      const refreshed = await fetchMeetingDetail(meeting.id)
      setDetail(refreshed)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Approve failed")
    } finally {
      setBusy(null)
    }
  }

  async function handleReject(id: string) {
    setBusy(id)
    try {
      await rejectPendingAction(id)
      toast.success("Follow-up rejected")
      const refreshed = await fetchMeetingDetail(meeting.id)
      setDetail(refreshed)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Reject failed")
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-lg font-semibold text-foreground">{m.title || m.id}</h3>
          {m.calendar_event_id && (
            <p className="text-xs text-muted-foreground">Calendar event {m.calendar_event_id}</p>
          )}
        </div>
        {onClose && (
          <Button variant="ghost" size="sm" className="cursor-pointer" onClick={onClose}>
            Close
          </Button>
        )}
      </div>

      {m.artifacts && (
        <div className="flex flex-wrap gap-2">
          {Object.entries(m.artifacts).map(([key, ok]) => (
            <Badge key={key} variant={ok ? "default" : "outline"}>
              {key} {ok ? "✓" : "—"}
            </Badge>
          ))}
        </div>
      )}

      {(minutes.tldr as string) && (
        <PanelCard title="Summary" description="Meeting TL;DR">
          <p className="text-sm text-foreground">{String(minutes.tldr)}</p>
        </PanelCard>
      )}

      {actionItems.length > 0 && (
        <PanelCard title="Action items" description={`${actionItems.length} tasks`}>
          <ul className="flex flex-col gap-2">
            {actionItems.map((item, i) => (
              <li key={i} className="text-sm text-foreground">
                <span className="font-medium">{item.owner || "Unassigned"}:</span> {item.task}
                {item.due && <span className="text-muted-foreground"> — due {item.due}</span>}
              </li>
            ))}
          </ul>
        </PanelCard>
      )}

      {decisions.length > 0 && (
        <PanelCard title="Decisions">
          <ul className="flex flex-col gap-2">
            {decisions.map((d, i) => (
              <li key={i} className="text-sm text-foreground">
                {d.summary}
                {d.made_by && <span className="text-muted-foreground"> ({d.made_by})</span>}
              </li>
            ))}
          </ul>
        </PanelCard>
      )}

      {pending.length > 0 && (
        <PanelCard title="Follow-up drafts" description="Approve to send">
          <ul className="flex flex-col gap-3">
            {pending.map((action) => (
              <li key={action.id} className="rounded-lg border border-border/60 p-3">
                <p className="text-sm font-medium">{action.title || action.type}</p>
                <ScrollArea className="mt-2 max-h-32">
                  <pre className="whitespace-pre-wrap text-xs text-muted-foreground">
                    {JSON.stringify(action.payload, null, 2)}
                  </pre>
                </ScrollArea>
                <div className="mt-2 flex gap-2">
                  <Button
                    size="sm"
                    className="cursor-pointer"
                    disabled={busy === action.id}
                    onClick={() => void handleApprove(action.id)}
                  >
                    <CheckIcon className="mr-1 size-3" /> Approve
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="cursor-pointer"
                    disabled={busy === action.id}
                    onClick={() => void handleReject(action.id)}
                  >
                    <XIcon className="mr-1 size-3" /> Reject
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </PanelCard>
      )}
    </div>
  )
}
