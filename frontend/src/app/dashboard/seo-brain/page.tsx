'use client';

import { Bot, GitPullRequest, Activity, Zap } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { Button } from '@/components/ui/button';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi } from '@/lib/dashboard-api';
import type { BrainMasterPlanItem } from '@/types/dashboard';

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'bg-red-100 text-red-800 border-red-200',
  high: 'bg-orange-100 text-orange-800 border-orange-200',
  medium: 'bg-amber-100 text-amber-800 border-amber-200',
  low: 'bg-slate-100 text-slate-700 border-slate-200',
};

function Badge({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${className}`}>
      {children}
    </span>
  );
}

function HealthRing({ value }: { value: number }) {
  const color = value >= 80 ? 'text-emerald-600' : value >= 50 ? 'text-amber-600' : 'text-red-600';
  return (
    <div className="flex flex-col items-center justify-center">
      <div className={`text-5xl font-bold ${color}`}>{value}</div>
      <div className="text-xs uppercase tracking-wide text-muted-foreground">Health</div>
    </div>
  );
}

export default function SeoBrainPage() {
  const { projectId, isLoading: projectLoading } = useDashboardProject();
  const queryClient = useQueryClient();

  const stateQuery = useQuery({
    queryKey: ['brain-state', projectId],
    queryFn: () => dashboardApi.brain.state(projectId as string),
    enabled: Boolean(projectId),
    refetchInterval: 15000,
  });

  const planQuery = useQuery({
    queryKey: ['brain-plan', projectId],
    queryFn: () => dashboardApi.brain.masterPlan(projectId as string),
    enabled: Boolean(projectId),
    refetchInterval: 30000,
  });

  const runCycle = useMutation({
    mutationFn: () => dashboardApi.brain.run(projectId as string),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['brain-state', projectId] });
      queryClient.invalidateQueries({ queryKey: ['brain-plan', projectId] });
    },
  });

  if (projectLoading || (projectId && stateQuery.isLoading)) {
    return <LoadingBlock label="Loading SEO Brain" />;
  }
  if (!projectId) {
    return <EmptyState title="No project selected" description="Create or select a project to open Mission Control." />;
  }
  if (stateQuery.isError) {
    return <ErrorState title="Could not load SEO Brain" message="Try again shortly." />;
  }

  const state = stateQuery.data;
  const plan = planQuery.data;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold">
            <Bot className="h-6 w-6" /> SEO Brain — Mission Control
          </h1>
          <p className="text-sm text-muted-foreground">
            {state?.project_name} · {state?.domain}
          </p>
        </div>
        <Button onClick={() => runCycle.mutate()} disabled={runCycle.isPending}>
          <Zap className="mr-2 h-4 w-4" />
          {runCycle.isPending ? 'Starting…' : 'Run full analysis cycle'}
        </Button>
      </header>

      {runCycle.isSuccess ? (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-800">
          Full cycle started (SEO run + robots + sitemap). This page updates live.
        </div>
      ) : null}

      {/* Top row: health, current run, pending, next action */}
      <section className="grid gap-4 md:grid-cols-4">
        <div className="rounded-xl border bg-card p-5">
          <HealthRing value={state?.overall_health ?? 0} />
        </div>
        <div className="rounded-xl border bg-card p-5">
          <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <Activity className="h-4 w-4" /> Current Run
          </div>
          <div className="mt-2 text-lg font-semibold capitalize">{state?.current_run.status ?? 'none'}</div>
          <div className="text-xs text-muted-foreground">stage: {state?.current_run.current_stage ?? '—'}</div>
        </div>
        <div className="rounded-xl border bg-card p-5">
          <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <GitPullRequest className="h-4 w-4" /> Pending Approvals
          </div>
          <div className="mt-2 text-lg font-semibold">
            {state?.pending_approvals.proposed_patches ?? 0} patches
          </div>
          <div className="text-xs text-muted-foreground">
            {state?.pending_approvals.open_pull_requests ?? 0} open PRs
          </div>
        </div>
        <div className="rounded-xl border bg-card p-5">
          <div className="text-sm font-medium text-muted-foreground">Next Action</div>
          <div className="mt-2 text-sm font-semibold">{state?.next_action}</div>
        </div>
      </section>

      {/* Module summaries */}
      <section className="rounded-xl border bg-card p-5">
        <h2 className="mb-3 text-lg font-semibold">Module Status</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Object.entries(state?.modules ?? {}).map(([name, data]) => (
            <div key={name} className="rounded-lg border bg-background p-3">
              <div className="text-sm font-semibold capitalize">{name.replace('_', ' ')}</div>
              <div className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                {Object.entries(data as Record<string, unknown>)
                  .filter(([k]) => !k.endsWith('_id') && k !== 'project_id')
                  .slice(0, 4)
                  .map(([k, v]) => (
                    <div key={k}>
                      {k.replace(/_/g, ' ')}: <span className="font-medium text-foreground">{String(v)}</span>
                    </div>
                  ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Master plan */}
      <section className="rounded-xl border bg-card p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Master Optimization Plan</h2>
          <div className="text-sm text-muted-foreground">
            {plan?.total_issues ?? 0} issues · {plan?.code_fixable_count ?? 0} code-fixable
          </div>
        </div>
        {planQuery.isLoading ? (
          <LoadingBlock label="Prioritizing" />
        ) : !plan || plan.items.length === 0 ? (
          <EmptyState title="No open issues" description="Run a full analysis cycle to refresh the plan." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs uppercase text-muted-foreground">
                  <th className="py-2 pr-3">#</th>
                  <th className="py-2 pr-3">Priority</th>
                  <th className="py-2 pr-3">Severity</th>
                  <th className="py-2 pr-3">Issue</th>
                  <th className="py-2 pr-3">Category</th>
                  <th className="py-2 pr-3">Traffic</th>
                  <th className="py-2 pr-3">Effort</th>
                  <th className="py-2 pr-3">Fix</th>
                </tr>
              </thead>
              <tbody>
                {plan.items.map((item: BrainMasterPlanItem, idx: number) => (
                  <tr key={`${item.reference_id}-${idx}`} className="border-b last:border-0">
                    <td className="py-2 pr-3 text-muted-foreground">{idx + 1}</td>
                    <td className="py-2 pr-3 font-semibold">{item.priority_score}</td>
                    <td className="py-2 pr-3">
                      <Badge className={SEVERITY_COLORS[item.severity] ?? SEVERITY_COLORS.low}>{item.severity}</Badge>
                    </td>
                    <td className="py-2 pr-3">
                      <div className="font-medium">{item.title}</div>
                      <div className="text-xs text-muted-foreground">via {item.source}</div>
                    </td>
                    <td className="py-2 pr-3 capitalize">{item.category.replace('_', ' ')}</td>
                    <td className="py-2 pr-3 text-emerald-600">{item.expected_traffic_gain}</td>
                    <td className="py-2 pr-3 capitalize">{item.difficulty}</td>
                    <td className="py-2 pr-3">
                      {item.code_fixable ? (
                        <Badge className="border-indigo-200 bg-indigo-100 text-indigo-800">code</Badge>
                      ) : (
                        <Badge className="border-slate-200 bg-slate-100 text-slate-600">manual</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
