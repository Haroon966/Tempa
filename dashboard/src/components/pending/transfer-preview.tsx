type Props = { payload: Record<string, unknown> }

export function TransferPreview({ payload }: Props) {
  return (
    <div className="space-y-2 text-sm">
      <p>
        <span className="text-muted-foreground">File:</span> {String(payload.filename ?? payload.path ?? "")}
      </p>
      <p className="text-muted-foreground">
        After approval, a QR code and download link will be generated for your phone on the same WiFi
        network.
      </p>
    </div>
  )
}
