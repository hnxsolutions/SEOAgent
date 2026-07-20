'use client';

import type { ReactNode } from 'react';
import { Cpu, RefreshCw, ShieldCheck, Gauge, Search, Eye, Layers } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { Button } from '@/components/ui/button';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi } from '@/lib/dashboard-api';
import type { TechnologyFingerprint, TechnologyItem } from '@/types/dashboard';

// Business-friendly labels for the raw detector categories.
const CATEGORY_LABELS: Record<string, string> = {
  framework: 'Frontend Framework',
  js_framework: 'JavaScript Library',
  cms: 'CMS',
  language: 'Language',
  rendering: 'Rendering',
  backend_framework: 'Backend',
  web_server: 'Web Server',
  hosting: 'Deployment / Hosting',
  cdn: 'CDN',
  image_system: 'Images',
  analytics: 'Analytics',
  seo: 'SEO',
  schema: 'Structured Data',
  robots: 'Robots',
  sitemap: 'Sitemap',
  caching: 'Caching',
  security: 'Security',
  fonts: 'Fonts',
  styling: 'Styling',
  build_system: 'Build System',
  package_manager: 'Package Manager',
};

const CATEGORY_ORDER = [
  'framework', 'js_framework', 'cms', 'language', 'rendering', 'backend_framework',
  'web_server', 'hosting', 'cdn', 'image_system', 'styling', 'fonts', 'build_system',
  'package_manager', 'seo', 'schema', 'robots', 'sitemap', 'analytics', 'caching', 'security',
];

function scoreTone(v?: number) {
  if (v == null) return 'text-slate-500';
  if (v >= 85) return 'text-emerald-600';
  if (v >= 60) return 'text-amber-600';
  return 'text-rose-600';
}
function barTone(v?: number) {
  if (v == null) return 'bg-slate-300';
  if (v >= 85) return 'bg-emerald-500';
  if (v >= 60) return 'bg-amber-500';
  return 'bg-rose-500';
}

function Readiness({ icon, label, value }: { icon: ReactNode; label: string; value?: number }) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground">{icon}{label}</span>
        <span className={`text-lg font-semibold ${scoreTone(value)}`}>{value != null ? `${value}%` : '—'}</span>
      </div>
      <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full rounded-full ${barTone(value)}`} style={{ width: `${Math.max(0, Math.min(100, value ?? 0))}%` }} />
      </div>
    </div>
  );
}

function ConfidenceBadge({ value }: { value: number }) {
  const tone = value >= 85 ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
    : value >= 60 ? 'bg-amber-50 text-amber-700 border-amber-200'
    : 'bg-slate-50 text-slate-600 border-slate-200';
  return <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${tone}`}>{value}%</span>;
}

function TechCard({ category, items }: { category: string; items: TechnologyItem[] }) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {CATEGORY_LABELS[category] ?? category}
      </h3>
      <ul className="mt-2 space-y-2">
        {items.map((t, i) => (
          <li key={`${t.name}-${i}`}>
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 font-medium text-slate-900">
                <span className="text-emerald-600">✓</span>
                {t.name}{t.version ? ` ${t.version}` : ''}
              </span>
              <ConfidenceBadge value={t.confidence} />
            </div>
            {t.evidence?.length ? (
              <p className="mt-0.5 pl-5 text-xs text-muted-foreground" title={t.evidence.join(' · ')}>
                {t.evidence[0]}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function TechnologyPage() {
  const { projectId } = useDashboardProject();
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ['technology', projectId],
    queryFn: () => dashboardApi.technology.get(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const analyzeMutation = useMutation({
    mutationFn: () => dashboardApi.technology.analyze(projectId!, true),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['technology', projectId] });
    },
  });

  if (!projectId) {
    return <EmptyState title="Select a project" description="Choose a project to see its technology stack." />;
  }
  if (query.isLoading) return <LoadingBlock label="Loading technology…" />;
  if (query.isError) {
    return (
      <ErrorState
        title="Technology could not load"
        message="The fingerprint API may be unavailable."
        onRetry={() => void query.refetch()}
      />
    );
  }

  const data = query.data as TechnologyFingerprint | undefined;
  const detected = data?.detected && (data?.technologies?.length ?? 0) > 0;
  const byCategory = data?.by_category ?? {};
  const orderedCats = [
    ...CATEGORY_ORDER.filter((c) => byCategory[c]?.length),
    ...Object.keys(byCategory).filter((c) => !CATEGORY_ORDER.includes(c)),
  ];
  const scores = data?.scores ?? {};

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-2xl font-semibold tracking-normal text-slate-950">
            <Cpu className="h-6 w-6" /> Website Technology
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            What your website is built with — detected automatically from the live site. Used to choose
            SEO-safe improvements. This never changes your design, content, or functionality.
          </p>
        </div>
        <Button type="button" onClick={() => analyzeMutation.mutate()} disabled={analyzeMutation.isPending}>
          <RefreshCw className={`mr-2 h-4 w-4 ${analyzeMutation.isPending ? 'animate-spin' : ''}`} />
          {analyzeMutation.isPending ? 'Analyzing…' : 'Re-analyze Technology'}
        </Button>
      </div>

      {analyzeMutation.isError ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          Analysis failed. The site may be unreachable. Try again.
        </div>
      ) : null}

      {!detected ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-6 text-center text-sm text-amber-900">
          <p className="font-medium">Technology not analyzed yet.</p>
          <p className="mt-1">{data?.note ?? 'Click “Re-analyze Technology” to detect your website’s stack.'}</p>
        </div>
      ) : (
        <>
          {/* Headline stack summary */}
          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Metric label="Framework" value={data?.primary_framework ?? '—'} />
            <Metric label="CMS" value={data?.primary_cms ?? 'None'} />
            <Metric label="Language" value={data?.primary_language ?? '—'} />
            <Metric label="Hosting" value={data?.hosting ?? '—'} />
            <Metric label="CDN" value={data?.cdn ?? '—'} />
            <Metric label="Rendering" value={data?.rendering ?? '—'} />
            <Metric label="Source" value={data?.source === 'hybrid' ? 'Site + Repository' : 'Live Site'} />
            <Metric label="Analyzed" value={data?.detected_at ? new Date(data.detected_at).toLocaleDateString() : '—'} />
          </section>

          {/* Readiness scores */}
          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Readiness icon={<Layers className="h-4 w-4" />} label="Framework Health" value={scores.framework_health} />
            <Readiness icon={<Search className="h-4 w-4" />} label="SEO Readiness" value={scores.seo_readiness} />
            <Readiness icon={<Gauge className="h-4 w-4" />} label="Performance" value={scores.performance_readiness} />
            <Readiness icon={<Eye className="h-4 w-4" />} label="Accessibility" value={scores.accessibility} />
            <Readiness icon={<ShieldCheck className="h-4 w-4" />} label="Security" value={scores.security} />
            <Readiness icon={<Search className="h-4 w-4" />} label="Indexability" value={scores.indexability} />
          </section>

          {/* Full stack cards */}
          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {orderedCats.map((cat) => (
              <TechCard key={cat} category={cat} items={byCategory[cat]} />
            ))}
          </section>
        </>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 truncate text-lg font-semibold text-slate-900" title={typeof value === 'string' ? value : undefined}>{value}</p>
    </div>
  );
}
