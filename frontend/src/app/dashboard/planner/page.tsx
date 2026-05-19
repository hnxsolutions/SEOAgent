'use client';

import { Play, RefreshCw } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { ActionNotice, EmptyState, ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { StatusBadge, formatLabel } from '@/components/dashboard/StatusBadge';
import { TaskTable } from '@/components/dashboard/TaskTable';
import { WeeklyReportCard } from '@/components/dashboard/WeeklyReportCard';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi, latestPlannerRun } from '@/lib/dashboard-api';
import { formatDateTime } from '@/lib/utils';
import type { PlannerTask, UUID } from '@/types/dashboard';

const allFilter = 'all';

export default function PlannerPage() {
  const queryClient = useQueryClient();
  const { projectId } = useDashboardProject();
  const [statusFilter, setStatusFilter] = useState(allFilter);
  const [priorityFilter, setPriorityFilter] = useState(allFilter);
  const [taskTypeFilter, setTaskTypeFilter] = useState(allFilter);
  const [sourceFilter, setSourceFilter] = useState(allFilter);
  const [selectedTask, setSelectedTask] = useState<PlannerTask | null>(null);
  const [notice, setNotice] = useState<string>();
  const [actionLoadingId, setActionLoadingId] = useState<UUID>();

  const runsQuery = useQuery({
    queryKey: ['planner-runs', projectId],
    queryFn: () => dashboardApi.planner.listRuns(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const tasksQuery = useQuery({
    queryKey: ['planner-tasks', projectId],
    queryFn: () => dashboardApi.planner.listTasks(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const summaryQuery = useQuery({
    queryKey: ['planner-summary', projectId],
    queryFn: () => dashboardApi.planner.summary(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const latestRun = latestPlannerRun(runsQuery.data?.runs);
  const reportQuery = useQuery({
    queryKey: ['planner-report', latestRun?.id],
    queryFn: () => dashboardApi.planner.getReport(latestRun!.id),
    enabled: Boolean(latestRun?.id),
    retry: false,
  });

  const runPlannerMutation = useMutation({
    mutationFn: () => dashboardApi.planner.run(projectId!),
    onSuccess: async () => {
      setNotice('Planner run completed and tasks were refreshed.');
      await invalidatePlanner(projectId, queryClient);
    },
  });

  const taskActionMutation = useMutation({
    mutationFn: async ({ taskId, action }: { taskId: UUID; action: string }) => {
      setActionLoadingId(taskId);
      if (action === 'approve') return dashboardApi.planner.approveTask(taskId);
      if (action === 'reject') return dashboardApi.planner.rejectTask(taskId);
      if (action === 'progress') return dashboardApi.planner.markTaskInProgress(taskId);
      return dashboardApi.planner.markTaskCompleted(taskId);
    },
    onSuccess: async (task) => {
      setNotice(`Task "${task.title}" updated.`);
      setSelectedTask(task);
      await invalidatePlanner(projectId, queryClient);
    },
    onSettled: () => setActionLoadingId(undefined),
  });

  const tasks = useMemo(() => {
    return (tasksQuery.data?.tasks ?? []).filter((task) => {
      return (
        (statusFilter === allFilter || task.status === statusFilter) &&
        (priorityFilter === allFilter || task.priority === priorityFilter) &&
        (taskTypeFilter === allFilter || task.task_type === taskTypeFilter) &&
        (sourceFilter === allFilter || task.source_type === sourceFilter)
      );
    });
  }, [priorityFilter, sourceFilter, statusFilter, taskTypeFilter, tasksQuery.data?.tasks]);

  const taskTypes = uniqueValues(tasksQuery.data?.tasks.map((task) => task.task_type));
  const sourceTypes = uniqueValues(tasksQuery.data?.tasks.map((task) => task.source_type));

  if (!projectId) {
    return <EmptyState title="Select a project" description="Planner data is scoped to one project." />;
  }

  if (runsQuery.isLoading || tasksQuery.isLoading || summaryQuery.isLoading) {
    return <LoadingBlock label="Loading weekly planner" />;
  }

  if (tasksQuery.isError || summaryQuery.isError) {
    return (
      <ErrorState
        title="Planner data could not load"
        message="Check the backend planner endpoints and authentication state."
        onRetry={() => {
          void tasksQuery.refetch();
          void summaryQuery.refetch();
        }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-normal text-slate-950">
            Weekly Planner
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Review the autonomous weekly plan and explicitly approve work.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              void runsQuery.refetch();
              void tasksQuery.refetch();
              void summaryQuery.refetch();
            }}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
          <Button
            type="button"
            onClick={() => runPlannerMutation.mutate()}
            disabled={runPlannerMutation.isPending}
          >
            <Play className="mr-2 h-4 w-4" />
            Run planner
          </Button>
        </div>
      </div>

      <ActionNotice message={notice} />

      <section className="grid gap-4 md:grid-cols-4">
        <PlannerStat label="Open tasks" value={summaryQuery.data?.open_tasks ?? 0} />
        <PlannerStat
          label="High priority"
          value={
            (summaryQuery.data?.tasks_by_priority?.high ?? 0) +
            (summaryQuery.data?.tasks_by_priority?.critical ?? 0)
          }
        />
        <PlannerStat label="Total tasks" value={summaryQuery.data?.total_tasks ?? 0} />
        <div className="rounded-lg border bg-white p-4">
          <p className="text-sm text-muted-foreground">Latest run</p>
          <div className="mt-3 flex items-center gap-2">
            <StatusBadge status={summaryQuery.data?.latest_run_status} />
          </div>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="rounded-lg border bg-white">
          <div className="border-b px-5 py-4">
            <h3 className="text-base font-semibold text-slate-950">Planner runs</h3>
          </div>
          <div className="divide-y">
            {(runsQuery.data?.runs ?? []).slice(0, 8).map((run) => (
              <div key={run.id} className="px-5 py-4">
                <div className="flex items-center justify-between gap-3">
                  <StatusBadge status={run.status} />
                  <span className="text-xs text-muted-foreground">
                    {formatDateTime(run.created_at)}
                  </span>
                </div>
                <p className="mt-2 text-sm text-slate-700">
                  {run.tasks_created} tasks created, {run.high_priority_tasks} high priority
                </p>
                {run.error_message ? (
                  <p className="mt-1 text-sm text-rose-700">{run.error_message}</p>
                ) : null}
              </div>
            ))}
            {!runsQuery.data?.runs.length ? (
              <div className="p-5 text-sm text-muted-foreground">No planner runs yet.</div>
            ) : null}
          </div>
        </div>

        <WeeklyReportCard report={reportQuery.data} />
      </section>

      <section className="space-y-4">
        <div className="flex flex-col gap-3 rounded-lg border bg-white p-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="text-base font-semibold text-slate-950">Task approval queue</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Filter by priority, state, task type, and source.
            </p>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <FilterSelect label="Status" value={statusFilter} onChange={setStatusFilter} options={statusOptions} />
            <FilterSelect label="Priority" value={priorityFilter} onChange={setPriorityFilter} options={priorityOptions} />
            <FilterSelect label="Task type" value={taskTypeFilter} onChange={setTaskTypeFilter} options={taskTypes} />
            <FilterSelect label="Source" value={sourceFilter} onChange={setSourceFilter} options={sourceTypes} />
          </div>
        </div>

        <TaskTable
          tasks={tasks}
          actionLoadingId={actionLoadingId}
          onSelect={setSelectedTask}
          onApprove={(taskId) => taskActionMutation.mutate({ taskId, action: 'approve' })}
          onReject={(taskId) => taskActionMutation.mutate({ taskId, action: 'reject' })}
          onProgress={(taskId) => taskActionMutation.mutate({ taskId, action: 'progress' })}
          onComplete={(taskId) => taskActionMutation.mutate({ taskId, action: 'complete' })}
        />
      </section>

      {selectedTask ? (
        <section className="rounded-lg border bg-white p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h3 className="text-base font-semibold text-slate-950">{selectedTask.title}</h3>
              <p className="mt-2 text-sm leading-6 text-slate-700">{selectedTask.description}</p>
            </div>
            <StatusBadge status={selectedTask.status} />
          </div>
          <dl className="mt-5 grid gap-4 text-sm md:grid-cols-3">
            <Detail label="Type" value={formatLabel(selectedTask.task_type)} />
            <Detail label="Source" value={formatLabel(selectedTask.source_type)} />
            <Detail label="Impact" value={formatLabel(selectedTask.estimated_impact)} />
            <Detail label="Effort" value={formatLabel(selectedTask.effort)} />
            <Detail label="Keyword" value={selectedTask.target_keyword || 'None'} />
            <Detail label="Page" value={selectedTask.target_page_url || 'None'} />
          </dl>
        </section>
      ) : null}
    </div>
  );
}

function PlannerStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border bg-white p-4">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-2 text-3xl font-semibold">{value}</p>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (_value: string) => void;
}) {
  return (
    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
      {label}
      <select
        className="mt-1 h-9 w-full rounded-md border bg-white px-2 text-sm normal-case tracking-normal text-slate-900 focus:outline-none focus:ring-2 focus:ring-ring"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value={allFilter}>All</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {formatLabel(option)}
          </option>
        ))}
      </select>
    </label>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-1 break-words text-slate-800">{value}</dd>
    </div>
  );
}

function uniqueValues(values?: string[]) {
  return Array.from(new Set(values ?? [])).sort();
}

async function invalidatePlanner(projectId: UUID | undefined, queryClient: ReturnType<typeof useQueryClient>) {
  if (!projectId) return;
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ['planner-runs', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['planner-tasks', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['planner-summary', projectId] }),
  ]);
}

const statusOptions = ['todo', 'in_progress', 'approved', 'rejected', 'completed', 'skipped'];
const priorityOptions = ['critical', 'high', 'medium', 'low'];
