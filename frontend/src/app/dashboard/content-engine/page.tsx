'use client';

import { parseApiDate } from '@/lib/utils';

/**
 * The autonomous content engine, as one screen with tabs.
 *
 * Everything the agent decides about content is visible here and nothing else
 * is: what it wants to write and why, what it refused to write and what to do
 * instead, what it has written that is waiting for a person, what shipped, and
 * what has since declined.
 *
 * Two display rules the backend depends on:
 *
 * - A score is labelled **Opportunity Score**, never "volume". Search volume is
 *   not obtainable for free and is never shown, estimated or implied.
 * - An unmeasured thing says **Not measured**, never 0. A zero reads as a
 *   measurement; the absence of a measurement is a different statement.
 */

import { useState } from 'react';
import {
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  FileText,
  Layers,
  Lightbulb,
  Loader2,
  RefreshCw,
  Sparkles,
  XCircle,
} from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { Button } from '@/components/ui/button';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi } from '@/lib/dashboard-api';
import type {
  ContentClusterView,
  ContentEngineOverview,
  ContentOpportunity,
  ContentSlot,
  ProfileField,
  RefreshProposalView,
  WebsiteProfileView,
} from '@/types/dashboard';

const TABS = [
  { key: 'overview', label: 'Overview', icon: Sparkles },
  { key: 'calendar', label: 'Calendar', icon: CalendarDays },
  { key: 'opportunities', label: 'Opportunities', icon: Lightbulb },
  { key: 'clusters', label: 'Clusters', icon: Layers },
  { key: 'refresh', label: 'Refresh queue', icon: RefreshCw },
  { key: 'knowledge', label: 'Website knowledge', icon: FileText },
] as const;

type TabKey = (typeof TABS)[number]['key'];

/* -------------------------------------------------------------------------- */
/* Small pieces                                                                */
/* -------------------------------------------------------------------------- */

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      <div className="mt-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      {hint ? <div className="mt-1 text-[11px] text-muted-foreground">{hint}</div> : null}
    </div>
  );
}

