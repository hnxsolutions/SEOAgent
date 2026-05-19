import { cn } from '@/lib/utils';

const statusStyles: Record<string, string> = {
  completed: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  applied: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  approved: 'border-blue-200 bg-blue-50 text-blue-700',
  running: 'border-sky-200 bg-sky-50 text-sky-700',
  queued: 'border-slate-200 bg-slate-50 text-slate-700',
  suggested: 'border-amber-200 bg-amber-50 text-amber-700',
  proposed: 'border-amber-200 bg-amber-50 text-amber-700',
  todo: 'border-amber-200 bg-amber-50 text-amber-700',
  draft: 'border-slate-200 bg-slate-50 text-slate-700',
  in_progress: 'border-sky-200 bg-sky-50 text-sky-700',
  rejected: 'border-rose-200 bg-rose-50 text-rose-700',
  failed: 'border-rose-200 bg-rose-50 text-rose-700',
  cancelled: 'border-rose-200 bg-rose-50 text-rose-700',
  skipped: 'border-zinc-200 bg-zinc-50 text-zinc-700',
  open: 'border-orange-200 bg-orange-50 text-orange-700',
};

export function formatLabel(value?: string | null) {
  if (!value) return 'Unavailable';
  return value.replace(/_/g, ' ');
}

export function StatusBadge({
  status,
  className,
}: {
  status?: string | null;
  className?: string;
}) {
  const normalized = status?.toLowerCase() ?? 'unknown';
  return (
    <span
      className={cn(
        'inline-flex h-6 items-center rounded-full border px-2 text-xs font-medium capitalize',
        statusStyles[normalized] ?? 'border-slate-200 bg-slate-50 text-slate-700',
        className
      )}
    >
      {formatLabel(status)}
    </span>
  );
}
