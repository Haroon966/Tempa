import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Loader2Icon, MicIcon, PauseIcon, PlayIcon, VolumeXIcon } from "lucide-react"
import { fetchMeetingWaveform, meetingDownloadUrl, type MeetingWaveform } from "@/lib/api"
import { formatDuration } from "@/lib/format"
import { cn } from "@/lib/utils"

type AudioWaveformProps = {
  meetingId: string
  src: string
  compact?: boolean
  lazy?: boolean
  className?: string
  initialDuration?: number
  /** WhatsApp-style bubble (default) or flat panel */
  variant?: "bubble" | "flat"
}

export function AudioWaveform({
  meetingId,
  src,
  compact = false,
  lazy = false,
  className,
  initialDuration,
  variant = "bubble",
}: AudioWaveformProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const [visible, setVisible] = useState(!lazy)
  const [waveform, setWaveform] = useState<MeetingWaveform | null>(null)
  const [loading, setLoading] = useState(!lazy)
  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(initialDuration ?? 0)
  const lastProgressUi = useRef(0)

  const barCount = compact ? 40 : 56
  const hasRealPeaks = Boolean(waveform?.available && waveform.peaks.length > 0)
  const peaks = hasRealPeaks ? waveform!.peaks : placeholderPeaks(barCount)
  const normalizedPeaks = useMemo(() => normalizePeaks(peaks, barCount), [peaks, barCount])
  const activity = useMemo(() => describeAudioActivity(normalizedPeaks, hasRealPeaks), [normalizedPeaks, hasRealPeaks])
  const totalDuration = waveform?.duration_seconds || duration || initialDuration || 0
  const progress = totalDuration > 0 ? currentTime / totalDuration : 0
  const timeLabel = playing ? formatDuration(currentTime) : formatDuration(totalDuration)

  useEffect(() => {
    if (!lazy || visible) return
    const node = rootRef.current
    if (!node) return

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setVisible(true)
          observer.disconnect()
        }
      },
      { rootMargin: "120px" },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [lazy, visible])

  useEffect(() => {
    if (!visible) return
    let cancelled = false
    setLoading(true)
    void fetchMeetingWaveform(meetingId, barCount)
      .then((data) => {
        if (cancelled) return
        setWaveform(data)
        if (data.duration_seconds > 0) setDuration(data.duration_seconds)
      })
      .catch(() => {
        if (!cancelled) setWaveform({ available: false, duration_seconds: 0, peaks: [] })
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [visible, meetingId, barCount])

  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return

    let raf = 0
    const tick = (now: number) => {
      if (now - lastProgressUi.current >= 120) {
        lastProgressUi.current = now
        setCurrentTime(audio.currentTime)
      }
      if (!audio.paused && !audio.ended) {
        raf = requestAnimationFrame(tick)
      }
    }

    const onMeta = () => {
      if (audio.duration && Number.isFinite(audio.duration)) {
        setDuration((prev) => prev || audio.duration)
      }
      setCurrentTime(audio.currentTime)
    }
    const onPlay = () => {
      setPlaying(true)
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(tick)
    }
    const onPause = () => {
      setPlaying(false)
      cancelAnimationFrame(raf)
      setCurrentTime(audio.currentTime)
    }
    const onEnded = () => {
      setPlaying(false)
      cancelAnimationFrame(raf)
      setCurrentTime(0)
    }

    audio.addEventListener("loadedmetadata", onMeta)
    audio.addEventListener("play", onPlay)
    audio.addEventListener("pause", onPause)
    audio.addEventListener("ended", onEnded)
    return () => {
      cancelAnimationFrame(raf)
      audio.removeEventListener("loadedmetadata", onMeta)
      audio.removeEventListener("play", onPlay)
      audio.removeEventListener("pause", onPause)
      audio.removeEventListener("ended", onEnded)
    }
  }, [src])

  const togglePlay = useCallback(() => {
    const audio = audioRef.current
    if (!audio) return
    if (audio.paused) {
      void audio.play()
    } else {
      audio.pause()
    }
  }, [])

  const seek = useCallback(
    (ratio: number) => {
      const audio = audioRef.current
      if (!audio || totalDuration <= 0) return
      const next = Math.max(0, Math.min(totalDuration, ratio * totalDuration))
      audio.currentTime = next
      setCurrentTime(next)
    },
    [totalDuration],
  )

  if (!visible) {
    return (
      <div
        ref={rootRef}
        className={cn(
          "rounded-2xl bg-muted/40",
          compact ? "h-11" : "h-14",
          className,
        )}
        aria-hidden
      />
    )
  }

  const ActivityIcon = activity.tone === "silent" ? VolumeXIcon : MicIcon

  return (
    <div
      ref={rootRef}
      className={cn(
        "transition-colors duration-200",
        variant === "bubble"
          ? cn(
              "rounded-2xl border border-primary/15 bg-gradient-to-r from-primary/8 via-primary/5 to-transparent shadow-sm",
              compact ? "px-2.5 py-2" : "px-3 py-3",
            )
          : cn(
              "rounded-xl border border-border/60 bg-muted/20",
              compact ? "p-2.5" : "p-4",
            ),
        className,
      )}
    >
      <audio ref={audioRef} src={meetingDownloadUrl(src)} preload="metadata" className="hidden" />

      <div className={cn("flex items-center gap-2.5", compact ? "gap-2" : "gap-3")}>
        <button
          type="button"
          onClick={togglePlay}
          disabled={loading && !totalDuration}
          aria-label={playing ? "Pause audio" : "Play audio"}
          className={cn(
            "flex shrink-0 cursor-pointer items-center justify-center rounded-full bg-primary text-primary-foreground shadow-md transition-all duration-200 hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:cursor-not-allowed disabled:opacity-50",
            compact ? "size-9" : "size-11",
          )}
        >
          {loading ? (
            <Loader2Icon className={cn("animate-spin", compact ? "size-3.5" : "size-4")} />
          ) : playing ? (
            <PauseIcon className={cn(compact ? "size-3.5" : "size-4")} fill="currentColor" />
          ) : (
            <PlayIcon className={cn(compact ? "size-3.5" : "size-4")} fill="currentColor" />
          )}
        </button>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <WhatsAppWaveform
              peaks={normalizedPeaks}
              progress={progress}
              loading={loading}
              compact={compact}
              onSeek={seek}
            />
            <span
              className={cn(
                "shrink-0 tabular-nums text-muted-foreground",
                compact ? "min-w-[2.25rem] text-[11px] font-semibold" : "min-w-[2.75rem] text-xs font-semibold",
              )}
              aria-live="polite"
            >
              {totalDuration > 0 ? timeLabel : loading ? "…" : "0:00"}
            </span>
          </div>

          <div
            className={cn(
              "mt-1 flex items-center gap-1 text-muted-foreground",
              compact ? "text-[10px]" : "text-[11px]",
            )}
          >
            <ActivityIcon className="size-3 shrink-0" aria-hidden />
            <span className={cn("font-medium", activity.className)}>{activity.label}</span>
            {hasRealPeaks && !compact && (
              <span className="text-muted-foreground/70">· {activity.detail}</span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function WhatsAppWaveform({
  peaks,
  progress,
  loading,
  compact,
  onSeek,
}: {
  peaks: number[]
  progress: number
  loading: boolean
  compact: boolean
  onSeek: (ratio: number) => void
}) {
  const height = compact ? 28 : 36

  return (
    <button
      type="button"
      aria-label="Seek audio"
      onClick={(event) => {
        event.stopPropagation()
        const rect = event.currentTarget.getBoundingClientRect()
        const ratio = rect.width > 0 ? (event.clientX - rect.left) / rect.width : 0
        onSeek(ratio)
      }}
      className="group relative flex flex-1 cursor-pointer items-center gap-[2px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
      style={{ height }}
    >
      {peaks.map((peak, index) => {
        const barProgress = (index + 0.5) / peaks.length
        const played = barProgress <= progress
        const barHeight = Math.max(3, Math.round(peak * (height * 0.88)))

        return (
          <span
            key={index}
            className="flex flex-1 items-center justify-center"
            style={{ height }}
          >
            <span
              className={cn(
                "w-full max-w-[3px] rounded-full transition-colors duration-150",
                played
                  ? "bg-primary"
                  : "bg-primary/25 group-hover:bg-primary/35",
                loading && !played && "animate-pulse bg-primary/15",
              )}
              style={{ height: barHeight }}
              aria-hidden
            />
          </span>
        )
      })}
    </button>
  )
}

function normalizePeaks(peaks: number[], target: number): number[] {
  if (peaks.length === target) return peaks
  if (peaks.length === 0) return placeholderPeaks(target)
  const out: number[] = []
  for (let i = 0; i < target; i++) {
    const pos = (i / target) * peaks.length
    const left = Math.floor(pos)
    const right = Math.min(peaks.length - 1, left + 1)
    const mix = pos - left
    out.push(peaks[left] * (1 - mix) + peaks[right] * mix)
  }
  return out
}

function describeAudioActivity(
  peaks: number[],
  fromFile: boolean,
): { label: string; detail: string; tone: "strong" | "moderate" | "quiet" | "silent"; className: string } {
  if (!fromFile) {
    return {
      label: "Loading waveform…",
      detail: "Reading audio levels",
      tone: "moderate",
      className: "text-muted-foreground",
    }
  }

  const max = Math.max(...peaks, 0)
  const avg = peaks.reduce((sum, p) => sum + p, 0) / Math.max(peaks.length, 1)
  const loudBars = peaks.filter((p) => p > 0.35).length / peaks.length

  if (max < 0.08 || avg < 0.05) {
    return {
      label: "Mostly silent",
      detail: "Very little speech detected",
      tone: "silent",
      className: "text-muted-foreground",
    }
  }
  if (loudBars > 0.2 || max > 0.75) {
    return {
      label: "Clear voice",
      detail: "Strong speech and variation",
      tone: "strong",
      className: "text-primary",
    }
  }
  if (avg > 0.15 || loudBars > 0.08) {
    return {
      label: "Voice detected",
      detail: "Moderate audio activity",
      tone: "moderate",
      className: "text-foreground",
    }
  }
  return {
    label: "Quiet recording",
    detail: "Low volume throughout",
    tone: "quiet",
    className: "text-muted-foreground",
  }
}

function placeholderPeaks(count: number): number[] {
  return Array.from({ length: count }, (_, index) => {
    const t = index / count
    return 0.2 + Math.abs(Math.sin(t * Math.PI * 5)) * 0.35 + Math.abs(Math.cos(t * Math.PI * 2.5)) * 0.2
  })
}

const waveformPreviewCache = new Map<string, MeetingWaveform>()

/** Compact static preview for lists — real waveform only, no playback. */
export function AudioWaveformPreview({
  meetingId,
  className,
}: {
  meetingId: string
  className?: string
}) {
  const rootRef = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)
  const [waveform, setWaveform] = useState<MeetingWaveform | null>(
    () => waveformPreviewCache.get(meetingId) ?? null,
  )

  useEffect(() => {
    const node = rootRef.current
    if (!node) return
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setVisible(true)
          observer.disconnect()
        }
      },
      { rootMargin: "120px" },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!visible) return
    const cached = waveformPreviewCache.get(meetingId)
    if (cached) {
      setWaveform(cached)
      return
    }
    void fetchMeetingWaveform(meetingId, 32)
      .then((data) => {
        waveformPreviewCache.set(meetingId, data)
        setWaveform(data)
      })
      .catch(() => null)
  }, [meetingId, visible])

  const peaks = normalizePeaks(
    waveform?.available && waveform.peaks.length ? waveform.peaks : placeholderPeaks(32),
    32,
  )
  const activity = describeAudioActivity(peaks, Boolean(waveform?.available && waveform.peaks.length))
  const duration = waveform?.duration_seconds ?? 0

  return (
    <div
      ref={rootRef}
      className={cn(
        "flex items-center gap-2 rounded-xl border border-primary/15 bg-primary/5 px-2 py-1.5",
        className,
      )}
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => event.stopPropagation()}
    >
      <MicIcon className="size-3.5 shrink-0 text-primary" aria-hidden />
      <div className="flex min-w-0 flex-1 items-center gap-[1px]" style={{ height: 20 }}>
        {peaks.map((peak, i) => (
          <span
            key={i}
            className="flex-1 rounded-full bg-primary/30"
            style={{ height: Math.max(2, Math.round(peak * 18)) }}
            aria-hidden
          />
        ))}
      </div>
      <span className="shrink-0 text-[10px] font-semibold tabular-nums text-muted-foreground">
        {duration > 0 ? formatDuration(duration) : activity.label}
      </span>
    </div>
  )
}
