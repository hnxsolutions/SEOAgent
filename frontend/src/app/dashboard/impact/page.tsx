'use client';

import { CheckCircle2, Play, RefreshCw } from 'lucide-react';
import type { ReactNode } from 'react';
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ActionNotice, EmptyState, ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { StatusBadge, formatLabel } from '@/components/dashboard/StatusBadge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { dashboardApi } from '@/lib/dashboard-api';
import { formatDate, formatDateTime } from '@/lib/utils';
import type { ImpactExperiment, ImpactResult, UUID } from '@/types/dashboard';

export default function ImpactPage() {
  const queryClient = useQueryClient();
  const { projectId } = useDashboardProject();
  const [targetPageUrl, setTargetPageUrl] = useState('');
  const [targetQuery, setTargetQuery] = useState('');
  const [baselineStart, setBaselineStart] = useState(dateInputDaysAgo(42));
  const [baselineEnd, setBaselineEnd] = useState(dateInputDaysAgo(28));
  const [notice, setNotice] = useState<string>();
  const [latestResults, setLatestResults] = useState<Record<string, ImpactResult>>({});

  const summaryQuery = useQuery({
    queryKey: ['impact-summary', projectId],
    queryFn: () => dashboardApi.impact.summary(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const experimentsQuery = useQuery({
    queryKey: ['impact-experiments', projectId],
    queryFn: () => dashboardApi.impact.experiments(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      dashboardApi.impact.createExperiment({
        project_id: projectId!,
        experiment_type: 'manual_seo_action',
        source_type: 'manual',
        target_page_url: targetPageUrl,
        target_query: targetQuery || undefined,
        baseline_start_date: toIsoDateStart(baselineStart),
        baseline_end_date: toIsoDateEnd(baselineEnd),
        review_after_days: 14,
      }),
    onSuccess: async () => {
      setTargetPageUrl('');
      setTargetQuery('');
      setNotice('Impact experiment created.');
      await invalidateImpact(projectId, queryClient);
    },
  });

  const actionMutation = useMutation({
    mutationFn: async ({ id, action }: { id: UUID; action: 'baseline' | 'applied' | 'evaluate' }) => {
      if (action === 'baseline') {
        await dashboardApi.impact.captureBaseline(id);
        return { id, result: undefined as ImpactResult | undefined, message: 'Baseline captured.' };
      }
      if (action === 'applied') {
        await dashboardApi.impact.markActionApplied(id);
        return { id, result: undefined as ImpactResult | undefined, message: 'Action marked as applied.' };
      }
      const result = await dashboardApi.impact.evaluate(id);
      return { id, result, message: `Evaluation complete: ${formatLabel(result.outcome)}.` };
    },
    onSuccess: async ({ id, result, message }) => {
      if (result) {
        setLatestResults((current) => ({ ...current, [id]: result }));
      }
      setNotice(message);
      await invalidateImpact(projectId, queryClient);
    },
  });

  const experiments = experimentsQuery.data?.experiments ?? [];
  const summary = summaryQuery.data;
  const statusRows = useMemo(() => Object.entries(summary?.by_status ?? {}), [summary?.by_status]);
  const outcomeRows = useMemo(() => Object.entries(summary?.by_outcome ?? {}), [summary?.by_outcome]);

  if (!projectId) {
    return <EmptyState title="Select a project" description="Impact experiments are scoped to one project." />;
  }

  if (summaryQuery.isLoading || experimentsQuery.isLoading) {
    return <LoadingBlock label="Loading impact tracking" />;
  }

  if (summaryQuery.isError || experimentsQuery.isError) {
    return (
      <ErrorState
        title="Impact tracking could not load"
        message="The API may be unavailable or this project may not have experiments yet."
        onRetry={() => {
          void summaryQuery.refetch();
          void experimentsQuery.refetch();
        }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-normal text-slate-950">
            SEO Impact Tracking
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Measure SEO action impact with GSC API or CSV rows before and after a change.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            void invalidateImpact(projectId, queryClient);
          }}
        >
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh
        </Button>
      </div>

      <ActionNotice message={notice} />

      <section className="grid gap-4 md:grid-cols-4">
        <MetricCard label="Experiments" value={summary?.total_experiments ?? 0} />
        <MetricCard label="Ready for review" value={summary?.ready_for_review ?? 0} />
        <MetricCard label="Improved" value={summary?.by_outcome?.improved ?? 0} />
        <MetricCard label="Declined" value={summary?.by_outcome?.declined ?? 0} />
      </section>

      <section className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
        <div className="rounded-lg border bg-white">
          <div className="border-b px-5 py-4">
            <h3 className="text-base font-semibold text-slate-950">Create experiment</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Capture a baseline before a manual SEO action, then evaluate after the review window.
            </p>
          </div>
          <div className="space-y-4 p-5">
            <Field label="Target page URL">
              <Input
                value={targetPageUrl}
                onChange={(event) => setTargetPageUrl(event.target.value)}
                placeholder="https://example.com/service"
              />
            </Field>
            <Field label="Target query">
              <Input
                value={targetQuery}
                onChange={(event) => setTargetQuery(event.target.value)}
                placeholder="Optional keyword"
              />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Baseline start">
                <Input
                  type="date"
                  value={baselineStart}
                  onChange={(event) => setBaselineStart(event.target.value)}
                />
              </Field>
              <Field label="Baseline end">
                <Input
                  type="date"
                  value={baselineEnd}
                  onChange={(event) => setBaselineEnd(event.target.value)}
                />
              </Field>
            </div>
            <Button
              type="button"
              onClick={() => createMutation.mutate()}
              disabled={!targetPageUrl || !baselineStart || !baselineEnd || createMutation.isPending}
              className="w-full"
            >
              <CheckCircle2 className="mr-2 h-4 w-4" />
              Create experiment
            </Button>
            {summary?.message ? (
              <p className="text-sm text-muted-foreground">{summary.message}</p>
            ) : null}
          </div>
        </div>

        <div className="rounded-lg border bg-white">
          <div className="border-b px-5 py-4">
            <h3 className="text-base font-semibold text-slate-950">Experiment summary</h3>
          </div>
          <div className="grid gap-4 p-5 sm:grid-cols-2">
            <SummaryList title="By status" rows={statusRows} />
            <SummaryList title="By outcome" rows={outcomeRows} />
          </div>
        </div>
      </section>

      <section className="rounded-lg border bg-white">
        <div className="border-b px-5 py-4">
          <h3 className="text-base font-semibold text-slate-950">Active experiments</h3>
        </div>
        {experiments.length === 0 ? (
          <div className="p-5">
            <EmptyState
              title="No impact experiments"
              description="Create an experiment after choosing an SEO action you want to measure."
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[960px] text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-5 py-3 font-medium">Target</th>
                  <th className="px-5 py-3 font-medium">Baseline</th>
                  <th className="px-5 py-3 font-medium">Action date</th>
                  <th className="px-5 py-3 font-medium">Review</th>
                  <th className="px-5 py-3 font-medium">Status</th>
                  <th className="px-5 py-3 font-medium">Latest result</th>
                  <th className="px-5 py-3 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {experiments.map((experiment) => (
                  <ExperimentRow
                    key={experiment.id}
                    experiment={experiment}
                    latestResult={latestResults[experiment.id]}
                    isBusy={actionMutation.isPending}
                    onAction={(action) => actionMutation.mutate({ id: experiment.id, action })}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function ExperimentRow({
  experiment,
  latestResult,
  isBusy,
  onAction,
}: {
  experiment: ImpactExperiment;
  latestResult?: ImpactResult;
  isBusy: boolean;
  onAction: (_action: 'baseline' | 'applied' | 'evaluate') => void;
}) {
  return (
    <tr className="align-top">
      <td className="max-w-md px-5 py-4">
        <p className="break-all font-medium text-slate-950">{experiment.target_page_url}</p>
        <p className="mt-1 text-sm text-muted-foreground">
          {experiment.target_query || formatLabel(experiment.experiment_type)}
        </p>
      </td>
      <td className="px-5 py-4 text-slate-600">
        {formatDate(experiment.baseline_start_date)} to {formatDate(experiment.baseline_end_date)}
      </td>
      <td className="px-5 py-4 text-slate-600">
        {experiment.action_date ? formatDateTime(experiment.action_date) : 'Not applied'}
      </td>
      <td className="px-5 py-4 text-slate-600">
        {experiment.review_end_date ? formatDate(experiment.review_end_date) : `${experiment.review_after_days} days`}
      </td>
      <td className="px-5 py-4">
        <StatusBadge status={experiment.status} />
      </td>
      <td className="px-5 py-4 text-slate-600">
        {latestResult ? (
          <div>
            <StatusBadge status={latestResult.outcome} />
            <p className="mt-2 text-xs text-muted-foreground">
              Position {formatDelta(latestResult.position_delta)}, clicks{' '}
              {formatSignedInteger(latestResult.clicks_delta)}, CTR {formatDelta(latestResult.ctr_delta * 100)} pts
            </p>
          </div>
        ) : (
          'No evaluation in this session'
        )}
      </td>
      <td className="px-5 py-4">
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" variant="outline" disabled={isBusy} onClick={() => onAction('baseline')}>
            Baseline
          </Button>
          <Button type="button" size="sm" variant="outline" disabled={isBusy} onClick={() => onAction('applied')}>
            Mark applied
          </Button>
          <Button type="button" size="sm" disabled={isBusy} onClick={() => onAction('evaluate')}>
            <Play className="mr-2 h-3.5 w-3.5" />
            Evaluate
          </Button>
        </div>
      </td>
    </tr>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-2">
      <span className="text-sm font-medium text-slate-700">{label}</span>
      {children}
    </label>
  );
}

function SummaryList({ title, rows }: { title: string; rows: Array<[string, number]> }) {
  return (
    <div>
      <p className="text-sm font-medium text-slate-950">{title}</p>
      <div className="mt-3 space-y-2">
        {rows.length ? (
          rows.map(([key, value]) => (
            <div key={key} className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2 text-sm">
              <span className="text-slate-600">{formatLabel(key)}</span>
              <span className="font-medium text-slate-950">{value}</span>
            </div>
          ))
        ) : (
          <p className="text-sm text-muted-foreground">No data yet</p>
        )}
      </div>
    </div>
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

function dateInputDaysAgo(days: number) {
  const date = new Date(Date.now() - days * 24 * 60 * 60 * 1000);
  return date.toISOString().slice(0, 10);
}

function toIsoDateStart(value: string) {
  return new Date(`${value}T00:00:00.000Z`).toISOString();
}

function toIsoDateEnd(value: string) {
  return new Date(`${value}T23:59:59.000Z`).toISOString();
}

function formatDelta(value: number) {
  if (value > 0) return `+${value.toFixed(2)}`;
  return value.toFixed(2);
}

function formatSignedInteger(value: number) {
  const formatted = new Intl.NumberFormat('en-US').format(value);
  return value > 0 ? `+${formatted}` : formatted;
}

async function invalidateImpact(projectId: UUID | undefined, queryClient: ReturnType<typeof useQueryClient>) {
  if (!projectId) return;
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ['impact-summary', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['impact-experiments', projectId] }),
  ]);
}
