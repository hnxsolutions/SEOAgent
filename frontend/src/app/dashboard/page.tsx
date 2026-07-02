'use client';

import {
  ClipboardList,
  FileEdit,
  GitPullRequest,
  Newspaper,
  PlayCircle,
  RefreshCw,
  SearchCheck,
  ShieldCheck,
  Target,
} from 'lucide-react';
import Link from 'next/link';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { DashboardMetricCard } from '@/components/dashboard/DashboardMetricCard';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { PriorityBadge } from '@/components/dashboard/PriorityBadge';
import { StatusBadge } from '@/components/dashboard/StatusBadge';
import { Button } from '@/components/ui/button';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi, latestCrawl, latestPlannerRun } from '@/lib/dashboard-api';
import { formatDateTime } from '@/lib/utils';
import type { SeoRunListResponse, UUID } from '@/types/dashboard';

const seoRunStages = [
  'crawl',
  'audit',
  'semantic_index',
  'content_optimization',
  'planner',
] as const;

const seoRunStageLabels: Record<(typeof seoRunStages)[number], string> = {
  crawl: 'Crawl',
  audit: 'Audit',
  semantic_index: 'Semantic Index',
  content_optimization: 'Content',
  planner: 'Planner',
};

function isActiveSeoRun(status?: string | null) {
  return status === 'queued' || status === 'running';
}

