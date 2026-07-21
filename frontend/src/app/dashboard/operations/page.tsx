'use client';

import { Activity, Gauge, ListChecks, GitBranch, RefreshCw } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { Button } from '@/components/ui/button';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi } from '@/lib/dashboard-api';
import type { OpsDimension, OpsAction, OpsLifecycleStage, OpsChange, OpsTimelineEntry } from '@/types/dashboard';

function scoreTone(score: number | null) {
  if (score == null) return 'text-slate-400';
  if (score >= 75) return 'text-emerald-600';
  if (score >= 50) return 'text-amber-600';
  return 'text-rose-600';
}
function barTone(score: number | null) {
  if (score == null) return 'bg-slate-200';
  if (score >= 75) return 'bg-emerald-500';
  if (score >= 50) return 'bg-amber-500';
  return 'bg-rose-500';
}

export default function OperationsPage() {
  const queryClient = useQueryClient();
  const { projectId } = useDashboardProject();

  const healthQuery = useQuery({ queryKey: ['ops-health', projectId], queryFn: () => dashboardApi.operations.health(projectId!), enabled: Boolean(projectId), retry: false });
  const actionsQuery = useQuery({ queryKey: ['ops-actions', projectId], queryFn: () => dashboardApi.operations.nextActions(projectId!), enabled: Boolean(projectId), retry: false });
  const lifecycleQuery = useQuery({ queryKey: ['ops-lifecycle', projectId], queryFn: () => dashboardApi.operations.lifecycle(projectId!), enabled: Boolean(projectId), retry: false });
  const changesQuery = useQuery({ queryKey: ['ops-changes', projectId], queryFn: () => dashboardApi.operations.changes(projectId!), enabled: Boolean(projectId), retry: false });
  const timelineQuery = useQuery({ queryKey: ['ops-timeline', projectId], queryFn: () => dashboardApi.operations.timeline(projectId!), enabled: Boolean(projectId), retry: false });

  const monitorMutation = useMutation({
    mutationFn: () => dashboardApi.operations.monitor(projectId!),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['ops-changes', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['ops-timeline', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['ops-health', projectId] }),
      ]);
    },
  });

  if (healthQuery.isLoading) return <LoadingBlock label="Loading SEO operations…" />;
  if (healthQuery.isError) return <ErrorState title="Could not load" message="The API may be unavailable." onRetry={() => void healthQuery.refetch()} />;

  const health = healthQuery.data;
  const dims: OpsDimension[] = health?.dimensions ?? [];
  const actions: OpsAction[] = actionsQuery.data?.actions ?? [];
  const stages: OpsLifecycleStage[] = lifecycleQuery.data?.stages ?? [];
  const changes: OpsChange[] = changesQuery.data?.changes ?? [];
  const timeline: OpsTimelineEntry[] = timelineQuery.data?.timeline ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-2xl font-semibold text-slate-950">
            <Activity className="h-6 w-6" /> SEO Operations
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            The autonomous engine watches this project 24×7 — real health, what changed, and the next best action. It only reads and recommends; it never modifies your site.
          </p>
        </div>
        <Button type="button" onClick={() => monitorMutation.mutate()} disabled={!projectId || monitorMutation.isPending}>
          <RefreshCw className={`mr-2 h-4 w-4 ${monitorMutation.isPending ? 'animate-spin' : ''}`} />
          {monitorMutation.isPending ? 'Monitoring…' : 'Run Monitor'}
        </Button>
      </div>

      {/* Overall + dimensions */}
      <section className="rounded-xl border bg-card p-5">
        <div className="flex items-center gap-4">
          <div className="flex h-20 w-20 flex-none items-center justify-center rounded-full border-4 border-slate-100">
            <div className="text-center">
              <div className={`text-2xl font-bold ${scoreTone(health?.overall ?? null)}`}>{health?.overall ?? '—'}</div>
              <div className="text-[10px] uppercase text-muted-foreground">/ 100</div>
            </div>
          </div>
          <div>
            <p className="flex items-center gap-2 text-sm font-semibold text-slate-950"><Gauge className="h-4 w-4" /> Overall SEO Health <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">Grade {health?.grade ?? '—'}</span></p>
            <p className="mt-1 text-xs text-muted-foreground">{health?.measured_dimensions}/{health?.total_dimensions} dimensions measured from real data.</p>
          </div>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {dims.map((d) => (
            <div key={d.key} className="rounded-lg border p-3" title={d.explanation}>
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-slate-800">{d.label}</span>
                <span className={`text-sm font-semibold ${scoreTone(d.score)}`}>{d.score != null ? Math.round(d.score) : '—'}</span>
              </div>
              <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                <div className={`h-full rounded-full ${barTone(d.score)}`} style={{ width: `${Math.max(0, Math.min(100, d.score ?? 0))}%` }} />
              </div>
              <p className="mt-1.5 text-[11px] text-muted-foreground">{d.explanation}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Next best actions */}
      <section className="rounded-xl border bg-card p-5">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-950"><ListChecks className="h-4 w-4" /> Next Best Actions</h3>
        {actions.length === 0 ? (
          <p className="mt-2 text-sm text-muted-foreground">Nothing pressing — the project is in good shape.</p>
        ) : (
          <ol className="mt-3 space-y-2">
            {actions.map((a, i) => (
              <li key={i} className="flex items-start gap-3 rounded-lg border p-3">
                <span className="mt-0.5 rounded-full bg-slate-900 px-2 py-0.5 text-xs font-semibold text-white">{a.priority}</span>
                <div>
                  <p className="text-sm font-medium text-slate-900">{a.action}</p>
                  <p className="text-xs text-muted-foreground">Why: {a.why}</p>
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>

      {/* Lifecycle */}
      <section className="rounded-xl border bg-card p-5">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-950"><GitBranch className="h-4 w-4" /> Project Lifecycle</h3>
        <div className="mt-3 flex flex-wrap gap-2">
          {stages.map((s) => (
            <span key={s.name} className={`rounded-full border px-2.5 py-1 text-xs font-medium ${
              s.status === 'done' ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
              : s.status === 'current' ? 'border-sky-200 bg-sky-50 text-sky-700'
              : 'border-slate-200 bg-slate-50 text-slate-500'}`}>{s.label}</span>
          ))}
        </div>
      </section>

      {/* Change detection */}
      <section className="rounded-xl border bg-card p-5">
        <h3 className="text-sm font-semibold text-slate-950">What Changed Since Last Check</h3>
        {changes.length === 0 ? (
          <p className="mt-2 text-sm text-muted-foreground">No changes detected since the previous snapshot.</p>
        ) : (
          <ul className="mt-3 space-y-1.5">
            {changes.map((c, i) => (
              <li key={i} className="flex items-center gap-2 text-sm">
                <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${
                  c.direction === 'improved' ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                  : c.direction === 'declined' ? 'border-rose-200 bg-rose-50 text-rose-700'
                  : 'border-slate-200 bg-slate-50 text-slate-600'}`}>{c.direction}</span>
                <span className="text-slate-700">{c.field.replace(/_/g, ' ')}: {String(c.before)} → <b>{String(c.after)}</b></span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Timeline */}
      <section className="rounded-xl border bg-card p-5">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-950"><Activity className="h-4 w-4" /> Activity Timeline</h3>
        {timeline.length === 0 ? (
          <p className="mt-2 text-sm text-muted-foreground">No recent activity yet.</p>
        ) : (
          <ol className="mt-3 space-y-2">
            {timeline.map((e, i) => (
              <li key={i} className="flex items-start gap-3 text-sm">
                <span className="mt-0.5 w-20 flex-none rounded bg-slate-100 px-1.5 py-0.5 text-center text-[10px] uppercase text-slate-500">{e.bucket.replace(/_/g, ' ')}</span>
                <span className="text-slate-800">{e.event}</span>
                <span className="ml-auto flex-none font-mono text-xs text-muted-foreground">{new Date(e.time).toLocaleDateString()}</span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}
