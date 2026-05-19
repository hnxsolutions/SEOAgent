import { CalendarCheck2 } from 'lucide-react';
import type { WeeklyReport } from '@/types/dashboard';
import { formatDateTime } from '@/lib/utils';

export function WeeklyReportCard({ report }: { report?: WeeklyReport | null }) {
  if (!report) {
    return (
      <div className="rounded-lg border border-dashed bg-white p-8 text-center text-sm text-muted-foreground">
        No weekly report is available for the selected run.
      </div>
    );
  }

  return (
    <section className="rounded-lg border bg-white">
      <div className="flex items-start gap-3 border-b bg-slate-50 px-5 py-4">
        <span className="flex h-9 w-9 items-center justify-center rounded-md bg-blue-50 text-blue-700">
          <CalendarCheck2 className="h-4 w-4" aria-hidden="true" />
        </span>
        <div>
          <h2 className="text-base font-semibold text-slate-950">Weekly report</h2>
          <p className="mt-1 text-sm text-muted-foreground">{formatDateTime(report.created_at)}</p>
        </div>
      </div>
      <div className="space-y-5 p-5">
        <p className="text-sm leading-6 text-slate-800">{report.summary}</p>
        <ReportList title="Wins" items={report.wins} />
        <ReportList title="Risks" items={report.risks} />
        <ReportList title="Next week priorities" items={report.next_week_priorities} />
        <div className="grid gap-4 lg:grid-cols-2">
          <ReportJson title="Technical SEO" value={report.technical_seo_summary} />
          <ReportJson title="Search Console" value={report.search_console_summary} />
          <ReportJson title="Content" value={report.content_summary} />
          <ReportJson title="GEO/AEO" value={report.geo_aeo_summary} />
          <ReportJson title="Blogs" value={report.blog_summary} />
          <ReportJson title="Repo patches" value={report.repo_patch_summary} />
        </div>
      </div>
    </section>
  );
}

function ReportList({ title, items }: { title: string; items?: unknown[] | null }) {
  if (!items?.length) return null;
  return (
    <div>
      <h3 className="text-sm font-semibold text-slate-950">{title}</h3>
      <ul className="mt-2 space-y-2 text-sm text-slate-700">
        {items.map((item, index) => (
          <li key={index} className="rounded-md border bg-slate-50 px-3 py-2">
            {typeof item === 'string' ? item : JSON.stringify(item)}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ReportJson({
  title,
  value,
}: {
  title: string;
  value?: Record<string, unknown> | null;
}) {
  if (!value || Object.keys(value).length === 0) return null;
  return (
    <div className="rounded-md border bg-slate-50 p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</p>
      <pre className="mt-2 max-h-44 overflow-auto whitespace-pre-wrap break-words text-xs leading-5 text-slate-700">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}
