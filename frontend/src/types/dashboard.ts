export type UUID = string;

export type Project = {
  id: UUID;
  name: string;
  domain?: string | null;
  description?: string | null;
  keywords?: string[] | null;
  status?: string;
  created_at?: string;
  updated_at?: string | null;
};

export type PlannerRun = {
  id: UUID;
  project_id: UUID;
  status: string;
  run_type: string;
  target_week_start: string;
  target_week_end: string;
  crawl_id?: UUID | null;
  audit_id?: UUID | null;
  content_optimization_run_id?: UUID | null;
  geo_aeo_run_id?: UUID | null;
  gsc_sync_job_id?: UUID | null;
  blog_plan_id?: UUID | null;
  repo_scan_run_id?: UUID | null;
  tasks_created: number;
  high_priority_tasks: number;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at?: string | null;
};

export type PlannerTask = {
  id: UUID;
  project_id: UUID;
  planner_run_id: UUID;
  task_type: string;
  title: string;
  description: string;
  source_type: string;
  source_reference_id?: UUID | null;
  target_page_url?: string | null;
  target_keyword?: string | null;
  priority: "low" | "medium" | "high" | "critical" | string;
  priority_score: number;
  estimated_impact: string;
  effort: string;
  status: string;
  due_date?: string | null;
  created_at: string;
  updated_at?: string | null;
};

export type PlannerSummary = {
  project_id: UUID;
  open_tasks: number;
  total_tasks: number;
  tasks_by_status: Record<string, number>;
  tasks_by_priority: Record<string, number>;
  latest_run_id?: UUID | null;
  latest_run_status?: string | null;
  top_tasks: PlannerTask[];
};

export type WeeklyReport = {
  id: UUID;
  project_id: UUID;
  planner_run_id: UUID;
  summary: string;
  wins?: unknown[] | null;
  risks?: unknown[] | null;
  technical_seo_summary?: Record<string, unknown> | null;
  search_console_summary?: Record<string, unknown> | null;
  content_summary?: Record<string, unknown> | null;
  geo_aeo_summary?: Record<string, unknown> | null;
  blog_summary?: Record<string, unknown> | null;
  repo_patch_summary?: Record<string, unknown> | null;
  next_week_priorities?: unknown[] | null;
  created_at: string;
};

export type CrawlJob = {
  id: UUID;
  url: string;
  name?: string | null;
  status: string;
  priority: string;
  progress: number;
  total_pages_crawled: number;
  total_pages_failed: number;
  total_pages_discovered: number;
  total_internal_links: number;
  total_external_links: number;
  total_issues_found: number;
  project_id?: UUID | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  updated_at?: string | null;
};

