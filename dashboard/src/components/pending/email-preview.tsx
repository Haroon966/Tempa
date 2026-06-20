type Props = { payload: Record<string, unknown> }

export function EmailPreview({ payload }: Props) {
  return (
    <div className="space-y-2 text-sm">
      <p>
        <span className="text-muted-foreground">To:</span> {String(payload.to ?? "")}
      </p>
      <p>
        <span className="text-muted-foreground">Subject:</span> {String(payload.subject ?? "")}
      </p>
      <pre className="max-h-48 overflow-auto rounded-md border border-border/60 bg-muted/30 p-3 whitespace-pre-wrap">
        {String(payload.body ?? payload.body_html ?? "")}
      </pre>
    </div>
  )
}
