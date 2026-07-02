'use client';

import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Circle,
  ClipboardList,
  Clock3,
  FileEdit,
  FileText,
  GitPullRequest,
  ListChecks,
  Newspaper,
  PlayCircle,
  RefreshCw,
  SearchCheck,
  ShieldCheck,
  Target,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
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
import type {
  AuditSummary,
  ContentOptimizationRun,
  CrawlJob,
  SemanticIndexRun,
  SeoRun,
  SeoRunListResponse,
  UUID,
} from '@/types/dashboard';

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
  const fallbackCrawl = latestCrawl(crawlsQuery.data?.crawls);
  const crawlId = latestSeoRun?.crawl_id ?? fallbackCrawl?.id ?? latestRun?.crawl_id ?? undefined;

  const crawlStatusQuery = useQuery({
    queryKey: ['crawl-status', crawlId],
    queryFn: () => dashboardApi.crawls.status(crawlId!),
    enabled: Boolean(crawlId),
    retry: false,
    refetchInterval: isSeoRunPolling ? 5000 : false,
  });

  const activeCrawl = crawlStatusQuery.data?.job ?? fallbackCrawl;

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

  const semanticRunQuery = useQuery({
    queryKey: ['semantic-run', latestSeoRun?.semantic_index_run_id],
    queryFn: () => dashboardApi.semantic.status(latestSeoRun!.semantic_index_run_id!),
    enabled: Boolean(latestSeoRun?.semantic_index_run_id),
    retry: false,
    refetchInterval: isSeoRunPolling ? 5000 : false,
  });

  const contentRunQuery = useQuery({
    queryKey: ['content-run', latestSeoRun?.content_optimization_run_id],
    queryFn: () => dashboardApi.content.runStatus(latestSeoRun!.content_optimization_run_id!),
    enabled: Boolean(latestSeoRun?.content_optimization_run_id),
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
        action={
          <Button asChild type="button">
            <Link href="/dashboard/setup">Open setup</Link>
          </Button>
        }
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
  const latestSeoPlannerRun =
    plannerRunsQuery.data?.runs.find((run) => run.id === latestSeoRun?.planner_run_id) ??
    latestRun;
  const plannerTasksCount = latestSeoPlannerRun?.tasks_created ?? summary?.total_tasks;
  const contentSuggestionsCount =
    contentRunQuery.data?.total_suggestions ?? contentSummaryQuery.data?.total_suggestions;
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
          {latestSeoRun?.status === 'completed' ? (
            <Button asChild type="button" variant="outline">
              <Link href={`/dashboard/report?runId=${latestSeoRun.id}`}>
                <FileText className="mr-2 h-4 w-4" aria-hidden="true" />
                View Report
              </Link>
            </Button>
          ) : null}
          <Link
            href="/dashboard/planner"
            className="text-sm font-medium text-blue-700 hover:text-blue-800"
          >
            Open planner
          </Link>
        </div>
      </div>

      <OnboardingChecklist
        projectReady={Boolean(projectId)}
        runReady={Boolean(latestSeoRun)}
        auditReady={Boolean(auditSummaryQuery.data)}
        suggestionsReady={(contentSuggestionsCount ?? 0) > 0}
        plannerReady={(plannerTasksCount ?? 0) > 0}
      />

      <DemoSafeLabels />

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
          href={crawlId ? `/dashboard/audit?crawlId=${crawlId}` : '/dashboard/audit'}
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
        isRunActive={isSeoRunActive}
        onRun={() => runSeoMutation.mutate()}
        errorMessage={
          runSeoMutation.error instanceof Error ? runSeoMutation.error.message : undefined
        }
        crawl={activeCrawl}
        auditSummary={auditSummaryQuery.data}
        semanticRun={semanticRunQuery.data}
        contentRun={contentRunQuery.data}
        plannerTasksCount={plannerTasksCount}
        plannerOpenTasks={summary?.open_tasks}
        contentSuggestionsCount={contentSuggestionsCount}
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
  isRunActive,
  onRun,
  errorMessage,
  crawl,
  auditSummary,
  semanticRun,
  contentRun,
  plannerTasksCount,
  plannerOpenTasks,
  contentSuggestionsCount,
}: {
  run?: SeoRun;
  isStarting: boolean;
  isRunActive: boolean;
  onRun: () => void;
  errorMessage?: string;
  crawl?: CrawlJob;
  auditSummary?: AuditSummary;
  semanticRun?: SemanticIndexRun;
  contentRun?: ContentOptimizationRun;
  plannerTasksCount?: number;
  plannerOpenTasks?: number;
  contentSuggestionsCount?: number;
}) {
  const stageErrors = run?.stage_errors ?? {};
  const currentStage = run?.current_stage as (typeof seoRunStages)[number] | 'completed' | undefined;
  const stageLabel =
    currentStage === 'completed'
      ? 'Completed'
      : currentStage
        ? seoRunStageLabels[currentStage as (typeof seoRunStages)[number]] ??
          currentStage.replace(/_/g, ' ')
        : 'Not started';
  const crawlFailed =
    crawl?.status === 'failed' ||
    run?.stage_statuses?.crawl === 'failed' ||
    Boolean(stageErrors.crawl);
  const contentError =
    stageErrors.content_optimization ?? contentRun?.error_message ?? undefined;
  const ollamaUnavailable =
    run?.stage_statuses?.content_optimization === 'skipped_or_failed' ||
    Boolean(contentError?.toLowerCase().includes('ollama')) ||
    Boolean(contentError?.toLowerCase().includes('not reachable'));
  const noSuggestions =
    run?.status === 'completed' &&
    !ollamaUnavailable &&
    (contentSuggestionsCount ?? contentRun?.total_suggestions ?? 0) === 0;
  const noPlannerTasks = run?.status === 'completed' && (plannerTasksCount ?? 0) === 0;
  const crawlParam = run?.crawl_id ? `?crawlId=${run.crawl_id}` : '';

  if (!run && !isStarting) {
    return (
      <section id="seo-run-progress" className="rounded-lg border bg-white">
        <div className="border-b px-5 py-4">
          <h3 className="text-base font-semibold text-slate-950">Latest SEO Run</h3>
          <p className="mt-1 text-sm text-muted-foreground">No SEO run yet.</p>
        </div>
        <div className="p-5">
          <EmptyState
            title="No SEO run yet"
            description="Start the one-click analysis to create crawl, audit, semantic, content, and planner data."
            action={
              <Button type="button" onClick={onRun} disabled={isRunActive}>
                <PlayCircle className="mr-2 h-4 w-4" aria-hidden="true" />
                Run SEO Analysis
              </Button>
            }
          />
        </div>
      </section>
    );
  }

  return (
    <section id="seo-run-progress" className="rounded-lg border bg-white">
      <div className="flex flex-col gap-3 border-b px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="text-base font-semibold text-slate-950">Latest SEO Run</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            {run?.status === 'completed' ? 'Final stage' : 'Current stage'}: {stageLabel}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={isStarting ? 'queued' : run?.status} />
          {run?.completed_at ? (
            <span className="text-sm text-muted-foreground">
              Completed {formatDateTime(run.completed_at)}
            </span>
          ) : null}
        </div>
      </div>
      <div className="space-y-4 p-5">
        <div className="grid gap-3 text-sm md:grid-cols-3">
          <RunFact
            icon={Clock3}
            label="Started"
            value={run?.started_at ? formatDateTime(run.started_at) : 'Not started'}
          />
          <RunFact
            icon={Clock3}
            label="Completed"
            value={run?.completed_at ? formatDateTime(run.completed_at) : 'Not complete'}
          />
          <RunFact icon={ListChecks} label="Stage" value={stageLabel} />
        </div>

        <div className="grid gap-3 md:grid-cols-5">
          {seoRunStages.map((stage) => (
            <div key={stage} className="rounded-md border bg-slate-50 px-3 py-3">
              <div className="flex items-center gap-2">
                <StageIcon status={run?.stage_statuses?.[stage] ?? 'pending'} />
                <p className="text-xs font-semibold uppercase tracking-normal text-slate-600">
                  {seoRunStageLabels[stage]}
                </p>
              </div>
              <StatusBadge status={run?.stage_statuses?.[stage] ?? 'pending'} className="mt-2" />
              {stageErrors[stage] ? (
                <p className="mt-2 line-clamp-2 text-xs text-amber-700">
                  {stageErrors[stage]}
                </p>
              ) : null}
            </div>
          ))}
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <RunMetric label="Crawl pages" value={crawl?.total_pages_crawled ?? auditSummary?.total_pages ?? 'N/A'} />
          <RunMetric label="Audit score" value={auditSummary?.site_score ?? 'N/A'} />
          <RunMetric label="Issue count" value={auditSummary?.total_issues ?? crawl?.total_issues_found ?? 'N/A'} />
          <RunMetric label="Semantic vectors" value={semanticRun?.indexed_vectors ?? semanticRun?.total_vectors ?? 'N/A'} />
          <RunMetric label="Content suggestions" value={contentSuggestionsCount ?? contentRun?.total_suggestions ?? 'N/A'} />
          <RunMetric label="Planner tasks" value={plannerTasksCount ?? 'N/A'} />
          <RunMetric label="Open tasks" value={plannerOpenTasks ?? 'N/A'} />
        </div>

        <div className="space-y-2">
          {crawlFailed ? (
            <RunNotice
              tone="error"
              title="Crawl failed"
              detail={stageErrors.crawl ?? crawl?.status ?? 'The crawl stage did not complete.'}
            />
          ) : null}
          {ollamaUnavailable ? (
            <RunNotice
              tone="warning"
              title="Ollama unavailable"
              detail={contentError ?? 'Content optimization was skipped or failed, and the run continued.'}
            />
          ) : null}
          {noSuggestions ? (
            <RunNotice
              tone="warning"
              title="No suggestions found"
              detail="Content optimization completed, but no suggestions were persisted for this crawl."
            />
          ) : null}
          {noPlannerTasks ? (
            <RunNotice
              tone="warning"
              title="No planner tasks found"
              detail="The planner completed without creating tasks for this project."
            />
          ) : null}
          {run?.error_message ? (
            <RunNotice tone="error" title="Run failed" detail={run.error_message} />
          ) : null}
          {errorMessage ? <RunNotice tone="error" title="Run could not start" detail={errorMessage} /> : null}
        </div>

        {run?.status === 'completed' ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <ResultShortcut href={`/dashboard/report?runId=${run.id}`} label="View Report" />
            <ResultShortcut href={`/dashboard/audit${crawlParam}`} label="View Audit Issues" />
            <ResultShortcut href={`/dashboard/content${crawlParam}`} label="View Content Suggestions" />
            <ResultShortcut href="/dashboard/planner" label="View Planner Tasks" />
          </div>
        ) : null}
      </div>
    </section>
  );
}

