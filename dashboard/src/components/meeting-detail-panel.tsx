import { useEffect, useMemo, useState } from "react"
import { CheckIcon, DownloadIcon, RefreshCwIcon, XIcon } from "lucide-react"
import { toast } from "sonner"
import type { MeetingRecord } from "@/types/dashboard"
import {
  approvePendingAction,
  fetchMeetingDetail,
  meetingDownloadUrl,
  rejectPendingAction,
  summarizeMeeting,
  transcribeMeeting,
} from "@/lib/api"
import { PanelCard } from "@/components/dashboard/panel-card"
import { AudioWaveform } from "@/components/audio-waveform"
import { VideoPlayer } from "@/components/video-player"
import { Button, buttonVariants } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { parseYoutubeVideoId } from "@/lib/youtube"
import { cn } from "@/lib/utils"

function formatTranscript(raw: string): string {
  const lines: string[] = []
  for (const line of raw.split("\n")) {
    if (!line.trim()) continue
    try {
      const row = JSON.parse(line) as { type?: string; speaker?: string; text?: string }
      if (row.type === "segment" && row.text) {
        lines.push(`${row.speaker || "Unknown"}: ${row.text}`)
      }
    } catch {
      lines.push(line)
    }
  }
  return lines.join("\n") || raw
}

interface MeetingDetailPanelProps {
  meeting: MeetingRecord
}

