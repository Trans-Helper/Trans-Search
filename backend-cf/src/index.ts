import { Hono } from "hono"
import { cors } from "hono/cors"
import { Config, loadConfig, saveConfig, validateBaseUrl, validateChunkSize, validateThreshold } from "./config"
import { sanitizeQuery, splitChunks, buildContextPrefix, parseTagList } from "./chunk"
import { textToSparse } from "./sparse"
import { embed, expandQuery } from "./embedding"
import { requireAdmin } from "./auth"
import { checkRateLimit, getClientIP } from "./rate-limit"
import {
  ensureCollection,
  upsertPoints,
  queryPoints,
  searchPoints,
  scrollPoints,
  deletePoints,
  setPayload,
  getCollectionInfo,
  buildFilter,
} from "./qdrant"
import {
  ArticleInput,
  ArticleMeta,
  ConfigUpdate,
  Env,
  SearchResult,
  VALID_FLAGS,
} from "./types"

const RATE_LIMITS = {
  search: { limit: 30, window: 60 },
  write: { limit: 20, window: 60 },
  config: { limit: 10, window: 60 },
}

const app = new Hono<{ Bindings: Env }>()

app.use(
  "*",
  cors({
    origin: (origin, c) => {
      const allowed = (c.env.ALLOWED_ORIGINS ?? "http://localhost,http://127.0.0.1").split(",")
      if (allowed.includes("*")) return origin
      if (allowed.includes(origin)) return origin
      return allowed[0] ?? ""
    },
    allowMethods: ["GET", "POST", "PATCH", "DELETE"],
    allowHeaders: ["Content-Type", "X-Admin-Key"],
    exposeHeaders: ["X-Expanded-Query"],
  }),
)

app.onError((err, c) => {
  const message = err.message
  if (message.startsWith("Rate limited")) {
    return c.json({ detail: message }, 429)
  }
  if (
    message.startsWith("Invalid admin key") ||
    message.startsWith("ADMIN_API_KEY not configured")
  ) {
    return c.json({ detail: message }, message.startsWith("ADMIN_API_KEY") ? 500 : 403)
  }
  if (
    message.startsWith("Search query") ||
    message.startsWith("chunk_size") ||
    message.startsWith("score_threshold") ||
    message.startsWith("Base URL not allowed")
  ) {
    return c.json({ detail: message }, 400)
  }
  console.error(`Unhandled error: ${err}`)
  return c.json({ detail: "Internal server error" }, 500)
})

app.get("/health", (c) => c.json({ status: "ok" }))

app.get("/search", async (c) => {
  const ip = getClientIP(c.req.raw)
  checkRateLimit("search", ip, RATE_LIMITS.search.limit, RATE_LIMITS.search.window)

  const cfg = await loadConfig(c.env)
  const q = sanitizeQuery(c.req.query("q") ?? "", parseInt(c.env.SEARCH_MAX_LEN ?? "200", 10))
  const category = c.req.query("category") ?? null
  const sourceSite = c.req.query("source_site") ?? null
  const chapter = c.req.query("chapter") ?? null
  const tags = parseTagList(c.req.query("tags") ?? null)
  const topK = Math.min(Math.max(parseInt(c.req.query("top_k") ?? "8", 10) || 8, 1), 20)

  const qfilter = buildFilter(category, tags, sourceSite, chapter)

  const expandedQ = await expandQuery(q, c.env, cfg)
  console.log(`search: original="${q}" expanded="${expandedQ}"`)
  const [queryVector, querySparse] = await Promise.all([
    embed(expandedQ, c.env, cfg),
    textToSparse(expandedQ),
  ])

  let hits
  if (cfg.hybrid_search) {
    hits = await queryPoints(c.env, {
      prefetch: [
        { query: queryVector, using: "dense", filter: qfilter, limit: topK * 4 },
        { query: querySparse, using: "sparse", filter: qfilter, limit: topK * 4 },
      ],
      query: { fusion: "rrf" },
      limit: topK * 3,
    })
  } else {
    hits = await queryPoints(c.env, {
      query: queryVector,
      using: "dense",
      filter: qfilter,
      limit: topK * 3,
      scoreThreshold: cfg.score_threshold,
    })
  }

  const seen = new Map<string, SearchResult>()
  for (const h of hits) {
    const p = h.payload
    if (!p) continue
    const aid = p["article_id"] as string
    if (seen.has(aid)) continue
    seen.set(aid, {
      article_id: aid,
      title: p["title"] as string,
      excerpt: ((p["chunk"] as string) ?? "").slice(0, 220).replace(/\s+$/, "") + "…",
      url: (p["url"] as string) ?? null,
      category: (p["category"] as string) ?? null,
      source_site: (p["source_site"] as string) ?? null,
      chapter: (p["chapter"] as string) ?? null,
      tags: (p["tags"] as string[]) ?? [],
      flags: (p["flags"] as string[]) ?? [],
      score: Math.round(h.score * 10000) / 10000,
      chunk_index: (p["chunk_index"] as number) ?? 0,
    })
    if (seen.size >= topK) break
  }

  const results = Array.from(seen.values())
  // 在响应体中返回 expanded_query，前端可直接读取
  return c.json({ results, expanded_query: expandedQ }, 200, {
    "X-Expanded-Query": expandedQ,
  })
})

