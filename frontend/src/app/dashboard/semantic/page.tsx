'use client';

import { Search } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { Button } from '@/components/ui/button';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi } from '@/lib/dashboard-api';
import type { SemanticSearchResult } from '@/types/dashboard';

export default function SemanticSearchPage() {
  const { projectId } = useDashboardProject();
  const [queryText, setQueryText] = useState('SEO recommendations');
  const [submittedQuery, setSubmittedQuery] = useState('SEO recommendations');

  useEffect(() => {
    const requestedQuery = new URLSearchParams(window.location.search).get('query');
    if (requestedQuery) {
      setQueryText(requestedQuery);
      setSubmittedQuery(requestedQuery);
    }
  }, []);

  const searchQuery = useQuery({
    queryKey: ['semantic-search', projectId, submittedQuery],
    queryFn: () => dashboardApi.semantic.search(submittedQuery, projectId),
    enabled: Boolean(projectId && submittedQuery.trim()),
    retry: false,
  });

  if (!projectId) {
    return (
      <EmptyState
        title="Select a project"
        description="Semantic search needs a selected project and an indexed crawl."
      />
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-normal text-slate-950">
          Semantic Search
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Search locally indexed crawl content in Qdrant.
        </p>
      </div>

      <form
        className="flex flex-col gap-3 rounded-lg border bg-white p-4 sm:flex-row sm:items-end"
        onSubmit={(event) => {
          event.preventDefault();
          setSubmittedQuery(queryText.trim());
        }}
      >
        <label className="flex-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Query
          <input
            className="mt-1 h-10 w-full rounded-md border bg-white px-3 text-sm normal-case tracking-normal text-slate-900 focus:outline-none focus:ring-2 focus:ring-ring"
            value={queryText}
            onChange={(event) => setQueryText(event.target.value)}
            placeholder="Find pages about pricing, metadata, blog topics..."
          />
        </label>
        <Button type="submit" disabled={!queryText.trim() || searchQuery.isFetching}>
          <Search className="mr-2 h-4 w-4" aria-hidden="true" />
          Search
        </Button>
      </form>

      {searchQuery.isLoading ? <LoadingBlock label="Searching semantic index" /> : null}
      {searchQuery.isError ? (
        <ErrorState
          title="Semantic search could not run"
          message="Run SEO Analysis first and confirm Qdrant is available."
          onRetry={() => void searchQuery.refetch()}
        />
      ) : null}
      {!searchQuery.isLoading && !searchQuery.isError ? (
        <SearchResults results={searchQuery.data?.results ?? []} query={submittedQuery} />
      ) : null}
    </div>
  );
}

function SearchResults({
  results,
  query,
}: {
  results: SemanticSearchResult[];
  query: string;
}) {
  if (!query.trim()) {
    return (
      <EmptyState
        title="Enter a semantic query"
        description="Try a topic, issue, or page intent from the latest crawl."
      />
    );
  }

  if (results.length === 0) {
    return (
      <div className="rounded-lg border border-dashed bg-white p-8 text-center">
        <p className="text-sm font-semibold text-slate-900">No semantic matches found</p>
        <p className="mx-auto mt-2 max-w-xl text-sm text-muted-foreground">
          The current query did not match indexed crawl vectors. Run SEO Analysis or try a broader query.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {results.map((result) => (
        <div key={result.point_id} className="rounded-lg border bg-white p-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="break-words text-sm font-medium text-slate-950">{result.url}</p>
              {result.heading_context ? (
                <p className="mt-1 text-sm text-slate-700">{result.heading_context}</p>
              ) : null}
            </div>
            <span className="text-xs font-medium text-muted-foreground">
              {(result.score * 100).toFixed(1)}%
            </span>
          </div>
          {result.text_preview ? (
            <p className="mt-3 line-clamp-4 text-sm leading-6 text-muted-foreground">
              {result.text_preview}
            </p>
          ) : null}
        </div>
      ))}
    </div>
  );
}
