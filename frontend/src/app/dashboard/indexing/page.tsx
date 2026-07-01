'use client';

import { CheckCircle2, ClipboardList, Play, RefreshCw, ShieldAlert } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { ActionNotice, EmptyState, ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { StatusBadge, formatLabel } from '@/components/dashboard/StatusBadge';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi } from '@/lib/dashboard-api';
import { formatDateTime } from '@/lib/utils';
import type { IndexingIssue, UUID } from '@/types/dashboard';

const allFilter = 'all';

export default function IndexingPage() {
  const queryClient = useQueryClient();
  const { projectId } = useDashboardProject();
  const [statusFilter, setStatusFilter] = useState(allFilter);
  const [issueTypeFilter, setIssueTypeFilter] = useState(allFilter);
  const [severityFilter, setSeverityFilter] = useState(allFilter);
  const [manualUrls, setManualUrls] = useState('');
  const [notice, setNotice] = useState<string>();
  const [actionLoadingId, setActionLoadingId] = useState<UUID>();

  const summaryQuery = useQuery({
    queryKey: ['indexing-summary', projectId],
    queryFn: () => dashboardApi.indexing.summary(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const runsQuery = useQuery({
    queryKey: ['indexing-runs', projectId],
    queryFn: () => dashboardApi.indexing.runs(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const issuesQuery = useQuery({
    queryKey: ['indexing-issues', projectId],
    queryFn: () => dashboardApi.indexing.issues(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const latestRun = runsQuery.data?.runs[0];
  const runDetailQuery = useQuery({
    queryKey: ['indexing-run-detail', latestRun?.id],
    queryFn: () => dashboardApi.indexing.run(latestRun!.id),
    enabled: Boolean(latestRun?.id),
    retry: false,
  });

  const inspectMutation = useMutation({
    mutationFn: () => {
      const urls = manualUrls
        .split(/\r?\n/)
        .map((value) => value.trim())
        .filter(Boolean);
      return dashboardApi.indexing.inspect(projectId!, urls.length ? { urls } : { limit: 12 });
    },
    onSuccess: async (run) => {
      setNotice(`Inspection ${run.status}; ${run.inspected_url_count} URLs inspected.`);
      setManualUrls('');
      await invalidateIndexing(projectId, queryClient);
    },
  });

  const issueActionMutation = useMutation({
    mutationFn: async ({ issue, action }: { issue: IndexingIssue; action: 'plan' | 'validate' | 'ignore' }) => {
      setActionLoadingId(issue.id);
      if (action === 'plan') return dashboardApi.indexing.createFixPlan(issue.id);
      if (action === 'validate') return dashboardApi.indexing.validate(issue.id, { validation_after_days: 7, run_now: true });
      return dashboardApi.indexing.ignore(issue.id);
    },
    onSuccess: async (_response, variables) => {
      const verb = variables.action === 'plan' ? 'Fix plan created' : variables.action === 'validate' ? 'Validation completed' : 'Issue ignored';
      setNotice(`${verb} for ${formatLabel(variables.issue.issue_type)}.`);
      await invalidateIndexing(projectId, queryClient);
    },
    onSettled: () => setActionLoadingId(undefined),
  });

  const issues = useMemo(() => {
    return (issuesQuery.data?.issues ?? []).filter((issue) => (
      (statusFilter === allFilter || issue.status === statusFilter) &&
      (issueTypeFilter === allFilter || issue.issue_type === issueTypeFilter) &&
      (severityFilter === allFilter || issue.severity === severityFilter)
    ));
  }, [issueTypeFilter, issuesQuery.data?.issues, severityFilter, statusFilter]);

  const issueTypes = uniqueValues(issuesQuery.data?.issues.map((issue) => issue.issue_type));
  const latestResults = runDetailQuery.data?.results ?? [];
  const resultsByUrl = new Map(latestResults.map((result) => [result.page_url, result]));

  if (!projectId) {
    return <EmptyState title="Select a project" description="Indexing intelligence is scoped to one project." />;
  }

  if (summaryQuery.isLoading || runsQuery.isLoading || issuesQuery.isLoading) {
    return <LoadingBlock label="Loading indexing intelligence" />;
  }

  if (summaryQuery.isError || issuesQuery.isError) {
    return (
      <ErrorState
        title="Indexing data could not load"
        message="Check the indexing API, GSC OAuth connection, and selected property."
        onRetry={() => {
          void summaryQuery.refetch();
          void issuesQuery.refetch();
        }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-normal text-slate-950">
            Indexing Intelligence
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            URL Inspection, diagnosis, fix planning, and post-deploy validation.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              void invalidateIndexing(projectId, queryClient);
            }}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
          <Button
            type="button"
            onClick={() => inspectMutation.mutate()}
            disabled={inspectMutation.isPending}
          >
            <Play className="mr-2 h-4 w-4" />
            Run inspection
          </Button>
        </div>
      </div>

      <ActionNotice message={notice} />

      <section className="grid gap-4 md:grid-cols-4">
        <SummaryBlock label="Indexed URLs" value={summaryQuery.data?.indexed_urls ?? 0} />
        <SummaryBlock label="Not indexed" value={summaryQuery.data?.not_indexed_urls ?? 0} />
        <SummaryBlock label="Open issues" value={summaryQuery.data?.issues_by_status?.open ?? 0} />
        <div className="rounded-lg border bg-white p-4">
          <p className="text-sm text-muted-foreground">URL Inspection API</p>
          <div className="mt-3">
            <StatusBadge status={summaryQuery.data?.url_inspection_connected ? 'connected' : 'not_configured'} />
          </div>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
        <div className="rounded-lg border bg-white">
          <div className="border-b px-5 py-4">
            <h3 className="text-base font-semibold text-slate-950">Manual inspection</h3>
          </div>
          <div className="space-y-3 p-5">
            <textarea
              className="min-h-32 w-full rounded-md border bg-white p-3 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
              placeholder="https://example.com/landing-page"
              value={manualUrls}
              onChange={(event) => setManualUrls(event.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Leave empty to inspect priority URLs selected from recent changes, key pages, crawl data, GSC signals, sitemap gaps, and prior issues.
            </p>
          </div>
        </div>

        <div className="rounded-lg border bg-white">
          <div className="border-b px-5 py-4">
            <h3 className="text-base font-semibold text-slate-950">Inspection runs</h3>
          </div>
          <div className="divide-y">
            {(runsQuery.data?.runs ?? []).slice(0, 8).map((run) => (
              <div key={run.id} className="flex flex-col gap-2 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-medium text-slate-950">
                    {run.inspected_url_count}/{run.requested_url_count} inspected
                  </p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {run.failed_url_count} failed - {formatDateTime(run.created_at)}
                  </p>
                </div>
                <StatusBadge status={run.status} />
              </div>
            ))}
            {!runsQuery.data?.runs.length ? (
              <div className="p-5 text-sm text-muted-foreground">No URL Inspection runs yet.</div>
            ) : null}
          </div>
        </div>
      </section>

      <section className="rounded-lg border bg-white">
        <div className="flex flex-col gap-3 border-b px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="text-base font-semibold text-slate-950">Latest inspected pages</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Canonical, robots, and coverage states from the latest run.
            </p>
          </div>
          <StatusBadge status={latestRun?.status} />
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y text-sm">
            <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-5 py-3">Page</th>
                <th className="px-5 py-3">Verdict</th>
                <th className="px-5 py-3">Coverage</th>
                <th className="px-5 py-3">Canonical</th>
                <th className="px-5 py-3">Robots</th>
                <th className="px-5 py-3">Last inspection</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {latestResults.slice(0, 20).map((result) => (
                <tr key={result.id} className="align-top">
                  <td className="max-w-xs px-5 py-4">
                    <p className="break-words font-medium text-slate-950">{result.page_url}</p>
                  </td>
                  <td className="px-5 py-4"><StatusBadge status={result.verdict} /></td>
                  <td className="max-w-xs px-5 py-4 text-slate-700">{result.coverage_state ?? 'Unavailable'}</td>
                  <td className="max-w-sm px-5 py-4 text-slate-700">
                    <p className="break-words">Google: {result.google_canonical ?? 'Unavailable'}</p>
                    <p className="mt-1 break-words text-muted-foreground">User: {result.user_canonical ?? 'Unavailable'}</p>
                  </td>
                  <td className="px-5 py-4 text-slate-700">{result.robots_txt_state ?? result.indexing_state ?? 'Unavailable'}</td>
                  <td className="px-5 py-4 text-muted-foreground">{formatDateTime(result.created_at)}</td>
                </tr>
              ))}
              {!latestResults.length ? (
                <tr>
                  <td colSpan={6} className="px-5 py-6 text-sm text-muted-foreground">
                    No inspected pages yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-4">
        <div className="flex flex-col gap-3 rounded-lg border bg-white p-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="text-base font-semibold text-slate-950">Indexing issue queue</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Create fix plans or validate issues after deployment.
            </p>
          </div>
          <div className="grid gap-2 sm:grid-cols-3">
            <FilterSelect label="Status" value={statusFilter} onChange={setStatusFilter} options={statusOptions} />
            <FilterSelect label="Type" value={issueTypeFilter} onChange={setIssueTypeFilter} options={issueTypes} />
            <FilterSelect label="Severity" value={severityFilter} onChange={setSeverityFilter} options={severityOptions} />
          </div>
        </div>

        <div className="grid gap-4">
          {issues.map((issue) => {
            const result = resultsByUrl.get(issue.page_url);
            return (
              <article key={issue.id} className="rounded-lg border bg-white p-5">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge status={issue.status} />
                      <SeverityBadge severity={issue.severity} />
                      <span className="text-sm font-medium text-slate-700">{formatLabel(issue.issue_type)}</span>
                    </div>
                    <h4 className="mt-3 break-words text-base font-semibold text-slate-950">{issue.page_url}</h4>
                    <p className="mt-2 text-sm leading-6 text-slate-700">{issue.likely_cause}</p>
                    <p className="mt-2 text-sm leading-6 text-slate-700">{issue.recommended_fix}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => issueActionMutation.mutate({ issue, action: 'plan' })}
                      disabled={actionLoadingId === issue.id}
                    >
                      <ClipboardList className="mr-2 h-4 w-4" />
                      Fix plan
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => issueActionMutation.mutate({ issue, action: 'validate' })}
                      disabled={actionLoadingId === issue.id}
                    >
                      <CheckCircle2 className="mr-2 h-4 w-4" />
                      Validate
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => issueActionMutation.mutate({ issue, action: 'ignore' })}
                      disabled={actionLoadingId === issue.id}
                    >
                      <ShieldAlert className="mr-2 h-4 w-4" />
                      Ignore
                    </Button>
                  </div>
                </div>
                <dl className="mt-5 grid gap-4 text-sm md:grid-cols-4">
                  <Detail label="Google canonical" value={result?.google_canonical || 'Unavailable'} />
                  <Detail label="User canonical" value={result?.user_canonical || 'Unavailable'} />
                  <Detail label="Robots/indexing" value={result?.robots_txt_state || result?.indexing_state || 'Unavailable'} />
                  <Detail label="Validation" value={formatLabel(issue.status)} />
                </dl>
              </article>
            );
          })}
          {!issues.length ? (
            <div className="rounded-lg border bg-white p-6 text-sm text-muted-foreground">
              No indexing issues match the current filters.
            </div>
          ) : null}
        </div>
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

function SeverityBadge({ severity }: { severity: string }) {
  const styles: Record<string, string> = {
    critical: 'border-rose-200 bg-rose-50 text-rose-700',
    high: 'border-orange-200 bg-orange-50 text-orange-700',
    medium: 'border-amber-200 bg-amber-50 text-amber-700',
    low: 'border-slate-200 bg-slate-50 text-slate-700',
  };
  return (
    <span className={`inline-flex h-6 items-center rounded-full border px-2 text-xs font-medium capitalize ${styles[severity] ?? styles.low}`}>
      {formatLabel(severity)}
    </span>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-1 break-words text-slate-800">{value}</dd>
    </div>
  );
}

function uniqueValues(values?: string[]) {
  return Array.from(new Set(values ?? [])).sort();
}

async function invalidateIndexing(projectId: UUID | undefined, queryClient: ReturnType<typeof useQueryClient>) {
  if (!projectId) return;
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ['indexing-summary', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['indexing-runs', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['indexing-issues', projectId] }),
  ]);
}

const statusOptions = ['open', 'in_progress', 'fix_proposed', 'fixed', 'validated', 'still_failing', 'inconclusive', 'ignored'];
const severityOptions = ['critical', 'high', 'medium', 'low'];
