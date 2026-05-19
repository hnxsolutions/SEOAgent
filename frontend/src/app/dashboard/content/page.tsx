'use client';

import { CheckCircle2, RefreshCw, XCircle } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { ActionNotice, EmptyState, ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { PriorityBadge } from '@/components/dashboard/PriorityBadge';
import { StatusBadge, formatLabel } from '@/components/dashboard/StatusBadge';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi, latestCrawl } from '@/lib/dashboard-api';
import type { ContentSuggestion, UUID } from '@/types/dashboard';

const allFilter = 'all';

export default function ContentSuggestionsPage() {
  const queryClient = useQueryClient();
  const { projectId } = useDashboardProject();
  const [crawlId, setCrawlId] = useState<UUID>();
  const [statusFilter, setStatusFilter] = useState(allFilter);
  const [typeFilter, setTypeFilter] = useState(allFilter);
  const [pageFilter, setPageFilter] = useState(allFilter);
  const [notice, setNotice] = useState<string>();
  const [actionLoadingId, setActionLoadingId] = useState<UUID>();

  const crawlsQuery = useQuery({
    queryKey: ['crawls', projectId],
    queryFn: () => dashboardApi.crawls.list(projectId),
    enabled: Boolean(projectId),
    retry: false,
  });

  const effectiveCrawlId = crawlId ?? latestCrawl(crawlsQuery.data?.crawls)?.id;

  const summaryQuery = useQuery({
    queryKey: ['content-summary', effectiveCrawlId],
    queryFn: () => dashboardApi.content.summary(effectiveCrawlId!),
    enabled: Boolean(effectiveCrawlId),
    retry: false,
  });

  const suggestionsQuery = useQuery({
    queryKey: ['content-suggestions', effectiveCrawlId],
    queryFn: () => dashboardApi.content.suggestions(effectiveCrawlId!),
    enabled: Boolean(effectiveCrawlId),
    retry: false,
  });

  const actionMutation = useMutation({
    mutationFn: async ({ id, action }: { id: UUID; action: string }) => {
      setActionLoadingId(id);
      if (action === 'approve') return dashboardApi.content.approve(id);
      if (action === 'reject') return dashboardApi.content.reject(id);
      return dashboardApi.content.apply(id);
    },
    onSuccess: async () => {
      setNotice('Content suggestion status updated.');
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['content-summary', effectiveCrawlId] }),
        queryClient.invalidateQueries({ queryKey: ['content-suggestions', effectiveCrawlId] }),
      ]);
    },
    onSettled: () => setActionLoadingId(undefined),
  });

  const suggestions = useMemo(() => {
    return (suggestionsQuery.data?.suggestions ?? []).filter((suggestion) => {
      return (
        (statusFilter === allFilter || suggestion.status === statusFilter) &&
        (typeFilter === allFilter || suggestion.suggestion_type === typeFilter) &&
        (pageFilter === allFilter || suggestion.page_id === pageFilter)
      );
    });
  }, [pageFilter, statusFilter, suggestionsQuery.data?.suggestions, typeFilter]);

  const typeOptions = uniqueValues(
    suggestionsQuery.data?.suggestions.map((suggestion) => suggestion.suggestion_type)
  );
  const pageOptions = uniqueValues(
    suggestionsQuery.data?.suggestions.map((suggestion) => suggestion.page_id)
  );

  if (!projectId) {
    return <EmptyState title="Select a project" description="Content suggestions need a selected project." />;
  }

  if (crawlsQuery.isLoading) return <LoadingBlock label="Loading crawls" />;

  if (!effectiveCrawlId) {
    return (
      <EmptyState
        title="No crawls found"
        description="Run a crawl before reviewing content optimization suggestions."
      />
    );
  }

  if (suggestionsQuery.isError) {
    return (
      <ErrorState
        title="Content suggestions could not load"
        message="The selected crawl may not have content optimization results yet."
        onRetry={() => void suggestionsQuery.refetch()}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-normal text-slate-950">
            Content Suggestions
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Approve, reject, or mark local LLM content optimization suggestions as applied.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            void summaryQuery.refetch();
            void suggestionsQuery.refetch();
          }}
        >
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh
        </Button>
      </div>

      <ActionNotice message={notice} />

      <section className="grid gap-4 md:grid-cols-4">
        <SummaryBlock label="Suggestions" value={summaryQuery.data?.total_suggestions ?? 0} />
        <SummaryBlock label="Pages affected" value={summaryQuery.data?.pages_with_suggestions ?? 0} />
        <SummaryBlock
          label="Avg priority"
          value={Math.round(summaryQuery.data?.average_priority_score ?? 0)}
        />
        <SummaryBlock
          label="Avg confidence"
          value={Math.round(summaryQuery.data?.average_confidence_score ?? 0)}
        />
      </section>

      <section className="flex flex-col gap-3 rounded-lg border bg-white p-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h3 className="text-base font-semibold text-slate-950">Suggestion queue</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Current values and suggested values are kept review-only.
          </p>
        </div>
        <div className="grid gap-2 sm:grid-cols-4">
          <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Crawl
            <select
              className="mt-1 h-9 w-full rounded-md border bg-white px-2 text-sm normal-case tracking-normal text-slate-900 focus:outline-none focus:ring-2 focus:ring-ring"
              value={effectiveCrawlId}
              onChange={(event) => setCrawlId(event.target.value)}
            >
              {(crawlsQuery.data?.crawls ?? []).map((crawl) => (
                <option key={crawl.id} value={crawl.id}>
                  {crawl.url}
                </option>
              ))}
            </select>
          </label>
          <FilterSelect label="Status" value={statusFilter} onChange={setStatusFilter} options={statusOptions} />
          <FilterSelect label="Type" value={typeFilter} onChange={setTypeFilter} options={typeOptions} />
          <FilterSelect label="Page" value={pageFilter} onChange={setPageFilter} options={pageOptions} compact />
        </div>
      </section>

      <SuggestionTable
        suggestions={suggestions}
        isLoading={suggestionsQuery.isLoading}
        actionLoadingId={actionLoadingId}
        onApprove={(id) => actionMutation.mutate({ id, action: 'approve' })}
        onReject={(id) => actionMutation.mutate({ id, action: 'reject' })}
        onApply={(id) => actionMutation.mutate({ id, action: 'apply' })}
      />
    </div>
  );
}

