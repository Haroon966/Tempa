import { useCallback, useEffect, useRef, useState } from "react"
import { MaximizeIcon, PauseIcon, PlayIcon } from "lucide-react"
import {
  fetchMeetingStoryboard,
  meetingDownloadUrl,
  type VideoStoryboard,
} from "@/lib/api"
import { formatDuration } from "@/lib/format"
import { cn } from "@/lib/utils"

type VideoPlayerProps = {
  meetingId: string
  src: string
  initialDuration?: number
  className?: string
}

type HoverState = {
  time: number
  ratio: number
  x: number
}

export function VideoPlayer({ meetingId, src, initialDuration, className }: VideoPlayerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const trackRef = useRef<HTMLDivElement>(null)
  const progressRef = useRef<HTMLDivElement>(null)
  const timeLabelRef = useRef<HTMLSpanElement>(null)
  const [storyboard, setStoryboard] = useState<VideoStoryboard | null>(null)
  const [playing, setPlaying] = useState(false)
  const [duration, setDuration] = useState(initialDuration ?? 0)
  const [hover, setHover] = useState<HoverState | null>(null)
  const [trackWidth, setTrackWidth] = useState(0)
  const [isFullscreen, setIsFullscreen] = useState(false)

  const videoSrc = meetingDownloadUrl(src)
  const totalDuration =
    duration ||
    storyboard?.duration_seconds ||
    initialDuration ||
    0

  const syncProgressUi = useCallback(
    (currentTime: number) => {
      const progress = totalDuration > 0 ? currentTime / totalDuration : 0
      if (progressRef.current) {
        progressRef.current.style.width = `${progress * 100}%`
      }
      if (timeLabelRef.current) {
        timeLabelRef.current.textContent = `${formatDuration(currentTime)} / ${
          totalDuration > 0 ? formatDuration(totalDuration) : "0:00"
        }`
      }
    },
    [totalDuration],
  )

  useEffect(() => {
    void fetchMeetingStoryboard(meetingId).then(setStoryboard)
  }, [meetingId])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return

    let raf = 0
    const tick = () => {
      syncProgressUi(video.currentTime)
      if (!video.paused && !video.ended) {
        raf = requestAnimationFrame(tick)
      }
    }

    const onMeta = () => {
      if (video.duration && Number.isFinite(video.duration)) {
        setDuration(video.duration)
      }
      syncProgressUi(video.currentTime)
    }
    const onPlay = () => {
      setPlaying(true)
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(tick)
    }
    const onPause = () => {
      setPlaying(false)
      cancelAnimationFrame(raf)
      syncProgressUi(video.currentTime)
    }
    const onEnded = () => {
      setPlaying(false)
      cancelAnimationFrame(raf)
      syncProgressUi(0)
      video.currentTime = 0
    }

    video.addEventListener("loadedmetadata", onMeta)
    video.addEventListener("play", onPlay)
    video.addEventListener("pause", onPause)
    video.addEventListener("ended", onEnded)
    return () => {
      cancelAnimationFrame(raf)
      video.removeEventListener("loadedmetadata", onMeta)
      video.removeEventListener("play", onPlay)
      video.removeEventListener("pause", onPause)
      video.removeEventListener("ended", onEnded)
    }
  }, [videoSrc, syncProgressUi])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const sync = () => {
      const el =
        document.fullscreenElement ??
        (document as Document & { webkitFullscreenElement?: Element }).webkitFullscreenElement
      setIsFullscreen(el === container)
    }

    document.addEventListener("fullscreenchange", sync)
    document.addEventListener("webkitfullscreenchange", sync)
    return () => {
      document.removeEventListener("fullscreenchange", sync)
      document.removeEventListener("webkitfullscreenchange", sync)
    }
  }, [])

  useEffect(() => {
    const track = trackRef.current
    if (!track) return
    const observer = new ResizeObserver(([entry]) => {
      setTrackWidth(entry.contentRect.width)
    })
    observer.observe(track)
    return () => observer.disconnect()
  }, [])

  const togglePlay = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    if (video.paused) {
      void video.play()
    } else {
      video.pause()
    }
  }, [])

  const seekToRatio = useCallback(
    (ratio: number) => {
      const video = videoRef.current
      if (!video || totalDuration <= 0) return
      const next = Math.max(0, Math.min(totalDuration, ratio * totalDuration))
      video.currentTime = next
      syncProgressUi(next)
    },
    [totalDuration, syncProgressUi],
  )

  const handleTrackMove = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      const track = trackRef.current
      if (!track || totalDuration <= 0) return
      const rect = track.getBoundingClientRect()
      const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width))
      setHover({
        time: ratio * totalDuration,
        ratio,
        x: event.clientX - rect.left,
      })
    },
    [totalDuration],
  )

  const toggleFullscreen = useCallback(() => {
    const container = containerRef.current
    if (!container) return
    const doc = document as Document & {
      webkitFullscreenElement?: Element
      webkitExitFullscreen?: () => Promise<void>
    }
    const active = doc.fullscreenElement ?? doc.webkitFullscreenElement
    if (active) {
      if (doc.exitFullscreen) void doc.exitFullscreen()
      else doc.webkitExitFullscreen?.()
    } else if (container.requestFullscreen) {
      void container.requestFullscreen()
    } else {
      const el = container as HTMLDivElement & { webkitRequestFullscreen?: () => void }
      el.webkitRequestFullscreen?.()
    }
  }, [])

  const preview =
    storyboard?.available && hover && storyboard.sprite_url
      ? storyboardPreview(storyboard, hover.time)
      : null

  const previewLeft =
    preview && hover
      ? Math.max(8, Math.min(hover.x - preview.width / 2, trackWidth - preview.width - 8))
      : 0

  return (
    <div
      ref={containerRef}
      className={cn(
        "group/player relative overflow-hidden rounded-xl border border-border/60 bg-black",
        isFullscreen && "flex h-full w-full flex-col justify-center rounded-none border-0",
        className,
      )}
    >
      <video
        ref={videoRef}
        src={videoSrc}
        preload="metadata"
        playsInline
        className={cn(
          "w-full bg-black object-contain",
          isFullscreen ? "h-full max-h-none" : "aspect-video max-h-80",
        )}
        onClick={togglePlay}
      />

      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 via-black/55 to-transparent px-3 pb-3 pt-10 opacity-100 transition-opacity duration-200 sm:opacity-0 sm:group-hover/player:opacity-100 sm:group-focus-within/player:opacity-100">
        {hover && (
          <div
            className="pointer-events-none absolute bottom-full mb-3"
            style={{
              left: preview ? previewLeft : Math.max(8, hover.x - 40),
              width: preview?.width ?? 80,
            }}
          >
            {preview ? (
              <div
                className="overflow-hidden rounded-lg border border-white/20 bg-black shadow-xl"
                style={{
                  width: preview.width,
                  height: preview.height,
                  backgroundImage: preview.backgroundImage,
                  backgroundPosition: preview.backgroundPosition,
                  backgroundSize: preview.backgroundSize,
                  backgroundRepeat: "no-repeat",
                }}
                role="img"
                aria-label={`Preview at ${formatDuration(hover.time)}`}
              />
            ) : null}
            <p
              className={cn(
                "rounded bg-black/85 px-2 py-0.5 text-center text-xs font-medium tabular-nums text-white",
                preview ? "mt-1.5" : "",
              )}
            >
              {formatDuration(hover.time)}
            </p>
          </div>
        )}

        <div
          ref={trackRef}
          className="relative mb-2 h-2 cursor-pointer rounded-full bg-white/20"
          onMouseMove={handleTrackMove}
          onMouseLeave={() => setHover(null)}
          onClick={(event) => {
            const rect = event.currentTarget.getBoundingClientRect()
            const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width))
            seekToRatio(ratio)
          }}
          role="slider"
          aria-label="Video timeline"
          aria-valuemin={0}
          aria-valuemax={totalDuration}
          aria-valuenow={0}
          tabIndex={0}
          onKeyDown={(event) => {
            const video = videoRef.current
            const progress = video && totalDuration > 0 ? video.currentTime / totalDuration : 0
            if (event.key === "ArrowLeft") seekToRatio(Math.max(0, progress - 0.02))
            if (event.key === "ArrowRight") seekToRatio(Math.min(1, progress + 0.02))
          }}
        >
          <div
            ref={progressRef}
            className="absolute inset-y-0 left-0 rounded-full bg-primary"
            style={{ width: "0%" }}
          />
          {hover && (
            <div
              className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary ring-2 ring-white/80"
              style={{ left: `${hover.ratio * 100}%` }}
            />
          )}
        </div>

        <div className="flex items-center justify-between gap-3 text-white">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={togglePlay}
              aria-label={playing ? "Pause video" : "Play video"}
              className="flex size-8 cursor-pointer items-center justify-center rounded-full transition-colors duration-200 hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/50"
            >
              {playing ? (
                <PauseIcon className="size-4" fill="currentColor" />
              ) : (
                <PlayIcon className="size-4" fill="currentColor" />
              )}
            </button>
            <span ref={timeLabelRef} className="text-xs tabular-nums text-white/90">
              {formatDuration(0)} / {totalDuration > 0 ? formatDuration(totalDuration) : "0:00"}
            </span>
          </div>
          <button
            type="button"
            onClick={toggleFullscreen}
            aria-label="Fullscreen"
            className="flex size-8 cursor-pointer items-center justify-center rounded-full transition-colors duration-200 hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/50"
          >
            <MaximizeIcon className="size-4" />
          </button>
        </div>
      </div>
    </div>
  )
}

function storyboardPreview(storyboard: VideoStoryboard, time: number) {
  const {
    interval_seconds: interval = 1,
    tile_width: tileWidth = 160,
    tile_height: tileHeight = 90,
    columns = 10,
    rows = 1,
    count = 1,
    sprite_url: spriteUrl = "",
  } = storyboard

  const index = Math.min(count - 1, Math.max(0, Math.floor(time / interval)))
  const col = index % columns
  const row = Math.floor(index / columns)

  return {
    width: tileWidth,
    height: tileHeight,
    backgroundImage: `url(${meetingDownloadUrl(spriteUrl)})`,
    backgroundPosition: `-${col * tileWidth}px -${row * tileHeight}px`,
    backgroundSize: `${columns * tileWidth}px ${rows * tileHeight}px`,
  }
}
