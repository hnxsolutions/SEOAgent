'use client';

import { Camera, RefreshCw, Save } from 'lucide-react';
import type { ReactNode } from 'react';
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ActionNotice, EmptyState, ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { StatusBadge } from '@/components/dashboard/StatusBadge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { dashboardApi } from '@/lib/dashboard-api';
import { formatDateTime } from '@/lib/utils';
import type { SerpSnapshot, UUID } from '@/types/dashboard';

type ResultInput = {
  position: number;
  title: string;
  url: string;
  snippet?: string;
};

const emptyResults: ResultInput[] = Array.from({ length: 10 }, (_item, index) => ({
  position: index + 1,
  title: '',
  url: '',
  snippet: '',
}));

export default function SerpSnapshotsPage() {
  const queryClient = useQueryClient();
  const { projectId } = useDashboardProject();
  const [keyword, setKeyword] = useState('pcd pharma company in haryana');
  const [targetDomain, setTargetDomain] = useState('novakoshealthcare.com');
  const [targetUrl, setTargetUrl] = useState('');
  const [country, setCountry] = useState('India');
  const [city, setCity] = useState('');
  const [device, setDevice] = useState<'desktop' | 'mobile'>('desktop');
  const [language, setLanguage] = useState('en');
  const [notes, setNotes] = useState('');
  const [results, setResults] = useState<ResultInput[]>(emptyResults);
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<UUID>();
  const [screenshot, setScreenshot] = useState<File>();
  const [notice, setNotice] = useState<string>();

  const summaryQuery = useQuery({
    queryKey: ['serp-summary', projectId],
    queryFn: () => dashboardApi.serpSnapshots.summary(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const snapshotsQuery = useQuery({
    queryKey: ['serp-snapshots', projectId],
    queryFn: () => dashboardApi.serpSnapshots.list(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const historyQuery = useQuery({
    queryKey: ['serp-history', projectId, keyword],
    queryFn: () => dashboardApi.serpSnapshots.history(projectId!, keyword || undefined),
    enabled: Boolean(projectId),
    retry: false,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      dashboardApi.serpSnapshots.create(projectId!, {
        keyword,
        target_domain: targetDomain,
        target_url: targetUrl || undefined,
        country,
        city: city || undefined,
        device,
        language: language || undefined,
        notes: notes || undefined,
        results: results.filter((item) => item.title.trim() && item.url.trim()),
      }),
    onSuccess: async (snapshot) => {
      setSelectedSnapshotId(snapshot.id);
      setNotice(
        snapshot.observed_target_rank
          ? `Snapshot saved. Target observed at position ${snapshot.observed_target_rank}.`
          : 'Snapshot saved. Target domain was not visible in the submitted results.'
      );
      await invalidateSerp(projectId, queryClient);
    },
  });

  const uploadMutation = useMutation({
    mutationFn: () => dashboardApi.serpSnapshots.uploadScreenshot(selectedSnapshotId!, screenshot!),
    onSuccess: async () => {
      setScreenshot(undefined);
      setNotice('Screenshot metadata saved.');
      await invalidateSerp(projectId, queryClient);
    },
  });

  if (!projectId) {
    return <EmptyState title="Select a project" description="SERP snapshots are scoped to one project." />;
  }

  if (summaryQuery.isLoading || snapshotsQuery.isLoading || historyQuery.isLoading) {
    return <LoadingBlock label="Loading SERP snapshots" />;
  }

  if (summaryQuery.isError || snapshotsQuery.isError || historyQuery.isError) {
    return (
      <ErrorState
        title="SERP snapshots could not load"
        message="The API may be unavailable or this project may not have manual snapshots yet."
        onRetry={() => {
          void summaryQuery.refetch();
          void snapshotsQuery.refetch();
          void historyQuery.refetch();
        }}
      />
    );
  }

  const snapshots = snapshotsQuery.data?.snapshots ?? [];
  const latestSnapshot = snapshots[0];
  const selectedSnapshot = snapshots.find((item) => item.id === selectedSnapshotId) ?? latestSnapshot;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-normal text-slate-950">
            Manual SERP Snapshots
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            SERP snapshots are manual evidence. Official rank tracking uses GSC average position.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            void invalidateSerp(projectId, queryClient);
          }}
        >
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh
        </Button>
      </div>

      <ActionNotice message={notice} />

      <section className="grid gap-4 md:grid-cols-3">
        <MetricCard label="Snapshots" value={summaryQuery.data?.total_snapshots ?? 0} />
        <MetricCard label="Keywords tracked" value={summaryQuery.data?.keywords_tracked ?? 0} />
        <MetricCard
          label="Latest observed rank"
          value={latestSnapshot?.observed_target_rank ? `#${latestSnapshot.observed_target_rank}` : 'Not visible'}
        />
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-lg border bg-white">
          <div className="border-b px-5 py-4">
            <h3 className="text-base font-semibold text-slate-950">Capture manual snapshot</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Paste visible results from your own manual search session. No Google search is automated here.
            </p>
          </div>
          <div className="space-y-4 p-5">
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Keyword">
                <Input value={keyword} onChange={(event) => setKeyword(event.target.value)} />
              </Field>
              <Field label="Target domain">
                <Input value={targetDomain} onChange={(event) => setTargetDomain(event.target.value)} />
              </Field>
              <Field label="Target URL">
                <Input
                  value={targetUrl}
                  onChange={(event) => setTargetUrl(event.target.value)}
                  placeholder="Optional exact URL"
                />
              </Field>
              <Field label="Country">
                <Input value={country} onChange={(event) => setCountry(event.target.value)} />
              </Field>
              <Field label="City">
                <Input value={city} onChange={(event) => setCity(event.target.value)} placeholder="Optional city" />
              </Field>
              <Field label="Language">
                <Input value={language} onChange={(event) => setLanguage(event.target.value)} />
              </Field>
              <Field label="Device">
                <select
                  className="h-10 w-full rounded-md border bg-white px-3 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  value={device}
                  onChange={(event) => setDevice(event.target.value as 'desktop' | 'mobile')}
                >
                  <option value="desktop">Desktop</option>
                  <option value="mobile">Mobile</option>
                </select>
              </Field>
              <Field label="Notes">
                <Input value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Optional note" />
              </Field>
            </div>

            <div className="rounded-md border">
              <div className="border-b bg-slate-50 px-3 py-2 text-sm font-medium text-slate-700">
                Top results
              </div>
              <div className="divide-y">
                {results.map((item, index) => (
                  <div key={item.position} className="grid gap-2 p-3 md:grid-cols-[70px_1fr_1.4fr]">
                    <Input
                      type="number"
                      min={1}
                      value={item.position}
                      onChange={(event) => updateResult(index, { position: Number(event.target.value) || index + 1 }, results, setResults)}
                      aria-label={`Position ${item.position}`}
                    />
                    <Input
                      value={item.title}
                      onChange={(event) => updateResult(index, { title: event.target.value }, results, setResults)}
                      placeholder="Result title"
                    />
                    <Input
                      value={item.url}
                      onChange={(event) => updateResult(index, { url: event.target.value }, results, setResults)}
                      placeholder="https://example.com/page"
                    />
                  </div>
                ))}
              </div>
            </div>

            <Button
              type="button"
              onClick={() => createMutation.mutate()}
              disabled={
                createMutation.isPending ||
                !keyword.trim() ||
                !targetDomain.trim() ||
                !country.trim() ||
                results.every((item) => !item.title.trim() || !item.url.trim())
              }
            >
              <Save className="mr-2 h-4 w-4" />
              Save snapshot
            </Button>
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-lg border bg-white">
            <div className="border-b px-5 py-4">
              <h3 className="text-base font-semibold text-slate-950">Screenshot evidence</h3>
            </div>
            <div className="space-y-4 p-5">
              <select
                className="h-10 w-full rounded-md border bg-white px-3 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                value={selectedSnapshot?.id ?? ''}
                onChange={(event) => setSelectedSnapshotId(event.target.value || undefined)}
                aria-label="Select snapshot"
              >
                {snapshots.length === 0 ? <option value="">No snapshots yet</option> : null}
                {snapshots.map((snapshot) => (
                  <option key={snapshot.id} value={snapshot.id}>
                    {snapshot.keyword} - {snapshot.observed_target_rank ? `#${snapshot.observed_target_rank}` : 'not visible'}
                  </option>
                ))}
              </select>
              <Input
                type="file"
                accept="image/*"
                onChange={(event) => setScreenshot(event.target.files?.[0])}
              />
              <Button
                type="button"
                variant="outline"
                onClick={() => uploadMutation.mutate()}
                disabled={!selectedSnapshot?.id || !screenshot || uploadMutation.isPending}
              >
                <Camera className="mr-2 h-4 w-4" />
                Save screenshot metadata
              </Button>
              <p className="text-sm text-muted-foreground">
                Upload stores evidence metadata with the manual snapshot. It does not search Google.
              </p>
            </div>
          </div>

          {selectedSnapshot ? <SnapshotDetail snapshot={selectedSnapshot} /> : null}
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <SnapshotList snapshots={snapshots} onSelect={(snapshot) => setSelectedSnapshotId(snapshot.id)} />
        <HistoryList snapshots={historyQuery.data?.history ?? []} />
      </section>
    </div>
  );
}

function SnapshotDetail({ snapshot }: { snapshot: SerpSnapshot }) {
  return (
    <div className="rounded-lg border bg-white">
      <div className="border-b px-5 py-4">
        <h3 className="text-base font-semibold text-slate-950">Observed target</h3>
      </div>
      <div className="space-y-4 p-5 text-sm">
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">Status</span>
          <StatusBadge status={snapshot.status} />
        </div>
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">Rank</span>
          <span className="font-medium text-slate-950">
            {snapshot.observed_target_rank ? `#${snapshot.observed_target_rank}` : 'Missing target'}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">Previous rank</span>
          <span className="font-medium text-slate-950">
            {snapshot.previous_rank ? `#${snapshot.previous_rank}` : 'No previous snapshot'}
          </span>
        </div>
        <div>
          <p className="font-medium text-slate-950">Competitors above target</p>
          <div className="mt-2 space-y-2">
            {snapshot.competitors_above_target.length ? (
              snapshot.competitors_above_target.slice(0, 5).map((result) => (
                <div key={result.id} className="rounded-md bg-slate-50 px-3 py-2">
                  <p className="font-medium text-slate-950">#{result.position} {result.domain}</p>
                  <p className="mt-1 break-all text-muted-foreground">{result.url}</p>
                </div>
              ))
            ) : (
              <p className="text-muted-foreground">No competitors above target in this snapshot.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function SnapshotList({
  snapshots,
  onSelect,
}: {
  snapshots: SerpSnapshot[];
  onSelect: (_snapshot: SerpSnapshot) => void;
}) {
  return (
    <div className="rounded-lg border bg-white">
      <div className="border-b px-5 py-4">
        <h3 className="text-base font-semibold text-slate-950">Recent snapshots</h3>
      </div>
      <div className="divide-y">
        {snapshots.length ? (
          snapshots.map((snapshot) => (
            <button
              key={snapshot.id}
              type="button"
              className="block w-full px-5 py-4 text-left hover:bg-slate-50"
              onClick={() => onSelect(snapshot)}
            >
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="font-medium text-slate-950">{snapshot.keyword}</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {snapshot.country} {snapshot.city ? `- ${snapshot.city}` : ''} - {snapshot.device}
                  </p>
                </div>
                <div className="text-right">
                  <p className="font-semibold text-slate-950">
                    {snapshot.observed_target_rank ? `#${snapshot.observed_target_rank}` : 'Missing'}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">{formatDateTime(snapshot.captured_at)}</p>
                </div>
              </div>
            </button>
          ))
        ) : (
          <div className="p-5">
            <EmptyState title="No snapshots yet" description="Add a manual snapshot to track visible SERP evidence." />
          </div>
        )}
      </div>
    </div>
  );
}

function HistoryList({ snapshots }: { snapshots: SerpSnapshot[] }) {
  return (
    <div className="rounded-lg border bg-white">
      <div className="border-b px-5 py-4">
        <h3 className="text-base font-semibold text-slate-950">Historical movement</h3>
      </div>
      <div className="divide-y">
        {snapshots.length ? (
          snapshots.map((snapshot) => (
            <div key={snapshot.id} className="flex items-center justify-between px-5 py-4 text-sm">
              <div>
                <p className="font-medium text-slate-950">{formatDateTime(snapshot.captured_at)}</p>
                <p className="mt-1 text-muted-foreground">{snapshot.keyword}</p>
              </div>
              <div className="text-right">
                <p className="font-semibold text-slate-950">
                  {snapshot.observed_target_rank ? `#${snapshot.observed_target_rank}` : 'Not visible'}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {snapshot.rank_delta ? `Change ${formatSigned(snapshot.rank_delta)}` : 'No prior comparison'}
                </p>
              </div>
            </div>
          ))
        ) : (
          <div className="p-5">
            <EmptyState title="No history" description="History appears after at least one manual snapshot." />
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-2">
      <span className="text-sm font-medium text-slate-700">{label}</span>
      {children}
    </label>
  );
}

function MetricCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border bg-white p-4">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-slate-950">{value}</p>
    </div>
  );
}

function updateResult(
  index: number,
  patch: Partial<ResultInput>,
  results: ResultInput[],
  setResults: (_results: ResultInput[]) => void
) {
  setResults(results.map((item, itemIndex) => (itemIndex === index ? { ...item, ...patch } : item)));
}

function formatSigned(value: number) {
  return value > 0 ? `+${value}` : `${value}`;
}

async function invalidateSerp(projectId: UUID | undefined, queryClient: ReturnType<typeof useQueryClient>) {
  if (!projectId) return;
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ['serp-summary', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['serp-snapshots', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['serp-history', projectId] }),
  ]);
}
