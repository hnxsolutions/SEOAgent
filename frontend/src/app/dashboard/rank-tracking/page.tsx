'use client';

import { RefreshCw } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { formatLabel } from '@/components/dashboard/StatusBadge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { dashboardApi } from '@/lib/dashboard-api';
import type { RankTrackingRow } from '@/types/dashboard';

const tabs = [
  { label: 'Top keywords', movement: undefined, sort: 'highest_impressions' },
  { label: 'Improved', movement: 'improved', sort: 'improved' },
  { label: 'Dropped', movement: 'dropped', sort: 'dropped' },
  { label: 'Striking distance', movement: 'striking_distance', sort: 'position' },
  { label: 'Low CTR', movement: 'low_ctr', sort: 'highest_impressions' },
];

export default function RankTrackingPage() {
  const { projectId } = useDashboardProject();
  const [activeTab, setActiveTab] = useState(0);
  const [query, setQuery] = useState('');
  const [pageUrl, setPageUrl] = useState('');
  const [device, setDevice] = useState('');
  const [country, setCountry] = useState('');

  const selectedTab = tabs[activeTab] ?? tabs[0];
  const params = useMemo(
    () => ({
      movement: selectedTab.movement,
      sort: selectedTab.sort,
      query: query || undefined,
      page_url: pageUrl || undefined,
      device: device || undefined,
      country: country || undefined,
      comparison_window: 'last_28_days',
    }),
    [country, device, pageUrl, query, selectedTab.movement, selectedTab.sort]
  );

  const summaryQuery = useQuery({
    queryKey: ['rank-tracking-summary', projectId],
    queryFn: () => dashboardApi.rankTracking.summary(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const rankingsQuery = useQuery({
    queryKey: ['rank-tracking-rankings', projectId, params],
    queryFn: () => dashboardApi.rankTracking.rankings(projectId!, params),
    enabled: Boolean(projectId),
    retry: false,
  });

  if (!projectId) {
    return <EmptyState title="Select a project" description="Rank tracking is scoped to one project." />;
  }

  if (summaryQuery.isLoading || rankingsQuery.isLoading) {
    return <LoadingBlock label="Loading rank tracking" />;
  }

  if (summaryQuery.isError || rankingsQuery.isError) {
    return (
      <ErrorState
        title="Rank tracking could not load"
        message="Check that the backend is running and that Search Console rows exist for this project."
        onRetry={() => {
          void summaryQuery.refetch();
          void rankingsQuery.refetch();
        }}
      />
    );
  }

  const rows = rankingsQuery.data?.rankings ?? [];
  const summary = summaryQuery.data;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-normal text-slate-950">
            Rank Tracking
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            GSC average-position tracking by keyword and page. CSV imports feed the same view.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            void summaryQuery.refetch();
            void rankingsQuery.refetch();
          }}
        >
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh
        </Button>
      </div>

      <section className="grid gap-4 md:grid-cols-4">
        <MetricCard label="Keywords" value={summary?.total_keywords ?? 0} />
        <MetricCard label="Average position" value={formatNumber(summary?.average_position)} />
        <MetricCard label="Impressions" value={formatInteger(summary?.total_impressions)} />
        <MetricCard label="Average CTR" value={formatPercent(summary?.average_ctr)} />
      </section>

      <section className="rounded-lg border bg-white">
        <div className="border-b px-5 py-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h3 className="text-base font-semibold text-slate-950">Keyword and page movement</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                Lower average position is better; negative position delta means an improvement.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {tabs.map((tab, index) => (
                <button
                  key={tab.label}
                  type="button"
                  className={`h-9 rounded-md border px-3 text-sm font-medium ${
                    activeTab === index
                      ? 'border-blue-200 bg-blue-50 text-blue-700'
                      : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                  }`}
                  onClick={() => setActiveTab(index)}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Filter query"
            />
            <Input
              value={pageUrl}
              onChange={(event) => setPageUrl(event.target.value)}
              placeholder="Filter page URL"
            />
            <Input
              value={country}
              onChange={(event) => setCountry(event.target.value)}
              placeholder="Country"
            />
            <select
              className="h-10 rounded-md border bg-white px-3 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
              value={device}
              onChange={(event) => setDevice(event.target.value)}
              aria-label="Filter by device"
            >
              <option value="">All devices</option>
              <option value="desktop">Desktop</option>
              <option value="mobile">Mobile</option>
              <option value="tablet">Tablet</option>
            </select>
          </div>
        </div>

        {rows.length === 0 ? (
          <div className="p-5">
            <EmptyState
              title="No ranking rows"
              description={summary?.message ?? 'Connect GSC OAuth or upload CSV.'}
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-5 py-3 font-medium">Query</th>
                  <th className="px-5 py-3 font-medium">Page</th>
                  <th className="px-5 py-3 font-medium">Position</th>
                  <th className="px-5 py-3 font-medium">Previous</th>
                  <th className="px-5 py-3 font-medium">Change</th>
                  <th className="px-5 py-3 font-medium">Clicks</th>
                  <th className="px-5 py-3 font-medium">Impressions</th>
                  <th className="px-5 py-3 font-medium">CTR</th>
                  <th className="px-5 py-3 font-medium">Device</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {rows.map((row) => (
                  <RankRow key={`${row.query}-${row.page_url}-${row.device ?? ''}-${row.country ?? ''}`} row={row} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function RankRow({ row }: { row: RankTrackingRow }) {
  return (
    <tr className="align-top">
      <td className="max-w-xs px-5 py-4 font-medium text-slate-950">{row.query}</td>
      <td className="max-w-md px-5 py-4 text-slate-600">
        <span className="break-all">{row.page_url}</span>
      </td>
      <td className="px-5 py-4 text-slate-950">{formatNumber(row.current_position)}</td>
      <td className="px-5 py-4 text-slate-600">{formatNumber(row.previous_position)}</td>
      <td className="px-5 py-4">
        <span className={row.position_delta < 0 ? 'text-emerald-700' : row.position_delta > 0 ? 'text-rose-700' : 'text-slate-600'}>
          {formatDelta(row.position_delta)}
        </span>
      </td>
      <td className="px-5 py-4 text-slate-600">
        {formatInteger(row.current_clicks)}
        <span className="ml-1 text-xs text-muted-foreground">({formatSignedInteger(row.clicks_delta)})</span>
      </td>
      <td className="px-5 py-4 text-slate-600">
        {formatInteger(row.current_impressions)}
        <span className="ml-1 text-xs text-muted-foreground">({formatSignedInteger(row.impressions_delta)})</span>
      </td>
      <td className="px-5 py-4 text-slate-600">
        {formatPercent(row.current_ctr)}
        <span className="ml-1 text-xs text-muted-foreground">({formatDelta(row.ctr_delta * 100)} pts)</span>
      </td>
      <td className="px-5 py-4 text-slate-600">
        {formatLabel(row.device)}
        {row.country ? <span className="block text-xs text-muted-foreground">{row.country}</span> : null}
      </td>
    </tr>
  );
}

function MetricCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border bg-white p-4">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-slate-950">{value}</p>
    </div>
  );
}

function formatNumber(value?: number | null) {
  return typeof value === 'number' ? value.toFixed(1) : '0.0';
}

function formatInteger(value?: number | null) {
  return new Intl.NumberFormat('en-US').format(value ?? 0);
}

function formatPercent(value?: number | null) {
  return `${((value ?? 0) * 100).toFixed(2)}%`;
}

function formatDelta(value: number) {
  if (value > 0) return `+${value.toFixed(2)}`;
  return value.toFixed(2);
}

function formatSignedInteger(value: number) {
  if (value > 0) return `+${formatInteger(value)}`;
  return formatInteger(value);
}
