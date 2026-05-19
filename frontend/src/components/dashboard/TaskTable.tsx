'use client';

import { CheckCircle2, Clock3, Eye, XCircle } from 'lucide-react';
import type React from 'react';
import { Button } from '@/components/ui/button';
import { PriorityBadge } from '@/components/dashboard/PriorityBadge';
import { StatusBadge, formatLabel } from '@/components/dashboard/StatusBadge';
import type { PlannerTask, UUID } from '@/types/dashboard';
import { formatDate } from '@/lib/utils';

export function TaskTable({
  tasks,
  isLoading,
  actionLoadingId,
  onApprove,
  onReject,
  onProgress,
  onComplete,
  onSelect,
}: {
  tasks: PlannerTask[];
  isLoading?: boolean;
  actionLoadingId?: UUID;
  onApprove?: (_taskId: UUID) => void;
  onReject?: (_taskId: UUID) => void;
  onProgress?: (_taskId: UUID) => void;
  onComplete?: (_taskId: UUID) => void;
  onSelect?: (_task: PlannerTask) => void;
}) {
  if (isLoading) {
    return <TableShell rows={6} />;
  }

  if (tasks.length === 0) {
    return (
      <div className="rounded-lg border border-dashed bg-white p-8 text-center text-sm text-muted-foreground">
        No SEO tasks match the current filters.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border bg-white">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-border text-sm">
          <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Task</th>
              <th className="px-4 py-3">Priority</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Source</th>
              <th className="px-4 py-3">Due</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {tasks.map((task) => (
              <tr key={task.id} className="align-top">
                <td className="max-w-xl px-4 py-4">
                  <button
                    type="button"
                    className="text-left font-medium text-slate-950 hover:text-blue-700"
                    onClick={() => onSelect?.(task)}
                  >
                    {task.title}
                  </button>
                  <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
                    {task.description}
                  </p>
                  {task.target_page_url ? (
                    <p className="mt-2 truncate text-xs text-slate-500">
                      {task.target_page_url}
                    </p>
                  ) : null}
                </td>
                <td className="px-4 py-4">
                  <PriorityBadge priority={task.priority} />
                  <p className="mt-1 text-xs text-muted-foreground">
                    {Math.round(task.priority_score)}
                  </p>
                </td>
                <td className="px-4 py-4">
                  <StatusBadge status={task.status} />
                </td>
                <td className="px-4 py-4 text-muted-foreground">
                  <p className="font-medium capitalize text-slate-700">
                    {formatLabel(task.task_type)}
                  </p>
                  <p className="mt-1 text-xs capitalize">{formatLabel(task.source_type)}</p>
                </td>
                <td className="px-4 py-4 text-muted-foreground">
                  {task.due_date ? formatDate(task.due_date) : 'No date'}
                </td>
                <td className="px-4 py-4">
                  <div className="flex justify-end gap-2">
                    <IconAction
                      label="View task"
                      icon={<Eye className="h-4 w-4" />}
                      onClick={() => onSelect?.(task)}
                    />
                    <IconAction
                      label="Approve"
                      icon={<CheckCircle2 className="h-4 w-4" />}
                      onClick={() => onApprove?.(task.id)}
                      disabled={!onApprove || actionLoadingId === task.id}
                    />
                    <IconAction
                      label="Reject"
                      icon={<XCircle className="h-4 w-4" />}
                      onClick={() => onReject?.(task.id)}
                      disabled={!onReject || actionLoadingId === task.id}
                    />
                    <IconAction
                      label="In progress"
                      icon={<Clock3 className="h-4 w-4" />}
                      onClick={() => onProgress?.(task.id)}
                      disabled={!onProgress || actionLoadingId === task.id}
                    />
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => onComplete?.(task.id)}
                      disabled={!onComplete || actionLoadingId === task.id}
                    >
                      Complete
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function IconAction({
  label,
  icon,
  onClick,
  disabled,
}: {
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <Button
      type="button"
      size="icon"
      variant="outline"
      className="h-8 w-8"
      title={label}
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
    >
      {icon}
    </Button>
  );
}

function TableShell({ rows }: { rows: number }) {
  return (
    <div className="overflow-hidden rounded-lg border bg-white">
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="flex items-center gap-4 border-b p-4 last:border-b-0">
          <div className="h-10 flex-1 animate-pulse rounded bg-slate-100" />
          <div className="h-8 w-24 animate-pulse rounded bg-slate-100" />
          <div className="h-8 w-28 animate-pulse rounded bg-slate-100" />
        </div>
      ))}
    </div>
  );
}
