export default defineNuxtConfig({
  devtools: { enabled: true },
  modules: ["@nuxtjs/tailwindcss"],
  nitro: {
    devProxy: {
      "/api": {
        target: process.env.API_BASE_URL || "http://localhost:8787/",
        changeOrigin: true,
      },
    },
  },
  app: {
    head: {
      title: "Trans-Search",
      meta: [{ name: "description", content: "跨性别信息聚合搜索" }],
    },
  },
  css: ["~/assets/css/main.css"],
  runtimeConfig: {
    public: {
      apiBase: "/api",
    },
  },
})
