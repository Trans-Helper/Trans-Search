"""
跨性别信息聚合站 · 语义搜索后端
依赖: fastapi uvicorn qdrant-client openai python-dotenv tiktoken
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os, uuid, textwrap
from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchAny, MatchValue,
    ScoredPoint,
)

load_dotenv()

# ── 初始化 ──────────────────────────────────────────────
app = FastAPI(title="Trans Search API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 生产环境改为你的前端域名
    allow_methods=["*"],
    allow_headers=["*"],
)

openai_client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
)

qdrant = QdrantClient(
    host=os.getenv("QDRANT_HOST", "localhost"),
    port=int(os.getenv("QDRANT_PORT", 6333)),
)

COLLECTION = "articles"
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
EMBED_DIM   = 2048
CHUNK_SIZE  = 400   # 字符数
CHUNK_OVERLAP = 80


# ── 启动时建集合（幂等）─────────────────────────────────
@app.on_event("startup")
def init_collection():
    existing = [c.name for c in qdrant.get_collections().collections]
    if COLLECTION not in existing:
        qdrant.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
        )
        print(f"[startup] 集合 '{COLLECTION}' 已创建")
    else:
        print(f"[startup] 集合 '{COLLECTION}' 已存在，跳过")


# ── 工具函数 ─────────────────────────────────────────────
def split_chunks(text: str, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP) -> list[str]:
    """按字符数分块，保留重叠以避免语义截断"""
    chunks, start = [], 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start += size - overlap
    return [c for c in chunks if c.strip()]


def embed(text: str) -> list[float]:
    """调用 OpenAI Embedding，返回向量"""
    resp = openai_client.embeddings.create(model=EMBED_MODEL, input=text[:8000])
    return resp.data[0].embedding


def build_filter(category: Optional[str], tags: Optional[list[str]]) -> Optional[Filter]:
    conditions = []
    if category:
        conditions.append(FieldCondition(key="category", match=MatchValue(value=category)))
    if tags:
        conditions.append(FieldCondition(key="tags", match=MatchAny(any=tags)))
    if not conditions:
        return None
    return Filter(must=conditions)


# ── Pydantic 模型 ─────────────────────────────────────────
class ArticleIn(BaseModel):
    id: Optional[str] = None          # 留空则自动生成
    title: str
    content: str
    url: Optional[str] = None
    category: Optional[str] = None    # 如 "医疗" / "法律" / "生活"
    tags: list[str] = []

class SearchResult(BaseModel):
    article_id: str
    title: str
    excerpt: str
    url: Optional[str]
    category: Optional[str]
    tags: list[str]
    score: float
    chunk_index: int


# ── 路由：录入文章 ────────────────────────────────────────
@app.post("/articles", summary="录入单篇文章并建立索引")
def index_article(article: ArticleIn):
    article_id = article.id or str(uuid.uuid4())
    chunks = split_chunks(article.content)
    points = []

    for i, chunk in enumerate(chunks):
        # 标题 + chunk 拼接，让每块都携带文章主题信息
        input_text = f"{article.title}\n\n{chunk}"
        vector = embed(input_text)

        points.append(PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload={
                "article_id": article_id,
                "chunk_index": i,
                "title":    article.title,
                "chunk":    chunk,
                "url":      article.url,
                "category": article.category,
                "tags":     article.tags,
            },
        ))

    qdrant.upsert(collection_name=COLLECTION, points=points)
    return {"article_id": article_id, "chunks_indexed": len(points)}


# ── 路由：批量录入 ────────────────────────────────────────
@app.post("/articles/batch", summary="批量录入文章")
def index_batch(articles: list[ArticleIn]):
    results = []
    for a in articles:
        try:
            r = index_article(a)
            results.append({"status": "ok", **r})
        except Exception as e:
            results.append({"status": "error", "title": a.title, "error": str(e)})
    return results


# ── 路由：语义搜索 ────────────────────────────────────────
@app.get("/search", response_model=list[SearchResult], summary="语义 + 关键词混合搜索")
def search(
    q:        str            = Query(..., description="搜索关键词或自然语言问题"),
    category: Optional[str] = Query(None, description="按分类筛选，如 医疗/法律/生活"),
    tags:     Optional[str] = Query(None, description="逗号分隔的标签，如 HRT,激素"),
    top_k:    int           = Query(8, ge=1, le=50),
):
    if not q.strip():
        raise HTTPException(400, "搜索词不能为空")

    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    query_vector = embed(q)
    qdrant_filter = build_filter(category, tag_list)

    hits: list[ScoredPoint] = qdrant.search(
        collection_name=COLLECTION,
        query_vector=query_vector,
        query_filter=qdrant_filter,
        limit=top_k * 3,          # 多取一些，后面去重到 top_k 篇
        with_payload=True,
        score_threshold=0.3,       # 过滤掉相关性极低的结果
    )

    # 按 article_id 去重，每篇只保留得分最高的 chunk
    seen: dict[str, SearchResult] = {}
    for h in hits:
        p = h.payload
        aid = p["article_id"]
        if aid not in seen:
            seen[aid] = SearchResult(
                article_id  = aid,
                title       = p["title"],
                excerpt     = p["chunk"][:220].rstrip() + "…",
                url         = p.get("url"),
                category    = p.get("category"),
                tags        = p.get("tags", []),
                score       = round(h.score, 4),
                chunk_index = p["chunk_index"],
            )
        if len(seen) >= top_k:
            break

    return list(seen.values())


# ── 路由：统计 ────────────────────────────────────────────
@app.get("/stats", summary="数据库统计")
def stats():
    info = qdrant.get_collection(COLLECTION)
    return {
        "total_chunks": info.points_count,
        "collection":   COLLECTION,
        "embed_model":  EMBED_MODEL,
    }


# ── 路由：健康检查 ────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}