/** A 0-100 Opportunity Score. Never called volume, because it is not volume. */
function ScoreBadge({ score }: { score: number }) {
  const tone =
    score >= 70 ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
      : score >= 45 ? 'border-amber-200 bg-amber-50 text-amber-700'
        : 'border-slate-200 bg-slate-50 text-slate-600';
  return (
    <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${tone}`} title="Opportunity Score — computed from measured Search Console signals, not search volume">
      {Math.round(score)}/100
    </span>
  );
}

function SourceChip({ field }: { field: ProfileField }) {
  if (field.source === 'user') {
    return <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">Confirmed</span>;
  }
  if (field.source === 'inferred') {
    return (
      <span className="rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-[11px] font-medium text-sky-700" title={field.evidence ?? undefined}>
        Inferred{field.confidence != null ? ` · ${Math.round(field.confidence * 100)}%` : ''}
      </span>
    );
  }
  return <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-500">Unknown</span>;
}

/** Shown wherever nothing was measured. Deliberately not a zero. */
function NotMeasured({ reason }: { reason: string }) {
  return (
    <div className="rounded-xl border border-dashed bg-muted/30 p-4">
      <div className="text-sm font-medium text-muted-foreground">Not measured</div>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">{reason}</p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */

export default function ContentEnginePage() {
  const queryClient = useQueryClient();
  const { projectId } = useDashboardProject();
  const [tab, setTab] = useState<TabKey>('overview');

  const enabled = Boolean(projectId);
  const overview = useQuery({
    queryKey: ['content-overview', projectId],
    queryFn: () => dashboardApi.contentEngine.overview(projectId!),
    enabled,
    retry: false,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['content-overview', projectId] });
    void queryClient.invalidateQueries({ queryKey: ['content-opportunities', projectId] });
    void queryClient.invalidateQueries({ queryKey: ['content-calendar', projectId] });
  };

  const scan = useMutation({
    mutationFn: () => dashboardApi.contentEngine.scan(projectId!),
    onSuccess: invalidate,
  });

  if (!projectId) return <ErrorState message="Select a project to see its content engine." />;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Content engine</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            What the agent wants to write, why, and what it refused to write. Nothing here
            publishes without your approval.
          </p>
        </div>
        <Button onClick={() => scan.mutate()} disabled={scan.isPending} size="sm">
          {scan.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Lightbulb className="mr-2 h-4 w-4" />}
          Scan for opportunities
        </Button>
      </div>

      <div className="no-scrollbar flex gap-1 overflow-x-auto border-b">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`flex shrink-0 items-center gap-1.5 border-b-2 px-3 pb-2 text-sm font-medium transition ${
              tab === key
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {tab === 'overview' && <OverviewTab query={overview} projectId={projectId} />}
      {tab === 'calendar' && <CalendarTab projectId={projectId} onChanged={invalidate} />}
      {tab === 'opportunities' && <OpportunitiesTab projectId={projectId} />}
      {tab === 'clusters' && <ClustersTab projectId={projectId} />}
      {tab === 'refresh' && <RefreshTab projectId={projectId} />}
      {tab === 'knowledge' && <KnowledgeTab projectId={projectId} />}
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function OverviewTab({
  query,
  projectId,
}: {
  query: ReturnType<typeof useQuery<ContentEngineOverview>>;
  projectId: string;
}) {
  const draft = useMutation({
    mutationFn: () => dashboardApi.contentEngine.draftNext(projectId),
  });

  if (query.isLoading) return <LoadingBlock label="Reading the content engine…" />;
  if (query.isError || !query.data) return <ErrorState message="Could not load the content overview." />;

  const d = query.data;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Blogs / week" value={d.blogs_per_week} hint="One slot per article" />
        <Stat label="Topics waiting" value={d.topics_waiting} />
        <Stat label="Drafts" value={d.drafts} />
        <Stat label="Pending approval" value={d.pending_approval} />
        <Stat label="Published" value={d.published} />
        <Stat label="Needs refresh" value={d.refresh_pending} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border bg-card p-4">
          <h2 className="text-sm font-semibold">Next drafting slot</h2>
          {d.next_slot ? (
            <p className="mt-2 text-sm text-muted-foreground">
              <span className="font-medium text-foreground">{d.next_slot.day}</span>
              {d.next_slot.next_run_at ? ` · ${parseApiDate(d.next_slot.next_run_at).toLocaleString()}` : ''}
            </p>
          ) : (
            <p className="mt-2 text-sm text-muted-foreground">
              No drafting slots. Set a cadence on the Calendar tab.
            </p>
          )}

          {d.top_opportunity ? (
            <div className="mt-3 rounded-lg border bg-muted/30 p-3">
              <div className="flex items-start justify-between gap-2">
                <span className="text-sm font-medium">{d.top_opportunity.title}</span>
                <ScoreBadge score={d.top_opportunity.opportunity_score} />
              </div>
              <p className="mt-1 text-xs text-muted-foreground">Highest-scoring topic waiting.</p>
            </div>
          ) : (
            <p className="mt-3 text-xs text-muted-foreground">
              Nothing above the quality bar is queued — the next slot will skip rather than
              write something not worth publishing.
            </p>
          )}

          <Button
            size="sm"
            variant="outline"
            className="mt-3"
            onClick={() => draft.mutate()}
            disabled={draft.isPending}
          >
            {draft.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Draft one now
          </Button>
          {draft.data ? (
            <p className="mt-2 text-xs text-muted-foreground">
              {(draft.data as Record<string, unknown>).drafted
                ? 'Draft created and sent for approval.'
                : String((draft.data as Record<string, unknown>).reason ?? '')}
            </p>
          ) : null}
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border bg-card p-4">
            <h2 className="text-sm font-semibold">Clusters</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              {d.clusters} cluster{d.clusters === 1 ? '' : 's'} · {d.cluster_gaps} gap
              {d.cluster_gaps === 1 ? '' : 's'} with nothing covering them yet.
            </p>
          </div>

          <div>
            <h2 className="mb-2 text-sm font-semibold">AI visibility</h2>
            {/* Never a 0%. See the module docstring. */}
            <NotMeasured reason={d.ai_visibility.reason} />
          </div>
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function CalendarTab({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const query = useQuery({
    queryKey: ['content-calendar', projectId],
    queryFn: () => dashboardApi.contentEngine.calendar(projectId),
    retry: false,
  });
  const cadence = useMutation({
    mutationFn: (count: number) => dashboardApi.contentEngine.setCadence(projectId, count),
    onSuccess: () => {
      void query.refetch();
      onChanged();
    },
  });

  if (query.isLoading) return <LoadingBlock label="Reading the content calendar…" />;
  if (query.isError || !query.data) return <ErrorState message="Could not load the calendar." />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-card p-4">
        <span className="text-sm font-medium">Articles per week</span>
        {[0, 1, 2, 3].map((n) => (
          <Button
            key={n}
            size="sm"
            variant={query.data.blogs_per_week === n ? 'default' : 'outline'}
            onClick={() => cadence.mutate(n)}
            disabled={cadence.isPending}
          >
            {n === 0 ? 'Off' : n}
          </Button>
        ))}
        <span className="ml-2 text-xs text-muted-foreground">
          Each article is its own slot on a different weekday. A slot with nothing worth
          writing skips — that is a correct decision, not a missed deadline.
        </span>
      </div>

      {query.data.slots.length === 0 ? (
        <div className="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">
          No drafting slots configured.
        </div>
      ) : (
        <div className="space-y-2">
          {query.data.slots.map((slot: ContentSlot) => (
            <div key={`${slot.day}-${slot.hour}`} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card p-4">
              <div className="min-w-[8rem]">
                <div className="text-sm font-semibold">{slot.day}</div>
                <div className="text-xs text-muted-foreground">
                  {String(slot.hour).padStart(2, '0')}:00
                  {slot.next_run_at ? ` · next ${parseApiDate(slot.next_run_at).toLocaleDateString()}` : ''}
                </div>
              </div>
              <div className="min-w-0 flex-1">
                {slot.topic ? (
                  <span className="text-sm">{slot.topic}</span>
                ) : (
                  <span className="text-sm text-muted-foreground">{slot.status}</span>
                )}
              </div>
              <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${slot.enabled ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-slate-200 bg-slate-50 text-slate-500'}`}>
                {slot.enabled ? 'Active' : 'Disabled'}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function OpportunitiesTab({ projectId }: { projectId: string }) {
  const query = useQuery({
    queryKey: ['content-opportunities', projectId],
    queryFn: () => dashboardApi.contentEngine.opportunities(projectId),
    retry: false,
  });

  if (query.isLoading) return <LoadingBlock label="Ranking opportunities…" />;
  if (query.isError || !query.data) return <ErrorState message="Could not load opportunities." />;
  if (query.data.topics.length === 0) {
    return (
      <div className="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">
        No topics yet. Run a scan — it reads Search Console queries, your own pages and your
        content gaps. No paid keyword data is used, and no search volume is invented.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {query.data.topics.map((topic: ContentOpportunity) => (
        <div key={topic.id} className="rounded-xl border bg-card p-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="text-sm font-semibold">{topic.title}</div>
              <div className="mt-0.5 text-xs text-muted-foreground">
                {topic.target_keyword} · {topic.search_intent} · {topic.status}
              </div>
            </div>
            <ScoreBadge score={topic.opportunity_score} />
          </div>
          {topic.reason ? (
            <pre className="mt-2 whitespace-pre-wrap font-sans text-xs leading-5 text-muted-foreground">
              {topic.reason}
            </pre>
          ) : null}
        </div>
      ))}
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function ClustersTab({ projectId }: { projectId: string }) {
  const query = useQuery({
    queryKey: ['content-clusters', projectId],
    queryFn: () => dashboardApi.contentEngine.clusters(projectId),
    retry: false,
  });
  const rebuild = useMutation({
    mutationFn: () => dashboardApi.contentEngine.rebuildClusters(projectId),
    onSuccess: () => void query.refetch(),
  });

  if (query.isLoading) return <LoadingBlock label="Building the topic graph…" />;
  if (query.isError || !query.data) return <ErrorState message="Could not load clusters." />;

  return (
    <div className="space-y-3">
      <Button size="sm" variant="outline" onClick={() => rebuild.mutate()} disabled={rebuild.isPending}>
        {rebuild.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Layers className="mr-2 h-4 w-4" />}
        Rebuild clusters
      </Button>

      {query.data.clusters.length === 0 ? (
        <div className="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">
          No clusters yet. They are built from measured opportunities.
        </div>
      ) : (
        query.data.clusters.map((cluster: ContentClusterView) => (
          <div key={cluster.id} className="rounded-xl border bg-card p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-sm font-semibold">{cluster.name}</div>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span>{Math.round(cluster.coverage * 100)}% covered</span>
                {cluster.missing_count > 0 ? (
                  <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 font-medium text-amber-700">
                    {cluster.missing_count} missing
                  </span>
                ) : null}
              </div>
            </div>
            <div className="mt-3 space-y-2">
              {Object.entries(cluster.nodes).map(([type, nodes]) => (
                <div key={type}>
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {type.replace(/_/g, ' ')}
                  </div>
                  <ul className="mt-1 space-y-1">
                    {nodes.map((node) => (
                      <li key={node.id} className="flex items-start justify-between gap-2 text-sm">
                        <span className="min-w-0">{node.title}</span>
                        <span className="shrink-0 text-xs text-muted-foreground">{node.status}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function RefreshTab({ projectId }: { projectId: string }) {
  const query = useQuery({
    queryKey: ['content-refresh', projectId],
    queryFn: () => dashboardApi.contentEngine.refreshProposals(projectId),
    retry: false,
  });
  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) =>
      dashboardApi.contentEngine.actOnProposal(id, action),
    onSuccess: () => void query.refetch(),
  });

  if (query.isLoading) return <LoadingBlock label="Reading the refresh queue…" />;
  if (query.isError || !query.data) return <ErrorState message="Could not load refresh proposals." />;
  if (query.data.proposals.length === 0) {
    return (
      <div className="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">
        Nothing needs refreshing. Proposals appear when a published article measurably
        declines in Search Console.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {query.data.proposals.map((proposal: RefreshProposalView) => (
        <div key={proposal.id} className="rounded-xl border bg-card p-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="text-sm font-semibold">{proposal.title}</div>
              <div className="mt-0.5 text-xs text-muted-foreground">
                {proposal.reason.replace(/_/g, ' ')} · {proposal.status.replace(/_/g, ' ')}
              </div>
            </div>
            <span className="shrink-0 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-700">
              priority {Math.round(proposal.priority)}
            </span>
          </div>

          <p className="mt-2 text-sm text-muted-foreground">{proposal.summary}</p>

          {proposal.proposed_changes.length > 0 ? (
            <ul className="mt-2 space-y-1">
              {proposal.proposed_changes.map((change, index) => (
                <li key={index} className="text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">{change.section}:</span> {change.action} — {change.why}
                </li>
              ))}
            </ul>
          ) : null}

          {proposal.next_actions.length > 0 ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {proposal.next_actions.includes('approved') ? (
                <Button size="sm" onClick={() => act.mutate({ id: proposal.id, action: 'approve' })} disabled={act.isPending}>
                  <CheckCircle2 className="mr-1.5 h-4 w-4" /> Approve
                </Button>
              ) : null}
              {proposal.next_actions.includes('rejected') ? (
                <Button size="sm" variant="outline" onClick={() => act.mutate({ id: proposal.id, action: 'reject' })} disabled={act.isPending}>
                  <XCircle className="mr-1.5 h-4 w-4" /> Reject
                </Button>
              ) : null}
              {proposal.next_actions.includes('applied') ? (
                <Button size="sm" variant="outline" onClick={() => act.mutate({ id: proposal.id, action: 'apply' })} disabled={act.isPending}>
                  Mark applied
                </Button>
              ) : null}
            </div>
          ) : (
            <p className="mt-3 text-xs text-muted-foreground">This proposal is closed.</p>
          )}
        </div>
      ))}
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function KnowledgeTab({ projectId }: { projectId: string }) {
  const query = useQuery({
    queryKey: ['website-profile', projectId],
    queryFn: () => dashboardApi.contentEngine.profile(projectId),
    retry: false,
  });
  const build = useMutation({
    mutationFn: () => dashboardApi.contentEngine.buildProfile(projectId, true),
    onSuccess: () => void query.refetch(),
  });

  if (query.isLoading) return <LoadingBlock label="Reading the website profile…" />;
  if (query.isError) return <ErrorState message="Could not load the website profile." />;

  const data = query.data as WebsiteProfileView | undefined;

  if (!data?.available) {
    return (
      <div className="space-y-3">
        <NotMeasured reason={data?.reason ?? 'No profile has been built yet.'} />
        <Button size="sm" onClick={() => build.mutate()} disabled={build.isPending}>
          {build.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
          Build profile
        </Button>
      </div>
    );
  }

  const fields = data.fields ?? {};

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border bg-card p-4">
        <div className="text-xs text-muted-foreground">
          Version {data.version} · built {data.generated_at ? parseApiDate(data.generated_at).toLocaleString() : '—'}
          {data.used_llm === 'yes' ? ' · local model used for semantic fields' : ' · deterministic extraction only'}
        </div>
        <Button size="sm" variant="outline" onClick={() => build.mutate()} disabled={build.isPending}>
          {build.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
          Re-analyse
        </Button>
      </div>

      <div className="flex items-start gap-2 rounded-xl border border-sky-100 bg-sky-50/60 p-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-sky-600" />
        <p className="text-xs leading-5 text-sky-900">
          <span className="font-medium">Confirmed</span> means you stated it.{' '}
          <span className="font-medium">Inferred</span> is the agent&rsquo;s reading of the site,
          with its confidence. <span className="font-medium">Unknown</span> means neither — not
          that the answer is empty.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {Object.entries(fields).map(([name, field]) => (
          <div key={name} className="rounded-xl border bg-card p-4">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {name.replace(/_/g, ' ')}
              </span>
              <SourceChip field={field} />
            </div>
            <div className="mt-2 text-sm">
              {Array.isArray(field.value)
                ? field.value.length > 0
                  ? (field.value as unknown[]).map(String).join(', ')
                  : <span className="text-muted-foreground">—</span>
                : field.value
                  ? String(field.value)
                  : <span className="text-muted-foreground">—</span>}
            </div>
            {field.evidence ? (
              <div className="mt-1 text-[11px] text-muted-foreground">{field.evidence}</div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
