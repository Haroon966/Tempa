/** Match tempa.meet.notify._youtube_video_id — derive embed id from common URL forms. */
export function parseYoutubeVideoId(urlOrId: string | null | undefined): string {
  const raw = (urlOrId || "").trim()
  if (!raw) return ""
  if (/^[A-Za-z0-9_-]{6,}$/.test(raw) && !raw.includes("/") && !raw.includes(".")) return raw
  const patterns = [
    /(?:youtube\.com\/watch\?[^#]*v=|youtube\.com\/embed\/|youtube\.com\/live\/|youtu\.be\/)([A-Za-z0-9_-]{6,})/,
    /youtube\.com\/shorts\/([A-Za-z0-9_-]{6,})/,
  ]
  for (const pattern of patterns) {
    const match = raw.match(pattern)
    if (match?.[1]) return match[1]
  }
  return ""
}
