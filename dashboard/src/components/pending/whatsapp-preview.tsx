type Props = { payload: Record<string, unknown> }

export function WhatsAppPreview({ payload }: Props) {
  return (
    <div className="space-y-2 text-sm">
      <p>
        <span className="text-muted-foreground">To:</span> {String(payload.number ?? "")}
      </p>
      {payload.media_path ? (
        <p>
          <span className="text-muted-foreground">Media:</span> {String(payload.media_path)}
        </p>
      ) : null}
      <pre className="max-h-40 overflow-auto rounded-md border border-border/60 bg-muted/30 p-3 whitespace-pre-wrap">
        {String(payload.text ?? "")}
      </pre>
    </div>
  )
}