app.get("/tree", async (c) => {
  const ip = getClientIP(c.req.raw)
  checkRateLimit("search", ip, RATE_LIMITS.search.limit, RATE_LIMITS.search.window)

  let offset: string | number | null = null
  const seenArticles = new Set<string>()
  const allPayloads: Record<string, unknown>[] = []

  while (true) {
    const result = await scrollPoints(c.env, { limit: 100, offset })
    for (const point of result.points) {
      const p = point.payload
      if (!p) continue
      const aid = p["article_id"] as string | undefined
      if (aid && (p["chunk_index"] as number) === 0 && !seenArticles.has(aid)) {
        seenArticles.add(aid)
        allPayloads.push(p)
      }
    }
    if (result.next_page_offset === null || result.next_page_offset === undefined) break
    offset = result.next_page_offset
  }

  type TreeNode = { name: string; type: string; children: TreeNode[] }

  function insertChapter(parent: TreeNode, parts: string[], article: TreeNode) {
    if (parts.length === 0) {
      parent.children.push(article)
      return
    }
    const [head, ...rest] = parts
    let node = parent.children.find((c) => c.type === "chapter" && c.name === head)
    if (!node) {
      node = { name: head, type: "chapter", children: [] }
      parent.children.push(node)
    }
    insertChapter(node, rest, article)
  }

  const siteMap = new Map<string, TreeNode>()
  for (const p of allPayloads) {
    const site = (p["source_site"] as string) || "未分类来源"
    const cat  = (p["category"]    as string) || "未分类"
    const ch   = (p["chapter"]     as string) || ""

    if (!siteMap.has(site)) siteMap.set(site, { name: site, type: "site", children: [] })
    const siteNode = siteMap.get(site)!

    let catNode = siteNode.children.find((c) => c.type === "category" && c.name === cat)
    if (!catNode) {
      catNode = { name: cat, type: "category", children: [] }
      siteNode.children.push(catNode)
    }

    const article: TreeNode = {
      name: p["title"] as string,
      type: "article",
      children: [],
      ...{ article_id: p["article_id"], title: p["title"], url: p["url"] ?? null, flags: p["flags"] ?? [], tags: p["tags"] ?? [] },
    }

    const parts = ch ? ch.split("/").filter(Boolean) : []
    insertChapter(catNode, parts, article)
  }

  return c.json(Array.from(siteMap.values()))
})

