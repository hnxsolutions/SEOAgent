'use client';

import { useState } from 'react';
import type { ReactNode } from 'react';
import { Check, X, Code2, GitBranch } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { Button } from '@/components/ui/button';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi } from '@/lib/dashboard-api';
import type { BrainPendingFix } from '@/types/dashboard';

function Chip({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${className}`}>
      {children}
    </span>
  );
}

function FixCard({
  fix,
  onApprove,
  onReject,
  busy,
}: {
  fix: BrainPendingFix;
  onApprove: () => void;
  onReject: () => void;
  busy: boolean;
}) {
  const [showDiff, setShowDiff] = useState(false);
  return (
    <div className="rounded-xl border bg-card p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Code2 className="h-4 w-4 text-indigo-600" />
            <h3 className="font-semibold">{fix.issue.title}</h3>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{fix.reason}</p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" onClick={onApprove} disabled={busy}>
            <Check className="mr-1 h-4 w-4" /> Approve
          </Button>
          <Button size="sm" variant="outline" onClick={onReject} disabled={busy}>
            <X className="mr-1 h-4 w-4" /> Reject
          </Button>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <Chip className="border-indigo-200 bg-indigo-100 text-indigo-800">{fix.patch_type}</Chip>
        <Chip className="border-slate-200 bg-slate-100 text-slate-700">{fix.category}</Chip>
        <Chip className="border-emerald-200 bg-emerald-100 text-emerald-800">traffic {fix.expected_traffic_gain}</Chip>
        <Chip className="border-amber-200 bg-amber-100 text-amber-800">confidence {fix.confidence}%</Chip>
        <Chip className="border-slate-200 bg-slate-100 text-slate-700">risk {fix.risk_level}</Chip>
        <Chip className="border-slate-200 bg-slate-100 text-slate-700">via {fix.issue.source}</Chip>
      </div>

      <dl className="mt-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        <div><dt className="inline text-muted-foreground">SEO impact: </dt><dd className="inline font-medium capitalize">{fix.seo_impact}</dd></div>
        <div><dt className="inline text-muted-foreground">Ranking gain: </dt><dd className="inline font-medium">{fix.expected_ranking_gain}</dd></div>
        <div><dt className="inline text-muted-foreground">Affected files: </dt><dd className="inline font-mono text-xs">{fix.affected_files.join(', ')}</dd></div>
        <div><dt className="inline text-muted-foreground">Issue type: </dt><dd className="inline font-medium">{fix.issue.issue_type}</dd></div>
      </dl>

      <div className="mt-3">
        <button
          className="text-sm font-medium text-indigo-600 hover:underline"
          onClick={() => setShowDiff((v) => !v)}
        >
          {showDiff ? 'Hide diff' : 'View diff (before/after)'}
        </button>
        {showDiff ? (
          <pre className="mt-2 max-h-72 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-100">
            {fix.diff || 'No diff available.'}
          </pre>
        ) : null}
      </div>

      <p className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-2 text-xs text-muted-foreground">
        <span className="font-semibold">Rollback:</span> {fix.rollback_strategy}
      </p>
    </div>
  );
}

export default function PendingFixesPage() {
  const { projectId, isLoading: projectLoading } = useDashboardProject();
  const queryClient = useQueryClient();

  const fixesQuery = useQuery({
    queryKey: ['pending-fixes', projectId],
    queryFn: () => dashboardApi.brain.pendingFixes(projectId as string),
    enabled: Boolean(projectId),
    refetchInterval: 15000,
  });

  const dispatch = useMutation({
    mutationFn: () => dashboardApi.brain.dispatch(projectId as string),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['pending-fixes', projectId] }),
  });

  const approve = useMutation({
    mutationFn: (patchId: string) => dashboardApi.brain.approvePatch(patchId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['pending-fixes', projectId] }),
  });
  const reject = useMutation({
    mutationFn: (patchId: string) => dashboardApi.brain.rejectPatch(patchId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['pending-fixes', projectId] }),
  });

  if (projectLoading || (projectId && fixesQuery.isLoading)) {
    return <LoadingBlock label="Loading pending AI fixes" />;
  }
  if (!projectId) {
    return <EmptyState title="No project selected" description="Select a project to review AI fixes." />;
  }
  if (fixesQuery.isError) {
    return <ErrorState title="Could not load pending fixes" message="Try again shortly." />;
  }

  const data = fixesQuery.data;
  const busy = approve.isPending || reject.isPending;

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold">
            <GitBranch className="h-6 w-6" /> Pending AI Fixes
          </h1>
          <p className="text-sm text-muted-foreground">
            AI-generated patches awaiting your approval. Nothing reaches git until you approve.
          </p>
        </div>
        <Button onClick={() => dispatch.mutate()} disabled={dispatch.isPending}>
          {dispatch.isPending ? 'Dispatching…' : 'Auto-dispatch code fixes'}
        </Button>
      </header>

      {dispatch.data?.status === 'no_repo_connected' ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">
          No repository connected. Connect one to enable automatic code fixes.
        </div>
      ) : null}
      {dispatch.data?.status === 'dispatching' ? (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-800">
          Dispatching to the Repo Agent — patches will appear here shortly.
        </div>
      ) : null}

      {!data || data.items.length === 0 ? (
        <EmptyState
          title="No pending fixes"
          description="Run auto-dispatch to generate code patches for code-fixable issues."
        />
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">{data.total} patch(es) awaiting approval</p>
          {data.items.map((fix) => (
            <FixCard
              key={fix.patch_id}
              fix={fix}
              busy={busy}
              onApprove={() => approve.mutate(fix.patch_id)}
              onReject={() => reject.mutate(fix.patch_id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
