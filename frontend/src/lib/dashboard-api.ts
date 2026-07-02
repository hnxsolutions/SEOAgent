import type { AxiosResponse } from 'axios';
import { api, projectAPI } from '@/lib/api';
import type {
  AuditRun,
  AuditSummary,
  BlogDraft,
  BlogInfrastructureCheck,
  BlogPlan,
  BlogPublishActionResponse,
  BlogPublishConnection,
  BlogTopic,
  ContentOptimizationRun,
  ContentSuggestion,
  ContentSummary,
  CrawlJob,
  CrawlListResponse,
  CrawlPage,
  GeoAeoPageScore,
  GeoAeoRecommendation,
  GeoAeoRun,
  GeoAeoSummary,
  GoogleOAuthStart,
  GSCProperty,
  GSCSyncJob,
  ImpactExperiment,
  ImpactResult,
  ImpactSummary,
  IndexingFixPlan,
  IndexingIssue,
  IndexingRun,
  IndexingRunDetail,
  IndexingSummary,
  IndexingValidationResponse,
  InternalLinkGeneration,
  InternalLinkSummary,
  KnowledgeIndexRun,
  KnowledgeSource,
  PatchApplyRun,
  PlannerRun,
  PlannerSummary,
  PlannerTask,
  Project,
  PullRequestRecord,
  RankTrackingKeywordRow,
  RankTrackingPageRow,
  RankTrackingRow,
  RankTrackingSummary,
  RepoConnection,
  RepoScanRun,
  SearchConsoleImport,
  SearchConsoleOpportunity,
  SearchConsoleSummary,
  SerpSnapshot,
  SerpSnapshotSummary,
  SemanticIndexRun,
  SemanticSearchResponse,
  SeoCodeIssue,
  SeoCodePatch,
  SeoRun,
  SeoRunListResponse,
  SEOIssueListResponse,
  UUID,
  WeeklyReport,
} from '@/types/dashboard';

type Envelope<T, K extends string> = Record<K, T[]> & {
  limit: number;
  offset: number;
  has_more: boolean;
};

async function unwrap<T>(request: Promise<AxiosResponse<T>>): Promise<T> {
  const response = await request;
  return response.data;
}

