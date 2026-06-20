import { useEffect, useId, useRef, useState } from "react"
import mermaid from "mermaid"

let mermaidReady = false

function ensureMermaid() {
  if (mermaidReady) return
  mermaid.initialize({
    startOnLoad: false,
    theme: "neutral",
    securityLevel: "strict",
    fontFamily: "inherit",
  })
  mermaidReady = true
}

export function MermaidBlock({
  chart,
  isComplete = true,
}: {
  chart: string
  isComplete?: boolean
}) {
  const id = useId().replace(/:/g, "")
  const containerRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [svg, setSvg] = useState<string | null>(null)

  useEffect(() => {
    if (!isComplete || !chart.trim()) {
      setSvg(null)
      setError(null)
      return
    }

    let cancelled = false
    const timer = window.setTimeout(async () => {
      try {
        ensureMermaid()
        const { svg: rendered } = await mermaid.render(`mermaid-${id}`, chart.trim())
        if (!cancelled) {
          setSvg(rendered)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) {
          setSvg(null)
          setError(err instanceof Error ? err.message : String(err))
        }
      }
    }, 200)

    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [chart, id, isComplete])

  if (!isComplete) {
    return (
      <pre className="overflow-x-auto rounded-lg border border-border bg-muted/50 p-3 text-xs text-muted-foreground">
        {chart}
      </pre>
    )
  }

  if (error) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
        <p className="text-xs font-medium text-amber-800">Mermaid render failed</p>
        <pre className="mt-2 overflow-x-auto text-xs text-amber-900">{chart}</pre>
      </div>
    )
  }

  if (!svg) {
    return (
      <div className="flex h-24 items-center justify-center rounded-lg border border-border bg-muted/30 text-xs text-muted-foreground">
        Rendering diagram…
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className="overflow-x-auto rounded-lg border border-border bg-card p-4 [&_svg]:mx-auto"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}
