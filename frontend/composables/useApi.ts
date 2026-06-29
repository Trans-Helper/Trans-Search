export function useApi() {
  const config = useRuntimeConfig()

  function baseURL(): string {
    return config.public.apiBase as string
  }

  async function request<T>(path: string, opts?: RequestInit & { params?: Record<string, string | number | undefined | null> }): Promise<T> {
    let url = `${baseURL()}${path}`
    if (opts?.params) {
      const qs = Object.entries(opts.params)
        .filter(([, v]) => v !== undefined && v !== null && v !== "")
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join("&")
      if (qs) url += `?${qs}`
    }

    const res = await fetch(url, {
      ...opts,
      headers: {
        "Content-Type": "application/json",
        ...(opts?.headers as Record<string, string>),
      },
    })

    const data = await res.json()
    if (!res.ok) throw new Error((data as { detail?: string })?.detail ?? `HTTP ${res.status}`)
    return data as T
  }
  function setAdminKey(key: string) {
    if (process.client) {
      localStorage.setItem("admin_key", key)
    }
  }

  function getAdminKey(): string | null {
    if (process.client) {
      return localStorage.getItem("admin_key")
    }
    return null
  }

  function authHeaders(): Record<string, string> {
    const key = getAdminKey()
    return key ? { "X-Admin-Key": key } : {}
  }

  /**
   * 搜索结果类型：新格式 { results, expanded_query }
   */
  interface SearchResponse {
    results: any[]
    expanded_query: string
  }

  async function search(params: {
    q: string
    category?: string
    source_site?: string
    chapter?: string
    tags?: string
    top_k?: number
  }) {
    const res = await fetch(`${baseURL()}/api/search?${new URLSearchParams(
      Object.entries(params as Record<string, string | number | undefined>)
        .filter(([, v]) => v !== undefined && v !== null && v !== "")
        .map(([k, v]) => [k, String(v)])
    )}`, {
      headers: { "Content-Type": "application/json" },
    })
    const data = await res.json()
    if (!res.ok) throw new Error((data as { detail?: string })?.detail ?? `HTTP ${res.status}`)
    // 新格式（Workers 后端）：{ results, expanded_query }
    // 兼容旧格式（Python 后端/旧版本）：直接返回数组
    if (data && typeof data === "object" && "results" in data && "expanded_query" in data) {
      return data as SearchResponse
    }
    return { results: data as any[], expanded_query: "" } as SearchResponse
  }

  async function getTree() {
    return request<any[]>("/api/tree")
  }

  async function getStats() {
    return request<any>("/api/stats")
  }

  async function getConfig() {
    return request<any>("/api/config", {
      headers: authHeaders(),
    })
  }

  async function updateConfig(data: Record<string, unknown>) {
    return request<any>("/api/config", {
      method: "PATCH",
      headers: authHeaders(),
      body: JSON.stringify(data),
    })
  }

  async function indexArticle(data: Record<string, unknown>) {
    return request<any>("/api/articles", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(data),
    })
  }

  async function deleteArticle(articleId: string) {
    return request<any>(`/api/articles/${articleId}`, {
      method: "DELETE",
      headers: authHeaders(),
    })
  }

  async function batchIndex(articles: Record<string, unknown>[]) {
    return request<any[]>("/api/articles/batch", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(articles),
    })
  }

  return {
    setAdminKey,
    getAdminKey,
    search,
    getTree,
    getStats,
    getConfig,
    updateConfig,
    indexArticle,
    deleteArticle,
    batchIndex,
  }
}