app.get("/stats", async (c) => {
  const ip = getClientIP(c.req.raw)
  checkRateLimit("search", ip, RATE_LIMITS.search.limit, RATE_LIMITS.search.window)
  const cfg = await loadConfig(c.env)
  const info = await getCollectionInfo(c.env)
  return c.json({
    total_chunks: info.points_count,
    embed_model: cfg.embed_model,
    chat_model: cfg.chat_model,
    query_expand: cfg.query_expand,
    hybrid_search: cfg.hybrid_search,
    chunk_size: cfg.chunk_size,
    score_threshold: cfg.score_threshold,
  })
})

app.get("/config", async (c) => {
  const ip = getClientIP(c.req.raw)
  checkRateLimit("config", ip, RATE_LIMITS.config.limit, RATE_LIMITS.config.window)
  requireAdmin(c.req.header("X-Admin-Key"), c.env)
  const cfg = new Config(c.env)
  return c.json(cfg.toJSON())
})

app.patch("/config", async (c) => {
  const ip = getClientIP(c.req.raw)
  checkRateLimit("config", ip, RATE_LIMITS.config.limit, RATE_LIMITS.config.window)
  requireAdmin(c.req.header("X-Admin-Key"), c.env)

  const update = await c.req.json<ConfigUpdate>()
  if (update.openai_base_url) {
    update.openai_base_url = validateBaseUrl(update.openai_base_url)
  }
  if (update.chunk_size !== undefined) validateChunkSize(update.chunk_size)
  if (update.score_threshold !== undefined) validateThreshold(update.score_threshold)

  const cfg = await saveConfig(c.env, update)
  return c.json(cfg.toJSON())
})

function validateArticle(a: ArticleInput, env: Env) {
  const titleMax = parseInt(env.TITLE_MAX_LEN ?? "200", 10)
  const contentMax = parseInt(env.CONTENT_MAX_LEN ?? "100000", 10)
  const tagsMax = parseInt(env.TAGS_MAX_COUNT ?? "20", 10)

  const title = a.title?.trim()
  if (!title) throw new Error("Title cannot be empty")
  if (title.length > titleMax) throw new Error(`Title max ${titleMax} characters`)

  const content = a.content?.trim()
  if (!content) throw new Error("Content cannot be empty")
  if (content.length > contentMax) throw new Error(`Content max ${contentMax} characters`)

  const tags = a.tags ?? []
  if (tags.length > tagsMax) throw new Error(`Tags max ${tagsMax}`)

  const flags = a.flags ?? []
  const invalid = flags.filter((f) => !VALID_FLAGS.has(f))
  if (invalid.length > 0) throw new Error(`Invalid flags: ${invalid}`)

  if (a.url && !/^https?:\/\//.test(a.url)) {
    throw new Error("URL must start with http:// or https://")
  }
}

app.post("/articles", async (c) => {
  const ip = getClientIP(c.req.raw)
  checkRateLimit("write", ip, RATE_LIMITS.write.limit, RATE_LIMITS.write.window)
  requireAdmin(c.req.header("X-Admin-Key"), c.env)

  const cfg = await loadConfig(c.env)
  const article = await c.req.json<ArticleInput>()
  validateArticle(article, c.env)

  const articleId = article.id ?? crypto.randomUUID()
  const chunks = splitChunks(article.content, cfg.chunk_size, cfg.chunk_overlap)
  const prefix = buildContextPrefix(article)
  const points: unknown[] = []

  for (let i = 0; i < chunks.length; i++) {
    const inputText = `${prefix}\n\n${chunks[i]}`
    const [denseVector, sparseVec] = await Promise.all([
      embed(inputText, c.env, cfg),
      textToSparse(inputText),
    ])
    points.push({
      id: crypto.randomUUID(),
      vector: { dense: denseVector, sparse: sparseVec },
      payload: {
        article_id: articleId,
        chunk_index: i,
        title: article.title,
        chunk: chunks[i],
        url: article.url ?? null,
        category: article.category ?? null,
        source_site: article.source_site ?? null,
        chapter: article.chapter ?? null,
        tags: article.tags ?? [],
        flags: article.flags ?? [],
      },
    })
  }

  await upsertPoints(c.env, points)
  console.log(`Article indexed: ${article.title} (${points.length} chunks)`)
  return c.json({ article_id: articleId, chunks_indexed: points.length })
})

