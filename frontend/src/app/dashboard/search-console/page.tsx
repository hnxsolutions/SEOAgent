'use client';

import { Play, RefreshCw } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { ActionNotice, EmptyState, ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { OpportunityTable } from '@/components/dashboard/OpportunityTable';
import { StatusBadge, formatLabel } from '@/components/dashboard/StatusBadge';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi } from '@/lib/dashboard-api';
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

  const summaryQuery = useQuery({
    queryKey: ['gsc-summary', projectId],
    queryFn: () => dashboardApi.searchConsole.summary(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const propertiesQuery = useQuery({
    queryKey: ['gsc-properties', projectId],
    queryFn: () => dashboardApi.searchConsole.properties(projectId!),
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
  const selectedProperty = propertiesQuery.data?.properties.find((property) => property.is_selected);

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

      <section className="grid gap-4 md:grid-cols-4">
        <SummaryBlock label="Rows imported" value={summaryQuery.data?.rows_count ?? 0} />
        <SummaryBlock label="Opportunities" value={summaryQuery.data?.opportunities_count ?? 0} />
        <SummaryBlock label="Open" value={summaryQuery.data?.opportunities_by_status?.open ?? 0} />
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
            <div>
              <p className="text-muted-foreground">OAuth</p>
              <p className="mt-1 font-medium text-slate-950">
                {propertiesQuery.data?.oauth_enabled ? 'Enabled' : 'Not configured'}
              </p>
            </div>
            <div>
              <p className="text-muted-foreground">Selected property</p>
              <p className="mt-1 break-words font-medium text-slate-950">
                {selectedProperty?.site_url ?? 'No property selected'}
              </p>
            </div>
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
    queryClient.invalidateQueries({ queryKey: ['gsc-properties', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['gsc-sync-jobs', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['gsc-imports', projectId] }),
  ]);
}

const statusOptions = ['open', 'approved', 'rejected', 'completed'];
const priorityOptions = ['critical', 'high', 'medium', 'low'];
