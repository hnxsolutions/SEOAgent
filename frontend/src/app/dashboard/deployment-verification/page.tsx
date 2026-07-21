'use client';

import type { ReactNode } from 'react';
import { BadgeCheck, Rocket, Gauge, Search, Activity, ArrowRight } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { Button } from '@/components/ui/button';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi } from '@/lib/dashboard-api';
import type { DeploymentVerificationRun, VerdictCell, TimelineEntry } from '@/types/dashboard';

function Verdict({ v }: { v: string }) {
  const map: Record<string, string> = {
    improved: 'text-emerald-700 bg-emerald-50 border-emerald-200',
    declined: 'text-rose-700 bg-rose-50 border-rose-200',
    no_change: 'text-slate-600 bg-slate-50 border-slate-200',
    no_data: 'text-slate-400 bg-slate-50 border-slate-200',
    present: 'text-emerald-700 bg-emerald-50 border-emerald-200',
    not_detected: 'text-amber-700 bg-amber-50 border-amber-200',
  };
  return <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${map[v] ?? map.no_data}`}>{v.replace(/_/g, ' ')}</span>;
}

function BeforeAfter({ label, cell, unit = '' }: { label: string; cell?: VerdictCell; unit?: string }) {
  const c = cell ?? { verdict: 'no_data' };
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</span>
        <Verdict v={c.verdict} />
      </div>
      <div className="mt-2 flex items-center gap-2 text-sm">
        <span className="text-slate-500">{c.before ?? '—'}{c.before != null ? unit : ''}</span>
        <ArrowRight className="h-3 w-3 text-slate-400" />
        <span className="font-semibold text-slate-900">{c.after ?? '—'}{c.after != null ? unit : ''}</span>
      </div>
    </div>
  );
}

function StatusPill({ status }: { status?: string | null }) {
  const map: Record<string, string> = {
    succeeded: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    gated: 'border-amber-200 bg-amber-50 text-amber-700',
    running: 'border-sky-200 bg-sky-50 text-sky-700',
    failed: 'border-rose-200 bg-rose-50 text-rose-700',
    pending: 'border-slate-200 bg-slate-50 text-slate-600',
  };
  return <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${map[status ?? 'pending'] ?? map.pending}`}>{status ?? '—'}</span>;
}

