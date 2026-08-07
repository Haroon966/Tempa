/** Google Calendar–style day timeline layout math. */

export const HOUR_HEIGHT_PX = 56
export const DAY_START_HOUR = 0
export const DAY_END_HOUR = 24
export const GRID_HOURS = DAY_END_HOUR - DAY_START_HOUR
export const GRID_HEIGHT_PX = GRID_HOURS * HOUR_HEIGHT_PX

export function minutesFromGridStart(date: Date, dayStart: Date): number {
  return (date.getTime() - dayStart.getTime()) / 60_000
}

export function eventBlockPosition(
  start: Date,
  end: Date,
  dayStart: Date,
  hourHeight = HOUR_HEIGHT_PX,
): { top: number; height: number } {
  const gridStartMin = DAY_START_HOUR * 60
  const gridEndMin = DAY_END_HOUR * 60
  let startMin = minutesFromGridStart(start, dayStart)
  let endMin = minutesFromGridStart(end, dayStart)
  startMin = Math.max(gridStartMin, Math.min(gridEndMin, startMin))
  endMin = Math.max(gridStartMin, Math.min(gridEndMin, endMin))
  if (endMin <= startMin) endMin = Math.min(gridEndMin, startMin + 15)
  const top = ((startMin - gridStartMin) / 60) * hourHeight
  const height = Math.max(((endMin - startMin) / 60) * hourHeight, hourHeight * 0.35)
  return { top, height }
}

export type TimedEvent = { id: string; startMs: number; endMs: number }

/** Assign overlap columns (GCal-style stacking). */
export function assignOverlapColumns<T extends TimedEvent>(
  events: T[],
): Map<string, { column: number; columnCount: number }> {
  const sorted = [...events].sort((a, b) => a.startMs - b.startMs || a.endMs - b.endMs)
  const result = new Map<string, { column: number; columnCount: number }>()
  type Active = { id: string; endMs: number; column: number }
  let active: Active[] = []
  let cluster: Active[] = []
  let clusterMaxCol = 0

  const flushCluster = () => {
    const count = clusterMaxCol + 1
    for (const item of cluster) {
      result.set(item.id, { column: item.column, columnCount: count })
    }
    cluster = []
    clusterMaxCol = 0
  }

  for (const ev of sorted) {
    active = active.filter((a) => a.endMs > ev.startMs)
    if (active.length === 0 && cluster.length > 0) flushCluster()
    const used = new Set(active.map((a) => a.column))
    let column = 0
    while (used.has(column)) column += 1
    const entry = { id: ev.id, endMs: ev.endMs, column }
    active.push(entry)
    cluster.push(entry)
    clusterMaxCol = Math.max(clusterMaxCol, column)
  }
  if (cluster.length > 0) flushCluster()
  return result
}

/** Throws if layout math drifts — call from UI or a check entrypoint. */
export function runDayTimelineSelfCheck(): void {
  const dayStart = new Date(2026, 7, 7, 0, 0, 0, 0) // Aug 7 local
  const nine = new Date(2026, 7, 7, 9, 0, 0, 0)
  const tenThirty = new Date(2026, 7, 7, 10, 30, 0, 0)
  const { top, height } = eventBlockPosition(nine, tenThirty, dayStart, 56)
  if (top !== 9 * 56) throw new Error(`expected top ${9 * 56}, got ${top}`)
  if (height !== 1.5 * 56) throw new Error(`expected height ${1.5 * 56}, got ${height}`)

  const cols = assignOverlapColumns([
    { id: "a", startMs: 0, endMs: 60 },
    { id: "b", startMs: 30, endMs: 90 },
    { id: "c", startMs: 100, endMs: 120 },
  ])
  if (cols.get("a")?.columnCount !== 2 || cols.get("b")?.columnCount !== 2) {
    throw new Error("overlap cluster a/b should share columnCount 2")
  }
  if (cols.get("c")?.columnCount !== 1) {
    throw new Error("non-overlapping c should be columnCount 1")
  }
}

if (import.meta.env?.DEV) {
  runDayTimelineSelfCheck()
}
