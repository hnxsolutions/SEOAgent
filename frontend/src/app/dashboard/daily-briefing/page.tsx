'use client';

import type { ReactNode } from 'react';
import { Activity, TrendingUp, TrendingDown, Minus, Rocket, ShieldCheck, Sparkles, Clock } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { EmptyState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { Button } from '@/components/ui/button';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi } from '@/lib/dashboard-api';

function StatCard({ label, value, sub, tone = 'default' }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string }) {
  const tones: Record<string, string> = {
    default: 'border-border',
    good: 'border-emerald-200 bg-emerald-50/50',
    warn: 'border-amber-200 bg-amber-50/50',
    bad: 'border-rose-200 bg-rose-50/50',
  };
  return (
    <div className={`rounded-xl border p-4 ${tones[tone] ?? tones.default}`}>
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
      {sub ? <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p> : null}
    </div>
  );
}

function TrendIcon({ trend }: { trend?: string }) {
  if (trend === 'up') return <TrendingUp className="h-4 w-4 text-emerald-600" />;
  if (trend === 'down') return <TrendingDown className="h-4 w-4 text-rose-600" />;
  return <Minus className="h-4 w-4 text-muted-foreground" />;
}

export default function DailyBriefingPage() {
  const { projectId, isLoading: projectLoading } = useDashboardProject();
  const queryClient = useQueryClient();

  const briefingQuery = useQuery({
    queryKey: ['briefing', projectId],
    queryFn: () => dashboardApi.briefing.latest(projectId as string),
    enabled: Boolean(projectId),
    retry: false,
  });
  const trendsQuery = useQuery({
    queryKey: ['briefing-trends', projectId],
    queryFn: () => dashboardApi.briefing.trends(projectId as string, 30),
    enabled: Boolean(projectId),
  });

  const generate = useMutation({
    mutationFn: () => dashboardApi.briefing.generate(projectId as string),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['briefing', projectId] });
      queryClient.invalidateQueries({ queryKey: ['briefing-trends', projectId] });
    },
  });

  if (projectLoading) return <LoadingBlock label="Loading briefing" />;
  if (!projectId) return <EmptyState title="No project selected" description="Select a project to view its briefing." />;

  const briefing = briefingQuery.data;
  const s = briefing?.sections ?? {};

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold">
            <Sparkles className="h-6 w-6 text-indigo-600" /> Daily Executive Briefing
          </h1>
          <p className="text-sm text-muted-foreground">
            {briefing ? `For ${briefing.briefing_date}` : 'Your AI-generated CEO view of SEO health.'}
          </p>
        </div>
        <Button onClick={() => generate.mutate()} disabled={generate.isPending}>
          {generate.isPending ? 'Generating…' : 'Generate today’s briefing'}
        </Button>
      </header>

      {briefingQuery.isLoading ? (
        <LoadingBlock label="Loading briefing" />
      ) : !briefing ? (
        <EmptyState
          title="No briefing yet"
          description="Generate today’s executive briefing to see health, trends, timeline and recommendations."
        />
      ) : (
        <>
          {/* Executive summary */}
          <div className="rounded-2xl border bg-gradient-to-br from-indigo-50 to-white p-6">
            <div className="mb-2 flex items-center gap-2 text-sm font-medium text-indigo-700">
              <Activity className="h-4 w-4" /> Executive Summary
              <span className="rounded-full border border-indigo-200 bg-white px-2 py-0.5 text-xs text-indigo-600">
                {briefing.summary_source === 'llm' ? 'AI-written' : 'auto'}
              </span>
            </div>
            <p className="text-base leading-relaxed text-slate-800">{briefing.executive_summary}</p>
          </div>

          {/* Stat cards */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Health Score" value={s.overall_health ?? '—'} tone={Number(s.overall_health) >= 80 ? 'good' : Number(s.overall_health) >= 60 ? 'warn' : 'bad'} />
            <StatCard
              label="SEO Score"
              value={<span className="inline-flex items-center gap-1">{s.seo_score ?? '—'} <TrendIcon trend={s.seo_score_trend} /></span>}
              sub={s.seo_score_prev != null ? `prev ${s.seo_score_prev}` : undefined}
            />
            <StatCard label="AI Confidence" value={s.ai_confidence != null ? `${s.ai_confidence}%` : '—'} sub={`${s.learning?.finalized ?? 0} verified`} />
            <StatCard label="Est. Traffic Gain" value={s.estimated_traffic_gain ?? '—'} sub={`ROI ${s.estimated_roi ?? '—'}`} tone="good" />
          </div>

          {/* Issue buckets */}
          <div className="grid gap-4 sm:grid-cols-4">
            <StatCard label="Critical" value={s.critical_issues ?? 0} tone={s.critical_issues ? 'bad' : 'default'} />
            <StatCard label="Warnings" value={s.warnings ?? 0} tone={s.warnings ? 'warn' : 'default'} />
            <StatCard label="Medium" value={s.medium_issues ?? 0} />
            <StatCard label="Low" value={s.low_issues ?? 0} />
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            {/* Timeline */}
            <section className="rounded-xl border p-5">
              <h2 className="mb-3 flex items-center gap-2 font-semibold"><Clock className="h-4 w-4" /> Timeline (last 24h)</h2>
              {(briefing.timeline ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">No recorded events in the last 24 hours.</p>
              ) : (
                <ol className="space-y-3">
                  {(briefing.timeline ?? []).map((e, i) => (
                    <li key={i} className="flex gap-3">
                      <span className="w-12 shrink-0 text-sm font-mono text-muted-foreground">{e.time}</span>
                      <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-indigo-500" />
                      <span className="text-sm">{e.event}</span>
                    </li>
                  ))}
                </ol>
              )}
            </section>

            {/* Recommended actions + deployments/verification */}
            <section className="space-y-4">
              <div className="rounded-xl border p-5">
                <h2 className="mb-3 font-semibold">Recommended Actions</h2>
                <ul className="space-y-2">
                  {(s.recommended_actions ?? []).map((a: string, i: number) => (
                    <li key={i} className="flex items-start gap-2 text-sm">
                      <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-indigo-500" /> {a}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="rounded-xl border p-4">
                  <p className="flex items-center gap-1.5 text-sm font-medium"><Rocket className="h-4 w-4" /> Deployments</p>
                  <p className="mt-1 text-2xl font-semibold">{(s.deployments ?? []).length}</p>
                  <p className="text-xs text-muted-foreground">
                    {(s.deployments ?? []).filter((d: any) => d.status === 'success').length} successful
                  </p>
                </div>
                <div className="rounded-xl border p-4">
                  <p className="flex items-center gap-1.5 text-sm font-medium"><ShieldCheck className="h-4 w-4" /> Verification</p>
                  <p className="mt-1 text-2xl font-semibold">{s.verification?.recently_verified?.length ?? 0}</p>
                  <p className="text-xs text-muted-foreground">{s.verification?.queue ?? 0} in queue</p>
                </div>
              </div>
            </section>
          </div>

          {/* PRs + learning */}
          <div className="grid gap-4 sm:grid-cols-3">
            <StatCard label="Open Pull Requests" value={s.pull_requests?.open ?? 0} />
            <StatCard label="Merged PRs" value={s.pull_requests?.merged ?? 0} tone="good" />
            <StatCard label="Learning Success Rate" value={s.learning?.success_rate != null ? `${s.learning.success_rate}%` : '—'} sub={`${s.learning?.finalized ?? 0} finalized`} />
          </div>

          {/* Trend history */}
          {trendsQuery.data && trendsQuery.data.count > 1 ? (
            <section className="rounded-xl border p-5">
              <h2 className="mb-3 font-semibold">Health &amp; SEO Score Trend ({trendsQuery.data.window_days}d)</h2>
              <div className="flex items-end gap-1">
                {trendsQuery.data.points.map((p, i) => (
                  <div key={i} className="flex flex-1 flex-col items-center gap-1">
                    <div className="w-full rounded-t bg-indigo-400" style={{ height: `${Math.max(4, Number(p.health ?? 0))}px` }} title={`${p.date}: health ${p.health}`} />
                  </div>
                ))}
              </div>
            </section>
          ) : null}
        </>
      )}
    </div>
  );
}