export type CrawlListResponse = {
  crawls: CrawlJob[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
};

export type CrawlPage = {
  id: UUID;
  url: string;
  final_url?: string | null;
  status_code?: number | null;
  title?: string | null;
  meta_description?: string | null;
  word_count: number;
  internal_links: number;
  external_links: number;
  issue_count: number;
  critical_issues: number;
  warning_issues: number;
  crawled_at: string;
};

export type AuditSummary = {
  audit_run_id: UUID;
  crawl_job_id: UUID;
  project_id?: UUID | null;
  status: string;
  site_score?: number | null;
  total_pages: number;
  total_issues: number;
  issue_counts_by_severity: Record<string, number>;
  issue_counts_by_category: Record<string, number>;
  top_issue_types: Record<string, number>;
};

export type SearchConsoleSummary = {
  project_id: UUID;
  imports_count: number;
  rows_count: number;
  opportunities_count: number;
  opportunities_by_status: Record<string, number>;
  opportunities_by_type: Record<string, number>;
  latest_sync_job_id?: UUID | null;
  latest_sync_status?: string | null;
  top_opportunities: SearchConsoleOpportunity[];
};

export type SearchConsoleImport = {
  id: UUID;
  project_id?: UUID | null;
  property_id?: UUID | null;
  source_type: string;
  status: string;
  filename?: string | null;
  date_start?: string | null;
  date_end?: string | null;
  comparison_window?: string | null;
  rows_imported: number;
  error_message?: string | null;
  created_at: string;
  updated_at?: string | null;
};

export type GSCProperty = {
  id: UUID;
  project_id?: UUID | null;
  connection_id: UUID;
  site_url: string;
  permission_level?: string | null;
  is_selected: boolean;
  last_synced_at?: string | null;
  created_at: string;
  updated_at?: string | null;
};

export type GSCSyncJob = {
  id: UUID;
  project_id?: UUID | null;
  property_id: UUID;
  import_id?: UUID | null;
  sync_type: string;
  date_start: string;
  date_end: string;
  comparison_window: string;
  status: string;
  rows_fetched: number;
  opportunities_created: number;
  opportunities_updated: number;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
};

export type SearchConsoleOpportunity = {
  id: UUID;
  project_id?: UUID | null;
  import_id?: UUID | null;
  property_id?: UUID | null;
  crawl_page_id?: UUID | null;
  query: string;
  page_url: string;
  opportunity_type: string;
  status: string;
  current_clicks: number;
  current_impressions: number;
  current_ctr: number;
  current_position: number;
  previous_clicks?: number | null;
  previous_impressions?: number | null;
  previous_ctr?: number | null;
  previous_position?: number | null;
  reason: string;
  recommended_action: string;
  priority_score: number;
  confidence_score: number;
  evidence?: Record<string, unknown> | null;
  created_at: string;
  updated_at?: string | null;
};

export type ContentSummary = {
  crawl_id: UUID;
  project_id?: UUID | null;
  total_suggestions: number;
  pages_with_suggestions: number;
  average_priority_score: number;
  average_confidence_score: number;
  suggestions_by_status: Record<string, number>;
  suggestions_by_type: Record<string, number>;
};

export type ContentSuggestion = {
  id: UUID;
  run_id: UUID;
  project_id?: UUID | null;
  crawl_id: UUID;
  page_id: UUID;
  suggestion_type: string;
  current_value?: string | null;
  suggested_value: string;
  reason: string;
  priority_score: number;
  confidence_score: number;
  status: string;
  created_at: string;
  updated_at?: string | null;
};

export type GeoAeoSummary = {
  crawl_id: UUID;
  project_id?: UUID | null;
  run_id?: UUID | null;
  status?: string | null;
  total_pages: number;
  total_recommendations: number;
  average_geo_score: number;
  average_aeo_score: number;
  average_citation_readiness_score: number;
  average_answer_block_score: number;
  average_entity_clarity_score: number;
  average_schema_readiness_score: number;
  average_trust_signal_score: number;
  average_topical_completeness_score: number;
  recommendations_by_status: Record<string, number>;
  recommendations_by_type: Record<string, number>;
};

export type GeoAeoPageScore = {
  id: UUID;
  run_id: UUID;
  project_id?: UUID | null;
  crawl_id: UUID;
  page_id: UUID;
  url: string;
  geo_score: number;
  aeo_score: number;
  citation_readiness_score: number;
  answer_block_score: number;
  entity_clarity_score: number;
  schema_readiness_score: number;
  trust_signal_score: number;
  topical_completeness_score: number;
  extracted_entities?: string[] | null;
  extracted_claims?: string[] | null;
};

export type GeoAeoRecommendation = {
  id: UUID;
  run_id: UUID;
  project_id?: UUID | null;
  crawl_id: UUID;
  page_id: UUID;
  recommendation_type: string;
  recommendation_text: string;
  reason: string;
  priority_score: number;
  confidence_score: number;
  status: string;
  created_at: string;
  updated_at?: string | null;
};

export type BlogPlan = {
  id: UUID;
  project_id?: UUID | null;
  title: string;
  description?: string | null;
  target_site_url?: string | null;
  status: string;
  blogs_per_week: number;
  created_at: string;
  updated_at?: string | null;
};

export type BlogTopic = {
  id: UUID;
  project_id?: UUID | null;
  blog_plan_id: UUID;
  target_keyword: string;
  search_intent: string;
  title: string;
  angle?: string | null;
  target_audience?: string | null;
  target_landing_page_id?: UUID | null;
  priority_score: number;
  status: string;
  reason?: string | null;
  created_at: string;
  updated_at?: string | null;
};

export type BlogDraft = {
  id: UUID;
  project_id?: UUID | null;
  blog_topic_id: UUID;
  title: string;
  slug: string;
  meta_title?: string | null;
  meta_description?: string | null;
  outline?: Record<string, unknown> | null;
  draft_markdown: string;
  faq_json?: Record<string, unknown>[] | null;
  schema_json?: Record<string, unknown> | null;
  internal_link_plan?: Record<string, unknown>[] | null;
  knowledge_sources_used?: Record<string, unknown>[] | null;
  status: string;
  created_at: string;
  updated_at?: string | null;
};

export type RepoConnection = {
  id: UUID;
  project_id?: UUID | null;
  provider: string;
  repo_url?: string | null;
  local_path?: string | null;
  default_branch?: string | null;
  framework?: string | null;
  status: string;
  created_at: string;
  updated_at?: string | null;
};

export type RepoScanRun = {
  id: UUID;
  project_id?: UUID | null;
  repo_connection_id: UUID;
  status: string;
  framework_detected?: string | null;
  files_scanned: number;
  issues_found: number;
  patches_created: number;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at?: string | null;
};

export type SeoCodeIssue = {
  id: UUID;
  project_id?: UUID | null;
  repo_connection_id: UUID;
  scan_run_id: UUID;
  file_id?: UUID | null;
  issue_type: string;
  severity: string;
  title: string;
  description: string;
  recommended_fix: string;
  source_reference_type: string;
  source_reference_id?: UUID | null;
  status: string;
  created_at: string;
  updated_at?: string | null;
};

export type SeoCodePatch = {
  id: UUID;
  project_id?: UUID | null;
  repo_connection_id: UUID;
  scan_run_id: UUID;
  issue_id: UUID;
  file_path: string;
  patch_type: string;
  original_content_hash: string;
  diff_text: string;
  proposed_content: string;
  explanation: string;
  risk_level: string;
  status: string;
  created_at: string;
  updated_at?: string | null;
};

export type PatchApplyRun = {
  id: UUID;
  project_id?: UUID | null;
  repo_connection_id: UUID;
  scan_run_id: UUID;
  branch_name?: string | null;
  status: string;
  patches_requested: number;
  patches_applied: number;
  patches_failed: number;
  validation_status: string;
  validation_output?: string | null;
  git_diff_summary?: string | null;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at?: string | null;
};

export type PullRequestRecord = {
  id: UUID;
  project_id?: UUID | null;
  repo_connection_id: UUID;
  apply_run_id: UUID;
  provider: string;
  branch_name: string;
  base_branch: string;
  commit_sha?: string | null;
  pr_number?: number | null;
  pr_url?: string | null;
  status: string;
  title: string;
  description: string;
  error_message?: string | null;
  created_at: string;
  updated_at?: string | null;
};