app.post("/articles/batch", async (c) => {
  const ip = getClientIP(c.req.raw)
  checkRateLimit("write", ip, RATE_LIMITS.write.limit, RATE_LIMITS.write.window)
  requireAdmin(c.req.header("X-Admin-Key"), c.env)

  const articles = await c.req.json<ArticleInput[]>()
  if (articles.length > 50) throw new Error("Max 50 articles per batch")

  const results: { status: string; title?: string; article_id?: string; chunks_indexed?: number; error?: string }[] = []
  for (const a of articles) {
    try {
      const req = new Request(c.req.raw.clone())
      const mockCtx = { env: c.env, req: { raw: req, json: () => Promise.resolve(a) } } as any
      const resp = await app.request(`/articles`, {
        method: "POST",
        headers: c.req.raw.headers,
        body: JSON.stringify(a),
      }, c.env)
      const data = await resp.json() as Record<string, unknown>
      if (resp.ok) {
        results.push({ status: "ok", ...data } as any)
      } else {
        results.push({ status: "error", title: a.title, error: (data.detail as string) ?? "Unknown error" })
      }
    } catch (e) {
      results.push({ status: "error", title: a.title, error: (e as Error).message })
    }
  }
  return c.json(results)
})

app.patch("/articles/:articleId/meta", async (c) => {
  const ip = getClientIP(c.req.raw)
  checkRateLimit("write", ip, RATE_LIMITS.write.limit, RATE_LIMITS.write.window)
  requireAdmin(c.req.header("X-Admin-Key"), c.env)

  const articleId = c.req.param("articleId")
  const meta = await c.req.json<ArticleMeta>()

  if (meta.flags !== undefined) {
    const invalid = meta.flags.filter((f) => !VALID_FLAGS.has(f))
    if (invalid.length > 0) throw new Error(`Invalid flags: ${invalid}`)
  }

  const scrollResult = await scrollPoints(c.env, {
    filter: { must: [{ key: "article_id", match: { value: articleId } }] },
    limit: 1,
  })
  if (scrollResult.points.length === 0) throw new Error("Article not found")

  const updatePayload: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(meta)) {
    if (v !== undefined && v !== null) updatePayload[k] = v
  }
  if (Object.keys(updatePayload).length === 0) return c.json({ updated: 0 })

  const allIds: string[] = []
  let offset: string | number | null = null
  while (true) {
    const r = await scrollPoints(c.env, {
      filter: { must: [{ key: "article_id", match: { value: articleId } }] },
      limit: 100,
      offset,
    })
    allIds.push(...r.points.map((p) => p.id))
    if (r.next_page_offset === null || r.next_page_offset === undefined) break
    offset = r.next_page_offset
  }

  await setPayload(c.env, updatePayload, allIds)
  return c.json({ article_id: articleId, updated_chunks: allIds.length })
})

app.delete("/articles/:articleId", async (c) => {
  const ip = getClientIP(c.req.raw)
  checkRateLimit("write", ip, RATE_LIMITS.write.limit, RATE_LIMITS.write.window)
  requireAdmin(c.req.header("X-Admin-Key"), c.env)

  const articleId = c.req.param("articleId")

  await deletePoints(c.env, {
    must: [{ key: "article_id", match: { value: articleId } }],
  })
  console.log(`Article deleted: ${articleId}`)
  return c.json({ deleted: articleId })
})

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    await ensureCollection(env)
    const url = new URL(request.url)
    if (url.pathname.startsWith("/api/")) {
      url.pathname = url.pathname.replace("/api", "")
      const req = new Request(url.toString(), request)
      return app.fetch(req, env, ctx)
    }
    return app.fetch(request, env, ctx)
  },
}
