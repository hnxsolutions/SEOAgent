'use client';

import type { ReactNode } from 'react';
import { Gauge, Zap, AlertTriangle } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { Button } from '@/components/ui/button';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi } from '@/lib/dashboard-api';
import type { PagespeedRun } from '@/types/dashboard';

function scoreTone(v?: number | null) {
  if (v == null) return 'text-slate-500';
  if (v >= 90) return 'text-emerald-600';
  if (v >= 50) return 'text-amber-600';
  return 'text-rose-600';
}

function Metric({ label, value, tone = 'text-foreground' }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div className="rounded-xl border p-4 text-center">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${tone}`}>{value}</p>
    </div>
  );
}

function StrategyCard({ title, run }: { title: string; run: PagespeedRun | null }) {
  if (!run || run.status !== 'completed') {
    return (
      <div className="rounded-xl border bg-card p-5">
        <h3 className="font-semibold">{title}</h3>
        <p className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {run?.status === 'quota_exceeded'
            ? 'PageSpeed quota exceeded — set a free GOOGLE_PAGESPEED_API_KEY.'
            : run?.error_message ?? 'No data yet.'}
        </p>
      </div>
    );
  }
  return (
    <div className="rounded-xl border bg-card p-5">
      <h3 className="mb-3 font-semibold">{title}</h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric label="Performance" value={run.performance_score ?? '—'} tone={scoreTone(run.performance_score)} />
        <Metric label="Accessibility" value={run.accessibility_score ?? '—'} tone={scoreTone(run.accessibility_score)} />
        <Metric label="Best Practices" value={run.best_practices_score ?? '—'} tone={scoreTone(run.best_practices_score)} />
        <Metric label="SEO" value={run.seo_score ?? '—'} tone={scoreTone(run.seo_score)} />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric label="LCP" value={run.lcp_ms != null ? `${(run.lcp_ms / 1000).toFixed(1)}s` : '—'} />
        <Metric label="CLS" value={run.cls ?? '—'} />
        <Metric label="INP" value={run.inp_ms != null ? `${Math.round(run.inp_ms)}ms` : '—'} />
        <Metric label="TBT" value={run.tbt_ms != null ? `${Math.round(run.tbt_ms)}ms` : '—'} />
      </div>
      {run.opportunities && run.opportunities.length > 0 ? (
        <div className="mt-4">
          <h4 className="mb-2 flex items-center gap-1 text-sm font-semibold"><Zap className="h-4 w-4" /> Top Opportunities</h4>
          <ul className="space-y-1.5">
            {run.opportunities.slice(0, 6).map((o, i) => (
              <li key={i} className="flex items-center justify-between rounded-lg border px-3 py-1.5 text-sm">
                <span>{o.title}</span>
                {o.savings_ms ? <span className="text-xs text-emerald-600">save ~{Math.round(o.savings_ms)}ms</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export default function CoreWebVitalsPage() {
  const { projectId, isLoading: projectLoading } = useDashboardProject();
  const queryClient = useQueryClient();

  const latest = useQuery({
    queryKey: ['pagespeed-latest', projectId],
    queryFn: () => dashboardApi.pagespeed.latest(projectId as string),
    enabled: Boolean(projectId),
  });

  const analyze = useMutation({
    mutationFn: () => dashboardApi.pagespeed.analyze(projectId as string),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['pagespeed-latest', projectId] }),
  });

  if (projectLoading || (projectId && latest.isLoading)) return <LoadingBlock label="Loading Core Web Vitals" />;
  if (!projectId) return <EmptyState title="No project selected" description="Select a project to see Core Web Vitals." />;
  if (latest.isError) return <ErrorState title="Could not load Core Web Vitals" message="Try again shortly." />;

  const data = latest.data;
  const hasData = data?.mobile || data?.desktop;

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold"><Gauge className="h-6 w-6" /> Core Web Vitals</h1>
          <p className="text-sm text-muted-foreground">Official Google PageSpeed Insights — mobile &amp; desktop.</p>
        </div>
        <Button onClick={() => analyze.mutate()} disabled={analyze.isPending}>
          {analyze.isPending ? 'Analyzing…' : 'Run PageSpeed analysis'}
        </Button>
      </header>

      {analyze.data?.runs?.some((r) => r.status === 'quota_exceeded') ? (
        <div className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">
          <AlertTriangle className="h-4 w-4" />
          PageSpeed Insights quota exceeded. Add a free <code className="mx-1">GOOGLE_PAGESPEED_API_KEY</code> for reliable live data.
        </div>
      ) : null}

      {!hasData ? (
        <EmptyState title="No Core Web Vitals yet" description="Run a PageSpeed analysis to fetch real mobile &amp; desktop performance." />
      ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          <StrategyCard title="Mobile" run={data?.mobile ?? null} />
          <StrategyCard title="Desktop" run={data?.desktop ?? null} />
        </div>
      )}
    </div>
  );
}
