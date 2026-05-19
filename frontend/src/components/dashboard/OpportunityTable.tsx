'use client';

import { CheckCircle2, XCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { PriorityBadge } from '@/components/dashboard/PriorityBadge';
import { StatusBadge, formatLabel } from '@/components/dashboard/StatusBadge';
import type { SearchConsoleOpportunity, UUID } from '@/types/dashboard';

export function OpportunityTable({
  opportunities,
  isLoading,
  actionLoadingId,
  onApprove,
  onReject,
  onComplete,
}: {
  opportunities: SearchConsoleOpportunity[];
  isLoading?: boolean;
  actionLoadingId?: UUID;
  onApprove?: (_id: UUID) => void;
  onReject?: (_id: UUID) => void;
  onComplete?: (_id: UUID) => void;
}) {
  if (isLoading) {
    return (
      <div className="rounded-lg border bg-white p-4">
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, index) => (
            <div key={index} className="h-12 animate-pulse rounded bg-slate-100" />
          ))}
        </div>
      </div>
    );
  }

  if (opportunities.length === 0) {
    return (
      <div className="rounded-lg border border-dashed bg-white p-8 text-center text-sm text-muted-foreground">
        No Search Console opportunities match the current filters.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border bg-white">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-border text-sm">
          <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Query and page</th>
              <th className="px-4 py-3">Type</th>
              <th className="px-4 py-3">Current</th>
              <th className="px-4 py-3">Priority</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {opportunities.map((opportunity) => (
              <tr key={opportunity.id} className="align-top">
                <td className="max-w-xl px-4 py-4">
                  <p className="font-medium text-slate-950">{opportunity.query}</p>
                  <p className="mt-1 truncate text-xs text-muted-foreground">
                    {opportunity.page_url}
                  </p>
                  <p className="mt-2 line-clamp-2 text-sm text-slate-600">
                    {opportunity.recommended_action}
                  </p>
                </td>
                <td className="px-4 py-4 capitalize text-muted-foreground">
                  {formatLabel(opportunity.opportunity_type)}
                </td>
                <td className="px-4 py-4 text-muted-foreground">
                  <p>{opportunity.current_impressions.toLocaleString()} impressions</p>
                  <p>{opportunity.current_clicks.toLocaleString()} clicks</p>
                  <p>CTR {(opportunity.current_ctr * 100).toFixed(1)}%</p>
                  <p>Pos {opportunity.current_position.toFixed(1)}</p>
                </td>
                <td className="px-4 py-4">
                  <PriorityBadge score={opportunity.priority_score} />
                  <p className="mt-1 text-xs text-muted-foreground">
                    {Math.round(opportunity.priority_score)}
                  </p>
                </td>
                <td className="px-4 py-4">
                  <StatusBadge status={opportunity.status} />
                </td>
                <td className="px-4 py-4">
                  <div className="flex justify-end gap-2">
                    <Button
                      type="button"
                      size="icon"
                      variant="outline"
                      className="h-8 w-8"
                      title="Approve"
                      aria-label="Approve"
                      onClick={() => onApprove?.(opportunity.id)}
                      disabled={!onApprove || actionLoadingId === opportunity.id}
                    >
                      <CheckCircle2 className="h-4 w-4" />
                    </Button>
                    <Button
                      type="button"
                      size="icon"
                      variant="outline"
                      className="h-8 w-8"
                      title="Reject"
                      aria-label="Reject"
                      onClick={() => onReject?.(opportunity.id)}
                      disabled={!onReject || actionLoadingId === opportunity.id}
                    >
                      <XCircle className="h-4 w-4" />
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => onComplete?.(opportunity.id)}
                      disabled={!onComplete || actionLoadingId === opportunity.id}
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
