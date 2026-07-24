/**
 * Runnable check for dashboard pure helpers fixed from Bugbot findings.
 * Run: npx tsx scripts/selfcheck-dashboard-helpers.ts
 */
import assert from "node:assert/strict"
import { recentDoneJobs } from "../src/lib/qa-jobs.ts"
import { parseYoutubeVideoId } from "../src/lib/youtube.ts"
import { buildClusters, flattenEntries } from "../src/components/presence/presence-board-model.ts"
import type { PresenceEntry, PresencePayload } from "../src/lib/api.ts"

assert.equal(parseYoutubeVideoId("https://youtu.be/sBg6Ra_soEU"), "sBg6Ra_soEU")
assert.equal(parseYoutubeVideoId("https://www.youtube.com/watch?v=abcDEF12345"), "abcDEF12345")
assert.equal(parseYoutubeVideoId("abcDEF12345"), "abcDEF12345")
assert.equal(parseYoutubeVideoId(""), "")

const done = recentDoneJobs(
  [
    { status: "completed", id: "old", completed_at: "2026-01-01T00:00:00Z" },
    { status: "queued", id: "q", enqueued_at: "2026-07-01T00:00:00Z" },
    { status: "failed", id: "new", completed_at: "2026-07-20T00:00:00Z" },
    { status: "completed", id: "mid", completed_at: "2026-06-01T00:00:00Z" },
  ] as Array<{ status: string; id: string; completed_at?: string; enqueued_at?: string }>,
  2,
)
assert.deepEqual(
  done.map((j) => j.id),
  ["new", "mid"],
)

const entry = (over: Partial<PresenceEntry>): PresenceEntry =>
  ({
    user_id: "U1",
    name: "Ada",
    status: "office",
    location: "i10",
    message_ts: "1.0",
    ts: "2026-07-01T09:00:00Z",
    source: "slack",
    note: "",
    raw_text: "",
    ...over,
  }) as PresenceEntry

const payload = {
  groups: { office: [entry({})] },
  by_location: { i10: [entry({})] },
  counts: {},
} as unknown as PresencePayload

const flat = flattenEntries(payload)
assert.equal(flat.length, 1)
const clusters = buildClusters(flat)
assert.equal(clusters.filter((c) => c.entries.some((e) => e.user_id === "U1")).length, 1)

console.log("selfcheck-dashboard-helpers: ok")
