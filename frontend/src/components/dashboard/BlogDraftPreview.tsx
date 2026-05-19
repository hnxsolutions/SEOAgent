import { BookOpenText } from 'lucide-react';
import { StatusBadge } from '@/components/dashboard/StatusBadge';
import type { BlogDraft } from '@/types/dashboard';

export function BlogDraftPreview({ draft }: { draft?: BlogDraft | null }) {
  if (!draft) {
    return (
      <div className="rounded-lg border border-dashed bg-white p-8 text-center text-sm text-muted-foreground">
        Select or generate a draft to preview it here.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border bg-white">
      <div className="flex flex-col gap-3 border-b bg-slate-50 px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <BookOpenText className="h-4 w-4 text-slate-500" aria-hidden="true" />
            <h2 className="text-lg font-semibold text-slate-950">{draft.title}</h2>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">/{draft.slug}</p>
        </div>
        <StatusBadge status={draft.status} />
      </div>

      <div className="grid gap-4 border-b p-5 md:grid-cols-2">
        <MetadataBlock title="Meta title" value={draft.meta_title} />
        <MetadataBlock title="Meta description" value={draft.meta_description} />
      </div>

      <div className="grid gap-4 border-b p-5 lg:grid-cols-2">
        <JsonBlock title="Outline" value={draft.outline} />
        <JsonBlock title="FAQ JSON" value={draft.faq_json} />
        <JsonBlock title="Schema JSON" value={draft.schema_json} />
        <JsonBlock title="Internal link plan" value={draft.internal_link_plan} />
        <JsonBlock title="Knowledge sources used" value={draft.knowledge_sources_used} />
      </div>

      <article className="max-h-[680px] overflow-auto p-5">
        <pre className="whitespace-pre-wrap break-words text-sm leading-7 text-slate-800">
          {draft.draft_markdown}
        </pre>
      </article>
    </div>
  );
}

function MetadataBlock({ title, value }: { title: string; value?: string | null }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</p>
      <p className="mt-2 text-sm text-slate-800">{value || 'No value generated'}</p>
    </div>
  );
}

function JsonBlock({ title, value }: { title: string; value?: unknown }) {
  return (
    <div className="min-w-0 rounded-md border bg-slate-50 p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</p>
      <pre className="mt-2 max-h-44 overflow-auto whitespace-pre-wrap break-words text-xs leading-5 text-slate-700">
        {value ? JSON.stringify(value, null, 2) : 'No data'}
      </pre>
    </div>
  );
}
