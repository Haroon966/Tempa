import type { PresenceEntry, PresenceLocation, PresencePayload, PresenceStatus } from "@/lib/api"

export type ClusterFamily = "away" | "elsewhere" | "onsite"

export interface BoardCluster {
  id: string
  label: string
  family: ClusterFamily
  entries: PresenceEntry[]
}

const STATUS_CLUSTERS: { id: PresenceStatus; label: string; family: ClusterFamily }[] = [
  { id: "leave", label: "On leave", family: "away" },
  { id: "half_day", label: "Half day", family: "away" },
  { id: "leave_early", label: "Leave early", family: "away" },
  { id: "remote", label: "Remote", family: "elsewhere" },
  { id: "field_visit", label: "Field visit", family: "elsewhere" },
  { id: "travel", label: "Travel", family: "elsewhere" },
  { id: "limited", label: "Limited", family: "elsewhere" },
  { id: "late", label: "Late", family: "onsite" },
  { id: "partial_away", label: "Partial away", family: "onsite" },
  { id: "ooo", label: "Short OOO", family: "onsite" },
  { id: "back", label: "Back", family: "onsite" },
  { id: "office", label: "In office", family: "onsite" },
  { id: "other", label: "Other", family: "elsewhere" },
]

const LOCATION_LABEL: Record<PresenceLocation, string> = {
  i10: "I10",
  niete: "Niete",
  h9: "H9",
  rawalpindi: "Rawalpindi",
  moawin_hq: "Moawin HQ",
  other_site: "Other site",
}

const LOCATION_ORDER: PresenceLocation[] = ["i10", "h9", "niete", "rawalpindi", "moawin_hq", "other_site"]

export function flattenEntries(payload: PresencePayload): PresenceEntry[] {
  const seen = new Set<string>()
  const out: PresenceEntry[] = []
  for (const rows of Object.values(payload.groups)) {
    for (const entry of rows) {
      const key = `${entry.user_id}:${entry.message_ts}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push(entry)
    }
  }
  return out
}

export function buildClusters(entries: PresenceEntry[]): BoardCluster[] {
  // Location wins: entries with a named site go to a location cluster
  const byLocation = new Map<PresenceLocation, PresenceEntry[]>()
  const byStatus = new Map<PresenceStatus, PresenceEntry[]>()

  for (const entry of entries) {
    if (entry.location) {
      const list = byLocation.get(entry.location) ?? []
      list.push(entry)
      byLocation.set(entry.location, list)
    } else {
      const list = byStatus.get(entry.status) ?? []
      list.push(entry)
      byStatus.set(entry.status, list)
    }
  }

  const clusters: BoardCluster[] = []
  for (const def of STATUS_CLUSTERS) {
    const rows = byStatus.get(def.id) ?? []
    if (def.id === "office") {
      // Explicit posts first, implied members after so real updates stand out
      rows.sort((a, b) => Number(a.source === "implied") - Number(b.source === "implied"))
    }
    if (rows.length > 0) clusters.push({ id: def.id, label: def.label, family: def.family, entries: rows })
  }
  for (const loc of LOCATION_ORDER) {
    const rows = byLocation.get(loc)
    if (rows?.length) clusters.push({ id: `loc-${loc}`, label: LOCATION_LABEL[loc], family: "onsite", entries: rows })
  }

  const familyRank: Record<ClusterFamily, number> = { away: 0, elsewhere: 1, onsite: 2 }
  clusters.sort((a, b) => familyRank[a.family] - familyRank[b.family])
  return clusters
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return "?"
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

export const FAMILY_LABEL: Record<ClusterFamily, string> = {
  away: "Away",
  elsewhere: "Working elsewhere",
  onsite: "On site / delayed",
}
