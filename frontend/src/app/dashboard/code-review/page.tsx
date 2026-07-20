'use client';

import { useState } from 'react';
import type { ReactNode } from 'react';
import { GitPullRequest, Check, X, Archive, ExternalLink, ShieldAlert, FileCode2 } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { Button } from '@/components/ui/button';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi } from '@/lib/dashboard-api';
import type { CodeReviewItem, CodeReviewFile } from '@/types/dashboard';

function RiskChip({ risk }: { risk: string }) {
  const map: Record<string, string> = {
    low: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    medium: 'border-amber-200 bg-amber-50 text-amber-700',
    high: 'border-rose-200 bg-rose-50 text-rose-700',
    blocked: 'border-slate-300 bg-slate-100 text-slate-700',
  };
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${map[risk] ?? map.low}`}>
    <ShieldAlert className="h-3 w-3" />{risk} risk
  </span>;
}

function StatusChip({ status }: { status: string }) {
  const map: Record<string, string> = {
    ready_for_review: 'border-sky-200 bg-sky-50 text-sky-700',
    approved: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    merged: 'border-emerald-300 bg-emerald-100 text-emerald-800',
    rejected: 'border-rose-200 bg-rose-50 text-rose-700',
    archived: 'border-slate-200 bg-slate-50 text-slate-600',
  };
  return <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${map[status] ?? map.ready_for_review}`}>{status.replace(/_/g, ' ')}</span>;
}

export default function CodeReviewPage() {
  const queryClient = useQueryClient();
  const { projectId } = useDashboardProject();
  const [openId, setOpenId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string>();

  const listQuery = useQuery({
    queryKey: ['code-reviews'],
    queryFn: () => dashboardApi.codeReview.list(),
    retry: false,
  });

  const prepareMutation = useMutation({
    mutationFn: () => dashboardApi.codeReview.prepare(projectId!),
    onSuccess: async (r) => {
      setNotice(r.status === 'ready_for_review' ? `Prepared review with ${r.files} file(s).` : (r.note ?? 'Nothing to review.'));
      await queryClient.invalidateQueries({ queryKey: ['code-reviews'] });
    },
  });

  const reviews = listQuery.data?.items ?? [];

  if (listQuery.isLoading) return <LoadingBlock label="Loading code reviews…" />;
  if (listQuery.isError) return <ErrorState title="Code reviews could not load" message="The API may be unavailable." onRetry={() => void listQuery.refetch()} />;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-2xl font-semibold text-slate-950">
            <GitPullRequest className="h-6 w-6" /> Code Review
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Review AI-generated, SEO-safe code before anything reaches production. Nothing merges without your approval.
          </p>
        </div>
        <Button type="button" onClick={() => prepareMutation.mutate()} disabled={!projectId || prepareMutation.isPending}>
          <FileCode2 className={`mr-2 h-4 w-4 ${prepareMutation.isPending ? 'animate-pulse' : ''}`} />
          {prepareMutation.isPending ? 'Preparing…' : 'Prepare Review'}
        </Button>
      </div>

      {notice ? <p className="rounded-md border bg-slate-50 px-4 py-2 text-sm text-slate-700">{notice}</p> : null}

      {reviews.length === 0 ? (
        <div className="rounded-xl border bg-card p-8 text-center text-sm text-muted-foreground">
          No reviews yet. Generate SEO patches on the Technology page, then click “Prepare Review”.
        </div>
      ) : (
        <div className="space-y-3">
          {reviews.map((r) => (
            <ReviewCard key={r.id} review={r} open={openId === r.id}
              onToggle={() => setOpenId(openId === r.id ? null : r.id)}
              onChanged={() => queryClient.invalidateQueries({ queryKey: ['code-reviews'] })} />
          ))}
        </div>
      )}
    </div>
  );
}

