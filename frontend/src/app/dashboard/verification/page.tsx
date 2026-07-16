'use client';

import type { ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, XCircle, Clock, AlertTriangle, Brain, TrendingUp, Rocket } from 'lucide-react';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { Button } from '@/components/ui/button';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi } from '@/lib/dashboard-api';
import type { AiFixVerification, Deployment, LearningStats } from '@/types/dashboard';

function deployStatusClass(status: string): string {
  switch (status) {
    case 'success': return 'border-emerald-200 bg-emerald-100 text-emerald-800';
    case 'failed': return 'border-red-200 bg-red-100 text-red-800';
    case 'building': return 'border-indigo-200 bg-indigo-100 text-indigo-800';
    case 'skipped': return 'border-slate-200 bg-slate-100 text-slate-600';
    default: return 'border-amber-200 bg-amber-100 text-amber-800';
  }
}

function statusMeta(status: string): { label: string; className: string; icon: ReactNode } {
  switch (status) {
    case 'verified_success':
      return { label: 'Verified success', className: 'border-emerald-200 bg-emerald-100 text-emerald-800', icon: <CheckCircle2 className="h-4 w-4" /> };
    case 'partially_successful':
      return { label: 'Partially successful', className: 'border-amber-200 bg-amber-100 text-amber-800', icon: <TrendingUp className="h-4 w-4" /> };
    case 'failed':
      return { label: 'Failed', className: 'border-red-200 bg-red-100 text-red-800', icon: <XCircle className="h-4 w-4" /> };
    case 'needs_human_review':
      return { label: 'Needs review', className: 'border-slate-200 bg-slate-100 text-slate-700', icon: <AlertTriangle className="h-4 w-4" /> };
    case 'running':
      return { label: 'Running', className: 'border-indigo-200 bg-indigo-100 text-indigo-800', icon: <Clock className="h-4 w-4 animate-pulse" /> };
    default:
      return { label: 'Pending', className: 'border-slate-200 bg-slate-100 text-slate-700', icon: <Clock className="h-4 w-4" /> };
  }
}

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </div>
  );
}

function VerificationCard({ v }: { v: AiFixVerification }) {
  const meta = statusMeta(v.status);
  const details = (v.details ?? {}) as Record<string, unknown>;
  const regression = Boolean(details['regression']);
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${meta.className}`}>
            {meta.icon} {meta.label}
          </span>
          <span className="font-mono text-xs text-muted-foreground">{v.patch_type}</span>
          {regression ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700">
              <AlertTriangle className="h-3 w-3" /> regression
            </span>
          ) : null}
        </div>
        {v.improvement_pct != null ? (
          <span className={`text-sm font-semibold ${v.improvement_pct >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
            {v.improvement_pct >= 0 ? '+' : ''}{v.improvement_pct}% SEO score
          </span>
        ) : null}
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg bg-slate-50 p-2 text-sm">
          <p className="text-muted-foreground">Before</p>
          <p className="font-semibold">{v.baseline_score ?? '—'}</p>
        </div>
        <div className="rounded-lg bg-slate-50 p-2 text-sm">
          <p className="text-muted-foreground">After</p>
          <p className="font-semibold">{v.followup_score ?? '—'}</p>
        </div>
        <div className="rounded-lg bg-slate-50 p-2 text-sm">
          <p className="text-muted-foreground">Issue resolved</p>
          <p className="font-semibold">{v.issue_resolved == null ? '—' : v.issue_resolved ? 'Yes' : 'No'}</p>
        </div>
      </div>
    </div>
  );
}

