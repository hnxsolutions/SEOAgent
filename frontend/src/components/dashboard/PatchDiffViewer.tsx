import { FileCode2 } from 'lucide-react';
import { StatusBadge, formatLabel } from '@/components/dashboard/StatusBadge';
import type { SeoCodePatch } from '@/types/dashboard';
import { cn } from '@/lib/utils';

export function PatchDiffViewer({ patch }: { patch?: SeoCodePatch | null }) {
  if (!patch) {
    return (
      <div className="rounded-lg border border-dashed bg-white p-8 text-center text-sm text-muted-foreground">
        Select a patch to inspect the proposed diff.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border bg-white">
      <div className="flex flex-col gap-3 border-b bg-slate-50 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <FileCode2 className="h-4 w-4 text-slate-500" aria-hidden="true" />
            <p className="truncate text-sm font-semibold text-slate-950">{patch.file_path}</p>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {formatLabel(patch.patch_type)} - {formatLabel(patch.risk_level)} risk
          </p>
        </div>
        <StatusBadge status={patch.status} />
      </div>
      <div className="border-b px-4 py-3 text-sm text-slate-700">{patch.explanation}</div>
      <pre className="max-h-[520px] overflow-auto bg-slate-950 p-4 text-xs leading-6 text-slate-100">
        {patch.diff_text.split('\n').map((line, index) => (
          <code
            key={`${index}-${line}`}
            className={cn(
              'block whitespace-pre-wrap',
              line.startsWith('+') && 'text-emerald-300',
              line.startsWith('-') && 'text-rose-300',
              line.startsWith('@@') && 'text-sky-300'
            )}
          >
            {line || ' '}
          </code>
        ))}
      </pre>
    </div>
  );
}
