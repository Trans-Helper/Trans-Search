import { ConfigUpdate, Env } from "./types"

const ALLOWED_BASE_URL_PREFIXES = [
  "https://api.openai.com",
  "https://open.bigmodel.cn",
  "https://api.moonshot.cn",
  "https://api.deepseek.com",
  "https://dashscope.aliyuncs.com",
]

export class Config {
  openai_base_url: string
  embed_model: string
  embed_dim: number
  chat_model: string
  chunk_size: number
  chunk_overlap: number
  score_threshold: number
  query_expand: boolean
  hybrid_search: boolean

  constructor(env: Env) {
    this.openai_base_url = env.OPENAI_BASE_URL ?? "https://open.bigmodel.cn/api/paas/v4/"
    this.embed_model = env.EMBED_MODEL ?? "embedding-3"
    this.embed_dim = parseInt(env.EMBED_DIM ?? "2048", 10)
    this.chat_model = env.CHAT_MODEL ?? "glm-4.7-flash"
    this.chunk_size = parseInt(env.CHUNK_SIZE ?? "600", 10)
    this.chunk_overlap = parseInt(env.CHUNK_OVERLAP ?? "80", 10)
    this.score_threshold = parseFloat(env.SCORE_THRESHOLD ?? "0.25")
    this.query_expand = (env.QUERY_EXPAND ?? "true").toLowerCase() === "true"
    this.hybrid_search = (env.HYBRID_SEARCH ?? "true").toLowerCase() === "true"
  }

  apply(update: ConfigUpdate) {
    if (update.openai_base_url !== undefined) this.openai_base_url = update.openai_base_url
    if (update.embed_model !== undefined) this.embed_model = update.embed_model
    if (update.embed_dim !== undefined) this.embed_dim = update.embed_dim
    if (update.chat_model !== undefined) this.chat_model = update.chat_model
    if (update.chunk_size !== undefined) this.chunk_size = update.chunk_size
    if (update.chunk_overlap !== undefined) this.chunk_overlap = update.chunk_overlap
    if (update.score_threshold !== undefined) this.score_threshold = update.score_threshold
    if (update.query_expand !== undefined) this.query_expand = update.query_expand
    if (update.hybrid_search !== undefined) this.hybrid_search = update.hybrid_search
  }

  toJSON() {
    return {
      openai_base_url: this.openai_base_url,
      embed_model: this.embed_model,
      embed_dim: this.embed_dim,
      chat_model: this.chat_model,
      chunk_size: this.chunk_size,
      chunk_overlap: this.chunk_overlap,
      score_threshold: this.score_threshold,
      query_expand: this.query_expand,
      hybrid_search: this.hybrid_search,
    }
  }
}

export function validateBaseUrl(url: string): string {
  url = url.trim().replace(/\/+$/, "") + "/"
  if (!ALLOWED_BASE_URL_PREFIXES.some((p) => url.startsWith(p))) {
    throw new Error(`Base URL not allowed. Allowed providers: ${ALLOWED_BASE_URL_PREFIXES.join(", ")}`)
  }
  return url
}

export function validateChunkSize(v: number): void {
  if (v < 100 || v > 2000) throw new Error("chunk_size range: 100~2000")
}

export function validateThreshold(v: number): void {
  if (v < 0 || v > 1) throw new Error("score_threshold range: 0.0~1.0")
}

export async function loadConfig(env: Env): Promise<Config> {
  const cfg = new Config(env)
  const saved = await env.CONFIG_KV.get("config", "json") as Partial<ConfigUpdate> | null
  if (saved) cfg.apply(saved)
  return cfg
}

export async function saveConfig(env: Env, update: ConfigUpdate): Promise<Config> {
  const cfg = await loadConfig(env)
  cfg.apply(update)
  await env.CONFIG_KV.put("config", JSON.stringify(cfg.toJSON()))
  return cfg
}