function OnboardingChecklist({
  projectReady,
  runReady,
  auditReady,
  suggestionsReady,
  plannerReady,
}: {
  projectReady: boolean;
  runReady: boolean;
  auditReady: boolean;
  suggestionsReady: boolean;
  plannerReady: boolean;
}) {
  const items = [
    { label: 'Create project', done: projectReady, href: '/dashboard/setup' },
    { label: 'Run SEO Analysis', done: runReady, href: '/dashboard' },
    { label: 'Review audit issues', done: auditReady, href: '/dashboard/audit' },
    { label: 'Review AI suggestions', done: suggestionsReady, href: '/dashboard/content' },
    { label: 'Review weekly planner tasks', done: plannerReady, href: '/dashboard/planner' },
  ];

  return (
    <section className="rounded-lg border bg-white p-4">
      <div className="mb-3 flex items-center gap-2">
        <ListChecks className="h-4 w-4 text-blue-700" aria-hidden="true" />
        <h3 className="text-sm font-semibold text-slate-950">Onboarding checklist</h3>
      </div>
      <div className="grid gap-2 md:grid-cols-5">
        {items.map((item) => (
          <Link
            key={item.label}
            href={item.href}
            className="flex min-h-12 items-center gap-2 rounded-md border bg-slate-50 px-3 py-2 text-sm text-slate-700 hover:bg-slate-100"
          >
            {item.done ? (
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" aria-hidden="true" />
            ) : (
              <Circle className="h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
            )}
            <span>{item.label}</span>
          </Link>
        ))}
      </div>
    </section>
  );
}