function SuggestionTable({
  suggestions,
  isLoading,
  actionLoadingId,
  onApprove,
  onReject,
  onApply,
}: {
  suggestions: ContentSuggestion[];
  isLoading?: boolean;
  actionLoadingId?: UUID;
  onApprove: (_id: UUID) => void;
  onReject: (_id: UUID) => void;
  onApply: (_id: UUID) => void;
}) {
  if (isLoading) return <LoadingBlock label="Loading suggestions" />;
  if (suggestions.length === 0) {
    return (
      <div className="rounded-lg border border-dashed bg-white p-8 text-center text-sm text-muted-foreground">
        No content suggestions match the current filters.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border bg-white">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-border text-sm">
          <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Suggestion</th>
              <th className="px-4 py-3">Current</th>
              <th className="px-4 py-3">Suggested</th>
              <th className="px-4 py-3">Score</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {suggestions.map((suggestion) => (
              <tr key={suggestion.id} className="align-top">
                <td className="max-w-sm px-4 py-4">
                  <p className="font-medium capitalize text-slate-950">
                    {formatLabel(suggestion.suggestion_type)}
                  </p>
                  <p className="mt-1 line-clamp-3 text-sm text-muted-foreground">
                    {suggestion.reason}
                  </p>
                </td>
                <td className="max-w-md px-4 py-4 text-muted-foreground">
                  <p className="line-clamp-4">{suggestion.current_value || 'No current value'}</p>
                </td>
                <td className="max-w-md px-4 py-4 text-slate-800">
                  <p className="line-clamp-5">{suggestion.suggested_value}</p>
                </td>
                <td className="px-4 py-4">
                  <PriorityBadge score={suggestion.priority_score} />
                  <p className="mt-1 text-xs text-muted-foreground">
                    {Math.round(suggestion.confidence_score)} confidence
                  </p>
                </td>
                <td className="px-4 py-4">
                  <StatusBadge status={suggestion.status} />
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
                      onClick={() => onApprove(suggestion.id)}
                      disabled={actionLoadingId === suggestion.id}
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
                      onClick={() => onReject(suggestion.id)}
                      disabled={actionLoadingId === suggestion.id}
                    >
                      <XCircle className="h-4 w-4" />
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => onApply(suggestion.id)}
                      disabled={actionLoadingId === suggestion.id}
                    >
                      Applied
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

function SummaryBlock({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border bg-white p-4">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-2 text-3xl font-semibold">{value.toLocaleString()}</p>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
  compact,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (_value: string) => void;
  compact?: boolean;
}) {
  return (
    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
      {label}
      <select
        className="mt-1 h-9 w-full rounded-md border bg-white px-2 text-sm normal-case tracking-normal text-slate-900 focus:outline-none focus:ring-2 focus:ring-ring"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value={allFilter}>All</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {compact ? option.slice(0, 8) : formatLabel(option)}
          </option>
        ))}
      </select>
    </label>
  );
}

function uniqueValues(values?: string[]) {
  return Array.from(new Set(values ?? [])).sort();
}

const statusOptions = ['suggested', 'approved', 'rejected', 'applied'];
