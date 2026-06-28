# Trans-Search API 文档

> 跨性别信息聚合搜索后端 API v3.1

## 基础信息

- **Base URL**: `https://trans-search-cf.<你的用户名>.workers.dev` (生产) 或 `http://localhost:8787` (开发)
- **Content-Type**: `application/json`
- **速率限制**: 基于 IP 的滑动窗口，超限返回 `429 Too Many Requests`
  - 搜索接口: 30 次/60 秒
  - 写入接口: 20 次/60 秒
  - 配置接口: 10 次/60 秒

## 鉴权

部分接口需要 `Admin Key`，通过请求头传递：

```
X-Admin-Key: <your_admin_key>
```

## 公共接口

---

### `GET /health`

健康检查。

**Response `200`**
```json
{ "status": "ok" }
```

---

### `GET /search`

语义搜索。支持关键词扩展、混合搜索、多维度筛选。

**Query Parameters**

| 参数          | 类型   | 必填 | 默认值 | 说明                                    |
| ------------- | ------ | ---- | ------ | --------------------------------------- |
| `q`           | string | 是   | —      | 搜索关键词或自然语言问题，最长 200 字符 |
| `category`    | string | 否   | —      | 分类筛选（如 `医疗`）                   |
| `source_site` | string | 否   | —      | 来源网站筛选                            |
| `chapter`     | string | 否   | —      | 章节筛选                                |
| `tags`        | string | 否   | —      | 标签筛选，逗号分隔（如 `HRT,激素`）     |
| `top_k`       | int    | 否   | `8`    | 返回结果数量，1~20                      |

**Response `200`**
```json
[
  {
    "article_id": "uuid-string",
    "title": "文章标题",
    "excerpt": "摘要文本…",
    "url": "https://example.com/article",
    "category": "医疗",
    "source_site": "某网站",
    "chapter": "第一章",
    "tags": ["HRT", "激素"],
    "flags": ["reviewed"],
    "score": 0.8532,
    "chunk_index": 0
  }
]
```

**说明**
- 搜索结果按 `article_id` 去重，每篇文章只返回得分最高的数据块
- 启用了 `query_expand` 时，系统会自动调用 AI 模型扩展搜索词
- 启用了 `hybrid_search` 时，会同时执行稠密向量 + 稀疏向量搜索并做 RRF 融合

---

### `GET /tree`

获取文章的分类树形结构：`来源 → 分类 → 章节 → 文章列表`

**Response `200`**
```json
[
  {
    "name": "某来源网站",
    "type": "site",
    "children": [
      {
        "name": "医疗",
        "type": "category",
        "children": [
          {
            "name": "激素治疗",
            "type": "chapter",
            "children": [
              {
                "type": "article",
                "article_id": "uuid",
                "title": "文章标题",
                "url": "https://...",
                "flags": ["reviewed"],
                "tags": ["HRT"]
              }
            ]
          }
        ]
      }
    ]
  }
]
```

---

### `GET /stats`

数据库统计信息。

**Response `200`**
```json
{
  "total_chunks": 1234,
  "embed_model": "embedding-3",
  "chat_model": "glm-4-flash",
  "query_expand": true,
  "hybrid_search": false,
  "chunk_size": 600,
  "score_threshold": 0.25
}
```

---

## 管理接口 (需 Admin Key)

以下接口需要在请求头中携带 `X-Admin-Key`。

---

### `GET /config`

获取当前运行时配置（不含 API Key 等敏感信息）。

**Response `200`**
```json
{
  "embed_model": "embedding-3",
  "chat_model": "glm-4-flash",
  "chunk_size": 600,
  "chunk_overlap": 80,
  "score_threshold": 0.25,
  "query_expand": true,
  "hybrid_search": false
}
```

---

### `PATCH /config`

更新运行时配置。只提交需要变更的字段。

**Request Body**
```json
{
  "embed_model": "text-embedding-3-small",
  "chunk_size": 400,
  "query_expand": false
}
```

**可用字段**

| 字段              | 类型   | 说明                 | 校验规则                  |
| ----------------- | ------ | -------------------- | ------------------------- |
| `openai_base_url` | string | OpenAI 兼容 API 地址 | 必须在白名单内（防 SSRF） |
| `embed_model`     | string | Embedding 模型名     | —                         |
| `embed_dim`       | int    | 向量维度             | —                         |
| `chat_model`      | string | 对话模型名           | —                         |
| `chunk_size`      | int    | 分块字符数           | 100~2000                  |
| `chunk_overlap`   | int    | 分块重叠字符数       | —                         |
| `score_threshold` | float  | 搜索分数阈值         | 0.0~1.0                   |
| `query_expand`    | bool   | 是否启用查询扩展     | —                         |
| `hybrid_search`   | bool   | 是否启用混合搜索     | —                         |

**Response `200`**
```json
{ "updated": ["embed_model", "chunk_size", "query_expand"] }
```

---

### `POST /articles`

录入单篇文章。系统会自动分块、生成稠密向量和稀疏向量。

**Request Body**
```json
{
  "id": "可选，自定义 ID，不传则自动生成",
  "title": "文章标题",
  "content": "文章正文内容…",
  "url": "https://example.com/article",
  "category": "医疗",
  "source_site": "某网站",
  "chapter": "激素治疗",
  "tags": ["HRT", "雌激素"],
  "flags": ["reviewed"]
}
```

**字段校验**

| 字段      | 必填 | 限制                                         |
| --------- | ---- | -------------------------------------------- |
| `title`   | 是   | 最长 200 字符                                |
| `content` | 是   | 最长 100,000 字符                            |
| `url`     | 否   | 必须以 `http://` 或 `https://` 开头          |
| `tags`    | 否   | 最多 20 个，每个最长 50 字符                 |
| `flags`   | 否   | 可选值: `ai`, `risk`, `reviewed`, `outdated` |

**Response `201`**
```json
{
  "article_id": "uuid-string",
  "chunks_indexed": 5
}
```

---

### `POST /articles/batch`

批量录入文章。单次最多 50 篇。

**Request Body**
```json
[
  { "title": "文章1", "content": "内容…" },
  { "title": "文章2", "content": "内容…" }
]
```

**Response `200`**
```json
[
  { "status": "ok", "article_id": "uuid", "chunks_indexed": 3 },
  { "status": "error", "title": "文章2", "error": "正文不能为空" }
]
```

---

### `PATCH /articles/{article_id}/meta`

更新文章的元数据（标题、分类、标签等）。只更新提交的字段。

**Request Body**
```json
{
  "title": "新标题",
  "category": "法律",
  "tags": ["新标签"],
  "flags": ["reviewed"]
}
```

**Response `200`**
```json
{
  "article_id": "uuid-string",
  "updated_chunks": 5
}
```

---

### `DELETE /articles/{article_id}`

删除文章及其所有数据块。

**Response `200`**
```json
{ "deleted": "uuid-string" }
```

---

## 错误响应

所有接口在出错时返回统一的错误格式：

```json
{ "detail": "错误描述信息" }
```

| HTTP 状态码 | 说明           |
| ----------- | -------------- |
| 400         | 请求参数错误   |
| 403         | Admin Key 无效 |
| 404         | 资源不存在     |
| 429         | 请求过于频繁   |
| 500         | 服务器内部错误 |