function DemoSafeLabels() {
  return (
    <section className="grid gap-3 md:grid-cols-3">
      <DemoLabel text="Automated SERP is disabled in local MVP" />
      <DemoLabel text="Billing is disabled in local MVP" />
      <DemoLabel text="GSC/manual SERP snapshots are real-data paths" />
    </section>
  );
}

function DemoLabel({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700">
      {text}
    </div>
  );
}

function StageIcon({ status }: { status?: string | null }) {
  if (status === 'completed') {
    return <CheckCircle2 className="h-4 w-4 text-emerald-600" aria-hidden="true" />;
  }
  if (status === 'running' || status === 'queued') {
    return <RefreshCw className="h-4 w-4 animate-spin text-sky-600" aria-hidden="true" />;
  }
  if (status === 'failed' || status === 'skipped_or_failed') {
    return <AlertTriangle className="h-4 w-4 text-amber-600" aria-hidden="true" />;
  }
  return <Circle className="h-4 w-4 text-slate-400" aria-hidden="true" />;
}

function RunFact({
  icon: Icon,
  label,
  value,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-md border bg-slate-50 px-3 py-3">
      <Icon className="h-4 w-4 text-slate-500" aria-hidden="true" />
      <div>
        <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">{label}</p>
        <p className="mt-1 text-sm font-medium text-slate-900">{value}</p>
      </div>
    </div>
  );
}

function RunMetric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border bg-white px-4 py-3">
      <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-slate-950">
        {typeof value === 'number' ? value.toLocaleString() : value}
      </p>
    </div>
  );
}

function RunNotice({
  title,
  detail,
  tone,
}: {
  title: string;
  detail: string;
  tone: 'warning' | 'error';
}) {
  return (
    <div
      className={
        tone === 'error'
          ? 'rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800'
          : 'rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800'
      }
    >
      <p className="font-semibold">{title}</p>
      <p className="mt-1">{detail}</p>
    </div>
  );
}

function ResultShortcut({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="flex min-h-11 items-center justify-between gap-3 rounded-md border bg-slate-50 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-100"
    >
      <span>{label}</span>
      <ArrowRight className="h-4 w-4 text-slate-500" aria-hidden="true" />
    </Link>
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
