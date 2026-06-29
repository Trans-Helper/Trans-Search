<template>
  <div class="max-w-4xl mx-auto px-4 py-8">
    <div class="mb-8">
      <h1 class="text-2xl font-bold mb-2">跨性别信息聚合搜索</h1>
      <p class="text-gray-500 text-sm">语义搜索引擎 — 支持关键词扩展与多维度筛选</p>
    </div>

    <div class="bg-white rounded-xl shadow-sm border border-gray-200 p-4 mb-6">
      <div class="flex gap-2 mb-3">
        <input
          v-model="query"
          type="text"
          placeholder="输入搜索关键词或自然语言问题…"
          class="flex-1 px-4 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent text-sm"
          @keydown.enter="doSearch"
        />
        <button
          class="px-6 py-2.5 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 text-sm font-medium"
          :disabled="loading || !query.trim()"
          @click="doSearch"
        >
          {{ loading ? "搜索中…" : "搜索" }}
        </button>
      </div>

      <div class="flex flex-wrap gap-2">
        <input
          v-model="filters.category"
          placeholder="分类（如 医疗）"
          class="px-3 py-1.5 border border-gray-200 rounded-md text-xs w-28 focus:outline-none focus:ring-1 focus:ring-primary-400"
        />
        <input
          v-model="filters.source_site"
          placeholder="来源网站"
          class="px-3 py-1.5 border border-gray-200 rounded-md text-xs w-32 focus:outline-none focus:ring-1 focus:ring-primary-400"
        />
        <input
          v-model="filters.chapter"
          placeholder="章节"
          class="px-3 py-1.5 border border-gray-200 rounded-md text-xs w-28 focus:outline-none focus:ring-1 focus:ring-primary-400"
        />
        <input
          v-model="filters.tags"
          placeholder="标签（逗号分隔）"
          class="px-3 py-1.5 border border-gray-200 rounded-md text-xs w-40 focus:outline-none focus:ring-1 focus:ring-primary-400"
        />
        <select
          v-model.number="filters.top_k"
          class="px-2 py-1.5 border border-gray-200 rounded-md text-xs bg-white focus:outline-none focus:ring-1 focus:ring-primary-400"
        >
          <option :value="5">5 条</option>
          <option :value="8">8 条</option>
          <option :value="12">12 条</option>
          <option :value="20">20 条</option>
        </select>
      </div>
    </div>

    <div v-if="error" class="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 mb-4 text-sm">
      {{ error }}
    </div>

    <div v-if="results.length > 0" class="space-y-4">
      <div class="flex items-center gap-2 mb-2 flex-wrap">
        <p class="text-sm text-gray-400">共 {{ results.length }} 条结果</p>
        <span v-if="expandedQuery && expandedQuery !== query" class="text-xs text-primary-500 bg-primary-50 px-2 py-0.5 rounded-full">
          搜索已扩展：<span class="font-medium">{{ expandedQuery }}</span>
        </span>
      </div>
      <div
        v-for="r in results"
        :key="r.article_id"
        class="bg-white rounded-xl shadow-sm border border-gray-200 p-5 hover:shadow-md transition-shadow"
      >
        <div class="flex items-start justify-between gap-3 mb-1">
          <h3 class="text-base font-semibold text-gray-900 leading-snug">{{ r.title }}</h3>
          <span class="shrink-0 text-xs font-mono text-gray-400">{{ (r.score * 100).toFixed(1) }}%</span>
        </div>
        <div class="md-render mb-2" v-html="renderMd(r.excerpt)"></div>
        <div class="flex flex-wrap items-center gap-2 text-xs text-gray-400">
          <span v-if="r.category" class="bg-blue-50 text-blue-600 px-2 py-0.5 rounded">{{ r.category }}</span>
          <span v-if="r.source_site" class="bg-green-50 text-green-600 px-2 py-0.5 rounded">{{ r.source_site }}</span>
          <span v-if="r.chapter" class="bg-purple-50 text-purple-600 px-2 py-0.5 rounded">{{ r.chapter }}</span>
          <span v-for="t in r.tags" :key="t" class="bg-gray-100 text-gray-500 px-2 py-0.5 rounded">{{ t }}</span>
          <span v-if="r.url" class="ml-auto">
            <a :href="r.url" target="_blank" class="text-primary-600 hover:underline">打开原文</a>
          </span>
        </div>
      </div>
    </div>

    <div v-if="!loading && query && results.length === 0 && !error" class="text-center py-16 text-gray-400">
      没有找到相关结果
    </div>
  </div>
</template>

<script setup lang="ts">
import { marked } from "marked"

// 配置 marked：在新窗口打开链接
marked.setOptions({
  breaks: true,
  gfm: true,
})

function renderMd(text: string): string {
  if (!text) return ""
  // 限制长度后渲染
  let s = text.slice(0, 300)
  // 补全被截断的 Markdown 链接 [text](url → [text](url)
  // 以及图片 ![alt](url → ![alt](url)
  const openParen = s.lastIndexOf("(")
  const closeParen = s.lastIndexOf(")")
  if (openParen > closeParen) {
    // 有未闭合的圆括号（链接被截断了），补上 )
    s += ")"
  }
  // 补全未闭合的加粗/斜体 **text → **text**
  const stars = (s.match(/\*{1,3}/g) || []).length
  if (stars % 2 !== 0) s += "**"
  // 补全未闭合的代码标记 `text → `text`
  const backticks = (s.match(/`/g) || []).length
  if (backticks % 2 !== 0) s += "`"

  return marked.parse(s, { async: false }) as string
}

const { search } = useApi()
const query = ref("")
const loading = ref(false)
const results = ref<any[]>([])
const error = ref("")
const expandedQuery = ref("")

const filters = reactive({
  category: "",
  source_site: "",
  chapter: "",
  tags: "",
  top_k: 8,
})

async function doSearch() {
  const q = query.value.trim()
  if (!q) return
  loading.value = true
  error.value = ""
  results.value = []
  expandedQuery.value = ""
  try {
    const data = await search({
      q,
      category: filters.category || undefined,
      source_site: filters.source_site || undefined,
      chapter: filters.chapter || undefined,
      tags: filters.tags || undefined,
      top_k: filters.top_k,
    })
    results.value = data.results
    expandedQuery.value = data.expanded_query
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
</script>
