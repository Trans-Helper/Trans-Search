<template>
  <div class="max-w-4xl mx-auto px-4 py-8">
    <h1 class="text-2xl font-bold mb-6">数据库统计</h1>

    <div v-if="loading" class="text-center py-16 text-gray-400">加载中…</div>
    <div v-if="error" class="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm mb-4">{{ error }}</div>

    <div v-if="stats" class="grid grid-cols-2 md:grid-cols-3 gap-4">
      <div class="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
        <p class="text-2xl font-bold text-primary-600">{{ stats.total_chunks ?? "—" }}</p>
        <p class="text-xs text-gray-400 mt-1">总数据块数</p>
      </div>
      <div class="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
        <p class="text-sm font-mono text-gray-800 break-all">{{ stats.embed_model ?? "—" }}</p>
        <p class="text-xs text-gray-400 mt-1">Embedding 模型</p>
      </div>
      <div class="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
        <p class="text-sm font-mono text-gray-800">{{ stats.chat_model ?? "—" }}</p>
        <p class="text-xs text-gray-400 mt-1">对话模型</p>
      </div>
      <div class="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
        <p class="text-lg font-bold" :class="stats.query_expand ? 'text-green-600' : 'text-gray-400'">
          {{ stats.query_expand ? "开启" : "关闭" }}
        </p>
        <p class="text-xs text-gray-400 mt-1">查询扩展</p>
      </div>
      <div class="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
        <p class="text-lg font-bold" :class="stats.hybrid_search ? 'text-green-600' : 'text-gray-400'">
          {{ stats.hybrid_search ? "开启" : "关闭" }}
        </p>
        <p class="text-xs text-gray-400 mt-1">混合搜索</p>
      </div>
      <div class="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
        <p class="text-sm text-gray-800">{{ stats.chunk_size ?? "—" }}</p>
        <p class="text-xs text-gray-400 mt-1">分块大小</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
const { getStats } = useApi()
const stats = ref<any>(null)
const loading = ref(true)
const error = ref("")

onMounted(async () => {
  try {
    stats.value = await getStats()
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
})
</script>
