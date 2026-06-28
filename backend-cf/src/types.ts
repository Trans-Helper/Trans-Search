export interface Env {
  OPENAI_API_KEY: string
  ADMIN_API_KEY?: string
  QDRANT_URL: string
  QDRANT_API_KEY: string
  CONFIG_KV: KVNamespace
  ALLOWED_ORIGINS?: string
  OPENAI_BASE_URL?: string
  EMBED_MODEL?: string
  EMBED_DIM?: string
  CHAT_MODEL?: string
  CHUNK_SIZE?: string
  CHUNK_OVERLAP?: string
  SCORE_THRESHOLD?: string
  QUERY_EXPAND?: string
  HYBRID_SEARCH?: string
  SEARCH_MAX_LEN?: string
  CONTENT_MAX_LEN?: string
  TITLE_MAX_LEN?: string
  TAGS_MAX_COUNT?: string
  ENV?: string
}

export interface ArticleInput {
  id?: string
  title: string
  content: string
  url?: string
  category?: string
  source_site?: string
  chapter?: string
  tags?: string[]
  flags?: string[]
}

export interface ArticleMeta {
  title?: string
  url?: string
  category?: string
  source_site?: string
  chapter?: string
  tags?: string[]
  flags?: string[]
}

export interface SearchResult {
  article_id: string
  title: string
  excerpt: string
  url: string | null
  category: string | null
  source_site: string | null
  chapter: string | null
  tags: string[]
  flags: string[]
  score: number
  chunk_index: number
}

export interface ConfigUpdate {
  openai_base_url?: string
  embed_model?: string
  embed_dim?: number
  chat_model?: string
  chunk_size?: number
  chunk_overlap?: number
  score_threshold?: number
  query_expand?: boolean
  hybrid_search?: boolean
}

export interface QdrantPoint {
  id: string
  vector: Record<string, number[] | SparseVector>
  payload: Record<string, unknown>
}

export interface SparseVector {
  indices: number[]
  values: number[]
}

export interface QdrantSearchResult {
  id: string
  version: number
  score: number
  payload: Record<string, unknown> | null
  vector?: unknown
}

export interface QdrantScrollResult {
  points: QdrantSearchResult[]
  next_page_offset?: number | null
}

export interface QdrantCollectionInfo {
  points_count: number
}

const VALID_FLAGS_SET = new Set(["ai", "risk", "reviewed", "outdated"])

export const VALID_FLAGS = VALID_FLAGS_SET
