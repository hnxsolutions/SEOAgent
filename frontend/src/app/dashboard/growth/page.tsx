'use client';

import type { ReactNode } from 'react';
import { TrendingUp, Search, FileText, Layers, CalendarDays, ShieldCheck } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { Button } from '@/components/ui/button';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi } from '@/lib/dashboard-api';
import type { GrowthKeyword, GrowthGap, GrowthCluster, GrowthBlogPost } from '@/types/dashboard';

function IntentChip({ intent }: { intent: string }) {
  const map: Record<string, string> = {
    transactional: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    commercial: 'border-sky-200 bg-sky-50 text-sky-700',
    local: 'border-violet-200 bg-violet-50 text-violet-700',
    question: 'border-amber-200 bg-amber-50 text-amber-700',
    long_tail: 'border-teal-200 bg-teal-50 text-teal-700',
    brand: 'border-slate-200 bg-slate-100 text-slate-700',
  };
  return <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${map[intent] ?? 'border-slate-200 bg-slate-50 text-slate-600'}`}>{intent.replace(/_/g, ' ')}</span>;
}

function ScoreRing({ value, label }: { value: number | null; label: string }) {
  const v = value ?? 0;
  const tone = v >= 75 ? 'text-emerald-600' : v >= 50 ? 'text-amber-600' : 'text-slate-500';
  return (
    <div className="rounded-xl border bg-card p-4 text-center">
      <div className={`text-3xl font-bold ${tone}`}>{value != null ? value : '—'}</div>
      <div className="mt-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
    </div>
  );
}

export default function GrowthPage() {
  const queryClient = useQueryClient();
  const { projectId } = useDashboardProject();

  const summaryQuery = useQuery({
    queryKey: ['growth-summary', projectId],
    queryFn: () => dashboardApi.growth.summary(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });
  const keywordsQuery = useQuery({
    queryKey: ['growth-keywords', projectId],
    queryFn: () => dashboardApi.growth.keywords(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });
  const clustersQuery = useQuery({
    queryKey: ['growth-clusters', projectId],
    queryFn: () => dashboardApi.growth.clusters(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });
  const roadmapQuery = useQuery({
    queryKey: ['growth-roadmap', projectId],
    queryFn: () => dashboardApi.growth.roadmap(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });
  const eeatQuery = useQuery({
    queryKey: ['growth-eeat', projectId],
    queryFn: () => dashboardApi.growth.eeat(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const analyzeMutation = useMutation({
    mutationFn: () => dashboardApi.growth.analyze(projectId!),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['growth-summary', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['growth-keywords', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['growth-roadmap', projectId] }),
      ]);
    },
  });

  if (summaryQuery.isLoading) return <LoadingBlock label="Analyzing growth opportunities…" />;
  if (summaryQuery.isError) return <ErrorState title="Growth could not load" message="The API may be unavailable." onRetry={() => void summaryQuery.refetch()} />;

  const s = summaryQuery.data;
  const dims = s?.dimensions ?? {};
  const keywords: GrowthKeyword[] = keywordsQuery.data?.keywords ?? [];
  const gaps: GrowthGap[] = s?.content_gaps ?? [];
  const clusters: GrowthCluster[] = clustersQuery.data?.clusters ?? [];
  const roadmap: GrowthBlogPost[] = roadmapQuery.data?.roadmap ?? [];
  const eeat = eeatQuery.data;
  const forecast = s?.traffic_forecast;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-2xl font-semibold text-slate-950">
            <TrendingUp className="h-6 w-6" /> SEO Growth
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Opportunities to grow traffic — keyword discovery, content gaps, topic clusters and a framework-aware blog roadmap. Recommendations only; never edits your site.
          </p>
        </div>
        <Button type="button" onClick={() => analyzeMutation.mutate()} disabled={!projectId || analyzeMutation.isPending}>
          <TrendingUp className={`mr-2 h-4 w-4 ${analyzeMutation.isPending ? 'animate-pulse' : ''}`} />
          {analyzeMutation.isPending ? 'Analyzing…' : 'Analyze Growth'}
        </Button>
      </div>

      {/* Scores */}
      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
        <ScoreRing value={s?.growth_score ?? null} label="Growth Score" />
        <ScoreRing value={dims.keyword_coverage ?? null} label="Keyword Coverage" />
        <ScoreRing value={dims.topic_coverage ?? null} label="Topic Coverage" />
        <ScoreRing value={dims.content_authority ?? null} label="Content Authority" />
        <ScoreRing value={dims.content_pipeline ?? null} label="Content Pipeline" />
        <ScoreRing value={s?.opportunity_score ?? null} label="Opportunity" />
      </section>

      {/* Traffic forecast (estimate) */}
      {forecast ? (
        <section className="rounded-xl border bg-gradient-to-br from-emerald-50 to-white p-4">
          <h3 className="text-sm font-semibold text-slate-950">Traffic Forecast <span className="ml-1 rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-normal text-amber-800">estimate</span></h3>
          <p className="mt-1 text-sm text-slate-700">
            ~<b>{forecast.estimated_monthly_clicks ?? '—'}</b> potential additional monthly clicks across <b>{forecast.keyword_opportunities ?? 0}</b> keyword opportunities · confidence <b>{forecast.confidence ?? '—'}</b>
          </p>
          <p className="mt-1 text-xs text-muted-foreground">{forecast.note}</p>
        </section>
      ) : null}

      {/* Keyword opportunities */}
      <Panel icon={<Search className="h-4 w-4" />} title={`Keyword Opportunities (${keywords.length})`}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="text-left text-xs uppercase text-muted-foreground">
              <tr><th className="pb-2 pr-4">Keyword</th><th className="pb-2 pr-4">Intent</th><th className="pb-2 pr-4">Difficulty</th><th className="pb-2 pr-4">Position</th><th className="pb-2 pr-4">Est. clicks</th><th className="pb-2">Priority</th></tr>
            </thead>
            <tbody>
              {keywords.slice(0, 20).map((k, i) => (
                <tr key={`${k.keyword}-${i}`} className="border-t">
                  <td className="py-2 pr-4 font-medium text-slate-900">{k.keyword}</td>
                  <td className="py-2 pr-4"><IntentChip intent={k.intent} /></td>
                  <td className="py-2 pr-4 text-slate-600">{k.difficulty}</td>
                  <td className="py-2 pr-4 text-slate-600">{k.position ?? '—'}</td>
                  <td className="py-2 pr-4 text-slate-600">{k.estimate?.estimated_monthly_clicks ?? '—'}</td>
                  <td className="py-2 font-semibold text-slate-900">{k.priority}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* Content gaps */}
      <Panel icon={<FileText className="h-4 w-4" />} title={`Content Gaps (${gaps.length})`}>
        <ul className="space-y-2">
          {gaps.map((g, i) => (
            <li key={i} className="flex items-start justify-between gap-3 rounded-lg border p-3">
              <div className="min-w-0">
                <p className="text-sm font-medium text-slate-900">{g.title}</p>
                <p className="text-xs text-muted-foreground">{g.why}</p>
              </div>
              <span className="flex-none rounded-full border bg-slate-50 px-2 py-0.5 text-xs text-slate-600">P{g.priority}</span>
            </li>
          ))}
        </ul>
      </Panel>

      {/* Topic clusters */}
      <Panel icon={<Layers className="h-4 w-4" />} title={`Topic Clusters (${clusters.length})`}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {clusters.map((c, i) => (
            <div key={i} className="rounded-lg border p-3">
              <p className="text-sm font-semibold text-slate-900">{c.pillar_title} <span className="text-xs font-normal text-muted-foreground">· {c.article_count} article(s)</span></p>
              <div className="mt-1 flex flex-wrap gap-1">
                {c.supporting_keywords.slice(0, 6).map((k, j) => (
                  <span key={j} className="rounded bg-slate-50 px-1.5 py-0.5 text-[11px] text-slate-600">{k}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Panel>

      {/* Blog roadmap (framework-aware) */}
      <Panel icon={<CalendarDays className="h-4 w-4" />} title={`Blog Roadmap (${roadmap.length})`}>
        <div className="space-y-2">
          {roadmap.map((p, i) => (
            <div key={i} className="rounded-lg border p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-medium text-slate-900">{p.suggested_title}</p>
                <span className="flex items-center gap-2 text-xs">
                  <IntentChip intent={p.search_intent} />
                  <span className="rounded-full border bg-slate-50 px-2 py-0.5 text-slate-600">P{p.priority}</span>
                </span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                <span className="font-mono">{p.suggested_url}</span> · target: <b>{p.target_keyword}</b> · schema: {p.suggested_schema}
              </p>
            </div>
          ))}
        </div>
      </Panel>

      {/* EEAT */}
      {eeat ? (
        <Panel icon={<ShieldCheck className="h-4 w-4" />} title={`E-E-A-T Authority (${eeat.score}/100)`}>
          <div className="flex flex-wrap gap-2">
            {Object.entries(eeat.checks).map(([k, v]) => (
              <span key={k} className={`rounded-full border px-2 py-0.5 text-xs ${v ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-700'}`}>
                {k.replace(/_/g, ' ')}: {v ? 'yes' : 'no'}
              </span>
            ))}
          </div>
          {eeat.suggestions.length ? (
            <ul className="mt-3 space-y-1">
              {eeat.suggestions.map((sg, i) => <li key={i} className="flex items-start gap-2 text-sm text-slate-700"><span className="mt-0.5 text-emerald-600">→</span>{sg}</li>)}
            </ul>
          ) : null}
        </Panel>
      ) : null}
    </div>
  );
}

function Panel({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border bg-card p-5">
      <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-950">{icon}{title}</h3>
      {children}
    </section>
  );
}
