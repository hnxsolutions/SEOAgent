'use client';

import { AlertTriangle, ExternalLink, Play, RefreshCw, Save, Unplug } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { ActionNotice, EmptyState, ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { OpportunityTable } from '@/components/dashboard/OpportunityTable';
import { StatusBadge, formatLabel } from '@/components/dashboard/StatusBadge';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi } from '@/lib/dashboard-api';
import { extractApiError } from '@/lib/api';
import { formatDateTime } from '@/lib/utils';
import type { UUID } from '@/types/dashboard';

const allFilter = 'all';

export default function SearchConsolePage() {
  const queryClient = useQueryClient();
  const { projectId } = useDashboardProject();
  const [statusFilter, setStatusFilter] = useState(allFilter);
  const [typeFilter, setTypeFilter] = useState(allFilter);
  const [priorityFilter, setPriorityFilter] = useState(allFilter);
  const [notice, setNotice] = useState<string>();
  const [actionLoadingId, setActionLoadingId] = useState<UUID>();
  const [selectedPropertyId, setSelectedPropertyId] = useState('');
  const [monitorEnabled, setMonitorEnabled] = useState(false);
  const [frequencyDays, setFrequencyDays] = useState<1 | 2 | 3>(1);
  const [lookbackDays, setLookbackDays] = useState(28);
  const [syncQueries, setSyncQueries] = useState(true);
  const [syncPages, setSyncPages] = useState(true);
  const [syncPairs, setSyncPairs] = useState(true);
  const [syncCountryDevice, setSyncCountryDevice] = useState(true);

  const summaryQuery = useQuery({
    queryKey: ['gsc-summary', projectId],
    queryFn: () => dashboardApi.searchConsole.summary(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const connectionsQuery = useQuery({
    queryKey: ['gsc-connections'],
    queryFn: dashboardApi.searchConsole.connections,
    enabled: Boolean(projectId),
    retry: false,
  });

  const propertiesQuery = useQuery({
    queryKey: ['gsc-properties', projectId],
    queryFn: () => dashboardApi.searchConsole.properties(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const selectedPropertyQuery = useQuery({
    queryKey: ['gsc-selected-property', projectId],
    queryFn: () => dashboardApi.searchConsole.selectedProperty(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const syncJobsQuery = useQuery({
    queryKey: ['gsc-sync-jobs', projectId],
    queryFn: () => dashboardApi.searchConsole.syncJobs(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const importsQuery = useQuery({
    queryKey: ['gsc-imports', projectId],
    queryFn: () => dashboardApi.searchConsole.imports(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const latestImport = importsQuery.data?.imports[0];
  const opportunitiesQuery = useQuery({
    queryKey: ['gsc-opportunities', latestImport?.id],
    queryFn: () => dashboardApi.searchConsole.opportunities(latestImport!.id),
    enabled: Boolean(latestImport?.id),
    retry: false,
  });

  const selectedProperty =
    selectedPropertyQuery.data?.selected_property ??
    propertiesQuery.data?.properties.find((property) => property.is_selected);
  const monitorSetting = selectedPropertyQuery.data?.monitor_setting ?? summaryQuery.data?.monitor_setting;
  const unhealthyConnection = (connectionsQuery.data?.connections ?? []).find((connection) =>
    ['expired', 'failed', 'revoked'].includes(String(connection.status).toLowerCase())
  );

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const gscStatus = params.get('gsc');
    if (gscStatus === 'connected') {
      setNotice('Google Search Console connected.');
    }
    if (gscStatus === 'error') {
      setNotice(params.get('message') ?? 'Google Search Console connection failed.');
    }
  }, []);

  useEffect(() => {
    setSelectedPropertyId(selectedProperty?.id ?? '');
  }, [selectedProperty?.id]);

  useEffect(() => {
    if (!monitorSetting) return;
    setMonitorEnabled(Boolean(monitorSetting.enabled));
    setFrequencyDays((monitorSetting.frequency_days === 2 || monitorSetting.frequency_days === 3 ? monitorSetting.frequency_days : 1) as 1 | 2 | 3);
    setLookbackDays(monitorSetting.lookback_days ?? 28);
    setSyncQueries(Boolean(monitorSetting.sync_queries));
    setSyncPages(Boolean(monitorSetting.sync_pages));
    setSyncPairs(Boolean(monitorSetting.sync_query_page_pairs));
    setSyncCountryDevice(Boolean(monitorSetting.sync_country_device));
  }, [monitorSetting]);

  const startOAuthMutation = useMutation({
    mutationFn: dashboardApi.searchConsole.startOAuth,
    onSuccess: (response) => {
      window.location.href = response.authorization_url;
    },
    onError: (error) => {
      setNotice(error instanceof Error ? error.message : 'Google OAuth is not configured.');
    },
  });

  const disconnectMutation = useMutation({
    mutationFn: dashboardApi.searchConsole.disconnect,
    onSuccess: async () => {
      setNotice('Search Console connection revoked locally.');
      await invalidateSearchConsole(projectId, queryClient);
    },
  });

  const selectPropertyMutation = useMutation({
    mutationFn: (propertyId: UUID) => dashboardApi.searchConsole.selectProperty(projectId!, propertyId),
    onSuccess: async () => {
      setNotice('Search Console property selected.');
      await invalidateSearchConsole(projectId, queryClient);
    },
  });

  const monitorMutation = useMutation({
    mutationFn: () =>
      dashboardApi.searchConsole.updateMonitor(projectId!, {
        property_id: selectedPropertyId || undefined,
        enabled: monitorEnabled,
        frequency_days: frequencyDays,
        lookback_days: lookbackDays,
        sync_queries: syncQueries,
        sync_pages: syncPages,
        sync_query_page_pairs: syncPairs,
        sync_country_device: syncCountryDevice,
      }),
    onSuccess: async (setting) => {
      setNotice(setting.enabled ? 'Automatic Search Console monitor saved.' : 'Search Console monitor disabled.');
      await invalidateSearchConsole(projectId, queryClient);
    },
    onError: (error) => {
      setNotice(error instanceof Error ? error.message : 'Monitor settings could not be saved.');
    },
  });

  const syncMutation = useMutation({
    mutationFn: () => dashboardApi.searchConsole.sync(projectId!),
    onSuccess: async (job) => {
      setNotice(`Manual sync ${job.status}; fetched ${job.rows_fetched} rows.`);
      await invalidateSearchConsole(projectId, queryClient);
    },
  });

  const actionMutation = useMutation({
    mutationFn: async ({ id, action }: { id: UUID; action: string }) => {
      setActionLoadingId(id);
      if (action === 'approve') return dashboardApi.searchConsole.approve(id);
      if (action === 'reject') return dashboardApi.searchConsole.reject(id);
      return dashboardApi.searchConsole.complete(id);
    },
    onSuccess: async () => {
      setNotice('Opportunity status updated.');
      await invalidateSearchConsole(projectId, queryClient);
    },
    onSettled: () => setActionLoadingId(undefined),
  });

  const opportunities = useMemo(() => {
    const source = opportunitiesQuery.data?.opportunities ?? summaryQuery.data?.top_opportunities ?? [];
    return source.filter((opportunity) => {
      return (
        (statusFilter === allFilter || opportunity.status === statusFilter) &&
        (typeFilter === allFilter || opportunity.opportunity_type === typeFilter) &&
        (priorityFilter === allFilter || scoreBucket(opportunity.priority_score) === priorityFilter)
      );
    });
  }, [
    opportunitiesQuery.data?.opportunities,
    priorityFilter,
    statusFilter,
    summaryQuery.data?.top_opportunities,
    typeFilter,
  ]);

  const typeOptions = Object.keys(summaryQuery.data?.opportunities_by_type ?? {}).sort();

  if (!projectId) {
    return <EmptyState title="Select a project" description="Search Console data is scoped to one project." />;
  }

  if (summaryQuery.isLoading || syncJobsQuery.isLoading || importsQuery.isLoading) {
    return <LoadingBlock label="Loading Search Console" />;
  }

  if (summaryQuery.isError) {
    return (
      <ErrorState
        title="Search Console summary could not load"
        message="The API may be unavailable or this project may not have Search Console data yet."
        onRetry={() => void summaryQuery.refetch()}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-normal text-slate-950">
            Search Console Opportunities
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Monitor GSC syncs and approve ranking, CTR, and content opportunities.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => startOAuthMutation.mutate()}
            disabled={startOAuthMutation.isPending || propertiesQuery.data?.oauth_enabled === false}
          >
            <ExternalLink className="mr-2 h-4 w-4" />
            Connect Google
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              void invalidateSearchConsole(projectId, queryClient);
            }}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
          <Button
            type="button"
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
          >
            <Play className="mr-2 h-4 w-4" />
            Manual sync
          </Button>
        </div>
      </div>

      <ActionNotice message={notice} />
      {unhealthyConnection ? (
        <div className="flex gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-none" />
          <div>
            <p className="font-medium">Search Console connection needs attention.</p>
            <p className="mt-1">
              The Google connection is {formatLabel(unhealthyConnection.status)}. Reconnect Google before scheduled sync can import fresh data.
            </p>
          </div>
        </div>
      ) : null}

      <section className="grid gap-4 md:grid-cols-5">
        <SummaryBlock label="Clicks" value={summaryQuery.data?.clicks ?? 0} />
        <SummaryBlock label="Impressions" value={summaryQuery.data?.impressions ?? 0} />
        <SummaryBlock label="Rows imported" value={summaryQuery.data?.rows_count ?? 0} />
        <SummaryBlock label="Opportunities" value={summaryQuery.data?.opportunities_count ?? 0} />
        <div className="rounded-lg border bg-white p-4">
          <p className="text-sm text-muted-foreground">Latest sync</p>
          <div className="mt-3">
            <StatusBadge status={summaryQuery.data?.latest_sync_status} />
          </div>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[0.75fr_1.25fr]">
        <div className="rounded-lg border bg-white">
          <div className="border-b px-5 py-4">
            <h3 className="text-base font-semibold text-slate-950">Connection</h3>
          </div>
          <div className="space-y-4 p-5 text-sm">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-muted-foreground">OAuth</p>
                <p className="mt-1 font-medium text-slate-950">
                  {propertiesQuery.data?.oauth_enabled ? 'Configured' : 'Not configured'}
                </p>
              </div>
              <Button
                type="button"
                size="sm"
                onClick={() => startOAuthMutation.mutate()}
                disabled={startOAuthMutation.isPending || propertiesQuery.data?.oauth_enabled === false}
              >
                <ExternalLink className="mr-2 h-4 w-4" />
                Connect
              </Button>
            </div>

            <div className="space-y-2">
              {(connectionsQuery.data?.connections ?? []).map((connection) => (
                <div key={connection.id} className="flex items-center justify-between gap-3 rounded-md border bg-slate-50 px-3 py-2">
                  <div>
                    <StatusBadge status={connection.status} />
                    <p className="mt-1 text-xs text-muted-foreground">
                      {formatDateTime(connection.updated_at ?? connection.created_at)}
                    </p>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => disconnectMutation.mutate(connection.id)}
                    disabled={disconnectMutation.isPending}
                  >
                    <Unplug className="mr-2 h-4 w-4" />
                    Revoke
                  </Button>
                </div>
              ))}
              {!connectionsQuery.data?.connections.length ? (
                <p className="rounded-md border border-dashed bg-white px-3 py-3 text-sm text-muted-foreground">
                  No OAuth connection stored.
                </p>
              ) : null}
            </div>

            <label className="block text-sm font-medium text-slate-700">
              Selected property
              <select
                className="mt-1 h-10 w-full rounded-md border bg-white px-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-ring"
                value={selectedPropertyId}
                onChange={(event) => setSelectedPropertyId(event.target.value)}
              >
                <option value="">Select property</option>
                {(propertiesQuery.data?.properties ?? []).map((property) => (
                  <option key={property.id} value={property.id}>
                    {property.site_url}
                  </option>
                ))}
              </select>
            </label>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => selectedPropertyId && selectPropertyMutation.mutate(selectedPropertyId)}
              disabled={!selectedPropertyId || selectPropertyMutation.isPending}
            >
              Save selected property
            </Button>

            <div>
              <p className="text-muted-foreground">Latest import</p>
              <p className="mt-1 font-medium text-slate-950">
                {latestImport
                  ? `${formatLabel(latestImport.source_type)} - ${latestImport.rows_imported} rows`
                  : 'No imports yet'}
              </p>
            </div>
          </div>
        </div>

        <div className="rounded-lg border bg-white">
          <div className="border-b px-5 py-4">
            <h3 className="text-base font-semibold text-slate-950">Sync job history</h3>
          </div>
          <div className="divide-y">
            {(syncJobsQuery.data?.sync_jobs ?? []).slice(0, 8).map((job) => (
              <div key={job.id} className="flex flex-col gap-2 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-medium text-slate-950">
                    {formatLabel(job.comparison_window)}
                  </p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {job.rows_fetched} rows, {job.opportunities_created} created,{' '}
                    {job.opportunities_updated} updated
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-muted-foreground">
                    {formatDateTime(job.created_at)}
                  </span>
                  <StatusBadge status={job.status} />
                </div>
              </div>
            ))}
            {!syncJobsQuery.data?.sync_jobs.length ? (
              <div className="p-5 text-sm text-muted-foreground">No sync jobs yet.</div>
            ) : null}
          </div>
        </div>
      </section>

      <section className="rounded-lg border bg-white">
        <div className="flex flex-col gap-3 border-b px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="text-base font-semibold text-slate-950">Automatic monitor</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Scheduled sync uses the official Search Console API and finalized data ending three days ago.
            </p>
          </div>
          <StatusBadge status={monitorSetting?.enabled ? 'enabled' : 'disabled'} />
        </div>
        <div className="grid gap-4 p-5 lg:grid-cols-[0.85fr_1.15fr]">
          <div className="space-y-4">
            <label className="flex items-center gap-3 text-sm font-medium text-slate-800">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-slate-300"
                checked={monitorEnabled}
                onChange={(event) => setMonitorEnabled(event.target.checked)}
              />
              Enable automatic sync
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="text-sm font-medium text-slate-700">
                Frequency
                <select
                  className="mt-1 h-10 w-full rounded-md border bg-white px-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-ring"
                  value={frequencyDays}
                  onChange={(event) => setFrequencyDays(Number(event.target.value) as 1 | 2 | 3)}
                >
                  <option value={1}>Every day</option>
                  <option value={2}>Every 2 days</option>
                  <option value={3}>Every 3 days</option>
                </select>
              </label>
              <label className="text-sm font-medium text-slate-700">
                Lookback days
                <input
                  type="number"
                  min={1}
                  max={90}
                  className="mt-1 h-10 w-full rounded-md border bg-white px-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-ring"
                  value={lookbackDays}
                  onChange={(event) => setLookbackDays(Math.max(1, Math.min(90, Number(event.target.value) || 1)))}
                />
              </label>
            </div>
            <Button
              type="button"
              onClick={() => monitorMutation.mutate()}
              disabled={monitorMutation.isPending || !selectedPropertyId}
            >
              <Save className="mr-2 h-4 w-4" />
              Save monitor
            </Button>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <MonitorToggle label="Queries" checked={syncQueries} onChange={setSyncQueries} />
            <MonitorToggle label="Pages" checked={syncPages} onChange={setSyncPages} />
            <MonitorToggle label="Query + page + date" checked={syncPairs} onChange={setSyncPairs} />
            <MonitorToggle label="Device + country" checked={syncCountryDevice} onChange={setSyncCountryDevice} />
            <MonitorFact label="Last scheduled" value={monitorSetting?.last_scheduled_at ? formatDateTime(monitorSetting.last_scheduled_at) : 'Not scheduled'} />
            <MonitorFact label="Next sync" value={monitorSetting?.next_sync_at ? formatDateTime(monitorSetting.next_sync_at) : 'Not scheduled'} />
            <MonitorFact label="Property last synced" value={selectedProperty?.last_synced_at ? formatDateTime(selectedProperty.last_synced_at) : 'Not synced'} />
          </div>
        </div>
      </section>

      <SitemapsPanel projectId={projectId} />

      <IndexQueuePanel projectId={projectId} />

      <section className="space-y-4">
        <div className="flex flex-col gap-3 rounded-lg border bg-white p-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="text-base font-semibold text-slate-950">Opportunity queue</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Uses the latest import when available, otherwise shows top summary opportunities.
            </p>
          </div>
          <div className="grid gap-2 sm:grid-cols-3">
            <FilterSelect label="Status" value={statusFilter} onChange={setStatusFilter} options={statusOptions} />
            <FilterSelect label="Type" value={typeFilter} onChange={setTypeFilter} options={typeOptions} />
            <FilterSelect label="Priority" value={priorityFilter} onChange={setPriorityFilter} options={priorityOptions} />
          </div>
        </div>

        <OpportunityTable
          opportunities={opportunities}
          isLoading={opportunitiesQuery.isLoading}
          actionLoadingId={actionLoadingId}
          onApprove={(id) => actionMutation.mutate({ id, action: 'approve' })}
          onReject={(id) => actionMutation.mutate({ id, action: 'reject' })}
          onComplete={(id) => actionMutation.mutate({ id, action: 'complete' })}
        />
      </section>
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

function SitemapsPanel({ projectId }: { projectId?: UUID }) {
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<string>();
  const [error, setError] = useState<string>();
  const [submitUrl, setSubmitUrl] = useState('');

  const sitemapsQuery = useQuery({
    queryKey: ['gsc-sitemaps', projectId],
    queryFn: () => dashboardApi.sitemaps.list(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const issuesQuery = useQuery({
    queryKey: ['gsc-sitemap-issues', projectId],
    queryFn: () => dashboardApi.sitemaps.issues(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const oauthEnabled = sitemapsQuery.data?.oauth_enabled ?? false;
  const sitemaps = sitemapsQuery.data?.sitemaps ?? [];
  const issues = issuesQuery.data?.issues ?? [];

  const refetchAll = async () => {
    await queryClient.invalidateQueries({ queryKey: ['gsc-sitemaps', projectId] });
    await queryClient.invalidateQueries({ queryKey: ['gsc-sitemap-issues', projectId] });
  };

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setNotice(undefined);
    setError(undefined);
    try {
      await fn();
      await refetchAll();
      setNotice(label);
    } catch (err) {
      setError(extractApiError(err, `${label} failed.`));
    }
  };

  const detectMutation = useMutation({
    mutationFn: () => dashboardApi.sitemaps.detect(projectId!),
  });
  const analyzeMutation = useMutation({
    mutationFn: () => dashboardApi.sitemaps.analyze(projectId!),
  });
  const submitMutation = useMutation({
    mutationFn: (url: string) => dashboardApi.sitemaps.submit(projectId!, url),
  });

  return (
    <section className="space-y-4">
      <div className="flex flex-col gap-3 rounded-lg border bg-white p-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h3 className="text-base font-semibold text-slate-950">Sitemaps</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Detect sitemaps from robots.txt and common paths, analyze them against the latest crawl, and
            {oauthEnabled ? ' submit/list them via the official Search Console Sitemaps API.' : ' (submit/list needs a connected Google account).'}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={!projectId || detectMutation.isPending}
            onClick={() => run('Sitemaps detected.', () => detectMutation.mutateAsync())}
          >
            {detectMutation.isPending ? 'Detecting…' : 'Detect'}
          </Button>
          <Button
            type="button"
            disabled={!projectId || analyzeMutation.isPending}
            onClick={() => run('Sitemaps analyzed.', () => analyzeMutation.mutateAsync())}
          >
            {analyzeMutation.isPending ? 'Analyzing…' : 'Analyze'}
          </Button>
        </div>
      </div>

      <ActionNotice message={notice} />
      <ActionNotice message={error} tone="error" />

      {oauthEnabled ? (
        <div className="flex flex-col gap-2 rounded-lg border bg-white p-4 sm:flex-row sm:items-center">
          <input
            value={submitUrl}
            onChange={(event) => setSubmitUrl(event.target.value)}
            placeholder="https://example.com/sitemap.xml"
            className="h-9 w-full rounded-md border px-3 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <Button
            type="button"
            disabled={!submitUrl.trim() || submitMutation.isPending}
            onClick={() =>
              run('Sitemap submitted to Search Console.', async () => {
                await submitMutation.mutateAsync(submitUrl.trim());
                setSubmitUrl('');
              })
            }
          >
            {submitMutation.isPending ? 'Submitting…' : 'Submit to GSC'}
          </Button>
        </div>
      ) : (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Submitting or listing sitemaps via the Sitemaps API needs a connected Google Search Console account with
          the write scope. Detection and analysis below work without Google credentials.
        </div>
      )}

      <div className="overflow-hidden rounded-lg border bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-2">Sitemap</th>
              <th className="px-4 py-2">Source</th>
              <th className="px-4 py-2">URLs</th>
              <th className="px-4 py-2">Errors</th>
              <th className="px-4 py-2">Warnings</th>
              <th className="px-4 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {sitemapsQuery.isLoading ? (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-muted-foreground">Loading sitemaps…</td>
              </tr>
            ) : sitemaps.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-muted-foreground">
                  No sitemaps yet. Click Detect to discover sitemaps from robots.txt and common paths.
                </td>
              </tr>
            ) : (
              sitemaps.map((sitemap) => (
                <tr key={sitemap.id} className="border-t">
                  <td className="max-w-[320px] truncate px-4 py-2" title={sitemap.sitemap_url}>
                    {sitemap.sitemap_url}
                    {sitemap.is_sitemaps_index ? (
                      <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">index</span>
                    ) : null}
                  </td>
                  <td className="px-4 py-2">{formatLabel(sitemap.source)}</td>
                  <td className="px-4 py-2">{sitemap.submitted_urls_count.toLocaleString()}</td>
                  <td className="px-4 py-2">{sitemap.errors_count}</td>
                  <td className="px-4 py-2">{sitemap.warnings_count}</td>
                  <td className="px-4 py-2"><StatusBadge status={sitemap.status} /></td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {issues.length > 0 ? (
        <div className="rounded-lg border bg-white">
          <div className="border-b px-4 py-3">
            <h4 className="text-sm font-semibold text-slate-950">Sitemap issues ({issues.length})</h4>
            <p className="mt-1 text-xs text-muted-foreground">
              Live crawl checks are labelled as such and reflect what our crawler observed, not Google index status.
            </p>
          </div>
          <ul className="divide-y">
            {issues.map((issue) => (
              <li key={issue.id} className="px-4 py-3">
                <div className="flex items-center gap-2">
                  <StatusBadge status={issue.severity} />
                  <span className="text-sm font-medium text-slate-900">{issue.title}</span>
                </div>
                <p className="mt-1 text-sm text-muted-foreground">{issue.description}</p>
                <p className="mt-1 text-sm text-slate-700">Recommended: {issue.recommended_action}</p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function IndexQueuePanel({ projectId }: { projectId?: UUID }) {
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<string>();
  const [error, setError] = useState<string>();

  const summaryQuery = useQuery({
    queryKey: ['index-queue-summary', projectId],
    queryFn: () => dashboardApi.indexQueue.summary(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const queueQuery = useQuery({
    queryKey: ['index-queue', projectId],
    queryFn: () => dashboardApi.indexQueue.queue(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const summary = summaryQuery.data;
  const items = queueQuery.data?.items ?? [];

  const refetchAll = async () => {
    await queryClient.invalidateQueries({ queryKey: ['index-queue-summary', projectId] });
    await queryClient.invalidateQueries({ queryKey: ['index-queue', projectId] });
  };

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setNotice(undefined);
    setError(undefined);
    try {
      await fn();
      await refetchAll();
      setNotice(label);
    } catch (err) {
      setError(extractApiError(err, `${label} failed.`));
    }
  };

  const discoverMutation = useMutation({ mutationFn: () => dashboardApi.indexQueue.discover(projectId!) });
  const approveAllMutation = useMutation({ mutationFn: () => dashboardApi.indexQueue.approveAll(projectId!) });
  const submitMutation = useMutation({ mutationFn: () => dashboardApi.indexQueue.submit(projectId!) });
  const rowMutation = useMutation({
    mutationFn: ({ id, action }: { id: UUID; action: 'approve' | 'reject' }) =>
      action === 'approve' ? dashboardApi.indexQueue.approve(id) : dashboardApi.indexQueue.reject(id),
  });

  return (
    <section className="space-y-4">
      <div className="flex flex-col gap-3 rounded-lg border bg-white p-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h3 className="text-base font-semibold text-slate-950">Auto Index Queue</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Discover indexable URLs from the latest crawl and blog drafts, approve them, then submit via the official
            Search Console Sitemaps API. Google offers no per-URL indexing API for general pages, so submission
            (re)submits your sitemap and is credential-gated on a connected Google account.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={!projectId || discoverMutation.isPending}
            onClick={() => run('URLs discovered.', () => discoverMutation.mutateAsync())}
          >
            {discoverMutation.isPending ? 'Discovering…' : 'Discover'}
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={!projectId || approveAllMutation.isPending}
            onClick={() => run('Eligible URLs approved.', () => approveAllMutation.mutateAsync())}
          >
            {approveAllMutation.isPending ? 'Approving…' : 'Approve all eligible'}
          </Button>
          <Button
            type="button"
            disabled={!projectId || submitMutation.isPending}
            onClick={() =>
              run('Submit requested.', async () => {
                const result = await submitMutation.mutateAsync();
                if (result.status === 'submitted') {
                  setNotice(`Sitemap submitted to Search Console (${result.submitted} URLs marked submitted).`);
                } else if (result.status === 'nothing_to_submit') {
                  setNotice('Nothing to submit — approve URLs first.');
                } else {
                  setError(result.note || result.error || 'Submission is not available yet.');
                }
              })
            }
          >
            {submitMutation.isPending ? 'Submitting…' : 'Submit via sitemap'}
          </Button>
        </div>
      </div>

      <ActionNotice message={notice} />
      <ActionNotice message={error} tone="error" />

      <section className="grid gap-4 sm:grid-cols-4">
        <SummaryBlock label="Pending" value={summary?.pending ?? 0} />
        <SummaryBlock label="Approved" value={summary?.approved ?? 0} />
        <SummaryBlock label="Submitted" value={summary?.submitted ?? 0} />
        <SummaryBlock label="Total" value={summary?.total ?? 0} />
      </section>

      <div className="overflow-hidden rounded-lg border bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-2">URL</th>
              <th className="px-4 py-2">Source</th>
              <th className="px-4 py-2">Eligible</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {queueQuery.isLoading ? (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-muted-foreground">Loading queue…</td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-muted-foreground">
                  No URLs yet. Click Discover to pull indexable URLs from the latest crawl and blog drafts.
                </td>
              </tr>
            ) : (
              items.map((item) => (
                <tr key={item.id} className="border-t">
                  <td className="max-w-[320px] truncate px-4 py-2" title={item.reason || item.url}>
                    {item.url}
                    {item.reason ? (
                      <span className="ml-2 text-xs text-amber-700">({item.reason})</span>
                    ) : null}
                  </td>
                  <td className="px-4 py-2">{formatLabel(item.source)}</td>
                  <td className="px-4 py-2">{item.eligible ? 'Yes' : 'No'}</td>
                  <td className="px-4 py-2"><StatusBadge status={item.status} /></td>
                  <td className="px-4 py-2">
                    <div className="flex justify-end gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={!item.eligible || item.status === 'approved' || rowMutation.isPending}
                        onClick={() => run('URL approved.', () => rowMutation.mutateAsync({ id: item.id, action: 'approve' }))}
                      >
                        Approve
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={item.status === 'rejected' || rowMutation.isPending}
                        onClick={() => run('URL rejected.', () => rowMutation.mutateAsync({ id: item.id, action: 'reject' }))}
                      >
                        Reject
                      </Button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function MonitorToggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (_checked: boolean) => void;
}) {
  return (
    <label className="flex min-h-11 items-center gap-3 rounded-md border bg-slate-50 px-3 py-2 text-sm font-medium text-slate-800">
      <input
        type="checkbox"
        className="h-4 w-4 rounded border-slate-300"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      {label}
    </label>
  );
}

function MonitorFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border bg-slate-50 px-3 py-3">
      <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">{label}</p>
      <p className="mt-2 text-sm font-medium text-slate-900">{value}</p>
    </div>
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

function scoreBucket(score: number) {
  if (score >= 85) return 'critical';
  if (score >= 70) return 'high';
  if (score >= 40) return 'medium';
  return 'low';
}

async function invalidateSearchConsole(projectId: UUID | undefined, queryClient: ReturnType<typeof useQueryClient>) {
  if (!projectId) return;
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ['gsc-summary', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['gsc-connections'] }),
    queryClient.invalidateQueries({ queryKey: ['gsc-properties', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['gsc-selected-property', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['gsc-sync-jobs', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['gsc-imports', projectId] }),
  ]);
}

const statusOptions = ['suggested', 'approved', 'rejected', 'completed'];
const priorityOptions = ['critical', 'high', 'medium', 'low'];
