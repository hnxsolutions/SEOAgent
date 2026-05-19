import { cn } from '@/lib/utils';
import { formatLabel } from '@/components/dashboard/StatusBadge';

const priorityStyles: Record<string, string> = {
  critical: 'border-red-200 bg-red-50 text-red-700',
  high: 'border-orange-200 bg-orange-50 text-orange-700',
  medium: 'border-amber-200 bg-amber-50 text-amber-700',
  low: 'border-slate-200 bg-slate-50 text-slate-700',
};

export function PriorityBadge({
  priority,
  score,
  className,
}: {
  priority?: string | null;
  score?: number;
  className?: string;
}) {
  const normalized = priority?.toLowerCase() ?? scoreToPriority(score);
  return (
    <span
      className={cn(
        'inline-flex h-6 items-center rounded-full border px-2 text-xs font-semibold capitalize',
        priorityStyles[normalized] ?? priorityStyles.low,
        className
      )}
    >
      {formatLabel(priority ?? normalized)}
    </span>
  );
}

function scoreToPriority(score?: number) {
  if (score === undefined) return 'low';
  if (score >= 85) return 'critical';
  if (score >= 70) return 'high';
  if (score >= 40) return 'medium';
  return 'low';
}
