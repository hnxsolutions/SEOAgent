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
import type { GeoAeoRecommendation, UUID } from '@/types/dashboard';

const allFilter = 'all';

export default function GeoAeoPage() {
  const queryClient = useQueryClient();
  const { projectId } = useDashboardProject();
  const [crawlId, setCrawlId] = useState<UUID>();
  const [statusFilter, setStatusFilter] = useState(allFilter);
  const [typeFilter, setTypeFilter] = useState(allFilter);
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
    queryKey: ['geo-summary', effectiveCrawlId],
    queryFn: () => dashboardApi.geoAeo.summary(effectiveCrawlId!),
    enabled: Boolean(effectiveCrawlId),
    retry: false,
  });

  const pagesQuery = useQuery({
    queryKey: ['crawl-pages', effectiveCrawlId],
    queryFn: () => dashboardApi.crawls.pages(effectiveCrawlId!),
    enabled: Boolean(effectiveCrawlId),
    retry: false,
  });

  const pageScoresQuery = useQuery({
    queryKey: ['geo-page-scores', effectiveCrawlId, pagesQuery.data?.map((page) => page.id).join(',')],
    queryFn: async () => {
      const pages = pagesQuery.data ?? [];
      const scores = await Promise.all(
        pages.slice(0, 25).map(async (page) => {
          try {
            return await dashboardApi.geoAeo.pageScore(page.id);
          } catch {
            return null;
          }
        })
      );
      return scores.filter(Boolean);
    },
    enabled: Boolean(effectiveCrawlId && pagesQuery.data?.length),
    retry: false,
  });

  const recommendationsQuery = useQuery({
    queryKey: ['geo-recommendations', effectiveCrawlId],
    queryFn: () => dashboardApi.geoAeo.recommendations(effectiveCrawlId!),
    enabled: Boolean(effectiveCrawlId),
    retry: false,
  });

  const actionMutation = useMutation({
    mutationFn: async ({ id, action }: { id: UUID; action: string }) => {
      setActionLoadingId(id);
      if (action === 'approve') return dashboardApi.geoAeo.approve(id);
      if (action === 'reject') return dashboardApi.geoAeo.reject(id);
      return dashboardApi.geoAeo.apply(id);
    },
    onSuccess: async () => {
      setNotice('GEO/AEO recommendation status updated.');
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['geo-summary', effectiveCrawlId] }),
        queryClient.invalidateQueries({ queryKey: ['geo-recommendations', effectiveCrawlId] }),
      ]);
    },
    onSettled: () => setActionLoadingId(undefined),
  });

  const recommendations = useMemo(() => {
    return (recommendationsQuery.data?.recommendations ?? []).filter((recommendation) => {
      return (
        (statusFilter === allFilter || recommendation.status === statusFilter) &&
        (typeFilter === allFilter || recommendation.recommendation_type === typeFilter)
      );
    });
  }, [recommendationsQuery.data?.recommendations, statusFilter, typeFilter]);

  const typeOptions = uniqueValues(
    recommendationsQuery.data?.recommendations.map((item) => item.recommendation_type)
  );

  if (!projectId) {
    return <EmptyState title="Select a project" description="GEO/AEO data is scoped to one project." />;
  }

  if (crawlsQuery.isLoading) return <LoadingBlock label="Loading crawls" />;

  if (!effectiveCrawlId) {
    return (
      <EmptyState
        title="No crawls found"
        description="Run a crawl and GEO/AEO analysis before using this console."
      />
    );
  }

  if (summaryQuery.isError) {
    return (
      <ErrorState
        title="GEO/AEO summary could not load"
        message="The selected crawl may not have GEO/AEO scoring results yet."
        onRetry={() => void summaryQuery.refetch()}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-normal text-slate-950">
            GEO/AEO Readiness
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Inspect AI-search page scores and review deterministic recommendations.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            void summaryQuery.refetch();
            void recommendationsQuery.refetch();
            void pageScoresQuery.refetch();
          }}
        >
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh
        </Button>
      </div>

      <ActionNotice message={notice} />

      <section className="grid gap-4 md:grid-cols-4">
        <SummaryBlock label="Avg GEO" value={Math.round(summaryQuery.data?.average_geo_score ?? 0)} />
        <SummaryBlock label="Avg AEO" value={Math.round(summaryQuery.data?.average_aeo_score ?? 0)} />
        <SummaryBlock
          label="Citation readiness"
          value={Math.round(summaryQuery.data?.average_citation_readiness_score ?? 0)}
        />
        <SummaryBlock label="Recommendations" value={summaryQuery.data?.total_recommendations ?? 0} />
      </section>

      <section className="flex flex-col gap-3 rounded-lg border bg-white p-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h3 className="text-base font-semibold text-slate-950">Crawl scope</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Page scores are loaded for the first 25 crawled pages.
          </p>
        </div>
        <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Crawl
          <select
            className="mt-1 h-9 min-w-72 rounded-md border bg-white px-2 text-sm normal-case tracking-normal text-slate-900 focus:outline-none focus:ring-2 focus:ring-ring"
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
      </section>

      <section className="rounded-lg border bg-white">
        <div className="border-b px-5 py-4">
          <h3 className="text-base font-semibold text-slate-950">Page score table</h3>
        </div>
        {pageScoresQuery.isLoading ? (
          <div className="p-5">
            <LoadingBlock label="Loading page scores" />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-border text-sm">
              <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-4 py-3">Page</th>
                  <th className="px-4 py-3">GEO</th>
                  <th className="px-4 py-3">AEO</th>
                  <th className="px-4 py-3">Citation</th>
                  <th className="px-4 py-3">Entity clarity</th>
                  <th className="px-4 py-3">Schema</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {(pageScoresQuery.data ?? []).map((score) => (
                  <tr key={score!.id}>
                    <td className="max-w-xl px-4 py-4">
                      <p className="truncate font-medium text-slate-950">{score!.url}</p>
                    </td>
                    <ScoreCell value={score!.geo_score} />
                    <ScoreCell value={score!.aeo_score} />
                    <ScoreCell value={score!.citation_readiness_score} />
                    <ScoreCell value={score!.entity_clarity_score} />
                    <ScoreCell value={score!.schema_readiness_score} />
                  </tr>
                ))}
                {!pageScoresQuery.data?.length ? (
                  <tr>
                    <td className="px-4 py-5 text-sm text-muted-foreground" colSpan={6}>
                      No page scores found for this crawl.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="space-y-4">
        <div className="flex flex-col gap-3 rounded-lg border bg-white p-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="text-base font-semibold text-slate-950">Recommendation queue</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Review AI-search readiness improvements before applying changes elsewhere.
            </p>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <FilterSelect label="Status" value={statusFilter} onChange={setStatusFilter} options={statusOptions} />
            <FilterSelect label="Type" value={typeFilter} onChange={setTypeFilter} options={typeOptions} />
          </div>
        </div>

        <RecommendationTable
          recommendations={recommendations}
          isLoading={recommendationsQuery.isLoading}
          actionLoadingId={actionLoadingId}
          onApprove={(id) => actionMutation.mutate({ id, action: 'approve' })}
          onReject={(id) => actionMutation.mutate({ id, action: 'reject' })}
          onApply={(id) => actionMutation.mutate({ id, action: 'apply' })}
        />
      </section>
    </div>
  );
}

function RecommendationTable({
  recommendations,
  isLoading,
  actionLoadingId,
  onApprove,
  onReject,
  onApply,
}: {
  recommendations: GeoAeoRecommendation[];
  isLoading?: boolean;
  actionLoadingId?: UUID;
  onApprove: (_id: UUID) => void;
  onReject: (_id: UUID) => void;
  onApply: (_id: UUID) => void;
}) {
  if (isLoading) return <LoadingBlock label="Loading recommendations" />;
  if (recommendations.length === 0) {
    return (
      <div className="rounded-lg border border-dashed bg-white p-8 text-center text-sm text-muted-foreground">
        No GEO/AEO recommendations match the current filters.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border bg-white">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-border text-sm">
          <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Recommendation</th>
              <th className="px-4 py-3">Type</th>
              <th className="px-4 py-3">Priority</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {recommendations.map((recommendation) => (
              <tr key={recommendation.id} className="align-top">
                <td className="max-w-2xl px-4 py-4">
                  <p className="font-medium text-slate-950">{recommendation.recommendation_text}</p>
                  <p className="mt-1 line-clamp-3 text-muted-foreground">{recommendation.reason}</p>
                </td>
                <td className="px-4 py-4 capitalize text-muted-foreground">
                  {formatLabel(recommendation.recommendation_type)}
                </td>
                <td className="px-4 py-4">
                  <PriorityBadge score={recommendation.priority_score} />
                  <p className="mt-1 text-xs text-muted-foreground">
                    {Math.round(recommendation.confidence_score)} confidence
                  </p>
                </td>
                <td className="px-4 py-4">
                  <StatusBadge status={recommendation.status} />
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
                      onClick={() => onApprove(recommendation.id)}
                      disabled={actionLoadingId === recommendation.id}
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
                      onClick={() => onReject(recommendation.id)}
                      disabled={actionLoadingId === recommendation.id}
                    >
                      <XCircle className="h-4 w-4" />
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => onApply(recommendation.id)}
                      disabled={actionLoadingId === recommendation.id}
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

function ScoreCell({ value }: { value: number }) {
  return (
    <td className="px-4 py-4">
      <span className="font-medium text-slate-950">{Math.round(value)}</span>
    </td>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (_value: string) => void;
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
            {formatLabel(option)}
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
