import { useMemo, useState } from "react"
import type { PresenceEntry, PresenceStatus } from "@/lib/api"
import { cn } from "@/lib/utils"
import {
  buildClusters,
  initials,
  type BoardCluster,
} from "@/components/presence/presence-board-model"

const ASSET = {
  bg: "/presence/presence-map-bg.jpg",
  hq: "/presence/presence-office-hq.png",
  officeSmall: "/presence/presence-office-small.png",
  house: "/presence/presence-house.png",
  vacation: "/presence/presence-vacation.png",
  bus: "/presence/presence-bus.png",
  camp: "/presence/presence-camp.png",
}

const STATUS_RING: Record<PresenceStatus, string> = {
  leave: "ring-red-500",
  half_day: "ring-orange-500",
  leave_early: "ring-amber-500",
  remote: "ring-sky-500",
  late: "ring-yellow-500",
  partial_away: "ring-violet-500",
  ooo: "ring-slate-500",
  back: "ring-emerald-500",
  office: "ring-teal-500",
  field_visit: "ring-indigo-500",
  travel: "ring-cyan-500",
  limited: "ring-rose-500",
  other: "ring-slate-400",
}

const STATUS_LABEL: Record<PresenceStatus, string> = {
  leave: "On leave",
  half_day: "Half day",
  leave_early: "Leaving early",
  remote: "Remote",
  late: "Running late",
  partial_away: "Partially away",
  ooo: "Briefly out",
  back: "Back",
  office: "In office",
  field_visit: "Field visit",
  travel: "Travelling",
  limited: "Limited availability",
  other: "Other",
}

const STATUS_CHIP: Record<PresenceStatus, string> = {
  leave: "bg-red-100 text-red-700",
  half_day: "bg-orange-100 text-orange-700",
  leave_early: "bg-amber-100 text-amber-700",
  remote: "bg-sky-100 text-sky-700",
  late: "bg-yellow-100 text-yellow-700",
  partial_away: "bg-violet-100 text-violet-700",
  ooo: "bg-slate-100 text-slate-600",
  back: "bg-emerald-100 text-emerald-700",
  office: "bg-teal-100 text-teal-700",
  field_visit: "bg-indigo-100 text-indigo-700",
  travel: "bg-cyan-100 text-cyan-700",
  limited: "bg-rose-100 text-rose-700",
  other: "bg-slate-100 text-slate-600",
}

/** Tiny badge on the avatar corner; office stays clean (too many people). */
const STATUS_BADGE: Partial<Record<PresenceStatus, string>> = {
  leave: "🌴",
  half_day: "🕑",
  leave_early: "🕔",
  remote: "🏠",
  late: "⏰",
  partial_away: "🚶",
  ooo: "☕",
  back: "✅",
  field_visit: "⛺",
  travel: "✈️",
  limited: "📶",
}

interface WorldZone {
  id: string
  label: string
  asset: string
  /** sprite anchor, % of scene */
  sprite: { x: number; y: number; h: number }
  /** crowd area, % of scene — rows fan out downward from y0, centered on cx */
  crowd: { cx: number; x0: number; x1: number; y0: number; y1: number }
  label_pos: { x: number; y: number }
  cap: number
}

