'use client';

import {
  CheckCircle2,
  Download,
  FilePlus2,
  GitBranch,
  PenLine,
  Play,
  SearchCheck,
  UploadCloud,
  XCircle,
} from 'lucide-react';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BlogDraftPreview } from '@/components/dashboard/BlogDraftPreview';
import { ConfirmDialog } from '@/components/dashboard/ConfirmDialog';
import { ActionNotice, EmptyState, ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { PriorityBadge } from '@/components/dashboard/PriorityBadge';
import { StatusBadge, formatLabel } from '@/components/dashboard/StatusBadge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi } from '@/lib/dashboard-api';
import type {
  BlogDraft,
  BlogPublishConnection,
  BlogPublishResult,
  BlogTopic,
  RepoConnection,
  UUID,
} from '@/types/dashboard';

const allFilter = 'all';

export default function BlogsPage() {
  const queryClient = useQueryClient();
  const { projectId, project } = useDashboardProject();
  const [selectedPlanId, setSelectedPlanId] = useState<UUID>();
  const [selectedDraftId, setSelectedDraftId] = useState<UUID>();
  const [topicStatusFilter, setTopicStatusFilter] = useState(allFilter);
  const [notice, setNotice] = useState<string>();
  const [actionLoadingId, setActionLoadingId] = useState<UUID>();
  const [newPlanTitle, setNewPlanTitle] = useState('Weekly buyer-intent content plan');
  const [blogsPerWeek, setBlogsPerWeek] = useState(3);
  const [exportFolderPath, setExportFolderPath] = useState('');
  const [selectedWordPressConnectionId, setSelectedWordPressConnectionId] = useState<UUID>();
  const [selectedRepoConnectionId, setSelectedRepoConnectionId] = useState<UUID>();
  const [confirmAction, setConfirmAction] = useState<
    'export-markdown' | 'wordpress-draft' | 'nextjs-patch' | 'infrastructure-patch'
  >();
  const [lastPublishResult, setLastPublishResult] = useState<BlogPublishResult>();

  const plansQuery = useQuery({
    queryKey: ['blog-plans', projectId],
    queryFn: () => dashboardApi.blogs.plans(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  useEffect(() => {
    if (!selectedPlanId && plansQuery.data?.plans[0]?.id) {
      setSelectedPlanId(plansQuery.data.plans[0].id);
    }
  }, [plansQuery.data?.plans, selectedPlanId]);

  const selectedPlan = plansQuery.data?.plans.find((plan) => plan.id === selectedPlanId);

  const topicsQuery = useQuery({
    queryKey: ['blog-topics', selectedPlanId],
    queryFn: () => dashboardApi.blogs.topics(selectedPlanId!),
    enabled: Boolean(selectedPlanId),
    retry: false,
  });

  const draftsQuery = useQuery({
    queryKey: ['blog-drafts', selectedPlanId],
    queryFn: () => dashboardApi.blogs.drafts(selectedPlanId!),
    enabled: Boolean(selectedPlanId),
    retry: false,
  });

  useEffect(() => {
    if (!selectedDraftId && draftsQuery.data?.drafts[0]?.id) {
      setSelectedDraftId(draftsQuery.data.drafts[0].id);
    }
  }, [draftsQuery.data?.drafts, selectedDraftId]);

  const selectedDraft = draftsQuery.data?.drafts.find((draft) => draft.id === selectedDraftId);
  const selectedDraftApproved = selectedDraft?.status === 'approved';

  const publishConnectionsQuery = useQuery({
    queryKey: ['blog-publish-connections', projectId],
    queryFn: () => dashboardApi.blogPublishing.connections(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const repoConnectionsQuery = useQuery({
    queryKey: ['repo-connections', projectId],
    queryFn: () => dashboardApi.repos.connections(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const infrastructureQuery = useQuery({
    queryKey: ['blog-infrastructure', projectId],
    queryFn: () => dashboardApi.blogPublishing.infrastructure(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const wordpressConnections = useMemo(
    () => (publishConnectionsQuery.data?.connections ?? []).filter((connection) => connection.provider === 'wordpress'),
    [publishConnectionsQuery.data?.connections]
  );

  const markdownConnections = useMemo(
    () => (publishConnectionsQuery.data?.connections ?? []).filter((connection) => connection.provider === 'markdown_export'),
    [publishConnectionsQuery.data?.connections]
  );

  const repoConnections = useMemo(
    () => repoConnectionsQuery.data?.connections ?? [],
    [repoConnectionsQuery.data?.connections]
  );

  useEffect(() => {
    if (!selectedWordPressConnectionId && wordpressConnections[0]?.id) {
      setSelectedWordPressConnectionId(wordpressConnections[0].id);
    }
  }, [selectedWordPressConnectionId, wordpressConnections]);

  useEffect(() => {
    if (!selectedRepoConnectionId && repoConnections[0]?.id) {
      setSelectedRepoConnectionId(repoConnections[0].id);
    }
  }, [repoConnections, selectedRepoConnectionId]);

  useEffect(() => {
    if (!exportFolderPath && markdownConnections[0]?.export_folder_path) {
      setExportFolderPath(markdownConnections[0].export_folder_path);
    }
  }, [exportFolderPath, markdownConnections]);

  const createPlanMutation = useMutation({
    mutationFn: () =>
      dashboardApi.blogs.createPlan({
        project_id: projectId!,
        title: newPlanTitle,
        target_site_url: project?.domain ?? undefined,
        blogs_per_week: blogsPerWeek,
      }),
    onSuccess: async (plan) => {
      setNotice('Blog plan created.');
      setSelectedPlanId(plan.id);
      await queryClient.invalidateQueries({ queryKey: ['blog-plans', projectId] });
    },
  });

  const generateTopicsMutation = useMutation({
    mutationFn: () =>
      dashboardApi.blogs.generateTopics(selectedPlanId!, selectedPlan?.blogs_per_week ?? 3),
    onSuccess: async (result) => {
      setNotice(`${result.topics.length} topics generated.`);
      await queryClient.invalidateQueries({ queryKey: ['blog-topics', selectedPlanId] });
    },
  });

  const topicActionMutation = useMutation({
    mutationFn: async ({ topicId, action }: { topicId: UUID; action: string }) => {
      setActionLoadingId(topicId);
      if (action === 'approve') return dashboardApi.blogs.approveTopic(topicId);
      if (action === 'reject') return dashboardApi.blogs.rejectTopic(topicId);
      const draft = await dashboardApi.blogs.draftTopic(topicId);
      return draft;
    },
    onSuccess: async (result) => {
      if ('draft_markdown' in result) {
        setSelectedDraftId(result.id);
        setNotice('Blog draft generated.');
      } else {
        setNotice('Blog topic status updated.');
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['blog-topics', selectedPlanId] }),
        queryClient.invalidateQueries({ queryKey: ['blog-drafts', selectedPlanId] }),
      ]);
    },
    onSettled: () => setActionLoadingId(undefined),
  });

  const checkInfrastructureMutation = useMutation({
    mutationFn: () =>
      dashboardApi.blogPublishing.checkInfrastructure(projectId!, {
        repo_connection_id: selectedRepoConnectionId,
      }),
    onSuccess: async (check) => {
      setNotice(`Blog infrastructure check completed: ${formatLabel(check.recommended_strategy)}.`);
      await queryClient.invalidateQueries({ queryKey: ['blog-infrastructure', projectId] });
    },
  });

  const publishActionMutation = useMutation({
    mutationFn: async (action: NonNullable<typeof confirmAction>) => {
      if (action === 'export-markdown') {
        return dashboardApi.blogPublishing.exportMarkdown(selectedDraftId!, {
          export_folder_path: exportFolderPath,
          overwrite: false,
        });
      }
      if (action === 'wordpress-draft') {
        return dashboardApi.blogPublishing.createWordPressDraft(
          selectedDraftId!,
          selectedWordPressConnectionId!
        );
      }
      if (action === 'nextjs-patch') {
        return dashboardApi.blogPublishing.createNextJsBlogPatch(selectedDraftId!, {
          repo_connection_id: selectedRepoConnectionId,
          content_directory: infrastructureQuery.data?.content_directory ?? undefined,
          extension: infrastructureQuery.data?.recommended_strategy === 'nextjs_mdx' ? 'mdx' : 'md',
          overwrite: false,
        });
      }
      return dashboardApi.blogPublishing.createInfrastructurePatch(projectId!, {
        repo_connection_id: selectedRepoConnectionId,
        strategy:
          infrastructureQuery.data?.recommended_strategy === 'nextjs_mdx'
            ? 'nextjs_mdx'
            : 'nextjs_markdown',
      });
    },
    onSuccess: async (response) => {
      if (response.result) {
        setLastPublishResult(response.result);
      }
      setNotice(`Publishing action completed: ${formatLabel(response.result?.status ?? response.run.status)}.`);
      setConfirmAction(undefined);
      await queryClient.invalidateQueries({ queryKey: ['repo-patches'] });
    },
  });

  const filteredTopics = useMemo(() => {
    return (topicsQuery.data?.topics ?? []).filter(
      (topic) => topicStatusFilter === allFilter || topic.status === topicStatusFilter
    );
  }, [topicStatusFilter, topicsQuery.data?.topics]);

  if (!projectId) {
    return <EmptyState title="Select a project" description="Blog plans are scoped to one project." />;
  }

  if (plansQuery.isLoading) return <LoadingBlock label="Loading blog pipeline" />;

  if (plansQuery.isError) {
    return (
      <ErrorState
        title="Blog plans could not load"
        message="The blog planner endpoint returned an error."
        onRetry={() => void plansQuery.refetch()}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-normal text-slate-950">
          Blog Pipeline
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Plan buyer-intent topics, approve them, and review local LLM blog drafts.
        </p>
      </div>

      <ActionNotice message={notice} />

      <section className="grid gap-4 lg:grid-cols-[0.8fr_1.2fr]">
        <div className="rounded-lg border bg-white">
          <div className="border-b px-5 py-4">
            <h3 className="text-base font-semibold text-slate-950">Blog plans</h3>
          </div>
          <div className="space-y-4 p-5">
            <form className="space-y-3" onSubmit={handleCreatePlan}>
              <Input
                value={newPlanTitle}
                onChange={(event) => setNewPlanTitle(event.target.value)}
                placeholder="Plan title"
              />
              <div className="flex gap-2">
                <Input
                  type="number"
                  min={1}
                  max={20}
                  value={blogsPerWeek}
                  onChange={(event) => setBlogsPerWeek(Number(event.target.value))}
                  aria-label="Blogs per week"
                />
                <Button type="submit" disabled={createPlanMutation.isPending || !newPlanTitle.trim()}>
                  <FilePlus2 className="mr-2 h-4 w-4" />
                  Create plan
                </Button>
              </div>
            </form>

            <div className="space-y-2">
              {(plansQuery.data?.plans ?? []).map((plan) => (
                <button
                  key={plan.id}
                  type="button"
                  onClick={() => setSelectedPlanId(plan.id)}
                  className={`w-full rounded-md border px-3 py-3 text-left text-sm transition-colors ${
                    selectedPlanId === plan.id
                      ? 'border-blue-300 bg-blue-50'
                      : 'bg-white hover:bg-slate-50'
                  }`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium text-slate-950">{plan.title}</span>
                    <StatusBadge status={plan.status} />
                  </div>
                  <p className="mt-1 text-muted-foreground">{plan.blogs_per_week} blogs/week</p>
                </button>
              ))}
              {!plansQuery.data?.plans.length ? (
                <p className="text-sm text-muted-foreground">No blog plans yet.</p>
              ) : null}
            </div>
          </div>
        </div>

        <div className="rounded-lg border bg-white">
          <div className="flex flex-col gap-3 border-b px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h3 className="text-base font-semibold text-slate-950">Topics</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                {selectedPlan?.title ?? 'Select a plan to manage topics.'}
              </p>
            </div>
            <Button
              type="button"
              onClick={() => generateTopicsMutation.mutate()}
              disabled={!selectedPlanId || generateTopicsMutation.isPending}
            >
              <Play className="mr-2 h-4 w-4" />
              Generate topics
            </Button>
          </div>
          <div className="border-b p-4">
            <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Topic status
              <select
                className="mt-1 h-9 w-full max-w-64 rounded-md border bg-white px-2 text-sm normal-case tracking-normal text-slate-900 focus:outline-none focus:ring-2 focus:ring-ring"
                value={topicStatusFilter}
                onChange={(event) => setTopicStatusFilter(event.target.value)}
              >
                <option value={allFilter}>All</option>
                {topicStatusOptions.map((status) => (
                  <option key={status} value={status}>
                    {formatLabel(status)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <TopicTable
            topics={filteredTopics}
            isLoading={topicsQuery.isLoading}
            actionLoadingId={actionLoadingId}
            onApprove={(topicId) => topicActionMutation.mutate({ topicId, action: 'approve' })}
            onReject={(topicId) => topicActionMutation.mutate({ topicId, action: 'reject' })}
            onDraft={(topicId) => topicActionMutation.mutate({ topicId, action: 'draft' })}
          />
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[0.35fr_0.65fr]">
        <div className="rounded-lg border bg-white">
          <div className="border-b px-5 py-4">
            <h3 className="text-base font-semibold text-slate-950">Drafts</h3>
          </div>
          <div className="divide-y">
            {(draftsQuery.data?.drafts ?? []).map((draft) => (
              <button
                key={draft.id}
                type="button"
                onClick={() => setSelectedDraftId(draft.id)}
                className={`block w-full px-5 py-4 text-left text-sm transition-colors ${
                  selectedDraftId === draft.id ? 'bg-blue-50' : 'hover:bg-slate-50'
                }`}
              >
                <p className="font-medium text-slate-950">{draft.title}</p>
                <p className="mt-1 text-muted-foreground">/{draft.slug}</p>
                <div className="mt-2">
                  <StatusBadge status={draft.status} />
                </div>
              </button>
            ))}
            {!draftsQuery.data?.drafts.length ? (
              <div className="p-5 text-sm text-muted-foreground">No drafts generated yet.</div>
            ) : null}
          </div>
        </div>
        <BlogDraftPreview draft={selectedDraft as BlogDraft | undefined} />
      </section>

      <section className="grid gap-4 xl:grid-cols-[0.42fr_0.58fr]">
        <div className="rounded-lg border bg-white">
          <div className="flex flex-col gap-3 border-b px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h3 className="text-base font-semibold text-slate-950">Blog infrastructure</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                {infrastructureQuery.data
                  ? formatLabel(infrastructureQuery.data.recommended_strategy)
                  : 'No infrastructure check recorded.'}
              </p>
            </div>
            <Button
              type="button"
              variant="outline"
              onClick={() => checkInfrastructureMutation.mutate()}
              disabled={!selectedRepoConnectionId || checkInfrastructureMutation.isPending}
            >
              <SearchCheck className="mr-2 h-4 w-4" />
              Check
            </Button>
          </div>
          <div className="space-y-4 p-5">
            <RepoSelect
              value={selectedRepoConnectionId}
              connections={repoConnections}
              onChange={setSelectedRepoConnectionId}
            />
            <div className="grid gap-3 sm:grid-cols-3">
              <InfrastructureStat label="Index" value={infrastructureQuery.data?.has_blog_index} />
              <InfrastructureStat label="Detail route" value={infrastructureQuery.data?.has_blog_detail_route} />
              <InfrastructureStat label="Content dir" value={infrastructureQuery.data?.has_content_directory} />
            </div>
            {infrastructureQuery.data?.issues?.length ? (
              <div className="rounded-md border bg-slate-50 p-3 text-sm text-muted-foreground">
                {infrastructureQuery.data.issues.slice(0, 3).map((issue, index) => (
                  <p key={`${String(issue.code ?? 'issue')}-${index}`}>{String(issue.message ?? issue.code)}</p>
                ))}
              </div>
            ) : null}
            <Button
              type="button"
              onClick={() => setConfirmAction('infrastructure-patch')}
              disabled={!selectedRepoConnectionId || publishActionMutation.isPending}
            >
              <GitBranch className="mr-2 h-4 w-4" />
              Create infrastructure patch
            </Button>
          </div>
        </div>

        <div className="rounded-lg border bg-white">
          <div className="border-b px-5 py-4">
            <h3 className="text-base font-semibold text-slate-950">Publish and export</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              {selectedDraftApproved
                ? selectedDraft?.title
                : 'Select an approved draft to enable publishing actions.'}
            </p>
          </div>
          <div className="space-y-4 p-5">
            <div className="grid gap-3 lg:grid-cols-[1fr_auto]">
              <Input
                value={exportFolderPath}
                onChange={(event) => setExportFolderPath(event.target.value)}
                placeholder="C:\\exports\\blog"
                aria-label="Markdown export folder"
              />
              <Button
                type="button"
                variant="outline"
                onClick={() => setConfirmAction('export-markdown')}
                disabled={!selectedDraftApproved || !exportFolderPath.trim() || publishActionMutation.isPending}
              >
                <Download className="mr-2 h-4 w-4" />
                Export Markdown
              </Button>
            </div>

            <div className="grid gap-3 lg:grid-cols-2">
              <PublishConnectionSelect
                label="WordPress connection"
                value={selectedWordPressConnectionId}
                options={wordpressConnections}
                onChange={setSelectedWordPressConnectionId}
              />
              <div className="flex items-end">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setConfirmAction('wordpress-draft')}
                  disabled={!selectedDraftApproved || !selectedWordPressConnectionId || publishActionMutation.isPending}
                >
                  <UploadCloud className="mr-2 h-4 w-4" />
                  Create WordPress Draft
                </Button>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                onClick={() => setConfirmAction('nextjs-patch')}
                disabled={!selectedDraftApproved || !selectedRepoConnectionId || publishActionMutation.isPending}
              >
                <GitBranch className="mr-2 h-4 w-4" />
                Create Next.js Blog Patch
              </Button>
            </div>

            {lastPublishResult ? (
              <div className="rounded-md border bg-slate-50 p-4 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge status={lastPublishResult.status} />
                  <span className="text-slate-700">{formatLabel(lastPublishResult.provider)}</span>
                </div>
                {lastPublishResult.file_path ? (
                  <p className="mt-2 break-words text-muted-foreground">{lastPublishResult.file_path}</p>
                ) : null}
                {lastPublishResult.external_url ? (
                  <p className="mt-2 break-words text-muted-foreground">{lastPublishResult.external_url}</p>
                ) : null}
                {lastPublishResult.patch_id ? (
                  <p className="mt-2 text-muted-foreground">Patch ID: {lastPublishResult.patch_id}</p>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      </section>

      <ConfirmDialog
        open={Boolean(confirmAction)}
        onOpenChange={(open) => {
          if (!open) setConfirmAction(undefined);
        }}
        title={confirmCopy(confirmAction).title}
        description={confirmCopy(confirmAction).description}
        confirmLabel={confirmCopy(confirmAction).label}
        isWorking={publishActionMutation.isPending}
        onConfirm={() => {
          if (confirmAction) publishActionMutation.mutate(confirmAction);
        }}
      />
    </div>
  );

  function handleCreatePlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    createPlanMutation.mutate();
  }
}

function TopicTable({
  topics,
  isLoading,
  actionLoadingId,
  onApprove,
  onReject,
  onDraft,
}: {
  topics: BlogTopic[];
  isLoading?: boolean;
  actionLoadingId?: UUID;
  onApprove: (_id: UUID) => void;
  onReject: (_id: UUID) => void;
  onDraft: (_id: UUID) => void;
}) {
  if (isLoading) return <LoadingBlock label="Loading topics" />;
  if (topics.length === 0) {
    return (
      <div className="p-8 text-center text-sm text-muted-foreground">
        No blog topics match the current filters.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-border text-sm">
        <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-4 py-3">Topic</th>
            <th className="px-4 py-3">Intent</th>
            <th className="px-4 py-3">Priority</th>
            <th className="px-4 py-3">Status</th>
            <th className="px-4 py-3 text-right">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {topics.map((topic) => (
            <tr key={topic.id} className="align-top">
              <td className="max-w-xl px-4 py-4">
                <p className="font-medium text-slate-950">{topic.title}</p>
                <p className="mt-1 text-sm text-muted-foreground">{topic.target_keyword}</p>
                {topic.angle ? <p className="mt-2 line-clamp-2 text-sm text-slate-600">{topic.angle}</p> : null}
              </td>
              <td className="px-4 py-4 capitalize text-muted-foreground">
                {formatLabel(topic.search_intent)}
              </td>
              <td className="px-4 py-4">
                <PriorityBadge score={topic.priority_score} />
                <p className="mt-1 text-xs text-muted-foreground">{Math.round(topic.priority_score)}</p>
              </td>
              <td className="px-4 py-4">
                <StatusBadge status={topic.status} />
              </td>
              <td className="px-4 py-4">
                <div className="flex justify-end gap-2">
                  <Button
                    type="button"
                    size="icon"
                    variant="outline"
                    className="h-8 w-8"
                    title="Approve"
                    aria-label="Approve"
                    onClick={() => onApprove(topic.id)}
                    disabled={actionLoadingId === topic.id}
                  >
                    <CheckCircle2 className="h-4 w-4" />
                  </Button>
                  <Button
                    type="button"
                    size="icon"
                    variant="outline"
                    className="h-8 w-8"
                    title="Reject"
                    aria-label="Reject"
                    onClick={() => onReject(topic.id)}
                    disabled={actionLoadingId === topic.id}
                  >
                    <XCircle className="h-4 w-4" />
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => onDraft(topic.id)}
                    disabled={actionLoadingId === topic.id}
                  >
                    <PenLine className="mr-2 h-4 w-4" />
                    Draft
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RepoSelect({
  value,
  connections,
  onChange,
}: {
  value?: UUID;
  connections: RepoConnection[];
  onChange: (_value: UUID | undefined) => void;
}) {
  return (
    <label className="block text-xs font-medium uppercase tracking-wide text-muted-foreground">
      Repo connection
      <select
        className="mt-1 h-9 w-full rounded-md border bg-white px-2 text-sm normal-case tracking-normal text-slate-900 focus:outline-none focus:ring-2 focus:ring-ring"
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value || undefined)}
      >
        <option value="">No repo selected</option>
        {connections.map((connection) => (
          <option key={connection.id} value={connection.id}>
            {connection.local_path ?? connection.repo_url ?? connection.id}
          </option>
        ))}
      </select>
    </label>
  );
}

function PublishConnectionSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value?: UUID;
  options: BlogPublishConnection[];
  onChange: (_value: UUID | undefined) => void;
}) {
  return (
    <label className="block text-xs font-medium uppercase tracking-wide text-muted-foreground">
      {label}
      <select
        className="mt-1 h-9 w-full rounded-md border bg-white px-2 text-sm normal-case tracking-normal text-slate-900 focus:outline-none focus:ring-2 focus:ring-ring"
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value || undefined)}
      >
        <option value="">No connection selected</option>
        {options.map((connection) => (
          <option key={connection.id} value={connection.id}>
            {connection.site_url ?? connection.username ?? connection.id}
          </option>
        ))}
      </select>
    </label>
  );
}

function InfrastructureStat({ label, value }: { label: string; value?: boolean }) {
  return (
    <div className="rounded-md border bg-slate-50 p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
      <div className="mt-2">
        <StatusBadge status={value ? 'completed' : value === false ? 'missing' : 'unknown'} />
      </div>
    </div>
  );
}

function confirmCopy(action?: 'export-markdown' | 'wordpress-draft' | 'nextjs-patch' | 'infrastructure-patch') {
  if (action === 'export-markdown') {
    return {
      title: 'Export approved draft?',
      description: 'This writes a markdown file for the selected approved draft. Existing files are not overwritten.',
      label: 'Export Markdown',
    };
  }
  if (action === 'wordpress-draft') {
    return {
      title: 'Create WordPress draft?',
      description: 'This uploads the selected approved BlogDraft to WordPress with status=draft only.',
      label: 'Create Draft',
    };
  }
  if (action === 'nextjs-patch') {
    return {
      title: 'Create Next.js blog patch?',
      description: 'This creates a reviewable repo patch for a new blog file. It does not apply the patch or create a PR.',
      label: 'Create Patch',
    };
  }
  if (action === 'infrastructure-patch') {
    return {
      title: 'Create blog infrastructure patch?',
      description: 'This creates reviewable repo patch records for blog infrastructure. It does not apply patches or change navigation.',
      label: 'Create Patch',
    };
  }
  return {
    title: 'Confirm action',
    description: 'Confirm the selected blog publishing action.',
    label: 'Confirm',
  };
}

const topicStatusOptions = ['suggested', 'approved', 'rejected', 'drafted', 'published'];
