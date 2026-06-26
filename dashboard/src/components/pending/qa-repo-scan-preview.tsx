import { Badge } from "@/components/ui/badge"

type QaRepoScanPayload = {
  repo?: string
  branch?: string | null
  pr_number?: number | null
  add_to_allowlist?: boolean
  source_channel?: string
}

export function QaRepoScanPreview({ payload }: { payload: QaRepoScanPayload }) {
  return (
    <div className="flex flex-col gap-2 text-sm">
      <p>
        <span className="font-medium">Repository:</span> <code>{payload.repo}</code>
      </p>
      {payload.branch && (
        <p>
          <span className="font-medium">Branch:</span> <code>{payload.branch}</code>
        </p>
      )}
      {payload.pr_number != null && (
        <p>
          <span className="font-medium">Pull request:</span> #{payload.pr_number}
        </p>
      )}
      {payload.add_to_allowlist && (
        <Badge variant="outline" className="w-fit border-amber-300 bg-amber-50 text-amber-800">
          Adds repo to allowlist on approval
        </Badge>
      )}
      <p className="text-muted-foreground">
        Approving will add this repo (if new) and queue a QA scan. Results appear in the QA dashboard.
      </p>
    </div>
  )
}
