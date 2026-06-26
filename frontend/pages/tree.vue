<template>
  <div class="max-w-5xl mx-auto px-4 py-8">
    <div class="mb-6">
      <h1 class="text-2xl font-bold mb-2">文章分类浏览</h1>
      <p class="text-gray-500 text-sm">按来源 → 分类 → 章节 组织</p>
    </div>

    <div v-if="loading" class="text-center py-16 text-gray-400">加载中…</div>
    <div v-if="error" class="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{{ error }}</div>

    <div v-if="!loading && tree.length === 0" class="text-center py-16 text-gray-400">
      暂无数据
    </div>

    <div class="space-y-4">
      <div v-for="site in tree" :key="site.name" class="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
        <button
          class="w-full flex items-center justify-between px-5 py-3 hover:bg-gray-50 text-left"
          @click="toggleSite(site.name)"
        >
          <span class="font-semibold text-gray-800">{{ site.name }}</span>
          <span class="text-xs text-gray-400">{{ countArticles(site) }} 篇</span>
        </button>
        <div v-if="expandedSites.has(site.name)" class="border-t border-gray-100">
          <div v-for="cat in site.children" :key="cat.name" class="border-b border-gray-50 last:border-0">
            <button
              class="w-full flex items-center justify-between px-8 py-2 hover:bg-gray-50 text-left"
              @click="toggleCat(site.name, cat.name)"
            >
              <span class="text-sm font-medium text-gray-700">{{ cat.name }}</span>
              <span class="text-xs text-gray-400">{{ countArticles(cat) }} 篇</span>
            </button>
            <div v-if="expandedCats.has(`${site.name}:${cat.name}`)" class="bg-gray-50">
              <div v-for="ch in cat.children" :key="ch.name" class="border-b border-gray-100 last:border-0">
                <button
                  class="w-full flex items-center justify-between px-11 py-2 hover:bg-white text-left"
                  @click="toggleChapter(site.name, cat.name, ch.name)"
                >
                  <span class="text-sm text-gray-600">{{ ch.name }}</span>
                  <span class="text-xs text-gray-400">{{ ch.children?.length ?? 0 }} 篇</span>
                </button>
                <div v-if="expandedChapters.has(`${site.name}:${cat.name}:${ch.name}`)" class="bg-white">
                  <div
                    v-for="art in ch.children"
                    :key="art.article_id"
                    class="px-14 py-2 border-b border-gray-50 last:border-0 flex items-center justify-between"
                  >
                    <div class="flex items-center gap-2 min-w-0">
                      <span class="text-sm text-gray-700 truncate">{{ art.title }}</span>
                      <span v-for="f in art.flags || []" :key="f" class="text-[10px] uppercase px-1 rounded" :class="flagClass(f)">{{ f }}</span>
                    </div>
                    <div class="flex items-center gap-2 shrink-0">
                      <span v-for="t in (art.tags || []).slice(0, 3)" :key="t" class="text-[10px] text-gray-400 bg-gray-100 px-1.5 rounded">{{ t }}</span>
                      <a v-if="art.url" :href="art.url" target="_blank" class="text-[10px] text-primary-600 hover:underline">链接</a>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
const { getTree } = useApi()
const tree = ref<any[]>([])
const loading = ref(true)
const error = ref("")
const expandedSites = reactive(new Set<string>())
const expandedCats = reactive(new Set<string>())
const expandedChapters = reactive(new Set<string>())

function countArticles(node: any): number {
  if (node.children) {
    return node.children.reduce((sum: number, c: any) => sum + countArticles(c), 0)
  }
  return node.length ?? 0
}

function toggleSite(name: string) {
  if (expandedSites.has(name)) expandedSites.delete(name)
  else expandedSites.add(name)
}

function toggleCat(site: string, cat: string) {
  const key = `${site}:${cat}`
  if (expandedCats.has(key)) expandedCats.delete(key)
  else expandedCats.add(key)
}

function toggleChapter(site: string, cat: string, ch: string) {
  const key = `${site}:${cat}:${ch}`
  if (expandedChapters.has(key)) expandedChapters.delete(key)
  else expandedChapters.add(key)
}

function flagClass(f: string): string {
  const map: Record<string, string> = {
    ai: "bg-purple-100 text-purple-600",
    risk: "bg-red-100 text-red-600",
    reviewed: "bg-green-100 text-green-600",
    outdated: "bg-yellow-100 text-yellow-600",
  }
  return map[f] ?? "bg-gray-100 text-gray-500"
}

onMounted(async () => {
  try {
    tree.value = await getTree()
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
})
</script>
