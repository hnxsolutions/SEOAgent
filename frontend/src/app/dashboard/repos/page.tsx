'use client';

import {
  CheckCircle2,
  FileSearch,
  GitPullRequest,
  Play,
  RefreshCw,
  Wand2,
  XCircle,
} from 'lucide-react';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import type React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ConfirmDialog } from '@/components/dashboard/ConfirmDialog';
import { ActionNotice, EmptyState, ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { PatchDiffViewer } from '@/components/dashboard/PatchDiffViewer';
import { PriorityBadge } from '@/components/dashboard/PriorityBadge';
import { StatusBadge, formatLabel } from '@/components/dashboard/StatusBadge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi, latestPlannerRun } from '@/lib/dashboard-api';
import type { RepoConnection, SeoCodeIssue, SeoCodePatch, UUID } from '@/types/dashboard';

const allFilter = 'all';

export default function RepoPatchesPage() {
  const queryClient = useQueryClient();
  const { projectId } = useDashboardProject();
  const [selectedConnectionId, setSelectedConnectionId] = useState<UUID>();
  const [selectedScanId, setSelectedScanId] = useState<UUID>();
  const [selectedPatch, setSelectedPatch] = useState<SeoCodePatch | null>(null);
  const [patchStatusFilter, setPatchStatusFilter] = useState(allFilter);
  const [issueStatusFilter, setIssueStatusFilter] = useState(allFilter);
  const [localPath, setLocalPath] = useState('');
  const [notice, setNotice] = useState<string>();
  const [actionLoadingId, setActionLoadingId] = useState<UUID>();
  const [applyConfirmOpen, setApplyConfirmOpen] = useState(false);
  const [lastApplyRunId, setLastApplyRunId] = useState<UUID>();

  const connectionsQuery = useQuery({
    queryKey: ['repo-connections', projectId],
    queryFn: () => dashboardApi.repos.connections(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const plannerRunsQuery = useQuery({
    queryKey: ['planner-runs', projectId],
    queryFn: () => dashboardApi.planner.listRuns(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  useEffect(() => {
    if (!selectedConnectionId && connectionsQuery.data?.connections[0]?.id) {
      setSelectedConnectionId(connectionsQuery.data.connections[0].id);
    }
  }, [connectionsQuery.data?.connections, selectedConnectionId]);

  useEffect(() => {
    const plannerScanId = latestPlannerRun(plannerRunsQuery.data?.runs)?.repo_scan_run_id;
    if (!selectedScanId && plannerScanId) {
      setSelectedScanId(plannerScanId);
    }
  }, [plannerRunsQuery.data?.runs, selectedScanId]);

  const scanStatusQuery = useQuery({
    queryKey: ['repo-scan-status', selectedScanId],
    queryFn: () => dashboardApi.repos.scanStatus(selectedScanId!),
    enabled: Boolean(selectedScanId),
    retry: false,
  });

  const issuesQuery = useQuery({
    queryKey: ['repo-issues', selectedScanId],
    queryFn: () => dashboardApi.repos.issues(selectedScanId!),
    enabled: Boolean(selectedScanId),
    retry: false,
  });

  const patchesQuery = useQuery({
    queryKey: ['repo-patches', selectedScanId],
    queryFn: () => dashboardApi.repos.patches(selectedScanId!),
    enabled: Boolean(selectedScanId),
    retry: false,
  });

  const applyRunQuery = useQuery({
    queryKey: ['repo-apply-run', lastApplyRunId],
    queryFn: () => dashboardApi.repos.applyRun(lastApplyRunId!),
    enabled: Boolean(lastApplyRunId),
    retry: false,
  });

  const createConnectionMutation = useMutation({
    mutationFn: () =>
      dashboardApi.repos.createConnection({
        project_id: projectId!,
        provider: 'local',
        local_path: localPath,
        framework: 'nextjs_app_router',
      }),
    onSuccess: async (connection) => {
      setNotice('Repository connection created.');
      setSelectedConnectionId(connection.id);
      setLocalPath('');
      await queryClient.invalidateQueries({ queryKey: ['repo-connections', projectId] });
    },
  });

  const scanMutation = useMutation({
    mutationFn: () => dashboardApi.repos.scan(selectedConnectionId!),
    onSuccess: async (scan) => {
      setNotice(`Scan completed with ${scan.issues_found} issues.`);
      setSelectedScanId(scan.id);
      await invalidateRepoScan(scan.id, queryClient);
    },
  });

  const generatePatchesMutation = useMutation({
    mutationFn: () => dashboardApi.repos.generatePatches(selectedScanId!),
    onSuccess: async (result) => {
      setNotice(`${result.patches_created} reviewable patches generated.`);
      await invalidateRepoScan(selectedScanId, queryClient);
    },
  });

  const patchActionMutation = useMutation({
    mutationFn: async ({ patchId, action }: { patchId: UUID; action: string }) => {
      setActionLoadingId(patchId);
      if (action === 'approve') return dashboardApi.repos.approvePatch(patchId);
      return dashboardApi.repos.rejectPatch(patchId);
    },
    onSuccess: async (patch) => {
      setSelectedPatch(patch);
      setNotice('Patch status updated.');
      await invalidateRepoScan(selectedScanId, queryClient);
    },
    onSettled: () => setActionLoadingId(undefined),
  });

  const applyMutation = useMutation({
    mutationFn: () => dashboardApi.repos.applyApproved(selectedScanId!, false, false),
    onSuccess: async (run) => {
      setLastApplyRunId(run.id);
      setNotice(`Patch apply run ${run.status}: ${run.patches_applied} applied.`);
      setApplyConfirmOpen(false);
      await invalidateRepoScan(selectedScanId, queryClient);
    },
  });

  const createPrMutation = useMutation({
    mutationFn: () => dashboardApi.repos.createPr(lastApplyRunId!),
    onSuccess: (pr) => {
      setNotice(pr.pr_url ? `Draft PR record created: ${pr.pr_url}` : 'Draft PR record created.');
    },
  });

  const selectedConnection = connectionsQuery.data?.connections.find(
    (connection) => connection.id === selectedConnectionId
  );

  const issues = useMemo(() => {
    return (issuesQuery.data?.issues ?? []).filter(
      (issue) => issueStatusFilter === allFilter || issue.status === issueStatusFilter
    );
  }, [issueStatusFilter, issuesQuery.data?.issues]);

  const patches = useMemo(() => {
    return (patchesQuery.data?.patches ?? []).filter(
      (patch) => patchStatusFilter === allFilter || patch.status === patchStatusFilter
    );
  }, [patchStatusFilter, patchesQuery.data?.patches]);

  useEffect(() => {
    if (!selectedPatch && patches[0]) {
      setSelectedPatch(patches[0]);
    }
  }, [patches, selectedPatch]);

  if (!projectId) {
    return <EmptyState title="Select a project" description="Repository scanning is scoped to one project." />;
  }

  if (connectionsQuery.isLoading) return <LoadingBlock label="Loading repository console" />;

  if (connectionsQuery.isError) {
    return (
      <ErrorState
        title="Repository connections could not load"
        message="The repo code agent endpoint returned an error."
        onRetry={() => void connectionsQuery.refetch()}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-normal text-slate-950">
            Repo Patches
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Scan Next.js repositories, review SEO-only patches, apply approved fixes, and create draft PR records.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            void connectionsQuery.refetch();
            void issuesQuery.refetch();
            void patchesQuery.refetch();
          }}
        >
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh
        </Button>
      </div>

      <ActionNotice message={notice} />
      {createConnectionMutation.isError || scanMutation.isError || applyMutation.isError || createPrMutation.isError ? (
        <ActionNotice message="The last repository action failed. Check the backend logs for details." tone="error" />
      ) : null}

      <section className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
        <div className="rounded-lg border bg-white">
          <div className="border-b px-5 py-4">
            <h3 className="text-base font-semibold text-slate-950">Repo connections</h3>
          </div>
          <div className="space-y-4 p-5">
            <form className="space-y-3" onSubmit={handleCreateConnection}>
              <Input
                value={localPath}
                onChange={(event) => setLocalPath(event.target.value)}
                placeholder="C:\\path\\to\\nextjs-site"
              />
              <Button
                type="submit"
                disabled={createConnectionMutation.isPending || !localPath.trim()}
              >
                <FileSearch className="mr-2 h-4 w-4" />
                Add local repo
              </Button>
            </form>

            <div className="space-y-2">
              {(connectionsQuery.data?.connections ?? []).map((connection) => (
                <ConnectionButton
                  key={connection.id}
                  connection={connection}
                  active={connection.id === selectedConnectionId}
                  onClick={() => setSelectedConnectionId(connection.id)}
                />
              ))}
              {!connectionsQuery.data?.connections.length ? (
                <p className="text-sm text-muted-foreground">No repository connections yet.</p>
              ) : null}
            </div>
          </div>
        </div>

        <div className="rounded-lg border bg-white">
          <div className="flex flex-col gap-3 border-b px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h3 className="text-base font-semibold text-slate-950">Scan status</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                {selectedConnection?.local_path ?? selectedConnection?.repo_url ?? 'Select a repository.'}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                onClick={() => scanMutation.mutate()}
                disabled={!selectedConnectionId || scanMutation.isPending}
              >
                <Play className="mr-2 h-4 w-4" />
                Scan repo
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => generatePatchesMutation.mutate()}
                disabled={!selectedScanId || generatePatchesMutation.isPending}
              >
                <Wand2 className="mr-2 h-4 w-4" />
                Generate patches
              </Button>
            </div>
          </div>
          <div className="grid gap-4 p-5 sm:grid-cols-4">
            <ScanStat label="Status" value={<StatusBadge status={scanStatusQuery.data?.status} />} />
            <ScanStat label="Framework" value={scanStatusQuery.data?.framework_detected ?? 'Unknown'} />
            <ScanStat label="Files" value={scanStatusQuery.data?.files_scanned ?? 0} />
            <ScanStat label="Issues" value={scanStatusQuery.data?.issues_found ?? 0} />
          </div>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[0.42fr_0.58fr]">
        <div className="space-y-4">
          <div className="rounded-lg border bg-white">
            <div className="flex items-center justify-between gap-3 border-b px-5 py-4">
              <h3 className="text-base font-semibold text-slate-950">SEO code issues</h3>
              <FilterSelect
                value={issueStatusFilter}
                onChange={setIssueStatusFilter}
                options={issueStatusOptions}
              />
            </div>
            <IssueList issues={issues} isLoading={issuesQuery.isLoading} />
          </div>

          <div className="rounded-lg border bg-white">
            <div className="flex items-center justify-between gap-3 border-b px-5 py-4">
              <h3 className="text-base font-semibold text-slate-950">Patch queue</h3>
              <FilterSelect
                value={patchStatusFilter}
                onChange={setPatchStatusFilter}
                options={patchStatusOptions}
              />
            </div>
            <PatchList
              patches={patches}
              selectedPatchId={selectedPatch?.id}
              actionLoadingId={actionLoadingId}
              onSelect={setSelectedPatch}
              onApprove={(patchId) => patchActionMutation.mutate({ patchId, action: 'approve' })}
              onReject={(patchId) => patchActionMutation.mutate({ patchId, action: 'reject' })}
            />
          </div>
        </div>

        <div className="space-y-4">
          <PatchDiffViewer patch={selectedPatch} />
          <div className="rounded-lg border bg-white p-5">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h3 className="text-base font-semibold text-slate-950">Apply and PR controls</h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  Approved patches are applied only after confirmation. Draft PR creation is a separate explicit action.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  onClick={() => setApplyConfirmOpen(true)}
                  disabled={!selectedScanId || applyMutation.isPending}
                >
                  Apply approved patches
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => createPrMutation.mutate()}
                  disabled={!lastApplyRunId || createPrMutation.isPending}
                >
                  <GitPullRequest className="mr-2 h-4 w-4" />
                  Create draft PR
                </Button>
              </div>
            </div>
            {applyRunQuery.data ? (
              <div className="mt-5 rounded-md border bg-slate-50 p-4 text-sm">
                <div className="flex flex-wrap items-center gap-3">
                  <StatusBadge status={applyRunQuery.data.status} />
                  <span>{applyRunQuery.data.branch_name ?? 'No branch recorded'}</span>
                  <span>{applyRunQuery.data.patches_applied} applied</span>
                  <span>{applyRunQuery.data.patches_failed} failed</span>
                </div>
                {applyRunQuery.data.git_diff_summary ? (
                  <pre className="mt-3 max-h-40 overflow-auto whitespace-pre-wrap text-xs text-slate-700">
                    {applyRunQuery.data.git_diff_summary}
                  </pre>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      </section>

      <ConfirmDialog
        open={applyConfirmOpen}
        onOpenChange={setApplyConfirmOpen}
        title="Apply approved SEO patches?"
        description="This writes approved low-risk patches to the connected local repository on a controlled branch. Rejected and unapproved patches are skipped."
        confirmLabel="Apply approved patches"
        isWorking={applyMutation.isPending}
        onConfirm={() => applyMutation.mutate()}
      />
    </div>
  );

  function handleCreateConnection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    createConnectionMutation.mutate();
  }
}

function ConnectionButton({
  connection,
  active,
  onClick,
}: {
  connection: RepoConnection;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full rounded-md border px-3 py-3 text-left text-sm transition-colors ${
        active ? 'border-blue-300 bg-blue-50' : 'bg-white hover:bg-slate-50'
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium text-slate-950">{connection.provider}</span>
        <StatusBadge status={connection.status} />
      </div>
      <p className="mt-1 break-words text-muted-foreground">
        {connection.local_path ?? connection.repo_url ?? 'No path recorded'}
      </p>
    </button>
  );
}

function ScanStat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-sm text-muted-foreground">{label}</p>
      <div className="mt-2 text-lg font-semibold text-slate-950">{value}</div>
    </div>
  );
}

function IssueList({ issues, isLoading }: { issues: SeoCodeIssue[]; isLoading?: boolean }) {
  if (isLoading) return <div className="p-5"><LoadingBlock label="Loading issues" /></div>;
  if (issues.length === 0) {
    return <div className="p-5 text-sm text-muted-foreground">No issues match this filter.</div>;
  }
  return (
    <div className="divide-y">
      {issues.map((issue) => (
        <div key={issue.id} className="px-5 py-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-slate-950">{issue.title}</p>
              <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{issue.description}</p>
            </div>
            <PriorityBadge priority={severityToPriority(issue.severity)} />
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <StatusBadge status={issue.status} />
            <span className="text-xs capitalize text-muted-foreground">
              {formatLabel(issue.issue_type)}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

function PatchList({
  patches,
  selectedPatchId,
  actionLoadingId,
  onSelect,
  onApprove,
  onReject,
}: {
  patches: SeoCodePatch[];
  selectedPatchId?: UUID;
  actionLoadingId?: UUID;
  onSelect: (_patch: SeoCodePatch) => void;
  onApprove: (_patchId: UUID) => void;
  onReject: (_patchId: UUID) => void;
}) {
  if (patches.length === 0) {
    return <div className="p-5 text-sm text-muted-foreground">No patches match this filter.</div>;
  }
  return (
    <div className="divide-y">
      {patches.map((patch) => (
        <div
          key={patch.id}
          className={`px-5 py-4 ${selectedPatchId === patch.id ? 'bg-blue-50' : ''}`}
        >
          <button type="button" className="block w-full text-left" onClick={() => onSelect(patch)}>
            <p className="truncate text-sm font-medium text-slate-950">{patch.file_path}</p>
            <p className="mt-1 text-sm text-muted-foreground">{formatLabel(patch.patch_type)}</p>
          </button>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <StatusBadge status={patch.status} />
              <PriorityBadge priority={patch.risk_level === 'high' ? 'high' : patch.risk_level === 'medium' ? 'medium' : 'low'} />
            </div>
            <div className="flex gap-2">
              <Button
                type="button"
                size="icon"
                variant="outline"
                className="h-8 w-8"
                title="Approve patch"
                aria-label="Approve patch"
                onClick={() => onApprove(patch.id)}
                disabled={actionLoadingId === patch.id}
              >
                <CheckCircle2 className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                size="icon"
                variant="outline"
                className="h-8 w-8"
                title="Reject patch"
                aria-label="Reject patch"
                onClick={() => onReject(patch.id)}
                disabled={actionLoadingId === patch.id}
              >
                <XCircle className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function FilterSelect({
  value,
  options,
  onChange,
}: {
  value: string;
  options: string[];
  onChange: (_value: string) => void;
}) {
  return (
    <select
      className="h-9 rounded-md border bg-white px-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-ring"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      aria-label="Filter"
    >
      <option value={allFilter}>All</option>
      {options.map((option) => (
        <option key={option} value={option}>
          {formatLabel(option)}
        </option>
      ))}
    </select>
  );
}

function severityToPriority(severity: string) {
  if (severity === 'critical') return 'critical';
  if (severity === 'high') return 'high';
  if (severity === 'medium') return 'medium';
  return 'low';
}

async function invalidateRepoScan(scanId: UUID | undefined, queryClient: ReturnType<typeof useQueryClient>) {
  if (!scanId) return;
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ['repo-scan-status', scanId] }),
    queryClient.invalidateQueries({ queryKey: ['repo-issues', scanId] }),
    queryClient.invalidateQueries({ queryKey: ['repo-patches', scanId] }),
  ]);
}

const issueStatusOptions = ['open', 'approved', 'rejected', 'fixed'];
const patchStatusOptions = ['proposed', 'approved', 'rejected', 'applied'];