const ZONES: WorldZone[] = [
  {
    id: "vacation",
    label: "On leave",
    asset: ASSET.vacation,
    sprite: { x: 10, y: 14, h: 17 },
    crowd: { cx: 11, x0: 2, x1: 21, y0: 25, y1: 44 },
    label_pos: { x: 10, y: 3.5 },
    cap: 24,
  },
  {
    id: "home",
    label: "Remote",
    asset: ASSET.house,
    sprite: { x: 89, y: 14, h: 19 },
    crowd: { cx: 89, x0: 79, x1: 98, y0: 26, y1: 44 },
    label_pos: { x: 89, y: 3.5 },
    cap: 24,
  },
  {
    id: "hq",
    label: "Taleemabad office",
    asset: ASSET.hq,
    sprite: { x: 50, y: 26, h: 32 },
    crowd: { cx: 50, x0: 26, x1: 74, y0: 45, y1: 79 },
    label_pos: { x: 50, y: 5 },
    cap: 60,
  },
  {
    id: "site-0",
    label: "Niete",
    asset: ASSET.officeSmall,
    sprite: { x: 14, y: 58, h: 32 },
    crowd: { cx: 14, x0: 4, x1: 24, y0: 76, y1: 92 },
    label_pos: { x: 14, y: 38 },
    cap: 18,
  },
  {
    id: "transit",
    label: "In transit / away briefly",
    asset: ASSET.bus,
    sprite: { x: 22, y: 89, h: 14 },
    crowd: { cx: 37, x0: 29, x1: 52, y0: 85, y1: 96 },
    label_pos: { x: 37, y: 81 },
    cap: 16,
  },
  {
    id: "camp",
    label: "Field visit",
    asset: ASSET.camp,
    sprite: { x: 89, y: 89, h: 14 },
    crowd: { cx: 74, x0: 60, x1: 82, y0: 85, y1: 96 },
    label_pos: { x: 74, y: 81 },
    cap: 14,
  },
]

const STATUS_TO_ZONE: Record<string, string> = {
  leave: "vacation",
  half_day: "vacation",
  leave_early: "vacation",
  remote: "home",
  office: "hq",
  back: "hq",
  late: "transit",
  partial_away: "transit",
  ooo: "transit",
  travel: "transit",
  limited: "transit",
  other: "transit",
  field_visit: "camp",
}

/** Zones whose people stay "inside" — click the building to see the roster. */
function isOfficeZone(id: string): boolean {
  return id === "hq" || id.startsWith("site-")
}

// --- tiny WebAudio sound kit (no audio assets) ---
let _audioCtx: AudioContext | null = null
let _muted = typeof localStorage !== "undefined" && localStorage.getItem("presence-muted") === "1"

export function presenceSoundMuted(): boolean {
  return _muted
}

export function setPresenceSoundMuted(muted: boolean): void {
  _muted = muted
  try {
    localStorage.setItem("presence-muted", muted ? "1" : "0")
  } catch {
    /* private mode */
  }
}

type SoundName = "open" | "close" | "pop"

function playSound(name: SoundName): void {
  if (_muted) return
  try {
    _audioCtx ??= new AudioContext()
    const ctx = _audioCtx
    if (ctx.state === "suspended") void ctx.resume()
    const t = ctx.currentTime
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)
    const [f0, f1, dur] =
      name === "open" ? [420, 760, 0.16] : name === "close" ? [620, 320, 0.14] : [520, 660, 0.09]
    osc.type = "sine"
    osc.frequency.setValueAtTime(f0, t)
    osc.frequency.exponentialRampToValueAtTime(f1, t + dur)
    gain.gain.setValueAtTime(0.0001, t)
    gain.gain.exponentialRampToValueAtTime(0.12, t + 0.02)
    gain.gain.exponentialRampToValueAtTime(0.0001, t + dur)
    osc.start(t)
    osc.stop(t + dur + 0.02)
  } catch {
    /* audio unavailable */
  }
}

function hash(str: string): number {
  let h = 5381
  for (let i = 0; i < str.length; i++) h = (h * 33) ^ str.charCodeAt(i)
  return Math.abs(h)
}

function firstName(name: string): string {
  return name.trim().split(/\s+/)[0] || name
}