export const dashboardApi = {
  listProjects: async () => unwrap<Project[]>(projectAPI.list()),
  createProject: (payload: {
    name: string;
    domain: string;
    description?: string;
    keywords?: string[];
  }) => unwrap<Project>(projectAPI.create(payload)),

  seoRuns: {
    start: (projectId: UUID) =>
      unwrap<SeoRun>(api.post(`/projects/${projectId}/seo-run`)),
    list: (projectId: UUID) =>
      unwrap<SeoRunListResponse>(
        api.get(`/projects/${projectId}/seo-runs`, { params: { limit: 10 } })
      ),
    status: (runId: UUID) =>
      unwrap<SeoRun>(api.get(`/seo-runs/${runId}/status`)),
  },

  planner: {
    run: (projectId: UUID) =>
      unwrap<PlannerRun>(
        api.post(`/planner/projects/${projectId}/run`, { run_type: 'manual' })
      ),
    listRuns: (projectId: UUID) =>
      unwrap<Envelope<PlannerRun, 'runs'>>(
        api.get(`/planner/projects/${projectId}/runs`, { params: { limit: 25 } })
      ),
    listTasks: (projectId: UUID, status?: string) =>
      unwrap<Envelope<PlannerTask, 'tasks'>>(
        api.get(`/planner/projects/${projectId}/tasks`, {
          params: { limit: 250, ...(status ? { status } : {}) },
        })
      ),
    getReport: (runId: UUID) =>
      unwrap<WeeklyReport>(api.get(`/planner/runs/${runId}/report`)),
    summary: (projectId: UUID) =>
      unwrap<PlannerSummary>(api.get(`/planner/projects/${projectId}/summary`)),
    approveTask: (taskId: UUID) =>
      unwrap<PlannerTask>(api.post(`/planner/tasks/${taskId}/approve`)),
    rejectTask: (taskId: UUID) =>
      unwrap<PlannerTask>(api.post(`/planner/tasks/${taskId}/reject`)),
    markTaskInProgress: (taskId: UUID) =>
      unwrap<PlannerTask>(api.post(`/planner/tasks/${taskId}/mark-in-progress`)),
    markTaskCompleted: (taskId: UUID) =>
      unwrap<PlannerTask>(api.post(`/planner/tasks/${taskId}/mark-completed`)),
  },

  crawls: {
    start: (payload: {
      url: string;
      project_id?: UUID;
      name?: string;
      max_pages?: number;
      depth?: number;
      priority?: string;
      render_javascript?: boolean;
      respect_robots_txt?: boolean;
    }) => unwrap<CrawlJob>(api.post('/crawls/start', payload)),
    status: (crawlId: UUID) =>
      unwrap<{ job: CrawlJob; progress: Record<string, unknown>; stats: Record<string, unknown> }>(
        api.get(`/crawls/${crawlId}/status`)
      ),
    list: (projectId?: UUID) =>
      unwrap<CrawlListResponse>(
        api.get('/crawls/', { params: { project_id: projectId, limit: 50 } })
      ),
    pages: (crawlId: UUID) =>
      unwrap<CrawlPage[]>(
        api.get(`/crawls/${crawlId}/pages`, { params: { limit: 50 } })
      ),
    auditSummary: (crawlId: UUID) =>
      unwrap<AuditSummary>(api.get(`/audits/crawls/${crawlId}/summary`)),
  },

  audits: {
    start: (crawlId: UUID) =>
      unwrap<AuditRun>(api.post(`/audits/crawls/${crawlId}/start`)),
    status: (auditId: UUID) =>
      unwrap<AuditRun>(api.get(`/audits/${auditId}/status`)),
    issues: (params?: { audit_id?: UUID; crawl_id?: UUID; project_id?: UUID }) =>
      unwrap<SEOIssueListResponse>(
        api.get('/audits/issues', { params: { limit: 250, ...params } })
      ),
  },

  semantic: {
    index: (crawlId: UUID) =>
      unwrap<SemanticIndexRun>(api.post(`/semantic/crawls/${crawlId}/index`)),
    status: (runId: UUID) =>
      unwrap<SemanticIndexRun>(api.get(`/semantic/index-runs/${runId}/status`)),
    search: (query: string, projectId?: UUID) =>
      unwrap<SemanticSearchResponse>(
        api.get('/semantic/search', {
          params: { query, project_id: projectId, limit: 10 },
        })
      ),
  },

  internalLinks: {
    generate: (crawlId: UUID) =>
      unwrap<InternalLinkGeneration>(
        api.post(`/internal-links/crawls/${crawlId}/generate`)
      ),
    summary: (crawlId: UUID) =>
      unwrap<InternalLinkSummary>(api.get(`/internal-links/crawls/${crawlId}/summary`)),
  },

  searchConsole: {
    startOAuth: () =>
      unwrap<GoogleOAuthStart>(api.post('/search-console/connections/google/start')),
    summary: (projectId: UUID) =>
      unwrap<SearchConsoleSummary>(
        api.get(`/search-console/projects/${projectId}/summary`)
      ),
    properties: (projectId: UUID) =>
      unwrap<{ properties: GSCProperty[]; oauth_enabled: boolean }>(
        api.get('/search-console/properties', { params: { project_id: projectId } })
      ),
    sync: (projectId: UUID) =>
      unwrap<GSCSyncJob>(
        api.post(`/search-console/projects/${projectId}/sync`, {
          sync_type: 'manual',
          comparison_window: 'last_28_days',
        })
      ),
    syncJobs: (projectId: UUID) =>
      unwrap<Envelope<GSCSyncJob, 'sync_jobs'>>(
        api.get(`/search-console/projects/${projectId}/sync-jobs`, {
          params: { limit: 25 },
        })
      ),
    registerManualProperty: (
      projectId: UUID,
      payload: { site_url: string; property_type: 'domain' | 'url_prefix'; notes?: string }
    ) =>
      unwrap<GSCProperty>(
        api.post(`/search-console/projects/${projectId}/property/manual`, payload)
      ),
    selectProperty: (projectId: UUID, propertyId: UUID) =>
      unwrap<GSCProperty>(
        api.post(`/search-console/projects/${projectId}/property`, {
          property_id: propertyId,
        })
      ),
    imports: (projectId: UUID) =>
      unwrap<Envelope<SearchConsoleImport, 'imports'>>(
        api.get('/search-console/imports', {
          params: { project_id: projectId, limit: 25 },
        })
      ),
    uploadCsv: (payload: {
      file: File;
      projectId?: UUID;
      dateStart: string;
      dateEnd: string;
      comparisonWindow?: string;
    }) => {
      const form = new FormData();
      form.append('file', payload.file);
      if (payload.projectId) form.append('project_id', payload.projectId);
      form.append('date_start', payload.dateStart);
      form.append('date_end', payload.dateEnd);
      if (payload.comparisonWindow) {
        form.append('comparison_window', payload.comparisonWindow);
      }
      return unwrap<SearchConsoleImport>(
        api.post('/search-console/imports', form, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
      );
    },
    opportunities: (importId: UUID, status?: string) =>
      unwrap<Envelope<SearchConsoleOpportunity, 'opportunities'>>(
        api.get(`/search-console/imports/${importId}/opportunities`, {
          params: { limit: 250, ...(status ? { status } : {}) },
        })
      ),
    approve: (id: UUID) =>
      unwrap<SearchConsoleOpportunity>(
        api.post(`/search-console/opportunities/${id}/approve`)
      ),
    reject: (id: UUID) =>
      unwrap<SearchConsoleOpportunity>(
        api.post(`/search-console/opportunities/${id}/reject`)
      ),
    complete: (id: UUID) =>
      unwrap<SearchConsoleOpportunity>(
        api.post(`/search-console/opportunities/${id}/mark-completed`)
      ),
  },

  rankTracking: {
    summary: (projectId: UUID) =>
      unwrap<RankTrackingSummary>(api.get(`/rank-tracking/projects/${projectId}/summary`)),
    rankings: (
      projectId: UUID,
      params?: {
        movement?: string;
        sort?: string;
        query?: string;
        page_url?: string;
        device?: string;
        country?: string;
        comparison_window?: string;
      }
    ) =>
      unwrap<Envelope<RankTrackingRow, 'rankings'>>(
        api.get(`/rank-tracking/projects/${projectId}/rankings`, {
          params: { limit: 250, ...params },
        })
      ),
    movements: (projectId: UUID, params?: { movement?: string; device?: string; country?: string }) =>
      unwrap<Envelope<RankTrackingRow, 'rankings'>>(
        api.get(`/rank-tracking/projects/${projectId}/movements`, {
          params: { limit: 100, ...params },
        })
      ),
    pages: (projectId: UUID, params?: { query?: string; device?: string; country?: string }) =>
      unwrap<Envelope<RankTrackingPageRow, 'pages'>>(
        api.get(`/rank-tracking/projects/${projectId}/pages`, {
          params: { limit: 100, ...params },
        })
      ),
    keywords: (projectId: UUID, params?: { query?: string; device?: string; country?: string }) =>
      unwrap<Envelope<RankTrackingKeywordRow, 'keywords'>>(
        api.get(`/rank-tracking/projects/${projectId}/keywords`, {
          params: { limit: 100, ...params },
        })
      ),
  },

  indexing: {
    summary: (projectId: UUID) =>
      unwrap<IndexingSummary>(api.get(`/indexing/projects/${projectId}/summary`)),
    inspect: (projectId: UUID, payload?: { urls?: string[]; limit?: number; language_code?: string }) =>
      unwrap<IndexingRun>(api.post(`/indexing/projects/${projectId}/inspect`, payload ?? {})),
    runs: (projectId: UUID) =>
      unwrap<Envelope<IndexingRun, 'runs'>>(
        api.get(`/indexing/projects/${projectId}/runs`, { params: { limit: 25 } })
      ),
    run: (runId: UUID) =>
      unwrap<IndexingRunDetail>(api.get(`/indexing/runs/${runId}`)),
    issues: (projectId: UUID, params?: { status?: string; issue_type?: string }) =>
      unwrap<Envelope<IndexingIssue, 'issues'>>(
        api.get(`/indexing/projects/${projectId}/issues`, {
          params: { limit: 250, ...params },
        })
      ),
    createFixPlan: (issueId: UUID) =>
      unwrap<IndexingFixPlan>(api.post(`/indexing/issues/${issueId}/create-fix-plan`)),
    ignore: (issueId: UUID) =>
      unwrap<IndexingIssue>(api.post(`/indexing/issues/${issueId}/ignore`)),
    validate: (issueId: UUID, payload?: { validation_after_days?: number; run_now?: boolean }) =>
      unwrap<IndexingValidationResponse>(
        api.post(`/indexing/issues/${issueId}/validate`, payload ?? { validation_after_days: 7, run_now: true })
      ),
  },

  impact: {
    summary: (projectId: UUID) =>
      unwrap<ImpactSummary>(api.get(`/impact/projects/${projectId}/summary`)),
    experiments: (projectId: UUID) =>
      unwrap<Envelope<ImpactExperiment, 'experiments'>>(
        api.get(`/impact/projects/${projectId}/experiments`, { params: { limit: 100 } })
      ),
    createExperiment: (payload: {
      project_id: UUID;
      experiment_type: string;
      source_type?: string;
      target_page_url: string;
      target_query?: string;
      baseline_start_date: string;
      baseline_end_date: string;
      review_after_days?: number;
      notes?: string;
    }) => unwrap<ImpactExperiment>(api.post('/impact/experiments', payload)),
    captureBaseline: (id: UUID) =>
      unwrap(api.post(`/impact/experiments/${id}/capture-baseline`)),
    markActionApplied: (id: UUID) =>
      unwrap<ImpactExperiment>(api.post(`/impact/experiments/${id}/mark-action-applied`, {})),
    evaluate: (id: UUID) =>
      unwrap<ImpactResult>(api.post(`/impact/experiments/${id}/evaluate`)),
  },

  serpSnapshots: {
    summary: (projectId: UUID) =>
      unwrap<SerpSnapshotSummary>(api.get(`/serp-snapshots/projects/${projectId}/summary`)),
    list: (projectId: UUID) =>
      unwrap<Envelope<SerpSnapshot, 'snapshots'>>(
        api.get(`/serp-snapshots/projects/${projectId}/snapshots`, { params: { limit: 100 } })
      ),
    history: (projectId: UUID, keyword?: string) =>
      unwrap<{ history: SerpSnapshot[] }>(
        api.get(`/serp-snapshots/projects/${projectId}/history`, {
          params: keyword ? { keyword } : undefined,
        })
      ),
    create: (projectId: UUID, payload: {
      keyword: string;
      target_url?: string;
      target_domain: string;
      country: string;
      city?: string;
      device: 'desktop' | 'mobile';
      language?: string;
      notes?: string;
      results: Array<{ position: number; title: string; url: string; snippet?: string }>;
    }) => unwrap<SerpSnapshot>(api.post(`/serp-snapshots/projects/${projectId}/snapshots`, payload)),
    uploadScreenshot: (snapshotId: UUID, file: File) => {
      const form = new FormData();
      form.append('file', file);
      return unwrap(api.post(`/serp-snapshots/${snapshotId}/screenshot`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      }));
    },
  },

  content: {
    generate: (crawlId: UUID) =>
      unwrap<ContentOptimizationRun>(
        api.post(`/content-optimization/crawls/${crawlId}/generate`)
      ),
    runStatus: (runId: UUID) =>
      unwrap<ContentOptimizationRun>(
        api.get(`/content-optimization/runs/${runId}/status`)
      ),
    summary: (crawlId: UUID) =>
      unwrap<ContentSummary>(
        api.get(`/content-optimization/crawls/${crawlId}/summary`)
      ),
    suggestions: (crawlId: UUID, params?: { status?: string; suggestion_type?: string }) =>
      unwrap<Envelope<ContentSuggestion, 'suggestions'>>(
        api.get(`/content-optimization/crawls/${crawlId}/suggestions`, {
          params: { limit: 250, ...params },
        })
      ),
    approve: (id: UUID) =>
      unwrap<ContentSuggestion>(
        api.post(`/content-optimization/suggestions/${id}/approve`)
      ),
    reject: (id: UUID) =>
      unwrap<ContentSuggestion>(
        api.post(`/content-optimization/suggestions/${id}/reject`)
      ),
    apply: (id: UUID) =>
      unwrap<ContentSuggestion>(
        api.post(`/content-optimization/suggestions/${id}/mark-applied`)
      ),
  },

  geoAeo: {
    analyze: (crawlId: UUID) =>
      unwrap<GeoAeoRun>(api.post(`/geo-aeo/crawls/${crawlId}/analyze`)),
    runStatus: (runId: UUID) =>
      unwrap<GeoAeoRun>(api.get(`/geo-aeo/runs/${runId}/status`)),
    summary: (crawlId: UUID) =>
      unwrap<GeoAeoSummary>(api.get(`/geo-aeo/crawls/${crawlId}/summary`)),
    pageScore: (pageId: UUID) =>
      unwrap<GeoAeoPageScore>(api.get(`/geo-aeo/pages/${pageId}/score`)),
    recommendations: (crawlId: UUID, params?: { status?: string; recommendation_type?: string }) =>
      unwrap<Envelope<GeoAeoRecommendation, 'recommendations'>>(
        api.get(`/geo-aeo/crawls/${crawlId}/recommendations`, {
          params: { limit: 250, ...params },
        })
      ),
    approve: (id: UUID) =>
      unwrap<GeoAeoRecommendation>(api.post(`/geo-aeo/recommendations/${id}/approve`)),
    reject: (id: UUID) =>
      unwrap<GeoAeoRecommendation>(api.post(`/geo-aeo/recommendations/${id}/reject`)),
    apply: (id: UUID) =>
      unwrap<GeoAeoRecommendation>(
        api.post(`/geo-aeo/recommendations/${id}/mark-applied`)
      ),
  },

  blogs: {
    plans: (projectId: UUID) =>
      unwrap<Envelope<BlogPlan, 'plans'>>(
        api.get('/blogs/plans', { params: { project_id: projectId, limit: 50 } })
      ),
    createPlan: (payload: {
      project_id: UUID;
      title: string;
      description?: string;
      target_site_url?: string;
      blogs_per_week: number;
    }) => unwrap<BlogPlan>(api.post('/blogs/plans', payload)),
    generateTopics: (planId: UUID, count?: number) =>
      unwrap<Envelope<BlogTopic, 'topics'>>(
        api.post(`/blogs/plans/${planId}/topics/generate`, { count })
      ),
    topics: (planId: UUID, status?: string) =>
      unwrap<Envelope<BlogTopic, 'topics'>>(
        api.get(`/blogs/plans/${planId}/topics`, {
          params: { limit: 250, ...(status ? { status } : {}) },
        })
      ),
    approveTopic: (id: UUID) => unwrap<BlogTopic>(api.post(`/blogs/topics/${id}/approve`)),
    rejectTopic: (id: UUID) => unwrap<BlogTopic>(api.post(`/blogs/topics/${id}/reject`)),
    draftTopic: (id: UUID) => unwrap<BlogDraft>(api.post(`/blogs/topics/${id}/draft`)),
    drafts: (planId: UUID) =>
      unwrap<Envelope<BlogDraft, 'drafts'>>(
        api.get(`/blogs/plans/${planId}/drafts`, { params: { limit: 50 } })
      ),
    draft: (draftId: UUID) => unwrap<BlogDraft>(api.get(`/blogs/drafts/${draftId}`)),
  },

  blogPublishing: {
    connections: (projectId: UUID) =>
      unwrap<Envelope<BlogPublishConnection, 'connections'>>(
        api.get(`/blog-publishing/connections/projects/${projectId}`, {
          params: { limit: 100 },
        })
      ),
    checkInfrastructure: (projectId: UUID, payload?: { repo_connection_id?: UUID }) =>
      unwrap<BlogInfrastructureCheck>(
        api.post(`/blog-publishing/projects/${projectId}/check-infrastructure`, payload ?? {})
      ),
    infrastructure: (projectId: UUID) =>
      unwrap<BlogInfrastructureCheck>(
        api.get(`/blog-publishing/projects/${projectId}/infrastructure`)
      ),
    exportMarkdown: (
      draftId: UUID,
      payload: { connection_id?: UUID; export_folder_path?: string; overwrite?: boolean }
    ) =>
      unwrap<BlogPublishActionResponse>(
        api.post(`/blog-publishing/drafts/${draftId}/export-markdown`, payload)
      ),
    createWordPressDraft: (draftId: UUID, connectionId: UUID) =>
      unwrap<BlogPublishActionResponse>(
        api.post(`/blog-publishing/drafts/${draftId}/create-wordpress-draft`, {
          connection_id: connectionId,
        })
      ),
    createNextJsBlogPatch: (
      draftId: UUID,
      payload: {
        connection_id?: UUID;
        repo_connection_id?: UUID;
        content_directory?: string;
        extension?: 'md' | 'mdx';
        overwrite?: boolean;
      }
    ) =>
      unwrap<BlogPublishActionResponse>(
        api.post(`/blog-publishing/drafts/${draftId}/create-nextjs-blog-patch`, payload)
      ),
    createInfrastructurePatch: (
      projectId: UUID,
      payload?: { connection_id?: UUID; repo_connection_id?: UUID; strategy?: string }
    ) =>
      unwrap<BlogPublishActionResponse>(
        api.post(`/blog-publishing/projects/${projectId}/create-blog-infrastructure-patch`, payload ?? {})
      ),
  },

  knowledge: {
    sources: (projectId: UUID) =>
      unwrap<Envelope<KnowledgeSource, 'sources'>>(
        api.get('/knowledge/sources', {
          params: { project_id: projectId, limit: 50 },
        })
      ),
    createSource: (payload: {
      project_id?: UUID;
      title: string;
      content: string;
      source_type?: string;
      description?: string;
      metadata?: Record<string, unknown>;
    }) => unwrap<KnowledgeSource>(api.post('/knowledge/sources', payload)),
    indexSource: (sourceId: UUID) =>
      unwrap<KnowledgeIndexRun>(api.post(`/knowledge/sources/${sourceId}/index`)),
    indexStatus: (runId: UUID) =>
      unwrap<KnowledgeIndexRun>(api.get(`/knowledge/index-runs/${runId}/status`)),
  },

  repos: {
    connections: (projectId: UUID) =>
      unwrap<Envelope<RepoConnection, 'connections'>>(
        api.get('/repos/connections', {
          params: { project_id: projectId, limit: 50 },
        })
      ),
    createConnection: (payload: {
      project_id: UUID;
      provider: 'local' | 'github';
      local_path?: string;
      repo_url?: string;
      default_branch?: string;
      framework?: string;
    }) => unwrap<RepoConnection>(api.post('/repos/connections', payload)),
    scan: (connectionId: UUID) =>
      unwrap<RepoScanRun>(api.post(`/repos/connections/${connectionId}/scan`)),
    scanStatus: (scanId: UUID) =>
      unwrap<RepoScanRun>(api.get(`/repos/scans/${scanId}/status`)),
    issues: (scanId: UUID, status?: string) =>
      unwrap<Envelope<SeoCodeIssue, 'issues'>>(
        api.get(`/repos/scans/${scanId}/issues`, {
          params: { limit: 250, ...(status ? { status } : {}) },
        })
      ),
    generatePatches: (scanId: UUID) =>
      unwrap<{ scan_id: UUID; patches_created: number; patches: SeoCodePatch[] }>(
        api.post(`/repos/scans/${scanId}/patches/generate`)
      ),
    patches: (scanId: UUID, status?: string) =>
      unwrap<Envelope<SeoCodePatch, 'patches'>>(
        api.get(`/repos/scans/${scanId}/patches`, {
          params: { limit: 250, ...(status ? { status } : {}) },
        })
      ),
    patch: (patchId: UUID) =>
      unwrap<SeoCodePatch>(api.get(`/repos/patches/${patchId}`)),
    approvePatch: (patchId: UUID) =>
      unwrap<SeoCodePatch>(api.post(`/repos/patches/${patchId}/approve`)),
    rejectPatch: (patchId: UUID) =>
      unwrap<SeoCodePatch>(api.post(`/repos/patches/${patchId}/reject`)),
    applyApproved: (scanId: UUID, runValidation = false, allowHighRisk = false) =>
      unwrap<PatchApplyRun>(
        api.post(`/repos/scans/${scanId}/apply-approved-patches`, {
          run_validation: runValidation,
          allow_high_risk: allowHighRisk,
        })
      ),
    applyRun: (runId: UUID) =>
      unwrap<PatchApplyRun>(api.get(`/repos/apply-runs/${runId}/status`)),
    createPr: (runId: UUID) =>
      unwrap<PullRequestRecord>(
        api.post(`/repos/apply-runs/${runId}/create-pr`, { draft: true })
      ),
  },
};

export function latestCrawl(crawls?: CrawlJob[]): CrawlJob | undefined {
  return crawls?.[0];
}

export function latestPlannerRun(runs?: PlannerRun[]): PlannerRun | undefined {
  return runs?.[0];
}
