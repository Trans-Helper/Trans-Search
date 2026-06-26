<template>
  <div class="max-w-3xl mx-auto px-4 py-8">
    <h1 class="text-2xl font-bold mb-6">管理设置</h1>

    <div class="bg-white rounded-xl shadow-sm border border-gray-200 p-5 mb-6">
      <label class="block text-sm font-medium text-gray-700 mb-1">Admin Key</label>
      <input
        v-model="adminKey"
        type="password"
        class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
        placeholder="输入 Admin Key 以解锁管理功能"
      />
    </div>

    <div v-if="!authenticated" class="text-center py-8 text-gray-400 text-sm">
      请输入上方 Admin Key 以查看和修改配置
    </div>

    <template v-if="authenticated">
      <div v-if="loading" class="text-center py-8 text-gray-400">加载配置…</div>
      <div v-if="error" class="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm mb-4">{{ error }}</div>

      <div v-if="config" class="bg-white rounded-xl shadow-sm border border-gray-200 p-5 mb-6">
        <h2 class="text-lg font-semibold mb-4">运行时配置</h2>
        <div class="space-y-4">
          <div v-for="(val, key) in config" :key="key" class="flex items-center justify-between">
            <span class="text-sm text-gray-600">{{ labelMap[key as string] ?? key }}</span>
            <span v-if="typeof val === 'boolean'" class="text-sm">
              <span :class="val ? 'text-green-600' : 'text-gray-400'">{{ val ? "开启" : "关闭" }}</span>
            </span>
            <span v-else class="text-sm font-mono text-gray-800">{{ val }}</span>
          </div>
        </div>
      </div>

      <div class="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
        <h2 class="text-lg font-semibold mb-4">修改配置</h2>
        <div class="space-y-3">
          <div v-for="field in editableFields" :key="field.key" class="flex items-center gap-3">
            <label class="text-sm text-gray-600 w-28 shrink-0">{{ field.label }}</label>
            <input
              v-if="field.type === 'text'"
              v-model="editForm[field.key]"
              class="flex-1 px-3 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-primary-400"
            />
            <input
              v-else-if="field.type === 'number'"
              v-model.number="editForm[field.key]"
              type="number"
              class="flex-1 px-3 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-primary-400 w-24"
            />
            <select
              v-else-if="field.type === 'boolean'"
              v-model="editForm[field.key]"
              class="px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white focus:outline-none focus:ring-1 focus:ring-primary-400"
            >
              <option :value="true">开启</option>
              <option :value="false">关闭</option>
            </select>
          </div>
          <div class="pt-2">
            <button
              class="px-4 py-2 bg-primary-600 text-white rounded-lg text-sm hover:bg-primary-700 disabled:opacity-50"
              :disabled="saving"
              @click="saveConfig"
            >
              {{ saving ? "保存中…" : "保存配置" }}
            </button>
            <span v-if="saved" class="text-green-600 text-sm ml-3">已保存</span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
const { setAdminKey, getAdminKey, getConfig, updateConfig } = useApi()
const adminKey = ref(getAdminKey() ?? "")
const authenticated = ref(!!getAdminKey())
const config = ref<any>(null)
const loading = ref(false)
const saving = ref(false)
const error = ref("")
const saved = ref(false)

const labelMap: Record<string, string> = {
  embed_model: "Embedding 模型",
  chat_model: "对话模型",
  chunk_size: "分块大小",
  chunk_overlap: "分块重叠",
  score_threshold: "分数阈值",
  query_expand: "查询扩展",
  hybrid_search: "混合搜索",
}

const editableFields = [
  { key: "embed_model", label: "Embedding 模型", type: "text" },
  { key: "chat_model", label: "对话模型", type: "text" },
  { key: "chunk_size", label: "分块大小", type: "number" },
  { key: "chunk_overlap", label: "分块重叠", type: "number" },
  { key: "score_threshold", label: "分数阈值", type: "number" },
  { key: "query_expand", label: "查询扩展", type: "boolean" },
  { key: "hybrid_search", label: "混合搜索", type: "boolean" },
]

const editForm = reactive<Record<string, any>>({})

watch(adminKey, (val) => {
  setAdminKey(val)
  if (val) {
    authenticated.value = true
    loadConfig()
  } else {
    authenticated.value = false
    config.value = null
  }
})

async function loadConfig() {
  loading.value = true
  error.value = ""
  try {
    config.value = await getConfig()
    for (const field of editableFields) {
      editForm[field.key] = config.value[field.key]
    }
  } catch (e: any) {
    error.value = e.message
    if (e.message.includes("admin") || e.message.includes("Admin")) {
      authenticated.value = false
      adminKey.value = ""
    }
  } finally {
    loading.value = false
  }
}

async function saveConfig() {
  saving.value = true
  saved.value = false
  error.value = ""
  try {
    const changed: Record<string, any> = {}
    for (const field of editableFields) {
      if (editForm[field.key] !== config.value[field.key]) {
        changed[field.key] = editForm[field.key]
      }
    }
    if (Object.keys(changed).length === 0) {
      saved.value = true
      return
    }
    const res = await updateConfig(changed)
    config.value = await getConfig()
    saved.value = true
  } catch (e: any) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}
</script>