function relativeTime(ts: string) {
  if (!ts) return ""
  const t = Date.parse(ts)
  if (Number.isNaN(t)) return ""
  const mins = Math.round((Date.now() - t) / 60_000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

interface ZoneBucket {
  zone: WorldZone
  label: string
  entries: PresenceEntry[]
}

/** Fixed landmark buildings: always on the map, even with nobody there.
 *  I10 IS the Taleemabad office, so loc-i10 folk join the HQ. */
const SITE_SLOTS: Record<string, { zoneId: string; label: string }> = {
  "loc-i10": { zoneId: "hq", label: "Taleemabad office" },
  "loc-niete": { zoneId: "site-0", label: "Niete" },
}

function buildWorld(clusters: BoardCluster[]): ZoneBucket[] {
  const buckets = new Map<string, ZoneBucket>()
  const zoneById = (id: string) => ZONES.find((z) => z.id === id)!

  buckets.set("hq", { zone: zoneById("hq"), label: "Taleemabad office", entries: [] })
  for (const { zoneId, label } of Object.values(SITE_SLOTS)) {
    buckets.set(zoneId, { zone: zoneById(zoneId), label, entries: [] })
  }

  for (const cluster of clusters) {
    let zoneId: string
    let label: string | null = null
    if (cluster.id.startsWith("loc-")) {
      const slot = SITE_SLOTS[cluster.id]
      // ponytail: only I10 and Niete get their own building; other sites join the HQ plaza
      zoneId = slot?.zoneId ?? "hq"
      label = slot?.label ?? null
    } else {
      zoneId = STATUS_TO_ZONE[cluster.id] ?? "transit"
    }
    const existing = buckets.get(zoneId)
    if (existing) {
      existing.entries.push(...cluster.entries)
      if (label) existing.label = label
    } else {
      const zone = zoneById(zoneId)
      buckets.set(zoneId, { zone, label: label ?? zone.label, entries: [...cluster.entries] })
    }
  }
  return Array.from(buckets.values())
}

interface TokenPos {
  x: number
  y: number
  row: number
}

/**
 * Crowd layout: centered rows that fan downward from the building,
 * like characters gathering in a game plaza. Later rows render in front.
 */
function crowdPositions(entries: PresenceEntry[], zone: WorldZone): TokenPos[] {
  const { cx, x0, x1, y0, y1 } = zone.crowd
  const n = entries.length
  if (n === 0) return []
  const width = x1 - x0
  const spacingX = 4.4
  const cols = Math.max(2, Math.floor(width / spacingX))
  const rows = Math.ceil(n / cols)
  const spacingY = Math.min((y1 - y0) / Math.max(rows - 1, 1), 7.5)

  return entries.map((entry, i) => {
    const row = Math.floor(i / cols)
    const inThisRow = row < rows - 1 || n % cols === 0 ? cols : n % cols
    const col = i - row * cols
    const hsh = hash(entry.user_id)
    const jx = (((hsh % 9) - 4) / 8) * spacingX * 0.45
    const jy = ((((hsh >> 4) % 9) - 4) / 8) * spacingY * 0.35
    const x = cx + (col - (inThisRow - 1) / 2) * spacingX + jx
    const y = rows === 1 ? (y0 + y1) / 2 : y0 + row * spacingY + jy
    return {
      x: Math.min(x1, Math.max(x0, x)),
      y: Math.min(y1, Math.max(y0, y)),
      row,
    }
  })
}

function TokenSprite({ entry, pos }: { entry: PresenceEntry; pos: TokenPos }) {
  const implied = entry.source === "implied"
  const ring = STATUS_RING[entry.status] ?? STATUS_RING.other
  const badge = STATUS_BADGE[entry.status]
  const bobDelay = (hash(entry.user_id) % 2600) / 1000

  return (
    <div
      className="group absolute -translate-x-1/2 -translate-y-1/2 hover:!z-40"
      style={{ left: `${pos.x}%`, top: `${pos.y}%`, zIndex: 10 + pos.row }}
    >
      <div className="presence-token flex flex-col items-center" style={{ animationDelay: `${bobDelay}s` }}>
        <div className="relative">
          {/* ground shadow */}
          <div className="absolute -bottom-1 left-1/2 h-1.5 w-6 -translate-x-1/2 rounded-full bg-emerald-950/25 blur-[2px]" />
          <div
            className={cn(
              "relative size-8 overflow-hidden rounded-full bg-white shadow-md ring-2 transition-transform duration-150 group-hover:scale-140 sm:size-9",
              ring,
              implied && "opacity-75 saturate-[0.65] group-hover:opacity-100 group-hover:saturate-100",
            )}
            tabIndex={0}
          >
            {entry.image ? (
              <img src={entry.image} alt="" loading="lazy" className="size-full object-cover" />
            ) : (
              <span className="flex size-full items-center justify-center bg-slate-200 text-[10px] font-bold text-slate-600">
                {initials(entry.name)}
              </span>
            )}
          </div>
          {badge ? (
            <span className="absolute -right-1.5 -bottom-1 z-10 flex size-4 items-center justify-center rounded-full bg-white text-[9px] shadow-sm">
              {badge}
            </span>
          ) : null}
        </div>
        <span className="mt-1 max-w-16 truncate rounded-full bg-white/85 px-1.5 py-px text-center text-[8.5px] leading-tight font-bold text-slate-700 shadow-sm">
          {firstName(entry.name)}
        </span>
      </div>

      <div className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 hidden -translate-x-1/2 group-hover:block">
        <ProfileCard entry={entry} />
      </div>
    </div>
  )
}

function ProfileCard({ entry }: { entry: PresenceEntry }) {
  const implied = entry.source === "implied"
  return (
    <div className="w-60 overflow-hidden rounded-xl border-2 border-amber-200 bg-white text-left shadow-xl">
      <div className="flex items-center gap-3 bg-gradient-to-r from-amber-50 to-orange-50 p-3">
        <div className={cn("size-14 shrink-0 overflow-hidden bg-white shadow ring-2", STATUS_RING[entry.status] ?? STATUS_RING.other)}>
          {entry.image ? (
            <img src={entry.image} alt="" className="size-full object-cover" />
          ) : (
            <span className="flex size-full items-center justify-center bg-slate-200 text-sm font-bold text-slate-600">
              {initials(entry.name)}
            </span>
          )}
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-bold text-slate-800">{entry.name}</p>
          <span
            className={cn(
              "mt-1 inline-block rounded-full px-2 py-0.5 text-[10px] font-bold",
              STATUS_CHIP[entry.status] ?? STATUS_CHIP.other,
            )}
          >
            {STATUS_BADGE[entry.status] ? `${STATUS_BADGE[entry.status]} ` : ""}
            {STATUS_LABEL[entry.status] ?? entry.status}
          </span>
        </div>
      </div>
      <div className="p-3">
        <p className="line-clamp-3 text-xs text-slate-600">{entry.note || entry.raw_text || "—"}</p>
        <div className="mt-2 flex items-center justify-between text-[10px] text-muted-foreground">
          <span>{relativeTime(entry.ts) || (implied ? "no post today" : "")}</span>
          <span className="uppercase opacity-70">{entry.source}</span>
        </div>
      </div>
    </div>
  )
}

function ZoneTokens({ bucket, expanded }: { bucket: ZoneBucket; expanded: boolean }) {
  const { zone } = bucket
  const shown = expanded ? bucket.entries : bucket.entries.slice(0, zone.cap)
  const positions = useMemo(() => crowdPositions(shown, zone), [shown, zone])

  return (
    <>
      {shown.map((entry, i) => (
        <TokenSprite key={`${entry.user_id}-${entry.message_ts}`} entry={entry} pos={positions[i]} />
      ))}
    </>
  )
}

function ZoneRosterPanel({ bucket, onClose }: { bucket: ZoneBucket; onClose: () => void }) {
  return (
    <>
      <button
        type="button"
        aria-label="Close roster"
        className="absolute inset-0 z-40 bg-emerald-950/20 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <div className="absolute top-1/2 left-1/2 z-50 flex max-h-[88%] w-80 max-w-[92%] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-2xl border-4 border-amber-200 bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-amber-100 bg-amber-50 px-4 py-2.5">
          <p className="text-sm font-extrabold text-amber-900">
            {bucket.label}
            <span className="ml-2 rounded-full bg-amber-200/80 px-2 py-0.5 text-[11px] text-amber-800">
              {bucket.entries.length}
            </span>
          </p>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full px-2 py-0.5 text-lg leading-none font-bold text-amber-700 transition-colors hover:bg-amber-200/60"
          >
            ×
          </button>
        </div>
        <div className="flex-1 divide-y divide-slate-100 overflow-y-auto">
          {bucket.entries.length === 0 ? (
            <p className="px-4 py-6 text-center text-xs text-muted-foreground">Nobody here today</p>
          ) : (
            bucket.entries.map((entry) => {
              const implied = entry.source === "implied"
              return (
                <div
                  key={`${entry.user_id}-${entry.message_ts}`}
                  className={cn(
                    "group/row flex items-center gap-2.5 px-4 py-2 transition-colors hover:bg-amber-50/60",
                    implied && "opacity-70 hover:opacity-100",
                  )}
                >
                  <div className={cn("size-8 shrink-0 overflow-hidden rounded-full bg-slate-200 ring-2 transition-transform group-hover/row:scale-125", STATUS_RING[entry.status] ?? STATUS_RING.other)}>
                    {entry.image ? (
                      <img src={entry.image} alt="" loading="lazy" className="size-full object-cover" />
                    ) : (
                      <span className="flex size-full items-center justify-center text-[10px] font-bold text-slate-600">
                        {initials(entry.name)}
                      </span>
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-semibold text-slate-800">{entry.name}</p>
                    <p className="truncate text-[10px] text-muted-foreground group-hover/row:whitespace-normal">
                      {entry.note || entry.raw_text || "—"}
                    </p>
                  </div>
                  <span className="shrink-0 text-[9px] text-muted-foreground">
                    {relativeTime(entry.ts)}
                  </span>
                </div>
              )
            })
          )}
        </div>
      </div>
    </>
  )
}

export function PresenceBoard({ entries }: { entries: PresenceEntry[] }) {
  const clusters = useMemo(() => buildClusters(entries), [entries])
  const world = useMemo(() => buildWorld(clusters), [clusters])
  const [expandedZones, setExpandedZones] = useState<Set<string>>(new Set())
  const [openZone, setOpenZone] = useState<string | null>(null)
  const [muted, setMuted] = useState(presenceSoundMuted)

  const openBucket = openZone ? world.find((b) => b.zone.id === openZone) : undefined

  const toggleMute = () => {
    const next = !muted
    setPresenceSoundMuted(next)
    setMuted(next)
    if (!next) playSound("pop")
  }

  const openRoster = (id: string) => {
    playSound("open")
    setOpenZone(id)
  }

  const closeRoster = () => {
    playSound("close")
    setOpenZone(null)
  }

  const toggleZone = (id: string) => {
    playSound("pop")
    setExpandedZones((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="relative w-full overflow-hidden rounded-3xl border border-border shadow-lg">
      <style>{`
        @keyframes presence-bob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-4px); } }
        .presence-token { animation: presence-bob 3.4s ease-in-out infinite; }
        @keyframes presence-cloud-a { 0% { transform: translateX(-20%); } 100% { transform: translateX(120%); } }
        @keyframes presence-cloud-b { 0% { transform: translateX(110%); } 100% { transform: translateX(-30%); } }
        .presence-cloud-a { animation: presence-cloud-a 90s linear infinite; }
        .presence-cloud-b { animation: presence-cloud-b 120s linear infinite; }
        @media (prefers-reduced-motion: reduce) {
          .presence-token, .presence-cloud-a, .presence-cloud-b { animation: none; }
        }
      `}</style>

      <div className="relative w-full" style={{ aspectRatio: "16 / 11", minHeight: 480 }}>
        {/* world ground */}
        <img
          src={ASSET.bg}
          alt=""
          className="absolute inset-0 size-full object-cover"
          draggable={false}
        />

        {/* drifting cloud shadows */}
        <div className="presence-cloud-a pointer-events-none absolute top-[8%] left-0 h-24 w-56 rounded-full bg-white/35 blur-2xl" />
        <div className="presence-cloud-b pointer-events-none absolute top-[55%] left-0 h-28 w-72 rounded-full bg-white/25 blur-3xl" />

        {/* buildings & props — office buildings open their roster on click */}
        {world.map(({ zone }) => {
          const clickable = isOfficeZone(zone.id)
          const img = (
            <img
              src={zone.asset}
              alt=""
              draggable={false}
              className="size-full object-contain drop-shadow-[0_8px_14px_rgba(30,60,30,0.3)]"
            />
          )
          const style = {
            left: `${zone.sprite.x}%`,
            top: `${zone.sprite.y}%`,
            height: `${zone.sprite.h}%`,
          }
          return clickable ? (
            <button
              key={`sprite-${zone.id}`}
              type="button"
              onClick={() => openRoster(zone.id)}
              className="absolute z-[5] -translate-x-1/2 -translate-y-1/2 cursor-pointer transition-transform duration-200 hover:scale-105 focus-visible:scale-105 focus-visible:outline-none"
              style={style}
            >
              {img}
            </button>
          ) : (
            <div key={`sprite-${zone.id}`} className="absolute z-[5] -translate-x-1/2 -translate-y-1/2" style={style}>
              {img}
            </div>
          )
        })}

        {/* zone name plates */}
        {world.map((bucket) => {
          const { zone } = bucket
          const office = isOfficeZone(zone.id)
          const overflow = office ? 0 : bucket.entries.length - zone.cap
          const expanded = expandedZones.has(zone.id)
          const Plate = office ? "button" : "span"
          return (
            <div
              key={`label-${zone.id}`}
              className="absolute z-30 flex -translate-x-1/2 items-center gap-1.5"
              style={{ left: `${zone.label_pos.x}%`, top: `${zone.label_pos.y}%` }}
            >
              <Plate
                {...(office ? { type: "button" as const, onClick: () => openRoster(zone.id) } : {})}
                className={cn(
                  "rounded-full border-2 border-amber-300/90 bg-amber-50/95 px-3 py-1 text-[11px] font-extrabold whitespace-nowrap text-amber-900 shadow-md",
                  office && "cursor-pointer transition-colors hover:bg-amber-100",
                )}
              >
                {bucket.label} <span className="ml-1 text-amber-600">×{bucket.entries.length}</span>
              </Plate>
              {overflow > 0 ? (
                <button
                  type="button"
                  onClick={() => toggleZone(zone.id)}
                  className="rounded-full border-2 border-amber-300/90 bg-white/95 px-2 py-1 text-[10px] font-bold text-amber-800 shadow-md transition-colors hover:bg-amber-100"
                >
                  {expanded ? "less" : `+${overflow}`}
                </button>
              ) : null}
            </div>
          )
        })}

        {/* people — office folk are "inside the building", everyone else on the map */}
        {world
          .filter((bucket) => !isOfficeZone(bucket.zone.id))
          .map((bucket) => (
            <ZoneTokens key={`tokens-${bucket.zone.id}`} bucket={bucket} expanded={expandedZones.has(bucket.zone.id)} />
          ))}

        {/* sound toggle */}
        <button
          type="button"
          onClick={toggleMute}
          aria-label={muted ? "Unmute sounds" : "Mute sounds"}
          className="absolute top-3 right-3 z-30 flex size-8 items-center justify-center rounded-full border-2 border-amber-300/90 bg-white/95 text-sm shadow-md transition-colors hover:bg-amber-100"
        >
          {muted ? "🔇" : "🔊"}
        </button>

        {/* soft edge vignette for depth */}
        <div className="pointer-events-none absolute inset-0 shadow-[inset_0_0_80px_rgba(40,80,40,0.18)]" />

        {openBucket ? <ZoneRosterPanel bucket={openBucket} onClose={closeRoster} /> : null}
      </div>
    </div>
  )
}
