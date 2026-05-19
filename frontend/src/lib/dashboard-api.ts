import type { AxiosResponse } from 'axios';
import { api, projectAPI } from '@/lib/api';
import type {
  AuditSummary,
  BlogDraft,
  BlogPlan,
  BlogTopic,
  ContentSuggestion,
  ContentSummary,
  CrawlJob,
  CrawlListResponse,
  CrawlPage,
  GeoAeoPageScore,
  GeoAeoRecommendation,
  GeoAeoSummary,
  GSCProperty,
  GSCSyncJob,
  PatchApplyRun,
  PlannerRun,
  PlannerSummary,
  PlannerTask,
  Project,
  PullRequestRecord,
  RepoConnection,
  RepoScanRun,
  SearchConsoleImport,
  SearchConsoleOpportunity,
  SearchConsoleSummary,
  SeoCodeIssue,
  SeoCodePatch,
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

  searchConsole: {
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
    imports: (projectId: UUID) =>
      unwrap<Envelope<SearchConsoleImport, 'imports'>>(
        api.get('/search-console/imports', {
          params: { project_id: projectId, limit: 25 },
        })
      ),
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

  content: {
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
