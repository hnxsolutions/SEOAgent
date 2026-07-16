export type UUID = string;

export type Project = {
  id: UUID;
  name: string;
  domain?: string | null;
  description?: string | null;
  keywords?: string[] | null;
  business_name?: string | null;
  industry?: string | null;
  target_location?: string | null;
  target_audience?: string | null;
  primary_services?: string[] | null;
  target_keywords?: string[] | null;
  competitor_urls?: string[] | null;
  seo_goal?: string | null;
  brand_tone?: string | null;
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

export type SeoRun = {
  id: UUID;
  tenant_id: UUID;
  project_id: UUID;
  status: string;
  current_stage: string;
  stage_statuses: Record<string, string>;
  stage_errors: Record<string, string>;
  crawl_id?: UUID | null;
  audit_id?: UUID | null;
  semantic_index_run_id?: UUID | null;
  content_optimization_run_id?: UUID | null;
  planner_run_id?: UUID | null;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at?: string | null;
};

export type SeoRunListResponse = {
  runs: SeoRun[];
  limit: number;
  offset: number;
  has_more: boolean;
};

export type SeoReportSection = {
  key: string;
  title: string;
  summary: string;
  status: string;
  metrics: Record<string, unknown>;
  items: Array<Record<string, unknown>>;
};

export type SeoReportActionItem = {
  title: string;
  description: string;
  priority: string;
  source_section: string;
  target_url?: string | null;
  status?: string | null;
  due_date?: string | null;
};

export type SeoRunReportResponse = {
  run_id: UUID;
  tenant_id: UUID;
  project_id: UUID;
  project_name: string;
  website_url: string;
  run_status: string;
  completed_at?: string | null;
  generated_at: string;
  crawl_pages_processed: number;
  audit_score?: number | null;
  total_issues: number;
  issue_counts_by_severity: Record<string, number>;
  issue_counts_by_category: Record<string, number>;
  semantic_vector_count: number;
  content_suggestions_count: number;
  planner_tasks_count: number;
  data_availability: Record<string, string>;
  executive_summary: string;
  sections: SeoReportSection[];
  top_audit_issues: Array<Record<string, unknown>>;
  semantic_summaries: Array<Record<string, unknown>>;
  content_suggestions: Array<Record<string, unknown>>;
  weekly_planner_tasks: Array<Record<string, unknown>>;
  next_actions: SeoReportActionItem[];
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

export type AuditRun = {
  id: UUID;
  crawl_job_id: UUID;
  project_id?: UUID | null;
  status: string;
  progress: number;
  site_score?: number | null;
  total_pages: number;
  total_issues: number;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at?: string | null;
};

export type SEOIssue = {
  id: UUID;
  audit_run_id: UUID;
  crawl_job_id: UUID;
  crawl_page_id?: UUID | null;
  project_id?: UUID | null;
  tenant_id: UUID;
  issue_type: string;
  title: string;
  message: string;
  recommendation?: string | null;
  severity: string;
  category: string;
  status: string;
  url?: string | null;
  evidence?: Record<string, unknown> | null;
  score_impact: number;
  created_at: string;
  updated_at?: string | null;
};

export type SEOIssueListResponse = {
  issues: SEOIssue[];
  limit: number;
  offset: number;
  has_more: boolean;
};

export type SemanticIndexRun = {
  id: UUID;
  crawl_job_id: UUID;
  project_id?: UUID | null;
  status: string;
  progress: number;
  embedding_provider: string;
  embedding_model: string;
  embedding_dimension: number;
  qdrant_collection: string;
  total_pages: number;
  total_vectors: number;
  indexed_vectors: number;
  skipped_duplicates: number;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at?: string | null;
};

export type SemanticSearchResult = {
  point_id: string;
  score: number;
  tenant_id: string;
  project_id?: string | null;
  crawl_id: string;
  page_id: string;
  url: string;
  content_type: string;
  heading_context?: string | null;
  chunk_index?: number | null;
  text_preview?: string | null;
};

export type SemanticSearchResponse = {
  query: string;
  results: SemanticSearchResult[];
  limit: number;
};

export type InternalLinkGeneration = {
  crawl_id: UUID;
  created_count: number;
  recommendations: unknown[];
};

export type InternalLinkSummary = {
  crawl_id: UUID;
  project_id?: UUID | null;
  total_pages: number;
  orphan_pages: number;
  weakly_linked_pages: number;
  pages_with_too_few_internal_links: number;
  pages_with_excessive_internal_links: number;
  duplicate_anchor_text_risks: number;
  total_recommendations: number;
  average_priority_score: number;
  recommendations_by_status: Record<string, number>;
  recommendations_by_type: Record<string, number>;
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
  selected_property?: GSCProperty | null;
  monitor_setting?: GSCMonitorSetting | null;
  clicks: number;
  impressions: number;
  average_ctr?: number | null;
  average_position?: number | null;
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
  connection_id?: UUID | null;
  site_url: string;
  source_type?: 'oauth' | 'manual' | string;
  property_type?: 'domain' | 'url_prefix' | string;
  permission_level?: string | null;
  notes?: string | null;
  is_selected: boolean;
  last_synced_at?: string | null;
  created_at: string;
  updated_at?: string | null;
};

export type GSCConnection = {
  id: UUID;
  tenant_id: UUID;
  user_id: UUID;
  provider: string;
  scopes?: string[] | null;
  status: string;
  metadata_json?: Record<string, unknown> | null;
  created_at: string;
  updated_at?: string | null;
};

export type GSCMonitorSetting = {
  id: UUID;
  tenant_id: UUID;
  project_id: UUID;
  property_id: UUID;
  enabled: boolean;
  frequency_days: 1 | 2 | 3 | number;
  lookback_days: number;
  sync_queries: boolean;
  sync_pages: boolean;
  sync_query_page_pairs: boolean;
  sync_country_device: boolean;
  last_scheduled_at?: string | null;
  next_sync_at?: string | null;
  created_at: string;
  updated_at?: string | null;
};

export type GSCMonitorPayload = {
  property_id?: UUID;
  enabled?: boolean;
  frequency_days?: 1 | 2 | 3;
  lookback_days?: number;
  sync_queries?: boolean;
  sync_pages?: boolean;
  sync_query_page_pairs?: boolean;
  sync_country_device?: boolean;
};

export type GSCSyncJob = {
  id: UUID;
  project_id?: UUID | null;
  connection_id?: UUID | null;
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

export type SitemapRecord = {
  id: UUID;
  tenant_id: UUID;
  project_id: UUID;
  property_id?: UUID | null;
  sitemap_url: string;
  is_submitted: boolean;
  is_pending: boolean;
  is_sitemaps_index: boolean;
  last_submitted_at?: string | null;
  last_downloaded_at?: string | null;
  errors_count: number;
  warnings_count: number;
  submitted_urls_count: number;
  source: 'gsc_api' | 'detected' | 'generated';
  status: 'active' | 'warning' | 'error' | 'deleted';
  created_at: string;
  updated_at?: string | null;
};

export type SitemapIssue = {
  id: UUID;
  tenant_id: UUID;
  project_id: UUID;
  sitemap_id: UUID;
  issue_type: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  title: string;
  description: string;
  recommended_action: string;
  sample_urls?: string[] | null;
  status: 'open' | 'approved' | 'fixed' | 'ignored';
  created_at: string;
  updated_at?: string | null;
};

export type SitemapListResponse = {
  sitemaps: SitemapRecord[];
  oauth_enabled: boolean;
};

export type SitemapAnalyzeResponse = {
  analyzed_sitemaps: number;
  issues_created: number;
  sitemaps: SitemapRecord[];
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

export type IndexingRun = {
  id: UUID;
  project_id: UUID;
  gsc_property_id: UUID;
  status: string;
  requested_url_count: number;
  inspected_url_count: number;
  failed_url_count: number;
  started_at?: string | null;
  completed_at?: string | null;
  error_message?: string | null;
  created_at: string;
};

export type IndexingResult = {
  id: UUID;
  project_id: UUID;
  inspection_run_id: UUID;
  page_url: string;
  inspection_result_link?: string | null;
  verdict?: string | null;
  coverage_state?: string | null;
  indexing_state?: string | null;
  robots_txt_state?: string | null;
  page_fetch_state?: string | null;
  google_canonical?: string | null;
  user_canonical?: string | null;
  sitemap_urls?: string[] | null;
  referring_urls?: string[] | null;
  last_crawl_time?: string | null;
  crawled_as?: string | null;
  mobile_usability_verdict?: string | null;
  rich_results_verdict?: string | null;
  created_at: string;
};

export type IndexingIssue = {
  id: UUID;
  project_id: UUID;
  inspection_result_id: UUID;
  page_url: string;
  issue_type: string;
  severity: 'low' | 'medium' | 'high' | 'critical' | string;
  likely_cause: string;
  recommended_fix: string;
  linked_repo_issue_id?: UUID | null;
  linked_patch_id?: UUID | null;
  status: string;
  created_at: string;
  updated_at?: string | null;
};

export type IndexingSummary = {
  project_id: UUID;
  url_inspection_connected: boolean;
  indexed_urls: number;
  not_indexed_urls: number;
  issues_count: number;
  issues_by_type: Record<string, number>;
  issues_by_status: Record<string, number>;
  latest_run?: IndexingRun | null;
  top_issues: IndexingIssue[];
  next_validation_date: string;
};

export type IndexingRunDetail = {
  run: IndexingRun;
  results: IndexingResult[];
  issues: IndexingIssue[];
};

export type IndexingValidationRun = {
  id: UUID;
  project_id: UUID;
  issue_id?: UUID | null;
  patch_id?: UUID | null;
  pull_request_id?: UUID | null;
  status: string;
  validation_after_days: number;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
};

export type IndexingValidationResult = {
  id: UUID;
  project_id: UUID;
  validation_run_id: UUID;
  issue_id: UUID;
  page_url: string;
  previous_issue_type: string;
  current_verdict?: string | null;
  current_coverage_state?: string | null;
  fixed: boolean;
  still_failing: boolean;
  notes?: string | null;
  created_at: string;
};

export type IndexingValidationResponse = {
  validation_run: IndexingValidationRun;
  result?: IndexingValidationResult | null;
  issue?: IndexingIssue | null;
};

export type IndexingFixPlan = {
  issue: IndexingIssue;
  planner_task?: PlannerTask | null;
  repo_issue?: SeoCodeIssue | null;
  patch?: SeoCodePatch | null;
  safety: string;
};

export type RankTrackingRow = {
  query: string;
  page_url: string;
  country?: string | null;
  device?: string | null;
  search_appearance?: string | null;
  current_clicks: number;
  current_impressions: number;
  current_ctr: number;
  current_position: number;
  previous_clicks: number;
  previous_impressions: number;
  previous_ctr: number;
  previous_position: number;
  position_delta: number;
  clicks_delta: number;
  impressions_delta: number;
  ctr_delta: number;
};

export type RankTrackingSummary = {
  project_id: UUID;
  total_keywords: number;
  total_pages: number;
  total_rows: number;
  improved_keywords: number;
  dropped_keywords: number;
  striking_distance_keywords: number;
  low_ctr_keywords: number;
  total_clicks: number;
  total_impressions: number;
  average_ctr: number;
  average_position: number;
  message?: string | null;
  top_movements: RankTrackingRow[];
};

export type RankTrackingPageRow = {
  page_url: string;
  query_count: number;
  current_clicks: number;
  current_impressions: number;
  current_ctr: number;
  current_position: number;
  previous_clicks: number;
  previous_impressions: number;
  previous_ctr: number;
  previous_position: number;
  position_delta: number;
  clicks_delta: number;
  impressions_delta: number;
};

export type RankTrackingKeywordRow = {
  query: string;
  page_count: number;
  current_clicks: number;
  current_impressions: number;
  current_ctr: number;
  current_position: number;
  previous_clicks: number;
  previous_impressions: number;
  previous_ctr: number;
  previous_position: number;
  position_delta: number;
  clicks_delta: number;
  impressions_delta: number;
};

export type ImpactExperiment = {
  id: UUID;
  project_id: UUID;
  experiment_type: string;
  source_type: string;
  source_reference_id?: UUID | null;
  target_page_url: string;
  target_query?: string | null;
  target_keywords?: string[] | null;
  baseline_start_date: string;
  baseline_end_date: string;
  action_date?: string | null;
  review_start_date?: string | null;
  review_end_date?: string | null;
  review_after_days: number;
  status: string;
  notes?: string | null;
  created_at: string;
  updated_at?: string | null;
};

export type ImpactResult = {
  id: UUID;
  project_id: UUID;
  experiment_id: UUID;
  clicks_delta: number;
  impressions_delta: number;
  ctr_delta: number;
  position_delta: number;
  percentage_clicks_change?: number | null;
  percentage_impressions_change?: number | null;
  outcome: string;
  confidence_score: number;
  summary: string;
  created_at: string;
};

export type ImpactSummary = {
  project_id: UUID;
  total_experiments: number;
  by_status: Record<string, number>;
  by_outcome: Record<string, number>;
  ready_for_review: number;
  message?: string | null;
};

export type SerpSnapshotResult = {
  id: UUID;
  position: number;
  title: string;
  url: string;
  domain: string;
  snippet?: string | null;
  is_target_domain: boolean;
  is_target_url: boolean;
};

export type SerpSnapshotAsset = {
  id: UUID;
  snapshot_id: UUID;
  asset_type: string;
  file_path: string;
  original_filename?: string | null;
  mime_type?: string | null;
  created_at: string;
};

export type SerpSnapshot = {
  id: UUID;
  project_id: UUID;
  keyword: string;
  target_url?: string | null;
  target_domain: string;
  search_engine: string;
  country: string;
  city?: string | null;
  device: string;
  language?: string | null;
  capture_mode: string;
  observed_target_rank?: number | null;
  status: string;
  captured_at: string;
  notes?: string | null;
  results: SerpSnapshotResult[];
  assets?: SerpSnapshotAsset[];
  competitors_above_target: SerpSnapshotResult[];
  previous_rank?: number | null;
  rank_delta?: number | null;
};

export type SerpSnapshotSummary = {
  project_id: UUID;
  total_snapshots: number;
  keywords_tracked: number;
  latest_snapshots: SerpSnapshot[];
  message: string;
};

export type KeywordBaselineDevice = 'desktop' | 'mobile' | string;

export type KeywordBaselineSource = 'manual' | 'csv' | 'imported' | string;

export type KeywordBaseline = {
  id: UUID;
  tenant_id: UUID;
  project_id: UUID;
  keyword: string;
  target_location?: string | null;
  search_engine: string;
  device: KeywordBaselineDevice;
  current_position?: number | null;
  current_url?: string | null;
  search_volume?: number | null;
  difficulty?: number | null;
  intent?: string | null;
  notes?: string | null;
  source: KeywordBaselineSource;
  captured_at: string;
  created_at: string;
  updated_at?: string | null;
};

export type KeywordBaselinePayload = {
  keyword: string;
  target_location?: string | null;
  search_engine?: string;
  device?: 'desktop' | 'mobile';
  current_position?: number | null;
  current_url?: string | null;
  search_volume?: number | null;
  difficulty?: number | null;
  intent?: string | null;
  notes?: string | null;
  source?: 'manual' | 'csv' | 'imported';
  captured_at?: string | null;
};

export type KeywordBaselineListResponse = {
  baselines: KeywordBaseline[];
  limit: number;
  offset: number;
  has_more: boolean;
};

export type KeywordBaselineBulkResponse = {
  created_count: number;
  baselines: KeywordBaseline[];
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

export type ContentOptimizationRun = {
  id: UUID;
  crawl_id: UUID;
  project_id?: UUID | null;
  status: string;
  progress: number;
  model: string;
  total_pages: number;
  total_suggestions: number;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at?: string | null;
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

export type GeoAeoRun = {
  id: UUID;
  crawl_id: UUID;
  project_id?: UUID | null;
  status: string;
  progress: number;
  model?: string | null;
  total_pages: number;
  total_recommendations: number;
  average_geo_score: number;
  average_aeo_score: number;
  average_citation_readiness_score: number;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at?: string | null;
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

export type BlogPublishConnection = {
  id: UUID;
  project_id?: UUID | null;
  provider: 'wordpress' | 'nextjs_repo' | 'markdown_export' | string;
  site_url?: string | null;
  repo_connection_id?: UUID | null;
  export_folder_path?: string | null;
  username?: string | null;
  status: string;
  auto_upload_drafts_enabled: boolean;
  auto_publish_enabled: boolean;
  created_at: string;
  updated_at?: string | null;
};

export type BlogInfrastructureCheck = {
  id: UUID;
  project_id?: UUID | null;
  repo_connection_id?: UUID | null;
  status: string;
  framework_detected?: string | null;
  has_blog_index: boolean;
  has_blog_detail_route: boolean;
  has_content_directory: boolean;
  blog_route_path?: string | null;
  content_directory?: string | null;
  recommended_strategy: string;
  issues?: Record<string, unknown>[] | null;
  created_at: string;
};

export type BlogPublishRun = {
  id: UUID;
  project_id?: UUID | null;
  blog_draft_id?: UUID | null;
  connection_id?: UUID | null;
  provider: string;
  mode: string;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  error_message?: string | null;
  created_at: string;
};

export type BlogPublishResult = {
  id: UUID;
  project_id?: UUID | null;
  publish_run_id: UUID;
  blog_draft_id?: UUID | null;
  provider: string;
  status: string;
  external_id?: string | null;
  external_url?: string | null;
  file_path?: string | null;
  patch_id?: UUID | null;
  pr_id?: UUID | null;
  title?: string | null;
  slug?: string | null;
  created_at: string;
};

export type BlogPublishActionResponse = {
  run: BlogPublishRun;
  result?: BlogPublishResult | null;
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

export type KnowledgeSource = {
  id: UUID;
  project_id?: UUID | null;
  source_type: string;
  title: string;
  description?: string | null;
  status: string;
  created_at: string;
  updated_at?: string | null;
};

export type KnowledgeIndexRun = {
  id: UUID;
  project_id?: UUID | null;
  source_id: UUID;
  status: string;
  progress: number;
  embedding_provider: string;
  embedding_model: string;
  embedding_dimension: number;
  qdrant_collection: string;
  documents_processed: number;
  chunks_indexed: number;
  skipped_duplicates: number;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at?: string | null;
};

export type GoogleOAuthStart = {
  authorization_url: string;
  state: string;
  expires_at: string;
  scopes: string[];
};

export type BrainMasterPlanItem = {
  source: string;
  issue_type: string;
  title: string;
  url?: string | null;
  reference_id?: string | null;
  severity: string;
  impact: string;
  difficulty: string;
  category: string;
  code_fixable: boolean;
  estimated_minutes: number;
  expected_traffic_gain: string;
  expected_ranking_gain: string;
  confidence: number;
  business_impact: string;
  priority_score: number;
};

export type BrainMasterPlan = {
  project_id: string;
  total_issues: number;
  code_fixable_count: number;
  by_category: Record<string, number>;
  top_priority?: BrainMasterPlanItem | null;
  items: BrainMasterPlanItem[];
};

export type BrainState = {
  project_id: string;
  project_name: string;
  domain: string;
  overall_health: number;
  current_run: {
    id?: string | null;
    status: string;
    current_stage?: string | null;
    stage_statuses?: Record<string, string> | null;
  };
  pending_approvals: { proposed_patches: number; open_pull_requests: number };
  master_plan_preview: BrainMasterPlanItem[];
  master_plan_total: number;
  code_fixable_count: number;
  next_action: string;
  modules: Record<string, Record<string, unknown>>;
};

export type BrainPendingFix = {
  patch_id: string;
  status: string;
  patch_type: string;
  file_path: string;
  affected_files: string[];
  issue: {
    id?: string | null;
    issue_type: string;
    title: string;
    source: string;
    source_reference_id?: string | null;
  };
  reason: string;
  seo_impact: string;
  expected_ranking_gain: string;
  expected_traffic_gain: string;
  confidence: number;
  category: string;
  risk_level: string;
  diff: string;
  before_after_available: boolean;
  rollback_strategy: string;
};

export type BrainPendingFixes = {
  project_id: string;
  total: number;
  items: BrainPendingFix[];
};

export type AiFixVerification = {
  id: string;
  project_id: string;
  patch_id: string;
  pull_request_id?: string | null;
  issue_id?: string | null;
  patch_type: string;
  issue_type?: string | null;
  status: string;
  scheduled_at: string;
  verified_at?: string | null;
  baseline_score?: number | null;
  followup_score?: number | null;
  issue_resolved?: boolean | null;
  improvement_pct?: number | null;
  details?: Record<string, unknown> | null;
  merged_at?: string | null;
};

export type VerificationList = {
  verifications: AiFixVerification[];
  total: number;
};

export type LearningStats = {
  total_verifications: number;
  finalized: number;
  by_status: Record<string, number>;
  success_rate?: number | null;
  average_improvement_pct?: number | null;
  most_successful_fixes: Array<Record<string, unknown>>;
  least_successful_fixes: Array<Record<string, unknown>>;
  confidence_by_patch_type: Record<string, {
    success: number; partial: number; failed: number; total: number;
    confidence: number | null; evidence_based: boolean;
  }>;
};

export type Deployment = {
  id: string;
  project_id: string;
  pull_request_id?: string | null;
  provider: string;
  status: string;
  commit_sha?: string | null;
  deployment_url?: string | null;
  external_id?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  duration_seconds?: number | null;
  logs?: string | null;
  error_message?: string | null;
  created_at?: string | null;
};

export type DeploymentList = {
  deployments: Deployment[];
  total: number;
};
