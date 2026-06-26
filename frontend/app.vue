<template>
  <div class="min-h-screen flex flex-col">
    <header class="bg-white border-b border-gray-200 sticky top-0 z-50">
      <div class="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
        <NuxtLink to="/" class="text-lg font-bold text-primary-600 hover:text-primary-700">
          Trans‑Search
        </NuxtLink>
        <nav class="flex items-center gap-1">
          <NuxtLink to="/" class="px-3 py-1.5 rounded-md text-sm hover:bg-gray-100" active-class="bg-primary-50 text-primary-700 font-medium">
            搜索
          </NuxtLink>
          <NuxtLink to="/tree" class="px-3 py-1.5 rounded-md text-sm hover:bg-gray-100" active-class="bg-primary-50 text-primary-700 font-medium">
            分类
          </NuxtLink>
          <NuxtLink to="/stats" class="px-3 py-1.5 rounded-md text-sm hover:bg-gray-100" active-class="bg-primary-50 text-primary-700 font-medium">
            统计
          </NuxtLink>
          <NuxtLink to="/config" class="px-3 py-1.5 rounded-md text-sm hover:bg-gray-100" active-class="bg-primary-50 text-primary-700 font-medium">
            管理
          </NuxtLink>
        </nav>
      </div>
    </header>
    <main class="flex-1">
      <NuxtPage />
    </main>
  </div>
</template>