export default function DeploymentVerificationPage() {
  const queryClient = useQueryClient();
  const { projectId } = useDashboardProject();

  const query = useQuery({
    queryKey: ['deployment-verification', projectId],
    queryFn: () => dashboardApi.deploymentVerification.summary(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const runMutation = useMutation({
    mutationFn: () => dashboardApi.deploymentVerification.run(projectId!),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ['deployment-verification', projectId] }); },
  });

  if (query.isLoading) return <LoadingBlock label="Loading deployment verification…" />;
  if (query.isError) return <ErrorState title="Could not load" message="The API may be unavailable." onRetry={() => void query.refetch()} />;

  const dv = query.data as DeploymentVerificationRun | undefined;
  const hasRun = dv?.has_run;
  const cwv = dv?.cwv_comparison ?? {};
  const seoCmp = dv?.seo_comparison ?? {};
  const seoScore = (seoCmp['seo_score'] as VerdictCell) ?? { before: dv?.seo_before, after: dv?.seo_after, verdict: 'no_data' };
  const timeline: TimelineEntry[] = dv?.timeline ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-2xl font-semibold text-slate-950">
            <BadgeCheck className="h-6 w-6" /> Deployment Verification
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            After approval, the agent verifies the <b>real deployed site</b> — measured before vs after, never predicted. It only verifies; it never modifies production.
          </p>
        </div>
        <Button type="button" onClick={() => runMutation.mutate()} disabled={!projectId || runMutation.isPending}>
          <BadgeCheck className={`mr-2 h-4 w-4 ${runMutation.isPending ? 'animate-pulse' : ''}`} />
          {runMutation.isPending ? 'Verifying live site…' : 'Run Verification'}
        </Button>
      </div>

      {!hasRun ? (
        <div className="rounded-xl border bg-card p-8 text-center text-sm text-muted-foreground">
          No verification yet. Approve a review (or click “Run Verification”) to measure the live site.
        </div>
      ) : (
        <>
          {/* Deployment + verification status */}
          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat icon={<Rocket className="h-4 w-4" />} label="Verification" value={<StatusPill status={dv?.status} />} />
            <Stat icon={<Rocket className="h-4 w-4" />} label="Deployment" value={<StatusPill status={dv?.deployment_status} />} />
            <Stat icon={<Rocket className="h-4 w-4" />} label="Provider" value={dv?.deployment_provider ?? '—'} />
            <Stat icon={<Search className="h-4 w-4" />} label="Search Console" value={<StatusPill status={dv?.gsc_status} />} />
          </section>

          {/* Live site */}
          <section className="rounded-xl border bg-card p-4">
            <h3 className="text-sm font-semibold text-slate-950">Live Site Verification</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              {dv?.live_site?.reachable ? (
                <>Reachable · HTTP {dv?.live_site?.http_status} · {dv?.live_site?.passed_count} checks passed{dv?.live_site?.url ? ` · ${dv.live_site.url}` : ''}</>
              ) : <span className="text-rose-600">Site unreachable{dv?.live_site?.error ? ` — ${dv.live_site.error}` : ''}</span>}
            </p>
          </section>

          {/* Before vs After (measured) */}
          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-950"><Gauge className="h-4 w-4" /> Before vs After (measured)</h3>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <BeforeAfter label="SEO score" cell={seoScore} />
              <BeforeAfter label="Performance" cell={cwv['performance']} />
              <BeforeAfter label="LCP" cell={cwv['lcp_ms']} unit="ms" />
              <BeforeAfter label="CLS" cell={cwv['cls']} />
              <BeforeAfter label="INP" cell={cwv['inp_ms']} unit="ms" />
              <BeforeAfter label="FCP" cell={cwv['fcp_ms']} unit="ms" />
              <BeforeAfter label="Accessibility" cell={cwv['accessibility']} />
              <BeforeAfter label="Best practices" cell={cwv['best_practices']} />
            </div>
          </section>

          {/* SEO dimension comparison */}
          <section className="rounded-xl border bg-card p-4">
            <h3 className="text-sm font-semibold text-slate-950">SEO Signals (measured on the live site)</h3>
            <div className="mt-3 flex flex-wrap gap-2">
              {(['metadata', 'canonical', 'robots', 'sitemap', 'structured_data', 'open_graph'] as const).map((k) => (
                <span key={k} className="flex items-center gap-1.5 text-xs">
                  <span className="text-slate-600">{k.replace(/_/g, ' ')}</span>
                  <Verdict v={(seoCmp[k] as string) ?? 'no_data'} />
                </span>
              ))}
            </div>
          </section>

          {/* Learning outcome */}
          {dv?.learning_outcome ? (
            <section className="rounded-xl border bg-card p-4">
              <h3 className="text-sm font-semibold text-slate-950">Learning (evidence-based)</h3>
              <p className="mt-1 text-sm text-slate-700">
                Direction <b>{dv.learning_outcome.direction}</b> ({(dv.learning_outcome.confidence_delta ?? 0) >= 0 ? '+' : ''}{dv.learning_outcome.confidence_delta}) — {dv.learning_outcome.reason}
                <span className="ml-2 rounded bg-emerald-50 px-1.5 py-0.5 text-xs text-emerald-700">real evidence</span>
              </p>
            </section>
          ) : null}

          {/* Activity timeline */}
          <section className="rounded-xl border bg-card p-4">
            <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-950"><Activity className="h-4 w-4" /> Activity Timeline</h3>
            <ol className="space-y-2">
              {timeline.map((e, i) => (
                <li key={i} className="flex items-start gap-3 text-sm">
                  <span className="mt-0.5 font-mono text-xs text-muted-foreground">{new Date(e.time).toLocaleTimeString()}</span>
                  <span className="text-slate-800">{e.event}</span>
                </li>
              ))}
            </ol>
          </section>
        </>
      )}
    </div>
  );
}

function Stat({ icon, label, value }: { icon: ReactNode; label: string; value: ReactNode }) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">{icon}{label}</p>
      <div className="mt-1 text-lg font-semibold text-slate-900">{value}</div>
    </div>
  );
}
