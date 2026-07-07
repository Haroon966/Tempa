import {
  AudioLinesIcon,
  CalendarIcon,
  FileTextIcon,
  MinusIcon,
  VideoIcon,
} from "lucide-react"
import type { MeetingRecord } from "@/types/dashboard"
import { MeetingDetailPanel } from "@/components/meeting-detail-panel"
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { formatTime } from "@/lib/format"
import { cn } from "@/lib/utils"

const ARTIFACT_META: Record<string, { label: string; icon: typeof VideoIcon }> = {
  audio: { label: "Audio", icon: AudioLinesIcon },
  video: { label: "Video", icon: VideoIcon },
  transcript: { label: "Transcript", icon: FileTextIcon },
}

type MeetingDetailModalProps = {
  meeting: MeetingRecord | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function MeetingDetailModal({ meeting, open, onOpenChange }: MeetingDetailModalProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-describedby={meeting ? "meeting-detail-desc" : undefined}>
        {meeting && (
          <>
            <DialogHeader>
              <DialogTitle className="pr-2">{meeting.title || "Untitled meeting"}</DialogTitle>
              <DialogDescription id="meeting-detail-desc" className="flex flex-wrap items-center gap-x-3 gap-y-1">
                {meeting.started_at && (
                  <span className="inline-flex items-center gap-1.5">
                    <CalendarIcon className="size-3.5 shrink-0" aria-hidden />
                    Recorded {formatTime(meeting.started_at)}
                  </span>
                )}
                {meeting.calendar_event_id && (
                  <span className="font-mono text-xs">Event {meeting.calendar_event_id}</span>
                )}
              </DialogDescription>
              {meeting.artifacts && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {Object.entries(meeting.artifacts).map(([key, ok]) => {
                    const meta = ARTIFACT_META[key]
                    const Icon = meta?.icon ?? FileTextIcon
                    return (
                      <Badge
                        key={key}
                        variant="outline"
                        className={cn(
                          "gap-1 text-[11px] font-medium transition-colors duration-200",
                          ok
                            ? "border-primary/25 bg-primary/5 text-primary"
                            : "border-border bg-muted/40 text-muted-foreground",
                        )}
                      >
                        {ok ? (
                          <Icon className="size-3" aria-hidden />
                        ) : (
                          <MinusIcon className="size-3" aria-hidden />
                        )}
                        {meta?.label ?? key}
                      </Badge>
                    )
                  })}
                </div>
              )}
            </DialogHeader>
            <DialogBody>
              <MeetingDetailPanel key={meeting.id} meeting={meeting} />
            </DialogBody>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