function ReviewCard({ review, open, onToggle, onChanged }: {
  review: CodeReviewItem; open: boolean; onToggle: () => void; onChanged: () => void;
}) {
  const queryClient = useQueryClient();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState('');

  const detailQuery = useQuery({
    queryKey: ['code-review', review.id],
    queryFn: () => dashboardApi.codeReview.get(review.id),
    enabled: open,
    retry: false,
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['code-review', review.id] });
    onChanged();
  };
  const approve = useMutation({ mutationFn: () => dashboardApi.codeReview.approve(review.id), onSuccess: refresh });
  const reject = useMutation({ mutationFn: () => dashboardApi.codeReview.reject(review.id, reason), onSuccess: refresh });
  const archive = useMutation({ mutationFn: () => dashboardApi.codeReview.archive(review.id), onSuccess: refresh });

  const files: CodeReviewFile[] = detailQuery.data?.files ?? [];
  const isOpen = review.status === 'ready_for_review' || review.status === 'approved';

  return (
    <div className="rounded-xl border bg-card">
      <button type="button" onClick={onToggle} className="flex w-full flex-col gap-2 px-5 py-4 text-left lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-slate-900">{review.framework ?? 'SEO patches'}</span>
            <StatusChip status={review.status} />
            <RiskChip risk={review.risk_level} />
            <span className="text-xs text-muted-foreground">{review.files_count} file(s)</span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {review.technology ?? ''} · confidence {review.confidence ?? '—'}% · SEO impact {review.estimated_seo_impact ?? '—'} · perf {review.estimated_performance_impact ?? '—'}
            {review.created_at ? ` · ${new Date(review.created_at).toLocaleString()}` : ''}
          </p>
        </div>
        <div className="flex flex-none items-center gap-3 text-xs text-muted-foreground">
          <span>SEO {review.seo_before ?? '—'} → <b>{review.seo_after_predicted ?? '—'}</b> <em>(predicted)</em></span>
          {review.pr_url ? <a href={review.pr_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sky-700 underline" onClick={(e) => e.stopPropagation()}>Draft PR<ExternalLink className="h-3 w-3" /></a> : null}
        </div>
      </button>

      {open ? (
        <div className="border-t px-5 py-4">
          {detailQuery.isLoading ? <LoadingBlock label="Loading diff…" /> : (
            <>
              <div className="space-y-4">
                {files.map((f) => <FileDiff key={f.id} file={f} />)}
              </div>

              {/* Admin actions — never an automatic Merge */}
              {isOpen ? (
                <div className="mt-4 flex flex-wrap items-center gap-2 border-t pt-4">
                  <Button type="button" onClick={() => approve.mutate()} disabled={approve.isPending}>
                    <Check className="mr-2 h-4 w-4" />{approve.isPending ? 'Approving…' : 'Approve'}
                  </Button>
                  <Button type="button" variant="outline" onClick={() => setRejecting((v) => !v)}>
                    <X className="mr-2 h-4 w-4" />Reject
                  </Button>
                  <Button type="button" variant="outline" onClick={() => archive.mutate()} disabled={archive.isPending}>
                    <Archive className="mr-2 h-4 w-4" />Archive
                  </Button>
                  {review.pr_url ? (
                    <a href={review.pr_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-md border px-3 py-2 text-sm text-slate-700">
                      Open Draft PR <ExternalLink className="h-4 w-4" />
                    </a>
                  ) : null}
                </div>
              ) : null}

              {rejecting && isOpen ? (
                <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                  <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason for rejection (sent to the learning engine)"
                    className="h-9 w-full rounded-md border px-3 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring" />
                  <Button type="button" variant="outline" disabled={!reason.trim() || reject.isPending} onClick={() => reject.mutate()}>
                    {reject.isPending ? 'Rejecting…' : 'Confirm reject'}
                  </Button>
                </div>
              ) : null}

              {approve.data && !approve.data.merged ? (
                <p className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  Approved. Merge is <b>gated</b> ({approve.data.deployment_status}) — connect a repository + GITHUB_TOKEN to merge the draft PR.
                </p>
              ) : null}
              {approve.data && approve.data.merged ? (
                <p className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
                  Merged ({approve.data.merge_sha?.slice(0, 8)}). Verification will run post-deploy.
                </p>
              ) : null}
              {review.status === 'rejected' && review.rejection_reason ? (
                <p className="mt-3 text-xs text-rose-700">Rejected by {review.rejected_by}: {review.rejection_reason}</p>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}

function Cell({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-md border bg-slate-50 px-2 py-1.5">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="text-xs font-medium text-slate-800">{value}</p>
    </div>
  );
}

function FileDiff({ file }: { file: CodeReviewFile }) {
  return (
    <div className="rounded-lg border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-slate-50 px-3 py-2">
        <span className="flex items-center gap-2 text-sm font-medium text-slate-900">
          <FileCode2 className="h-4 w-4" />{file.target_file}
        </span>
        <span className="flex items-center gap-2 text-xs">
          <RiskChip risk={file.risk} />
          <span className="text-emerald-600">+{file.lines_added}</span>
          <span className="text-rose-600">-{file.lines_removed}</span>
        </span>
      </div>

      {/* WHY explanation */}
      <div className="border-b px-3 py-2 text-xs text-slate-700">
        <p><b>Why:</b> {file.explanation.problem} {file.explanation.consequence}</p>
        <p className="mt-0.5 text-slate-600">{file.explanation.fix}</p>
      </div>

      {/* line-by-line diff */}
      <pre className="max-h-72 overflow-auto bg-slate-950 p-3 text-xs leading-relaxed">
        {file.diff.map((l, i) => (
          <div key={i} className={
            l.type === 'add' ? 'text-emerald-300' : l.type === 'remove' ? 'text-rose-300' : 'text-slate-400'
          }>
            <span className="select-none opacity-60">{l.type === 'add' ? '+ ' : l.type === 'remove' ? '- ' : '  '}</span>{l.text || ' '}
          </div>
        ))}
      </pre>

      {/* expected result (predictions) */}
      <div className="px-3 py-2">
        <p className="mb-1 text-[11px] italic text-muted-foreground">{file.expected_result.disclaimer}</p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          <Cell label="Crawling" value={file.expected_result.crawling_improvement} />
          <Cell label="Rich results" value={file.expected_result.rich_result_improvement} />
          <Cell label="Metadata" value={file.expected_result.metadata_quality} />
          <Cell label="Indexability" value={file.expected_result.indexability} />
          <Cell label="Lighthouse SEO" value={file.expected_result.lighthouse_seo} />
        </div>
      </div>
    </div>
  );
}
