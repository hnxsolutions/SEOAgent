'use client';

import {
  KeyRound,
  Pencil,
  PlusCircle,
  RefreshCw,
  Save,
  Trash2,
  Upload,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi } from '@/lib/dashboard-api';
import { formatDateTime } from '@/lib/utils';
import type { KeywordBaseline, KeywordBaselinePayload, UUID } from '@/types/dashboard';

type FormState = {
  keyword: string;
  target_location: string;
  device: 'desktop' | 'mobile';
  current_position: string;
  current_url: string;
  search_volume: string;
  difficulty: string;
  intent: string;
  notes: string;
};

const emptyForm: FormState = {
  keyword: '',
  target_location: '',
  device: 'desktop',
  current_position: '',
  current_url: '',
  search_volume: '',
  difficulty: '',
  intent: '',
  notes: '',
};

export default function DashboardKeywordsPage() {
  const { projectId, project, isLoading: projectLoading } = useDashboardProject();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<FormState>(emptyForm);
  const [editing, setEditing] = useState<KeywordBaseline | null>(null);
  const [bulkText, setBulkText] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [bulkError, setBulkError] = useState<string | null>(null);

  const baselinesQuery = useQuery({
    queryKey: ['keyword-baselines', projectId],
    queryFn: () => dashboardApi.keywordBaselines.list(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const invalidate = async () => {
    if (!projectId) return;
    await queryClient.invalidateQueries({ queryKey: ['keyword-baselines', projectId] });
    await queryClient.invalidateQueries({ queryKey: ['planner-summary', projectId] });
  };

  const createMutation = useMutation({
    mutationFn: (payload: KeywordBaselinePayload) =>
      dashboardApi.keywordBaselines.create(projectId!, payload),
    onSuccess: async () => {
      setForm(emptyForm);
      setFormError(null);
      await invalidate();
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: UUID; payload: Partial<KeywordBaselinePayload> }) =>
      dashboardApi.keywordBaselines.update(id, payload),
    onSuccess: async () => {
      setForm(emptyForm);
      setEditing(null);
      setFormError(null);
      await invalidate();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: UUID) => dashboardApi.keywordBaselines.delete(id),
    onSuccess: invalidate,
  });

  const bulkMutation = useMutation({
    mutationFn: (items: KeywordBaselinePayload[]) =>
      dashboardApi.keywordBaselines.bulk(projectId!, items),
    onSuccess: async () => {
      setBulkText('');
      setBulkError(null);
      await invalidate();
    },
  });

  const baselines = useMemo(() => baselinesQuery.data?.baselines ?? [], [baselinesQuery.data?.baselines]);
  const summary = useMemo(() => keywordSummary(baselines), [baselines]);

  if (projectLoading) return <LoadingBlock label="Loading keyword baselines" />;

  if (!projectId) {
    return (
      <EmptyState
        title="Select a project"
        description="Keyword baselines belong to a project, so choose or create one first."
      />
    );
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const payload = payloadFromForm(form);
    if ('error' in payload) {
      setFormError(payload.error);
      return;
    }
    if (editing) {
      updateMutation.mutate({ id: editing.id, payload: payload.value });
    } else {
      createMutation.mutate(payload.value);
    }
  };

  const handleBulkImport = () => {
    const parsed = parseBulkRows(bulkText);
    if ('error' in parsed) {
      setBulkError(parsed.error);
      return;
    }
    bulkMutation.mutate(parsed.value);
  };

  const startEdit = (baseline: KeywordBaseline) => {
    setEditing(baseline);
    setForm(formFromBaseline(baseline));
    setFormError(null);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-2xl font-semibold tracking-normal text-slate-950">
            <KeyRound className="h-6 w-6 text-blue-700" aria-hidden="true" />
            Keywords
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Manual keyword baselines for {project?.name ?? 'this project'}.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => void baselinesQuery.refetch()}
          disabled={baselinesQuery.isFetching}
        >
          <RefreshCw
            className={baselinesQuery.isFetching ? 'mr-2 h-4 w-4 animate-spin' : 'mr-2 h-4 w-4'}
            aria-hidden="true"
          />
          Refresh
        </Button>
      </div>

      <section className="grid gap-4 md:grid-cols-4">
        <SummaryCard label="Total Keywords" value={summary.total} />
        <SummaryCard label="Top 10" value={summary.top10} />
        <SummaryCard label="Top 20" value={summary.top20} />
        <SummaryCard label="Missing Position" value={summary.missing} />
      </section>

      <section className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
        <form onSubmit={handleSubmit} className="rounded-lg border bg-white">
          <div className="border-b px-5 py-4">
            <h3 className="text-base font-semibold text-slate-950">
              {editing ? 'Edit keyword baseline' : 'Add keyword baseline'}
            </h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Example: local seo services, Phoenix, desktop, 18, https://example.com/services.
            </p>
          </div>
          <div className="grid gap-4 p-5 sm:grid-cols-2">
            <Field label="Keyword" required>
              <Input
                value={form.keyword}
                onChange={(event) => setForm({ ...form, keyword: event.target.value })}
                placeholder="local seo services"
              />
            </Field>
            <Field label="Location">
              <Input
                value={form.target_location}
                onChange={(event) => setForm({ ...form, target_location: event.target.value })}
                placeholder="Phoenix, AZ"
              />
            </Field>
            <Field label="Device">
              <select
                className={selectClassName}
                value={form.device}
                onChange={(event) =>
                  setForm({ ...form, device: event.target.value as 'desktop' | 'mobile' })
                }
              >
                <option value="desktop">Desktop</option>
                <option value="mobile">Mobile</option>
              </select>
            </Field>
            <Field label="Position">
              <Input
                type="number"
                min={1}
                max={100}
                value={form.current_position}
                onChange={(event) => setForm({ ...form, current_position: event.target.value })}
                placeholder="1-100"
              />
            </Field>
            <Field label="Current URL">
              <Input
                value={form.current_url}
                onChange={(event) => setForm({ ...form, current_url: event.target.value })}
                placeholder="https://example.com/service-page"
              />
            </Field>
            <Field label="Intent">
              <Input
                value={form.intent}
                onChange={(event) => setForm({ ...form, intent: event.target.value })}
                placeholder="commercial"
              />
            </Field>
            <Field label="Search Volume">
              <Input
                type="number"
                min={0}
                value={form.search_volume}
                onChange={(event) => setForm({ ...form, search_volume: event.target.value })}
                placeholder="Optional"
              />
            </Field>
            <Field label="Difficulty">
              <Input
                type="number"
                min={0}
                max={100}
                value={form.difficulty}
                onChange={(event) => setForm({ ...form, difficulty: event.target.value })}
                placeholder="0-100"
              />
            </Field>
            <div className="sm:col-span-2">
              <Label>Notes</Label>
              <textarea
                className={textareaClassName}
                value={form.notes}
                onChange={(event) => setForm({ ...form, notes: event.target.value })}
                placeholder="Manual source, date checked, or client notes"
                rows={3}
              />
            </div>
            {formError || createMutation.isError || updateMutation.isError ? (
              <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800 sm:col-span-2">
                {formError ?? 'Keyword baseline could not be saved.'}
              </p>
            ) : null}
            <div className="flex flex-wrap gap-2 sm:col-span-2">
              <Button type="submit" disabled={createMutation.isPending || updateMutation.isPending}>
                {editing ? (
                  <Save className="mr-2 h-4 w-4" aria-hidden="true" />
                ) : (
                  <PlusCircle className="mr-2 h-4 w-4" aria-hidden="true" />
                )}
                {editing ? 'Save Changes' : 'Add Keyword'}
              </Button>
              {editing ? (
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setEditing(null);
                    setForm(emptyForm);
                    setFormError(null);
                  }}
                >
                  Cancel
                </Button>
              ) : null}
            </div>
          </div>
        </form>

        <section className="rounded-lg border bg-white">
          <div className="border-b px-5 py-4">
            <h3 className="text-base font-semibold text-slate-950">Bulk paste</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              One keyword per line, or keyword,location,device,position,url,intent,notes.
            </p>
          </div>
          <div className="space-y-4 p-5">
            <textarea
              className={textareaClassName}
              value={bulkText}
              onChange={(event) => setBulkText(event.target.value)}
              rows={10}
              placeholder={'local seo services,Phoenix,desktop,18,https://example.com/services,commercial,manual check\ntechnical seo audit'}
            />
            {bulkError || bulkMutation.isError ? (
              <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
                {bulkError ?? 'Bulk import could not be saved.'}
              </p>
            ) : null}
            <Button
              type="button"
              onClick={handleBulkImport}
              disabled={bulkMutation.isPending || !bulkText.trim()}
            >
              <Upload className="mr-2 h-4 w-4" aria-hidden="true" />
              Import Lines
            </Button>
          </div>
        </section>
      </section>

      {baselinesQuery.isLoading ? <LoadingBlock label="Loading baselines" /> : null}
      {baselinesQuery.isError ? (
        <ErrorState
          title="Keyword baselines could not load"
          message="The keyword baseline endpoint returned an error."
          onRetry={() => void baselinesQuery.refetch()}
        />
      ) : null}

      {!baselinesQuery.isLoading && !baselines.length ? (
        <EmptyState
          title="No keyword baselines"
          description="Add manual keyword baseline data. This MVP does not scrape Google automatically."
        />
      ) : null}

      {baselines.length ? (
        <section className="overflow-hidden rounded-lg border bg-white">
          <div className="border-b px-5 py-4">
            <h3 className="text-base font-semibold text-slate-950">Baseline table</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Manual current position context for reports and weekly planner tasks.
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-[980px] w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-normal text-slate-500">
                <tr>
                  <Th>Keyword</Th>
                  <Th>Location</Th>
                  <Th>Device</Th>
                  <Th>Position</Th>
                  <Th>Current URL</Th>
                  <Th>Intent</Th>
                  <Th>Captured</Th>
                  <Th>Notes</Th>
                  <Th>Actions</Th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {baselines.map((baseline) => (
                  <tr key={baseline.id} className="align-top">
                    <Td className="font-medium text-slate-950">{baseline.keyword}</Td>
                    <Td>{baseline.target_location || 'Not provided'}</Td>
                    <Td className="capitalize">{baseline.device}</Td>
                    <Td>{baseline.current_position ?? 'Missing'}</Td>
                    <Td>
                      {baseline.current_url ? (
                        <span className="break-words text-slate-700">{baseline.current_url}</span>
                      ) : (
                        'Not mapped'
                      )}
                    </Td>
                    <Td>{baseline.intent || 'Not provided'}</Td>
                    <Td>{formatDateTime(baseline.captured_at)}</Td>
                    <Td>{baseline.notes || 'None'}</Td>
                    <Td>
                      <div className="flex gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => startEdit(baseline)}
                          title="Edit keyword baseline"
                        >
                          <Pencil className="h-4 w-4" aria-hidden="true" />
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            if (window.confirm('Delete this keyword baseline?')) {
                              deleteMutation.mutate(baseline.id);
                            }
                          }}
                          title="Delete keyword baseline"
                          disabled={deleteMutation.isPending}
                        >
                          <Trash2 className="h-4 w-4" aria-hidden="true" />
                        </Button>
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}

function SummaryCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border bg-white p-4">
      <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">{label}</p>
      <p className="mt-2 text-3xl font-semibold text-slate-950">{value.toLocaleString()}</p>
    </div>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <div>
      <Label>
        {label}
        {required ? <span className="text-rose-600"> *</span> : null}
      </Label>
      <div className="mt-2">{children}</div>
    </div>
  );
}

function Th({ children }: { children: ReactNode }) {
  return <th className="px-4 py-3 font-semibold">{children}</th>;
}

function Td({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <td className={`max-w-56 px-4 py-3 text-slate-700 ${className}`}>{children}</td>;
}

function formFromBaseline(baseline: KeywordBaseline): FormState {
  return {
    keyword: baseline.keyword,
    target_location: baseline.target_location ?? '',
    device: baseline.device === 'mobile' ? 'mobile' : 'desktop',
    current_position: baseline.current_position?.toString() ?? '',
    current_url: baseline.current_url ?? '',
    search_volume: baseline.search_volume?.toString() ?? '',
    difficulty: baseline.difficulty?.toString() ?? '',
    intent: baseline.intent ?? '',
    notes: baseline.notes ?? '',
  };
}

function payloadFromForm(form: FormState): { value: KeywordBaselinePayload } | { error: string } {
  const keyword = form.keyword.trim();
  if (!keyword) return { error: 'Keyword is required.' };
  const currentPosition = parseOptionalNumber(form.current_position, 1, 100, 'Position');
  if ('error' in currentPosition) return currentPosition;
  const searchVolume = parseOptionalNumber(form.search_volume, 0, undefined, 'Search volume');
  if ('error' in searchVolume) return searchVolume;
  const difficulty = parseOptionalNumber(form.difficulty, 0, 100, 'Difficulty');
  if ('error' in difficulty) return difficulty;

  return {
    value: {
      keyword,
      target_location: optionalText(form.target_location),
      search_engine: 'google',
      device: form.device,
      current_position: currentPosition.value,
      current_url: optionalText(form.current_url),
      search_volume: searchVolume.value,
      difficulty: difficulty.value,
      intent: optionalText(form.intent),
      notes: optionalText(form.notes),
      source: 'manual',
    },
  };
}

function parseBulkRows(text: string): { value: KeywordBaselinePayload[] } | { error: string } {
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (!lines.length) return { error: 'Paste at least one keyword.' };
  const items: KeywordBaselinePayload[] = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const parts = line.includes(',') ? line.split(',').map((part: string) => part.trim()) : [line];
    const [keyword, location, deviceRaw, positionRaw, url, intent, ...notesParts] = parts;
    if (!keyword?.trim()) return { error: `Line ${index + 1} is missing a keyword.` };
    const position = parseOptionalNumber(positionRaw ?? '', 1, 100, `Line ${index + 1} position`);
    if ('error' in position) return position;
    const device = deviceRaw?.toLowerCase() === 'mobile' ? 'mobile' : 'desktop';
    items.push({
      keyword: keyword.trim(),
      target_location: optionalText(location),
      search_engine: 'google',
      device,
      current_position: position.value,
      current_url: optionalText(url),
      intent: optionalText(intent),
      notes: optionalText(notesParts.join(',')),
      source: 'csv',
    });
  }
  return { value: items };
}

function parseOptionalNumber(
  value: string,
  min: number,
  max: number | undefined,
  label: string
): { value: number | null } | { error: string } {
  const text = value.trim();
  if (!text) return { value: null };
  const parsed = Number(text);
  if (!Number.isInteger(parsed)) return { error: `${label} must be a whole number.` };
  if (parsed < min || (max !== undefined && parsed > max)) {
    return { error: `${label} must be ${max ? `${min}-${max}` : `${min} or higher`}.` };
  }
  return { value: parsed };
}

function optionalText(value?: string | null) {
  const text = value?.trim();
  return text || null;
}

function keywordSummary(baselines: KeywordBaseline[]) {
  return baselines.reduce(
    (acc, baseline) => {
      acc.total += 1;
      const position = baseline.current_position;
      if (position === null || position === undefined) {
        acc.missing += 1;
      } else {
        if (position <= 10) acc.top10 += 1;
        if (position <= 20) acc.top20 += 1;
      }
      return acc;
    },
    { total: 0, top10: 0, top20: 0, missing: 0 }
  );
}

const selectClassName =
  'flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2';

const textareaClassName =
  'mt-2 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50';
