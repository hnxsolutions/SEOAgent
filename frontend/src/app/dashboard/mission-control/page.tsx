'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';
import {
  Activity, CheckCircle2, AlertTriangle, Server, Database, Cpu, Boxes,
  Rocket, ShieldCheck, GitPullRequest, Sparkles, Bell, Clock, Gauge,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { LoadingBlock, ErrorState } from '@/components/dashboard/DashboardStates';
import { dashboardApi } from '@/lib/dashboard-api';

function statusTone(status?: string) {
  if (status === 'ok' || status === 'healthy' || status === 'success' || status === 'verified_success') return 'text-emerald-600 bg-emerald-50 border-emerald-200';
  if (status === 'optional' || status === 'configured' || status === 'partially_successful') return 'text-amber-600 bg-amber-50 border-amber-200';
  if (status === 'down' || status === 'failed' || status === 'degraded') return 'text-rose-600 bg-rose-50 border-rose-200';
  return 'text-slate-600 bg-slate-50 border-slate-200';
}

function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-xl border bg-card p-5 ${className}`}>{children}</div>;
}

function Metric({ label, value, sub, tone = 'text-foreground' }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string }) {
  return (
    <div className="rounded-xl border p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${tone}`}>{value}</p>
      {sub ? <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p> : null}
    </div>
  );
}

const INFRA_ICONS: Record<string, ReactNode> = {
  database: <Database className="h-4 w-4" />,
  redis: <Boxes className="h-4 w-4" />,
  qdrant: <Boxes className="h-4 w-4" />,
  ollama: <Cpu className="h-4 w-4" />,
  backend: <Server className="h-4 w-4" />,
};

const PENDING_LINKS: Record<string, string> = {
  pending_ai_fixes: '/dashboard/pending-fixes',
  open_pull_requests: '/dashboard/repos',
  pending_verification: '/dashboard/verification',
  needs_human_review: '/dashboard/verification',
};