export default function DashboardOverviewPage() {
  const { projectId, isLoading: projectLoading } = useDashboardProject();
  const queryClient = useQueryClient();

  const seoRunsQuery = useQuery({
    queryKey: ['seo-runs', projectId],
    queryFn: () => dashboardApi.seoRuns.list(projectId!),
    enabled: Boolean(projectId),
    retry: false,
    refetchInterval: (query) => {
      const latest = (query.state.data as SeoRunListResponse | undefined)?.runs?.[0];
      return isActiveSeoRun(latest?.status) ? 3000 : false;
    },
  });

  const latestSeoRun = seoRunsQuery.data?.runs?.[0];
  const isSeoRunPolling = isActiveSeoRun(latestSeoRun?.status);

  const plannerSummaryQuery = useQuery({
    queryKey: ['planner-summary', projectId],
    queryFn: () => dashboardApi.planner.summary(projectId!),
    enabled: Boolean(projectId),
    retry: false,
    refetchInterval: isSeoRunPolling ? 5000 : false,
  });

  const plannerRunsQuery = useQuery({
    queryKey: ['planner-runs', projectId],
    queryFn: () => dashboardApi.planner.listRuns(projectId!),
    enabled: Boolean(projectId),
    retry: false,
    refetchInterval: isSeoRunPolling ? 5000 : false,
  });

  const gscSummaryQuery = useQuery({
    queryKey: ['gsc-summary', projectId],
    queryFn: () => dashboardApi.searchConsole.summary(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const crawlsQuery = useQuery({
    queryKey: ['crawls', projectId],
    queryFn: () => dashboardApi.crawls.list(projectId),
    enabled: Boolean(projectId),
    retry: false,
    refetchInterval: isSeoRunPolling ? 5000 : false,
  });

  const latestRun = latestPlannerRun(plannerRunsQuery.data?.runs);
  const activeCrawl = latestCrawl(crawlsQuery.data?.crawls);
  const crawlId = activeCrawl?.id ?? latestRun?.crawl_id ?? undefined;

  const auditSummaryQuery = useQuery({
    queryKey: ['audit-summary', crawlId],
    queryFn: () => dashboardApi.crawls.auditSummary(crawlId!),
    enabled: Boolean(crawlId),
    retry: false,
    refetchInterval: isSeoRunPolling ? 5000 : false,
  });

  const contentSummaryQuery = useQuery({
    queryKey: ['content-summary', crawlId],
    queryFn: () => dashboardApi.content.summary(crawlId!),
    enabled: Boolean(crawlId),
    retry: false,
    refetchInterval: isSeoRunPolling ? 5000 : false,
  });

  const geoSummaryQuery = useQuery({
    queryKey: ['geo-summary', crawlId],
    queryFn: () => dashboardApi.geoAeo.summary(crawlId!),
    enabled: Boolean(crawlId),
    retry: false,
  });

  const blogPlansQuery = useQuery({
    queryKey: ['blog-plans', projectId],
    queryFn: () => dashboardApi.blogs.plans(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const draftsQuery = useQuery({
    queryKey: ['blog-drafts', blogPlansQuery.data?.plans[0]?.id],
    queryFn: () => dashboardApi.blogs.drafts(blogPlansQuery.data!.plans[0].id),
    enabled: Boolean(blogPlansQuery.data?.plans[0]?.id),
    retry: false,
  });

  const repoPatchesQuery = useQuery({
    queryKey: ['repo-patches', latestRun?.repo_scan_run_id],
    queryFn: () => dashboardApi.repos.patches(latestRun!.repo_scan_run_id!),
    enabled: Boolean(latestRun?.repo_scan_run_id),
    retry: false,
  });

  const runSeoMutation = useMutation({
    mutationFn: () => dashboardApi.seoRuns.start(projectId!),
    onSuccess: async () => {
      await invalidateOverview(projectId, queryClient);
    },
  });

  const isSeoRunActive = runSeoMutation.isPending || isSeoRunPolling;

  if (projectLoading) return <LoadingBlock label="Loading dashboard" />;
  if (!projectId) {
    return (
      <EmptyState
        title="Select a project"
        description="The dashboard needs a project before it can load planner, Search Console, crawl, content, blog, and repository data."
      />
    );
  }

  if (plannerSummaryQuery.isError) {
    return (
      <ErrorState
        title="Dashboard summary could not load"
        message="The planner summary endpoint returned an error."
        onRetry={() => void plannerSummaryQuery.refetch()}
      />
    );
  }

  const summary = plannerSummaryQuery.data;
  const pendingDrafts = (draftsQuery.data?.drafts ?? []).filter(
    (draft) => draft.status === 'draft'
  ).length;
  const pendingPatches = (repoPatchesQuery.data?.patches ?? []).filter(
    (patch) => patch.status === 'proposed' || patch.status === 'approved'
  ).length;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-normal text-slate-950">
            Project overview
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Monitor the weekly SEO operating system and pending approvals.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            onClick={() => runSeoMutation.mutate()}
            disabled={isSeoRunActive}
          >
            {isSeoRunActive ? (
              <RefreshCw className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <PlayCircle className="mr-2 h-4 w-4" aria-hidden="true" />
            )}
            {isSeoRunActive ? 'Running SEO Analysis' : 'Run SEO Analysis'}
          </Button>
          <Link
            href="/dashboard/planner"
            className="text-sm font-medium text-blue-700 hover:text-blue-800"
          >
            Open planner
          </Link>
        </div>
      </div>

      <section id="health" className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <DashboardMetricCard
          title="SEO Health"
          value={auditSummaryQuery.data?.site_score ?? 'N/A'}
          detail={
            auditSummaryQuery.data
              ? `${auditSummaryQuery.data.total_issues} audit issues`
              : 'Latest audit summary unavailable'
          }
          icon={ShieldCheck}
          href="/dashboard/content"
          tone="emerald"
        />
        <DashboardMetricCard
          title="Weekly Planner"
          value={summary?.open_tasks ?? 0}
          detail={`${summary?.tasks_by_priority?.high ?? 0} high, ${
            summary?.tasks_by_priority?.critical ?? 0
          } critical`}
          icon={ClipboardList}
          href="/dashboard/planner"
          tone="blue"
        />
        <DashboardMetricCard
          title="GEO/AEO Score"
          value={
            geoSummaryQuery.data
              ? Math.round(
                  (geoSummaryQuery.data.average_geo_score +
                    geoSummaryQuery.data.average_aeo_score) /
                    2
                )
              : 'N/A'
          }
          detail={
            geoSummaryQuery.data
              ? `GEO ${Math.round(geoSummaryQuery.data.average_geo_score)}, AEO ${Math.round(
                  geoSummaryQuery.data.average_aeo_score
                )}`
              : 'No readiness scores yet'
          }
          icon={Target}
          href="/dashboard/geo-aeo"
          tone="emerald"
        />
        <DashboardMetricCard
          title="Search Console Opportunities"
          value={gscSummaryQuery.data?.opportunities_count ?? 0}
          detail={gscSummaryQuery.data?.latest_sync_status ?? 'No latest sync'}
          icon={SearchCheck}
          href="/dashboard/search-console"
          tone="amber"
        />
        <DashboardMetricCard
          title="Content Improvements"
          value={contentSummaryQuery.data?.total_suggestions ?? 0}
          detail={`${contentSummaryQuery.data?.pages_with_suggestions ?? 0} pages with suggestions`}
          icon={FileEdit}
          href="/dashboard/content"
          tone="slate"
        />
        <DashboardMetricCard
          title="Blog Pipeline"
          value={pendingDrafts}
          detail={`${blogPlansQuery.data?.plans.length ?? 0} active plans`}
          icon={Newspaper}
          href="/dashboard/blogs"
          tone="blue"
        />
        <DashboardMetricCard
          title="Repo Patches"
          value={pendingPatches}
          detail="0 draft PRs loaded"
          icon={GitPullRequest}
          href="/dashboard/repos"
          tone="rose"
        />
      </section>

      <SeoRunProgress
        run={latestSeoRun}
        isStarting={runSeoMutation.isPending}
        errorMessage={
          runSeoMutation.error instanceof Error ? runSeoMutation.error.message : undefined
        }
        totalPages={activeCrawl?.total_pages_crawled ?? auditSummaryQuery.data?.total_pages}
        totalIssues={auditSummaryQuery.data?.total_issues}
        totalSuggestions={contentSummaryQuery.data?.total_suggestions}
        openTasks={summary?.open_tasks}
      />

      <section id="pipeline" className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-lg border bg-white">
          <div className="border-b px-5 py-4">
            <h3 className="text-base font-semibold text-slate-950">Weekly Planner</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Latest run and highest-priority tasks.
            </p>
          </div>
          <div className="space-y-4 p-5">
            <div className="flex flex-wrap items-center gap-3">
              <StatusBadge status={summary?.latest_run_status} />
              <span className="text-sm text-muted-foreground">
                {latestRun?.created_at ? formatDateTime(latestRun.created_at) : 'No run yet'}
              </span>
              <span className="text-sm text-muted-foreground">
                {latestRun ? `${latestRun.tasks_created} tasks created` : ''}
              </span>
            </div>
            <div className="space-y-3">
              {(summary?.top_tasks ?? []).slice(0, 5).map((task) => (
                <div
                  key={task.id}
                  className="flex flex-col gap-2 rounded-md border bg-slate-50 px-3 py-3 sm:flex-row sm:items-start sm:justify-between"
                >
                  <div>
                    <p className="text-sm font-medium text-slate-950">{task.title}</p>
                    <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
                      {task.description}
                    </p>
                  </div>
                  <PriorityBadge priority={task.priority} />
                </div>
              ))}
              {!summary?.top_tasks?.length ? (
                <p className="text-sm text-muted-foreground">No top tasks yet.</p>
              ) : null}
            </div>
          </div>
        </div>

        <div className="rounded-lg border bg-white">
          <div className="border-b px-5 py-4">
            <h3 className="text-base font-semibold text-slate-950">Runtime status</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Crawl, audit, GEO/AEO, and GSC snapshots.
            </p>
          </div>
          <div className="divide-y">
            <StatusRow
              label="Latest crawl"
              status={activeCrawl?.status}
              detail={activeCrawl ? `${activeCrawl.total_pages_crawled} pages` : 'No crawl found'}
            />
            <StatusRow
              label="Latest audit"
              status={auditSummaryQuery.data?.status}
              detail={
                auditSummaryQuery.data
                  ? `${auditSummaryQuery.data.total_issues} issues`
                  : 'No audit summary'
              }
            />
            <StatusRow
              label="GEO/AEO"
              status={geoSummaryQuery.data?.status}
              detail={
                geoSummaryQuery.data
                  ? `Avg GEO ${Math.round(geoSummaryQuery.data.average_geo_score)}`
                  : 'No scoring run'
              }
            />
            <StatusRow
              label="Search Console"
              status={gscSummaryQuery.data?.latest_sync_status}
              detail={`${gscSummaryQuery.data?.rows_count ?? 0} rows imported`}
            />
          </div>
        </div>
      </section>
    </div>
  );
}

function SeoRunProgress({
  run,
  isStarting,
  errorMessage,
  totalPages,
  totalIssues,
  totalSuggestions,
  openTasks,
}: {
  run?: SeoRunListResponse['runs'][number];
  isStarting: boolean;
  errorMessage?: string;
  totalPages?: number;
  totalIssues?: number;
  totalSuggestions?: number;
  openTasks?: number;
}) {
  const stageErrors = run?.stage_errors ?? {};
  const summary =
    run?.status === 'completed'
      ? `${totalPages ?? 0} pages, ${totalIssues ?? 0} issues, ${
          totalSuggestions ?? 0
        } content suggestions, ${openTasks ?? 0} open tasks`
      : run
        ? `Current stage: ${seoRunStageLabels[run.current_stage as (typeof seoRunStages)[number]] ?? run.current_stage.replace(/_/g, ' ')}`
        : 'No run data yet';

  return (
    <section id="seo-run-progress" className="rounded-lg border bg-white">
      <div className="flex flex-col gap-3 border-b px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="text-base font-semibold text-slate-950">SEO Analysis Run</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            {run?.created_at ? formatDateTime(run.created_at) : 'No run yet'}
          </p>
        </div>
        <StatusBadge status={isStarting ? 'queued' : run?.status} />
      </div>
      <div className="space-y-4 p-5">
        <div className="grid gap-3 md:grid-cols-5">
          {seoRunStages.map((stage) => (
            <div key={stage} className="rounded-md border bg-slate-50 px-3 py-3">
              <p className="text-xs font-semibold uppercase tracking-normal text-slate-600">
                {seoRunStageLabels[stage]}
              </p>
              <StatusBadge
                status={run?.stage_statuses?.[stage] ?? 'pending'}
                className="mt-2"
              />
              {stageErrors[stage] ? (
                <p className="mt-2 line-clamp-2 text-xs text-amber-700">
                  {stageErrors[stage]}
                </p>
              ) : null}
            </div>
          ))}
        </div>
        <div className="rounded-md border bg-white px-4 py-3">
          <p className="text-sm font-medium text-slate-950">Last result</p>
          <p className="mt-1 text-sm text-muted-foreground">{summary}</p>
          {run?.error_message ? (
            <p className="mt-2 text-sm text-rose-700">{run.error_message}</p>
          ) : null}
          {errorMessage ? <p className="mt-2 text-sm text-rose-700">{errorMessage}</p> : null}
        </div>
      </div>
    </section>
  );
}

function StatusRow({
  label,
  status,
  detail,
}: {
  label: string;
  status?: string | null;
  detail: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 px-5 py-4">
      <div>
        <p className="text-sm font-medium text-slate-950">{label}</p>
        <p className="mt-1 text-sm text-muted-foreground">{detail}</p>
      </div>
      <StatusBadge status={status} />
    </div>
  );
}

async function invalidateOverview(
  projectId: UUID | undefined,
  queryClient: ReturnType<typeof useQueryClient>
) {
  if (!projectId) return;
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ['seo-runs', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['planner-summary', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['planner-runs', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['crawls', projectId] }),
  ]);
}