function DeploymentRow({ d, onSimulate, busy }: { d: Deployment; onSimulate: () => void; busy: boolean }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-card p-3 text-sm">
      <div className="flex items-center gap-2">
        <Rocket className="h-4 w-4 text-indigo-600" />
        <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-medium ${deployStatusClass(d.status)}`}>
          {d.status}
        </span>
        <span className="font-mono text-xs text-muted-foreground">{d.provider}</span>
        {d.deployment_url ? <span className="max-w-[220px] truncate text-xs text-indigo-600">{d.deployment_url}</span> : null}
        {d.duration_seconds != null ? <span className="text-xs text-muted-foreground">{d.duration_seconds}s</span> : null}
      </div>
      {d.status === 'pending' || d.status === 'building' ? (
        <Button size="sm" variant="outline" onClick={onSimulate} disabled={busy}>
          Simulate deploy success
        </Button>
      ) : null}
    </div>
  );
}

export default function VerificationPage() {
  const { projectId, isLoading: projectLoading } = useDashboardProject();
  const queryClient = useQueryClient();

  const deployments = useQuery({
    queryKey: ['deployments', projectId],
    queryFn: () => dashboardApi.deployments.list(projectId as string),
    enabled: Boolean(projectId),
    refetchInterval: 15000,
  });
  const simulateDeploy = useMutation({
    mutationFn: (deploymentId: string) =>
      dashboardApi.deployments.updateStatus(deploymentId, 'success', 'https://novakoshealthcare.com'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deployments', projectId] });
      queryClient.invalidateQueries({ queryKey: ['verif-queue', projectId] });
    },
  });

  const queue = useQuery({
    queryKey: ['verif-queue', projectId],
    queryFn: () => dashboardApi.verification.queue(projectId as string),
    enabled: Boolean(projectId),
    refetchInterval: 15000,
  });
  const history = useQuery({
    queryKey: ['verif-history', projectId],
    queryFn: () => dashboardApi.verification.history(projectId as string),
    enabled: Boolean(projectId),
    refetchInterval: 20000,
  });
  const learning = useQuery({
    queryKey: ['verif-learning', projectId],
    queryFn: () => dashboardApi.verification.learningStats(projectId as string),
    enabled: Boolean(projectId),
    refetchInterval: 20000,
  });

  if (projectLoading) return <LoadingBlock label="Loading verification" />;
  if (!projectId) return <EmptyState title="No project selected" description="Select a project to view verification." />;
  if (queue.isError || history.isError) return <ErrorState title="Could not load verification" message="Try again shortly." />;

  const stats: LearningStats | undefined = learning.data;
  const confidence = stats?.confidence_by_patch_type ?? {};

  return (
    <div className="space-y-6">
      <header>
        <h1 className="flex items-center gap-2 text-2xl font-semibold">
          <Brain className="h-6 w-6" /> Verification & Learning
        </h1>
        <p className="text-sm text-muted-foreground">
          After merge, the AI re-runs analysis, compares before vs after, and learns which fixes work.
        </p>
      </header>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="In queue" value={queue.data?.total ?? 0} />
        <Stat label="Finalized" value={stats?.finalized ?? 0} />
        <Stat label="Success rate" value={stats?.success_rate == null ? '—' : `${stats.success_rate}%`} />
        <Stat label="Avg improvement" value={stats?.average_improvement_pct == null ? '—' : `${stats.average_improvement_pct}%`} />
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Deployments</h2>
        <p className="mb-2 text-xs text-muted-foreground">
          After a PR merges, the AI waits for deployment before re-measuring SEO. On deploy
          success, linked verifications run against the live site.
        </p>
        {!deployments.data || deployments.data.deployments.length === 0 ? (
          <EmptyState title="No deployments yet" description="Merged PRs create a deployment record here." />
        ) : (
          <div className="space-y-2">
            {deployments.data.deployments.map((d) => (
              <DeploymentRow
                key={d.id}
                d={d}
                busy={simulateDeploy.isPending}
                onSimulate={() => simulateDeploy.mutate(d.id)}
              />
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Verification queue</h2>
        {!queue.data || queue.data.verifications.length === 0 ? (
          <EmptyState title="Queue empty" description="Merged PRs schedule automatic verification here." />
        ) : (
          <div className="space-y-3">{queue.data.verifications.map((v) => <VerificationCard key={v.id} v={v} />)}</div>
        )}
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Recently verified</h2>
        {!history.data || history.data.verifications.length === 0 ? (
          <EmptyState title="No completed verifications yet" description="Results appear here once follow-up analysis finishes." />
        ) : (
          <div className="space-y-3">{history.data.verifications.map((v) => <VerificationCard key={v.id} v={v} />)}</div>
        )}
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Confidence by fix type (evidence-based)</h2>
        {Object.keys(confidence).length === 0 ? (
          <EmptyState title="No learning data yet" description="Confidence becomes evidence-based after fixes are verified." />
        ) : (
          <div className="overflow-x-auto rounded-xl border">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="p-2">Fix type</th><th className="p-2">Confidence</th><th className="p-2">Success</th>
                  <th className="p-2">Partial</th><th className="p-2">Failed</th><th className="p-2">Source</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(confidence).map(([type, m]) => (
                  <tr key={type} className="border-t">
                    <td className="p-2 font-mono text-xs">{type}</td>
                    <td className="p-2 font-semibold">{m.confidence == null ? '—' : `${m.confidence}%`}</td>
                    <td className="p-2">{m.success}</td>
                    <td className="p-2">{m.partial}</td>
                    <td className="p-2">{m.failed}</td>
                    <td className="p-2">{m.evidence_based ? 'evidence' : 'heuristic'}</td>
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
