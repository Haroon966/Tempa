type Props = { type: string; payload: Record<string, unknown> }

export function FileOpPreview({ type, payload }: Props) {
  const op = type.replace("pc_", "")
  return (
    <div className="space-y-2 text-sm">
      <p>
        <span className="text-muted-foreground">Operation:</span> {op}
      </p>
      <p>
        <span className="text-muted-foreground">Path:</span>{" "}
        <code className="text-xs">{String(payload.path ?? "")}</code>
      </p>
      {payload.content ? (
        <pre className="max-h-40 overflow-auto rounded-md border border-border/60 bg-muted/30 p-3 whitespace-pre-wrap">
          {String(payload.content).slice(0, 2000)}
        </pre>
      ) : null}
    </div>
  )
}
