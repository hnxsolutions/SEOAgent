'use client';

import {
  ArrowLeft,
  ClipboardList,
  FileText,
  Printer,
  SearchCheck,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import Link from 'next/link';
import { Suspense, useMemo } from 'react';
import type { ReactNode } from 'react';
import { useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { PriorityBadge } from '@/components/dashboard/PriorityBadge';
import { StatusBadge, formatLabel } from '@/components/dashboard/StatusBadge';
import { Button } from '@/components/ui/button';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi } from '@/lib/dashboard-api';
import { formatDateTime } from '@/lib/utils';
import type { SeoReportActionItem, SeoRunListResponse, SeoRunReportResponse } from '@/types/dashboard';

export default function DashboardReportPage() {
  return (
    <Suspense fallback={<LoadingBlock label="Loading report" />}>
      <DashboardReportContent />
    </Suspense>
  );
}

function DashboardReportContent() {
  const searchParams = useSearchParams();
  const requestedRunId = searchParams.get('runId') ?? undefined;
  const { projectId, isLoading: projectLoading } = useDashboardProject();

  const seoRunsQuery = useQuery({
    queryKey: ['seo-runs', projectId],
    queryFn: () => dashboardApi.seoRuns.list(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const latestCompletedRun = useMemo(
    () => (seoRunsQuery.data as SeoRunListResponse | undefined)?.runs.find((run) => run.status === 'completed'),
    [seoRunsQuery.data]
  );
  const reportRunId = requestedRunId ?? latestCompletedRun?.id;

  const reportQuery = useQuery({
    queryKey: ['seo-run-report', reportRunId],
    queryFn: () => dashboardApi.seoRuns.report(reportRunId!),
    enabled: Boolean(reportRunId),
    retry: false,
  });

  if (projectLoading || (seoRunsQuery.isLoading && !requestedRunId)) {
    return <LoadingBlock label="Loading report" />;
  }

  if (!projectId) {
    return (
      <EmptyState
        title="Select a project"
        description="A completed SEO run is required before a report can be generated."
        action={
          <Button asChild type="button">
            <Link href="/dashboard/setup">Open setup</Link>
          </Button>
        }
      />
    );
  }

  if (!reportRunId) {
    return (
      <EmptyState
        title="No completed SEO run"
        description="Run SEO Analysis from the overview, then the client-facing report will appear here."
        action={
          <Button asChild type="button">
            <Link href="/dashboard">Open overview</Link>
          </Button>
        }
      />
    );
  }

  if (reportQuery.isLoading) {
    return <LoadingBlock label="Building report" />;
  }

  if (reportQuery.isError || !reportQuery.data) {
    return (
      <ErrorState
        title="Report could not load"
        message="The report endpoint did not return data for this SEO run."
        onRetry={() => void reportQuery.refetch()}
      />
    );
  }

  return <ReportView report={reportQuery.data} />;
}

function ReportView({ report }: { report: SeoRunReportResponse }) {
  const businessSection = report.sections.find((section) => section.key === 'business_context');
  const keywordBaselineSection = report.sections.find((section) => section.key === 'keyword_baseline');
  const contentSection = report.sections.find((section) => section.key === 'content_optimization');
  const plannerSection = report.sections.find((section) => section.key === 'weekly_planner');
  const realSearchSection = report.sections.find((section) => section.key === 'real_search_data');

  return (
    <div className="mx-auto max-w-6xl space-y-6 print:max-w-none">
      <div className="flex flex-col gap-3 print:hidden sm:flex-row sm:items-center sm:justify-between">
        <Button asChild type="button" variant="outline">
          <Link href="/dashboard">
            <ArrowLeft className="mr-2 h-4 w-4" aria-hidden="true" />
            Overview
          </Link>
        </Button>
        <Button type="button" variant="outline" onClick={() => window.print()}>
          <Printer className="mr-2 h-4 w-4" aria-hidden="true" />
          Print / Save PDF
        </Button>
      </div>

      <section className="rounded-lg border bg-white p-5 print:border-0 print:p-0">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-sm font-medium text-muted-foreground">SEO Report</p>
            <h2 className="mt-1 text-2xl font-semibold text-slate-950">{report.project_name}</h2>
            <p className="mt-1 break-words text-sm text-muted-foreground">{report.website_url}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={report.run_status} />
            {report.completed_at ? (
              <span className="text-sm text-muted-foreground">
                Completed {formatDateTime(report.completed_at)}
              </span>
            ) : null}
          </div>
        </div>
        <p className="mt-5 max-w-4xl text-sm leading-6 text-slate-700">{report.executive_summary}</p>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <ReportMetric
          label="Audit Score"
          value={report.audit_score ?? 'N/A'}
          detail={`${report.total_issues.toLocaleString()} audit issues`}
          icon={ShieldCheck}
        />
        <ReportMetric
          label="Pages Processed"
          value={report.crawl_pages_processed}
          detail="Crawl scope for this run"
          icon={SearchCheck}
        />
        <ReportMetric
          label="Semantic Vectors"
          value={report.semantic_vector_count}
          detail="Indexed page knowledge"
          icon={FileText}
        />
        <ReportMetric
          label="Planner Tasks"
          value={report.planner_tasks_count}
          detail="Weekly action items"
          icon={ClipboardList}
        />
      </section>

      <ReportSection title="Business Context" status={businessSection?.status} summary={businessSection?.summary}>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {(businessSection?.items ?? []).length ? (
            businessSection!.items.map((item) => (
              <ContextValue key={text(item.label, text(item.value))} item={item} />
            ))
          ) : (
            <EmptyInline text="Business context was not provided for this project." />
          )}
        </div>
      </ReportSection>

      <ReportSection title="Keyword Baseline" status={keywordBaselineSection?.status} summary={keywordBaselineSection?.summary}>
        <div className="grid gap-3 lg:grid-cols-2">
          {(keywordBaselineSection?.items ?? []).length ? (
            keywordBaselineSection!.items.slice(0, 8).map((baseline) => (
              <KeywordBaselineRow key={text(baseline.id, text(baseline.keyword))} baseline={baseline} />
            ))
          ) : (
            <EmptyInline text="No manual keyword baseline provided." />
          )}
        </div>
      </ReportSection>

      <section className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
        <div className="rounded-lg border bg-white p-5">
          <h3 className="text-base font-semibold text-slate-950">Issue Breakdown</h3>
          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
            <Breakdown title="Severity" data={report.issue_counts_by_severity} />
            <Breakdown title="Category" data={report.issue_counts_by_category} />
          </div>
        </div>
        <div className="rounded-lg border bg-white p-5">
          <h3 className="text-base font-semibold text-slate-950">Top Audit Issues</h3>
          <div className="mt-4 space-y-3">
            {report.top_audit_issues.length ? (
              report.top_audit_issues.slice(0, 5).map((issue) => (
                <IssueRow key={text(issue.id, text(issue.title))} issue={issue} />
              ))
            ) : (
              <EmptyInline text="No audit issues are available for this run." />
            )}
          </div>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <ReportSection title="AI Content Suggestions" status={contentSection?.status} summary={contentSection?.summary}>
          <div className="space-y-3">
            {report.content_suggestions.length ? (
              report.content_suggestions.slice(0, 6).map((suggestion) => (
                <SuggestionRow key={text(suggestion.id, text(suggestion.suggestion_type))} suggestion={suggestion} />
              ))
            ) : (
              <EmptyInline text="No content suggestions were generated for this run." />
            )}
          </div>
        </ReportSection>

        <ReportSection title="Weekly Action Plan" status={plannerSection?.status} summary={plannerSection?.summary}>
          <div className="space-y-3">
            {report.weekly_planner_tasks.length ? (
              report.weekly_planner_tasks.slice(0, 6).map((task) => (
                <TaskRow key={text(task.id, text(task.title))} task={task} />
              ))
            ) : (
              <EmptyInline text="No planner tasks were created for this run." />
            )}
          </div>
        </ReportSection>
      </section>

      <section className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <ReportSection title="Semantic Page Summaries" status={semanticStatus(report)} summary="Indexed page summaries from the semantic index.">
          <div className="space-y-3">
            {report.semantic_summaries.length ? (
              report.semantic_summaries.slice(0, 5).map((summary) => (
                <SemanticRow key={text(summary.id, text(summary.url))} summary={summary} />
              ))
            ) : (
              <EmptyInline text="No indexed page summaries are available." />
            )}
          </div>
        </ReportSection>

        <ReportSection title="Real Ranking Data" status={realSearchSection?.status} summary={realSearchSection?.summary}>
          <div className="grid gap-3 sm:grid-cols-3">
            {Object.entries(report.data_availability).map(([key, value]) => (
              <div key={key} className="rounded-md border bg-slate-50 px-3 py-3">
                <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">
                  {formatLabel(key)}
                </p>
                <p className="mt-2 text-sm font-medium text-slate-900">{value}</p>
              </div>
            ))}
          </div>
        </ReportSection>
      </section>

      <ReportSection title="Next Steps" status="available" summary={`${report.next_actions.length} prioritized next actions.`}>
        <div className="grid gap-3 md:grid-cols-2">
          {report.next_actions.map((action) => (
            <ActionRow key={`${action.source_section}-${action.title}`} action={action} />
          ))}
        </div>
      </ReportSection>
    </div>
  );
}

function ReportMetric({
  label,
  value,
  detail,
  icon: Icon,
}: {
  label: string;
  value: string | number;
  detail: string;
  icon: LucideIcon;
}) {
  return (
    <div className="rounded-lg border bg-white p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-muted-foreground">{label}</p>
          <p className="mt-2 text-3xl font-semibold text-slate-950">
            {typeof value === 'number' ? value.toLocaleString() : value}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">{detail}</p>
        </div>
        <span className="flex h-9 w-9 items-center justify-center rounded-md bg-slate-100 text-slate-700">
          <Icon className="h-4 w-4" aria-hidden="true" />
        </span>
      </div>
    </div>
  );
}

function ReportSection({
  title,
  status,
  summary,
  children,
}: {
  title: string;
  status?: string;
  summary?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-lg border bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-slate-950">{title}</h3>
          {summary ? <p className="mt-1 text-sm text-muted-foreground">{summary}</p> : null}
        </div>
        <StatusBadge status={status ?? 'available'} />
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Breakdown({ title, data }: { title: string; data: Record<string, number> }) {
  const entries = Object.entries(data);
  return (
    <div>
      <p className="text-sm font-medium text-slate-700">{title}</p>
      <div className="mt-3 space-y-2">
        {entries.length ? (
          entries.map(([key, value]) => (
            <div key={key} className="flex items-center justify-between gap-3 rounded-md border bg-slate-50 px-3 py-2">
              <span className="text-sm capitalize text-slate-700">{formatLabel(key)}</span>
              <span className="text-sm font-semibold text-slate-950">{value.toLocaleString()}</span>
            </div>
          ))
        ) : (
          <EmptyInline text="No breakdown available." />
        )}
      </div>
    </div>
  );
}

function ContextValue({ item }: { item: Record<string, unknown> }) {
  return (
    <div className="rounded-md border bg-slate-50 px-3 py-3">
      <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">
        {text(item.label, 'Context')}
      </p>
      <p className="mt-2 break-words text-sm font-medium text-slate-900">
        {readableValue(item.value)}
      </p>
      {item.note ? (
        <p className="mt-2 text-xs text-muted-foreground">{text(item.note)}</p>
      ) : null}
    </div>
  );
}

function KeywordBaselineRow({ baseline }: { baseline: Record<string, unknown> }) {
  const position = baseline.current_position ? `Position ${text(baseline.current_position)}` : 'Position missing';
  const location = text(baseline.target_location, 'Location not provided');
  const device = formatLabel(text(baseline.device, 'desktop'));

  return (
    <div className="rounded-md border bg-slate-50 px-3 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={text(baseline.source, 'manual')} />
        <span className="text-xs font-medium uppercase tracking-normal text-slate-500">
          {device}
        </span>
      </div>
      <p className="mt-2 text-sm font-semibold text-slate-950">
        {text(baseline.keyword, 'Keyword')}
      </p>
      <p className="mt-1 text-sm text-muted-foreground">
        {position} | {location}
        {baseline.intent ? ` | ${formatLabel(text(baseline.intent))}` : ''}
      </p>
      {baseline.current_url ? (
        <p className="mt-2 break-words text-xs text-slate-500">{text(baseline.current_url)}</p>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">No current URL mapped.</p>
      )}
      {baseline.notes ? (
        <p className="mt-2 text-xs text-muted-foreground">{text(baseline.notes)}</p>
      ) : null}
    </div>
  );
}

function IssueRow({ issue }: { issue: Record<string, unknown> }) {
  return (
    <div className="rounded-md border bg-slate-50 px-3 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={text(issue.severity, 'open')} />
        <span className="text-xs font-medium uppercase tracking-normal text-slate-500">
          {formatLabel(text(issue.category, 'audit'))}
        </span>
      </div>
      <p className="mt-2 text-sm font-semibold text-slate-950">{text(issue.title, 'Audit issue')}</p>
      <p className="mt-1 text-sm text-muted-foreground">{text(issue.recommendation ?? issue.message, 'Review this issue.')}</p>
      {issue.url ? <p className="mt-2 break-words text-xs text-slate-500">{text(issue.url)}</p> : null}
    </div>
  );
}

function SuggestionRow({ suggestion }: { suggestion: Record<string, unknown> }) {
  return (
    <div className="rounded-md border bg-slate-50 px-3 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <PriorityBadge score={numberValue(suggestion.priority_score)} />
        <StatusBadge status={text(suggestion.status, 'suggested')} />
      </div>
      <p className="mt-2 text-sm font-semibold capitalize text-slate-950">
        {formatLabel(text(suggestion.suggestion_type, 'content suggestion'))}
      </p>
      <p className="mt-1 text-sm text-muted-foreground">{text(suggestion.reason, 'Review this content suggestion.')}</p>
      <p className="mt-2 line-clamp-2 text-sm text-slate-700">{text(suggestion.suggested_value, '')}</p>
      {suggestion.page_url ? <p className="mt-2 break-words text-xs text-slate-500">{text(suggestion.page_url)}</p> : null}
    </div>
  );
}

function TaskRow({ task }: { task: Record<string, unknown> }) {
  return (
    <div className="rounded-md border bg-slate-50 px-3 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <PriorityBadge priority={text(task.priority, 'medium')} />
        <StatusBadge status={text(task.status, 'todo')} />
      </div>
      <p className="mt-2 text-sm font-semibold text-slate-950">{text(task.title, 'Planner task')}</p>
      <p className="mt-1 text-sm text-muted-foreground">{text(task.description, 'Review this planner task.')}</p>
      {task.target_page_url ? <p className="mt-2 break-words text-xs text-slate-500">{text(task.target_page_url)}</p> : null}
    </div>
  );
}

function SemanticRow({ summary }: { summary: Record<string, unknown> }) {
  return (
    <div className="rounded-md border bg-slate-50 px-3 py-3">
      <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-normal text-slate-500">
        <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
        {formatLabel(text(summary.content_type, 'indexed page'))}
      </div>
      <p className="mt-2 break-words text-sm font-semibold text-slate-950">{text(summary.url, 'Indexed page')}</p>
      {summary.heading_context ? <p className="mt-1 text-sm text-slate-700">{text(summary.heading_context)}</p> : null}
      {summary.text_preview ? <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{text(summary.text_preview)}</p> : null}
    </div>
  );
}

function ActionRow({ action }: { action: SeoReportActionItem }) {
  return (
    <div className="rounded-md border bg-slate-50 px-3 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <PriorityBadge priority={action.priority} />
        {action.status ? <StatusBadge status={action.status} /> : null}
      </div>
      <p className="mt-2 text-sm font-semibold text-slate-950">{action.title}</p>
      <p className="mt-1 text-sm text-muted-foreground">{action.description}</p>
      {action.target_url ? <p className="mt-2 break-words text-xs text-slate-500">{action.target_url}</p> : null}
    </div>
  );
}

function EmptyInline({ text: value }: { text: string }) {
  return <p className="rounded-md border border-dashed bg-white px-3 py-3 text-sm text-muted-foreground">{value}</p>;
}

function semanticStatus(report: SeoRunReportResponse) {
  return report.semantic_vector_count > 0 ? 'available' : 'no_data';
}

function text(value: unknown, fallback = 'Unavailable') {
  if (value === null || value === undefined || value === '') return fallback;
  return String(value);
}

function readableValue(value: unknown) {
  if (Array.isArray(value)) {
    return value.length ? value.map((item) => String(item)).join(', ') : 'Not provided';
  }
  if (value && typeof value === 'object') {
    return JSON.stringify(value);
  }
  return text(value, 'Not provided');
}

function numberValue(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}