export function MeetingDetailPanel({ meeting }: MeetingDetailPanelProps) {
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
  const transcriptText = useMemo(
    () => (detail?.transcript_raw ? formatTranscript(detail.transcript_raw) : ""),
    [detail?.transcript_raw],
  )

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

  async function refreshDetail() {
    const refreshed = await fetchMeetingDetail(meeting.id)
    setDetail(refreshed)
    return refreshed
  }

  async function handleTranscribe() {
    setBusy("transcribe")
    try {
      const result = await transcribeMeeting(meeting.id)
      if (result.status === "error") {
        toast.error(result.detail || "Transcription failed")
        return
      }
      toast.success(`Transcribed ${result.transcript_segments ?? 0} segments`)
      await refreshDetail()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Transcription failed")
    } finally {
      setBusy(null)
    }
  }

  async function handleSummarize() {
    setBusy("summarize")
    try {
      const result = await summarizeMeeting(meeting.id)
      if (result.status === "error") {
        toast.error(result.detail || "Summary generation failed")
        return
      }
      toast.success("Meeting summary regenerated")
      await refreshDetail()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Summary generation failed")
    } finally {
      setBusy(null)
    }
  }

  const media = detail?.media
  const artifacts = m.artifacts ?? {}
  const hasAudio = media?.has_audio ?? artifacts.audio
  const hasLocalVideo = media?.has_video ?? artifacts.video
  const youtubeUrl = m.youtube_url
  const youtubeVideoId = parseYoutubeVideoId(m.youtube_video_id) || parseYoutubeVideoId(youtubeUrl)
  const youtubeEmbedUrl = youtubeVideoId
    ? `https://www.youtube.com/embed/${youtubeVideoId}`
    : null
  // Only claim a Video section when we can render a player or a real YouTube link.
  const hasVideo = Boolean(hasLocalVideo || youtubeEmbedUrl || youtubeUrl)
  const hasTranscript = media?.has_transcript ?? artifacts.transcript

  return (
    <div className="flex flex-col gap-4">
      {(hasVideo || hasAudio || hasTranscript) && (
        <PanelCard title="Media & processing" description="Play, download, or re-run pipeline steps">
          {hasVideo && (
            <div className="mb-4">
              <p className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                Video
              </p>
              {hasLocalVideo ? (
                <VideoPlayer
                  meetingId={meeting.id}
                  src={media?.video_url || `/api/meetings/${meeting.id}/video`}
                  initialDuration={media?.video_duration_seconds}
                />
              ) : youtubeEmbedUrl ? (
                <div className="aspect-video overflow-hidden rounded-xl border border-border/60 bg-black">
                  <iframe
                    src={youtubeEmbedUrl}
                    title="Meeting recording on YouTube"
                    className="h-full w-full"
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                    allowFullScreen
                  />
                </div>
              ) : null}
              {youtubeUrl && (
                <a
                  href={youtubeUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-2 inline-block text-sm text-primary underline-offset-4 hover:underline"
                >
                  Open on YouTube
                </a>
              )}
            </div>
          )}
          {hasAudio && (
            <div className="mb-4">
              <p className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                Audio
              </p>
              <AudioWaveform
                meetingId={meeting.id}
                src={media?.audio_url || `/api/meetings/${meeting.id}/audio`}
                initialDuration={media?.duration_seconds}
                variant="flat"
              />
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            {hasAudio && (
              <a
                href={meetingDownloadUrl(media?.audio_url || `/api/meetings/${meeting.id}/audio`)}
                download
                className={cn(buttonVariants({ variant: "outline", size: "sm" }), "cursor-pointer")}
              >
                <DownloadIcon className="mr-1 size-3" /> Audio
              </a>
            )}
            {hasLocalVideo && (
              <a
                href={meetingDownloadUrl(media?.video_url || `/api/meetings/${meeting.id}/video`)}
                download
                className={cn(buttonVariants({ variant: "outline", size: "sm" }), "cursor-pointer")}
              >
                <DownloadIcon className="mr-1 size-3" /> Video
              </a>
            )}
            {hasTranscript && (
              <a
                href={meetingDownloadUrl(media?.transcript_url || `/api/meetings/${meeting.id}/transcript`)}
                download
                className={cn(buttonVariants({ variant: "outline", size: "sm" }), "cursor-pointer")}
              >
                <DownloadIcon className="mr-1 size-3" /> Transcript
              </a>
            )}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="secondary"
              className="cursor-pointer"
              disabled={!hasAudio || busy === "transcribe"}
              onClick={() => void handleTranscribe()}
            >
              <RefreshCwIcon className="mr-1 size-3" />
              {busy === "transcribe" ? "Transcribing…" : "Re-run audio → text"}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              className="cursor-pointer"
              disabled={!hasTranscript || busy === "summarize"}
              onClick={() => void handleSummarize()}
            >
              <RefreshCwIcon className="mr-1 size-3" />
              {busy === "summarize" ? "Summarizing…" : "Re-run text → summary"}
            </Button>
          </div>
        </PanelCard>
      )}

      {(minutes.tldr as string) ? (
        <PanelCard title="Summary" description="Meeting TL;DR">
          <p className="text-sm leading-relaxed text-foreground">{String(minutes.tldr)}</p>
        </PanelCard>
      ) : m.minutes_status === "partial" || m.minutes_status === "none" ? (
        <PanelCard title="Summary" description="Minutes not generated yet">
          <p className="text-sm text-muted-foreground">
            This session was archived with transcript only. Re-run finalization to generate minutes.
          </p>
        </PanelCard>
      ) : null}

      {actionItems.length > 0 && (
        <PanelCard title="Action items" description={`${actionItems.length} tasks`}>
          <ul className="flex flex-col gap-2">
            {actionItems.map((item, i) => (
              <li key={i} className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2 text-sm text-foreground">
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
              <li key={i} className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2 text-sm text-foreground">
                {d.summary}
                {d.made_by && <span className="text-muted-foreground"> ({d.made_by})</span>}
              </li>
            ))}
          </ul>
        </PanelCard>
      )}

      {detail?.transcript_raw && (
        <PanelCard title="Transcript" description="Recorded session text">
          <ScrollArea className="max-h-64">
            <pre className="whitespace-pre-wrap text-xs leading-relaxed text-foreground">
              {transcriptText}
            </pre>
          </ScrollArea>
        </PanelCard>
      )}

      {pending.length > 0 && (
        <PanelCard title="Follow-up drafts" description="Approve to send">
          <ul className="flex flex-col gap-3">
            {pending.map((action) => (
              <li key={action.id} className="rounded-xl border border-border/60 bg-muted/20 p-3">
                <p className="text-sm font-medium text-foreground">{action.title || action.type}</p>
                <ScrollArea className="mt-2 max-h-32">
                  <pre className="whitespace-pre-wrap text-xs text-muted-foreground">
                    {JSON.stringify(action.payload, null, 2)}
                  </pre>
                </ScrollArea>
                <div className="mt-3 flex gap-2">
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
