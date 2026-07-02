'use client';

import { RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { StatusBadge, formatLabel } from '@/components/dashboard/StatusBadge';
import { Button } from '@/components/ui/button';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi, latestCrawl } from '@/lib/dashboard-api';
import type { SEOIssue } from '@/types/dashboard';

export default function AuditIssuesPage() {
  const { projectId } = useDashboardProject();
  const [requestedCrawlId, setRequestedCrawlId] = useState<string>();

  useEffect(() => {
    setRequestedCrawlId(new URLSearchParams(window.location.search).get('crawlId') ?? undefined);
  }, []);

  const crawlsQuery = useQuery({
    queryKey: ['crawls', projectId],
    queryFn: () => dashboardApi.crawls.list(projectId),
    enabled: Boolean(projectId),
    retry: false,
  });

  const effectiveCrawlId = requestedCrawlId ?? latestCrawl(crawlsQuery.data?.crawls)?.id;

  const summaryQuery = useQuery({
    queryKey: ['audit-summary', effectiveCrawlId],
    queryFn: () => dashboardApi.crawls.auditSummary(effectiveCrawlId!),
    enabled: Boolean(effectiveCrawlId),
    retry: false,
  });

  const issuesQuery = useQuery({
    queryKey: ['audit-issues', effectiveCrawlId],
    queryFn: () => dashboardApi.audits.issues({ crawl_id: effectiveCrawlId }),
    enabled: Boolean(effectiveCrawlId),
    retry: false,
  });

  if (!projectId) {
    return (
      <EmptyState
        title="Select a project"
        description="Audit issues are scoped to the selected project."
      />
    );
  }

  if (crawlsQuery.isLoading) return <LoadingBlock label="Loading crawls" />;

  if (!effectiveCrawlId) {
    return (
      <EmptyState
        title="No crawl results found"
        description="Run SEO Analysis first, then audit issues will appear here."
      />
    );
  }

  if (summaryQuery.isError || issuesQuery.isError) {
    return (
      <ErrorState
        title="Audit issues could not load"
        message="The latest crawl may not have a completed audit yet."
        onRetry={() => {
          void summaryQuery.refetch();
          void issuesQuery.refetch();
        }}
      />
    );
  }

  const issues = issuesQuery.data?.issues ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-normal text-slate-950">
            Audit Issues
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Deterministic technical and on-page issues from the latest audit.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            void summaryQuery.refetch();
            void issuesQuery.refetch();
          }}
        >
          <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
          Refresh
        </Button>
      </div>

      <section className="grid gap-4 md:grid-cols-4">
        <AuditStat label="Audit score" value={summaryQuery.data?.site_score ?? 'N/A'} />
        <AuditStat label="Issues" value={summaryQuery.data?.total_issues ?? 0} />
        <AuditStat label="Pages" value={summaryQuery.data?.total_pages ?? 0} />
        <div className="rounded-lg border bg-white p-4">
          <p className="text-sm text-muted-foreground">Status</p>
          <div className="mt-3">
            <StatusBadge status={summaryQuery.data?.status} />
          </div>
        </div>
      </section>

      <IssueTable issues={issues} isLoading={issuesQuery.isLoading} />
    </div>
  );
}

function IssueTable({ issues, isLoading }: { issues: SEOIssue[]; isLoading?: boolean }) {
  if (isLoading) return <LoadingBlock label="Loading audit issues" />;
  if (issues.length === 0) {
    return (
      <div className="rounded-lg border border-dashed bg-white p-8 text-center">
        <p className="text-sm font-semibold text-slate-900">No audit issues found</p>
        <p className="mx-auto mt-2 max-w-xl text-sm text-muted-foreground">
          This crawl has no audit issues returned by the current rule set.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border bg-white">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-border text-sm">
          <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Issue</th>
              <th className="px-4 py-3">Severity</th>
              <th className="px-4 py-3">Category</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Page</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {issues.map((issue) => (
              <tr key={issue.id} className="align-top">
                <td className="max-w-xl px-4 py-4">
                  <p className="font-medium text-slate-950">{issue.title}</p>
                  <p className="mt-1 line-clamp-3 text-sm text-muted-foreground">
                    {issue.message}
                  </p>
                  {issue.recommendation ? (
                    <p className="mt-2 line-clamp-2 text-sm text-slate-700">
                      {issue.recommendation}
                    </p>
                  ) : null}
                </td>
                <td className="px-4 py-4">
                  <StatusBadge status={issue.severity} />
                </td>
                <td className="px-4 py-4 text-slate-700">{formatLabel(issue.category)}</td>
                <td className="px-4 py-4">
                  <StatusBadge status={issue.status} />
                </td>
                <td className="max-w-xs px-4 py-4 text-muted-foreground">
                  <p className="truncate">{issue.url ?? 'No URL'}</p>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AuditStat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border bg-white p-4">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-2 text-3xl font-semibold">{value}</p>
    </div>
  );
}