export default function MissionControlPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['mission-control'],
    queryFn: () => dashboardApi.missionControl.overview(),
    refetchInterval: 15000,
  });

  if (isLoading) return <LoadingBlock label="Loading Mission Control" />;
  if (isError || !data) return <ErrorState title="Could not load Mission Control" message="Try again shortly." />;

  const act = data.current_activity;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold">
            <Gauge className="h-6 w-6 text-indigo-600" /> Mission Control
          </h1>
          <p className="text-sm text-muted-foreground">Live system overview · refreshes every 15s</p>
        </div>
        <span className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm font-medium ${statusTone(data.system_health.status)}`}>
          {data.system_health.status === 'healthy' ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
          System {data.system_health.status}
        </span>
      </header>

      {/* Headline metrics */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Metric label="AI Health Score" value={data.ai_health_score ?? '—'} tone={Number(data.ai_health_score) >= 80 ? 'text-emerald-600' : Number(data.ai_health_score) >= 60 ? 'text-amber-600' : 'text-rose-600'} sub="0–100" />
        <Metric label="Overall Health" value={data.overall_health ?? '—'} tone={Number(data.overall_health) >= 80 ? 'text-emerald-600' : Number(data.overall_health) >= 60 ? 'text-amber-600' : 'text-rose-600'} />
        <Metric label="AI Confidence" value={data.ai_confidence != null ? `${data.ai_confidence}%` : '—'} sub={`${data.learning?.finalized ?? 0} verified`} />
        <Metric label="Active Projects" value={data.project_count} />
        <Metric label="Pending AI Fixes" value={data.pending_approvals?.pending_ai_fixes ?? 0} sub="awaiting approval" />
      </div>

      {/* System health pills */}
      <Card>
        <h2 className="mb-3 flex items-center gap-2 font-semibold"><Server className="h-4 w-4" /> System Health</h2>
        <div className="flex flex-wrap gap-2">
          {Object.entries(data.system_health.components).map(([name, c]) => (
            <span key={name} className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm ${statusTone(c.status)}`}>
              {INFRA_ICONS[name] ?? <Server className="h-4 w-4" />} {name}: {c.status}
            </span>
          ))}
        </div>
      </Card>

      {/* Current AI activity */}
      <Card>
        <h2 className="mb-3 flex items-center gap-2 font-semibold"><Activity className="h-4 w-4" /> Current AI Activity</h2>
        {act.active ? (
          <div>
            <p className="text-sm">
              <span className="font-medium">{act.task}</span> on <span className="font-medium">{act.project_name}</span> · stage <span className="font-mono">{act.current_stage}</span>
            </p>
            <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full bg-indigo-500 transition-all" style={{ width: `${act.progress_pct ?? 0}%` }} />
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{act.progress_pct ?? 0}% complete</p>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No active AI task — system idle and monitoring.</p>
        )}
      </Card>

      {/* Pending approvals quick-nav */}
      <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-6">
        {Object.entries(data.pending_approvals).map(([key, val]) => {
          const href = PENDING_LINKS[key];
          const inner = (
            <div className="rounded-xl border p-4 transition hover:border-indigo-300 hover:shadow-sm">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{key.replace(/_/g, ' ')}</p>
              <p className="mt-1 text-2xl font-semibold">{val}</p>
            </div>
          );
          return href ? <Link key={key} href={href}>{inner}</Link> : <div key={key}>{inner}</div>;
        })}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Active projects */}
        <Card className="lg:col-span-2">
          <h2 className="mb-3 font-semibold">Active Projects</h2>
          <div className="space-y-3">
            {data.projects.map((p) => (
              <div key={p.project_id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3">
                <div>
                  <p className="font-medium">{p.name}</p>
                  <p className="text-xs text-muted-foreground">{p.domain}</p>
                </div>
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="rounded-full border bg-slate-50 px-2 py-0.5">SEO {p.seo_score ?? '—'}</span>
                  <span className="rounded-full border bg-slate-50 px-2 py-0.5">{p.pending_fixes} fixes</span>
                  <span className="rounded-full border bg-slate-50 px-2 py-0.5">{p.open_prs} PRs</span>
                  {p.last_deployment ? <span className={`rounded-full border px-2 py-0.5 ${statusTone(p.last_deployment)}`}>deploy {p.last_deployment}</span> : null}
                  {p.last_verification ? <span className={`rounded-full border px-2 py-0.5 ${statusTone(p.last_verification)}`}>verify {p.last_verification}</span> : null}
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Notifications */}
        <Card>
          <h2 className="mb-3 flex items-center gap-2 font-semibold">
            <Bell className="h-4 w-4" /> Notifications
            {data.notifications.unread_count ? <span className="rounded-full bg-rose-100 px-2 text-xs text-rose-700">{data.notifications.unread_count}</span> : null}
          </h2>
          {data.notifications.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">No notifications.</p>
          ) : (
            <ul className="space-y-2">
              {data.notifications.items.slice(0, 6).map((n) => (
                <li key={n.id} className={`rounded-lg border p-2 text-sm ${statusTone(n.level === 'critical' ? 'failed' : n.level === 'warning' ? 'optional' : 'ok')}`}>
                  <p className="font-medium">{n.title}</p>
                  <p className="text-xs text-muted-foreground">{n.message}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {/* AI recommendations */}
      <Card>
        <h2 className="mb-3 flex items-center gap-2 font-semibold"><Sparkles className="h-4 w-4" /> AI Recommendations</h2>
        {data.recommendations.length === 0 ? (
          <p className="text-sm text-muted-foreground">No recommendations right now.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs uppercase text-muted-foreground">
                  <th className="py-2">Action</th><th>Impact</th><th>Traffic</th><th>Difficulty</th><th>Confidence</th><th></th>
                </tr>
              </thead>
              <tbody>
                {data.recommendations.map((r, i) => (
                  <tr key={i} className="border-b last:border-0">
                    <td className="py-2 pr-3 font-medium">{r.title}</td>
                    <td className="capitalize">{r.impact}</td>
                    <td>{r.expected_traffic_gain}</td>
                    <td className="capitalize">{r.difficulty}</td>
                    <td>{r.confidence}%</td>
                    <td>{r.code_fixable ? <Link href="/dashboard/pending-fixes" className="text-indigo-600 hover:underline">Fix</Link> : <Link href="/dashboard/planner" className="text-muted-foreground hover:underline">Plan</Link>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Scheduler telemetry */}
      {data.telemetry ? (
        <Card>
          <h2 className="mb-3 flex items-center gap-2 font-semibold"><Activity className="h-4 w-4" /> Scheduler & Workers (24h)</h2>
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Metric label="Jobs" value={data.telemetry.stats.total} />
            <Metric label="Running" value={data.telemetry.stats.running} tone={data.telemetry.stats.running ? 'text-indigo-600' : 'text-foreground'} />
            <Metric label="Success" value={data.telemetry.stats.success_rate != null ? `${data.telemetry.stats.success_rate}%` : '—'} tone="text-emerald-600" />
            <Metric label="Failure" value={data.telemetry.stats.failure_rate != null ? `${data.telemetry.stats.failure_rate}%` : '—'} tone={Number(data.telemetry.stats.failure_rate) > 0 ? 'text-rose-600' : 'text-foreground'} />
            <Metric label="Retry" value={data.telemetry.stats.retry_rate != null ? `${data.telemetry.stats.retry_rate}%` : '—'} tone="text-amber-600" />
            <Metric label="Avg" value={data.telemetry.stats.average_duration_ms != null ? `${(data.telemetry.stats.average_duration_ms / 1000).toFixed(1)}s` : '—'} />
          </div>
          {data.telemetry.workers.length ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {data.telemetry.workers.map((w) => (
                <span key={w.job_name} className="inline-flex items-center gap-1.5 rounded-full border bg-slate-50 px-3 py-1 text-xs">
                  <span className="font-medium">{w.job_name}</span> · {w.runs} runs
                  {w.avg_duration_ms != null ? ` · ${(w.avg_duration_ms / 1000).toFixed(1)}s` : ''}
                  {w.failed ? <span className="text-rose-600">· {w.failed} failed</span> : null}
                </span>
              ))}
            </div>
          ) : null}
        </Card>
      ) : null}

      {/* Failure center */}
      {data.telemetry && data.telemetry.failures.length > 0 ? (
        <Card className="border-rose-200">
          <h2 className="mb-3 flex items-center gap-2 font-semibold text-rose-700"><AlertTriangle className="h-4 w-4" /> Failure Center</h2>
          <ul className="space-y-2">
            {data.telemetry.failures.map((f) => (
              <li key={f.id} className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{f.job_name}</span>
                  <span className="text-xs text-muted-foreground">retries: {f.retry_count}</span>
                </div>
                <p className="mt-1 text-xs text-rose-700">{f.error_message ?? 'Unknown error'}</p>
                <p className="mt-1 text-xs text-muted-foreground">Auto-retry applies to transient failures; deterministic errors need a fix.</p>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {/* Live activity feed (newest first) */}
      {data.telemetry && data.telemetry.recent.length > 0 ? (
        <Card>
          <h2 className="mb-3 flex items-center gap-2 font-semibold"><Activity className="h-4 w-4" /> Live Activity (newest first)</h2>
          <ol className="space-y-1.5">
            {data.telemetry.recent.map((j) => (
              <li key={j.id} className="flex items-center gap-3 text-sm">
                <span className="w-14 shrink-0 font-mono text-xs text-muted-foreground">{j.started_at ? new Date(j.started_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—'}</span>
                <span className={`inline-flex h-2 w-2 shrink-0 rounded-full ${j.status === 'completed' ? 'bg-emerald-500' : j.status === 'failed' ? 'bg-rose-500' : j.status === 'running' || j.status === 'retrying' ? 'bg-indigo-500' : 'bg-slate-400'}`} />
                <span className="font-medium">{j.job_name}</span>
                <span className="text-xs text-muted-foreground">{j.status}{j.duration_ms != null ? ` · ${(j.duration_ms / 1000).toFixed(1)}s` : ''}</span>
              </li>
            ))}
          </ol>
        </Card>
      ) : null}

      {/* Summary strip: verification / deployment / learning + timeline */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="mb-3 flex items-center gap-2 font-semibold"><Clock className="h-4 w-4" /> Timeline (last 24h)</h2>
          {data.timeline.length === 0 ? (
            <p className="text-sm text-muted-foreground">No recent events.</p>
          ) : (
            <ol className="space-y-2">
              {data.timeline.map((e, i) => (
                <li key={i} className="flex gap-3 text-sm">
                  <span className="w-12 shrink-0 font-mono text-muted-foreground">{e.time}</span>
                  <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-indigo-500" />
                  {e.event}
                </li>
              ))}
            </ol>
          )}
        </Card>
        <div className="grid grid-cols-2 gap-4">
          <Metric label="Verified Success" value={data.verification.verified_success ?? 0} tone="text-emerald-600" sub={<span className="inline-flex items-center gap-1"><ShieldCheck className="h-3 w-3" /> verification</span>} />
          <Metric label="Needs Review" value={data.verification.needs_human_review ?? 0} tone="text-amber-600" />
          <Metric label="Deployments" value={data.deployment.recent.length} sub={<span className="inline-flex items-center gap-1"><Rocket className="h-3 w-3" /> recent</span>} />
          <Metric label="Open PRs" value={data.pending_approvals.open_pull_requests ?? 0} sub={<span className="inline-flex items-center gap-1"><GitPullRequest className="h-3 w-3" /> to merge</span>} />
        </div>
      </div>
    </div>
  );
}
