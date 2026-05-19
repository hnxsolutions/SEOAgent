'use client';

import { CheckCircle2, FilePlus2, PenLine, Play, XCircle } from 'lucide-react';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BlogDraftPreview } from '@/components/dashboard/BlogDraftPreview';
import { ActionNotice, EmptyState, ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { PriorityBadge } from '@/components/dashboard/PriorityBadge';
import { StatusBadge, formatLabel } from '@/components/dashboard/StatusBadge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi } from '@/lib/dashboard-api';
import type { BlogDraft, BlogTopic, UUID } from '@/types/dashboard';

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

const topicStatusOptions = ['suggested', 'approved', 'rejected', 'drafted', 'published'];
