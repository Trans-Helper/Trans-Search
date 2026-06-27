"""
Trans-Search 后端 v3
By TransHelper
"""

import hashlib
import hmac
import json
import logging
import os
import re
import time
import typing
import uuid
from collections import defaultdict
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import OpenAI, OpenAIError
from pydantic import BaseModel, field_validator
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchAny,
    MatchValue,
    Modifier,
    PointStruct,
    Prefetch,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("trans-search")

# ════════════════════════════════════════
# 安全常量
# ════════════════════════════════════════
ADMIN_KEY = os.environ.get("ADMIN_API_KEY", "")  # 管理接口鉴权 key，必须在 .env 中设置
SEARCH_MAX_LEN = 200  # 搜索词最大字符数
CONTENT_MAX_LEN = 100_000  # 正文最大字符数
TITLE_MAX_LEN = 200
TAGS_MAX_COUNT = 20

# 速率限制
RATE_LIMITS = {
    "search": (30, 60),  # 每 60 秒最多 30 次搜索
    "write": (20, 60),  # 每 60 秒最多 20 次写入
    "config": (10, 60),  # 每 60 秒最多 10 次配置读写
}
_rate_store: dict[str, list[float]] = defaultdict(list)

# 合法的 HTTPS URL 前缀白名单
ALLOWED_BASE_URL_PREFIXES = [
    "https://api.openai.com",
    "https://open.bigmodel.cn",
    "https://api.moonshot.cn",
    "https://api.deepseek.com",
    "https://dashscope.aliyuncs.com",
]

# 允许的前端域名（CORS）
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS", "http://localhost,http://127.0.0.1"
).split(",")

# ════════════════════════════════════════
# 配置
# ════════════════════════════════════════
CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "./config.json"))

DEFAULT_CONFIG = {
    "openai_base_url": os.getenv(
        "OPENAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/"
    ),
    "embed_model": os.getenv("OPENAI_EMBED_MODEL", "embedding-3"),
    "embed_dim": int(os.getenv("EMBED_DIM", "2048")),
    "chat_model": os.getenv("CHAT_MODEL", "glm-4-flash"),
    "chunk_size": int(os.getenv("CHUNK_SIZE", "600")),
    "chunk_overlap": int(os.getenv("CHUNK_OVERLAP", "80")),
    "score_threshold": float(os.getenv("SCORE_THRESHOLD", "0.25")),
    "query_expand": os.getenv("QUERY_EXPAND", "true").lower() == "true",
    "hybrid_search": os.getenv("HYBRID_SEARCH", "false").lower() == "true",
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return {**DEFAULT_CONFIG, **json.loads(CONFIG_PATH.read_text())}
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return DEFAULT_CONFIG.copy()


def save_config(c: dict):
    CONFIG_PATH.write_text(json.dumps(c, ensure_ascii=False, indent=2))


cfg = load_config()

# ════════════════════════════════════════
# FastAPI 初始化 + Lifespan
# ════════════════════════════════════════


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    if not ADMIN_KEY:
        logger.warning(
            "ADMIN_API_KEY 未设置！写入接口处于无保护状态，请立即在 .env 中配置。"
        )
    existing = [c.name for c in qdrant.get_collections().collections]
    if COLLECTION not in existing:
        qdrant.create_collection(
            collection_name=COLLECTION,
            vectors_config={
                "dense": VectorParams(size=cfg["embed_dim"], distance=Distance.COSINE)
            },
            sparse_vectors_config={"sparse": SparseVectorParams(modifier=Modifier.IDF)},
        )
        logger.info(f"集合 '{COLLECTION}' 已创建")
    yield


app = FastAPI(
    title="Trans-Search API",
    version="3.1",
    lifespan=lifespan,
    # 生产环境关闭自动文档（防止接口探测）
    docs_url=None if os.getenv("ENV") == "production" else "/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-Admin-Key"],
)

qdrant = QdrantClient(
    host=os.getenv("QDRANT_HOST", "localhost"),
    port=int(os.getenv("QDRANT_PORT", "6333")),
)

COLLECTION = "articles"
VALID_FLAGS = {"ai", "risk", "reviewed", "outdated"}


# ════════════════════════════════════════
# 安全中间件 & 依赖
# ════════════════════════════════════════


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(key: str, ip: str, limit: int, window: int):
    """滑动窗口速率限制，超限抛 429"""
    store_key = f"{key}:{ip}"
    now = time.time()
    timestamps = _rate_store[store_key]
    # 清理过期记录
    _rate_store[store_key] = [t for t in timestamps if now - t < window]
    if len(_rate_store[store_key]) >= limit:
        raise HTTPException(
            status_code=429, detail=f"请求过于频繁，请 {window} 秒后再试"
        )
    _rate_store[store_key].append(now)


def require_admin(request: Request):
    """验证管理接口 Key（写入、配置、删除等操作需要）"""
    if not ADMIN_KEY:
        raise HTTPException(500, "服务端未配置 ADMIN_API_KEY，请联系管理员")
    provided = request.headers.get("X-Admin-Key", "")
    # 使用 hmac 比较，防止时序攻击
    if not hmac.compare_digest(provided, ADMIN_KEY):
        raise HTTPException(403, "无效的管理员 Key")


AdminDepends = Depends(require_admin)


def validate_base_url(url: str) -> str:
    """防 SSRF：只允许白名单内的 HTTPS 地址"""
    url = url.strip().rstrip("/") + "/"
    if not any(url.startswith(prefix) for prefix in ALLOWED_BASE_URL_PREFIXES):
        raise HTTPException(
            400,
            f"Base URL 不在允许列表内。允许的服务商：{', '.join(ALLOWED_BASE_URL_PREFIXES)}",
        )
    return url


def sanitize_search_query(q: str) -> str:
    """清理搜索词：去除控制字符，截断长度"""
    q = re.sub(r"[\x00-\x1f\x7f]", "", q).strip()
    if len(q) > SEARCH_MAX_LEN:
        raise HTTPException(400, f"搜索词过长，最多 {SEARCH_MAX_LEN} 个字符")
    if not q:
        raise HTTPException(400, "搜索词不能为空")
    return q


# ════════════════════════════════════════
# 错误处理：脱敏内部错误
# ════════════════════════════════════════
@app.exception_handler(Exception)
async def generic_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    # 内部错误只记日志，不暴露堆栈给客户端
    logger.error(f"Unhandled error: {type(exc).__name__}: {exc}", True)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误"})


# ════════════════════════════════════════
# 工具函数
# ════════════════════════════════════════


def split_chunks(text: str) -> list[str]:
    size = cfg["chunk_size"]
    overlap = cfg["chunk_overlap"]
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks, current = [], ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= size:
            current += ("\n\n" if current else "") + para
        else:
            if current:
                chunks.append(current)
            if len(para) > size:
                for i in range(0, len(para), size - overlap):
                    part = para[i : i + size]
                    if part.strip():
                        chunks.append(part)
                current = ""
            else:
                current = para
    if current:
        chunks.append(current)
    return [c for c in chunks if c.strip()]


def build_context_prefix(article) -> str:
    parts = []
    if article.source_site:
        parts.append(f"来源：{article.source_site}")
    if article.category:
        parts.append(f"分类：{article.category}")
    if article.chapter:
        parts.append(f"章节：{article.chapter}")
    parts.append(f"标题：{article.title}")
    return "\n".join(parts)


def make_client():
    return OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=cfg["openai_base_url"],
    )


def embed(text: str) -> list[float]:
    resp = make_client().embeddings.create(
        model=cfg["embed_model"],
        input=text[:8000],
    )
    return resp.data[0].embedding


def text_to_sparse(text: str) -> SparseVector:
    tokens: dict[int, float] = {}
    for i in range(len(text)):
        for n in (1, 2):
            if i + n <= len(text):
                gram = text[i : i + n]
                h = int(hashlib.md5(gram.encode()).hexdigest(), 16) % (2**20)
                tokens[h] = tokens.get(h, 0) + (1.0 if n == 1 else 1.5)
    return SparseVector(indices=list(tokens.keys()), values=list(tokens.values()))


def expand_query(q: str) -> str:
    if not cfg.get("query_expand"):
        return q
    # 防 prompt injection：只取前 100 字，去除换行和特殊字符
    safe_q = re.sub(r"[^\w\s\u4e00-\u9fff，。？！、]", "", q[:100])
    try:
        resp = make_client().chat.completions.create(
            model=cfg["chat_model"],
            messages=[
                {
                    "role": "system",
                    "content": "你是一个搜索词扩展助手。只输出扩展后的词，用逗号分隔，不要解释，不要其他内容。",
                },
                {
                    "role": "user",
                    "content": f"扩展搜索词（2-3个同义表达）：{safe_q}",
                },
            ],
            max_tokens=60,
            temperature=0.3,
        )
        expanded = resp.choices[0].message.content.strip()
        # 只保留中文、字母、数字、逗号，防止注入内容污染向量
        expanded = re.sub(r"[^\w\s\u4e00-\u9fff，,、]", "", expanded)[:200]
        return f"{q}，{expanded}"
    except OpenAIError as e:
        logger.warning(f"查询扩展失败，使用原始查询: {e}")
        return q


def build_filter(category, tags, source_site, chapter) -> Filter | None:
    conditions: list[FieldCondition] = []
    if category:
        conditions.append(
            FieldCondition(key="category", match=MatchValue(value=category))
        )
    if source_site:
        conditions.append(
            FieldCondition(key="source_site", match=MatchValue(value=source_site))
        )
    if chapter:
        conditions.append(
            FieldCondition(key="chapter", match=MatchValue(value=chapter))
        )
    if tags:
        conditions.append(FieldCondition(key="tags", match=MatchAny(any=tags)))
    if not conditions:
        return None
    return Filter(must=typing.cast("list", conditions))


# ════════════════════════════════════════
# Pydantic 模型（含输入校验）
# ════════════════════════════════════════


class ArticleIn(BaseModel):
    id: str | None = None
    title: str
    content: str
    url: str | None = None
    category: str | None = None
    source_site: str | None = None
    chapter: str | None = None
    tags: list[str] = []
    flags: list[str] = []

    @field_validator("title")
    @classmethod
    def validate_title(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("标题不能为空")
        if len(v) > TITLE_MAX_LEN:
            raise ValueError(f"标题最多 {TITLE_MAX_LEN} 字符")
        return v

    @field_validator("content")
    @classmethod
    def validate_content(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("正文不能为空")
        if len(v) > CONTENT_MAX_LEN:
            raise ValueError(f"正文最多 {CONTENT_MAX_LEN} 字符")
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v):
        if len(v) > TAGS_MAX_COUNT:
            raise ValueError(f"标签最多 {TAGS_MAX_COUNT} 个")
        return [t[:50] for t in v]  # 每个标签最长 50 字符

    @field_validator("flags")
    @classmethod
    def validate_flags(cls, v):
        invalid = set(v) - VALID_FLAGS
        if invalid:
            raise ValueError(f"非法 flag：{invalid}")
        return v

    @field_validator("url")
    @classmethod
    def validate_url(cls, v):
        if v and not re.match(r"^https?://", v):
            raise ValueError("URL 必须以 http:// 或 https:// 开头")
        return v


class ArticleMeta(BaseModel):
    title: str | None = None
    url: str | None = None
    category: str | None = None
    source_site: str | None = None
    chapter: str | None = None
    tags: list[str] | None = None
    flags: list[str] | None = None

    @field_validator("flags")
    @classmethod
    def validate_flags(cls, v):
        if v is not None:
            invalid = set(v) - VALID_FLAGS
            if invalid:
                raise ValueError(f"非法 flag：{invalid}")
        return v


class SearchResult(BaseModel):
    article_id: str
    title: str
    excerpt: str
    url: str | None
    category: str | None
    source_site: str | None
    chapter: str | None
    tags: list[str]
    flags: list[str]
    score: float
    chunk_index: int


class ConfigUpdate(BaseModel):
    openai_base_url: str | None = None
    embed_model: str | None = None
    embed_dim: int | None = None
    chat_model: str | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    score_threshold: float | None = None
    query_expand: bool | None = None
    hybrid_search: bool | None = None

    @field_validator("openai_base_url")
    @classmethod
    def validate_url(cls, v):
        if v:
            validate_base_url(v)
        return v

    @field_validator("chunk_size")
    @classmethod
    def validate_chunk_size(cls, v):
        if v is not None and not (100 <= v <= 2000):
            raise ValueError("chunk_size 范围：100~2000")
        return v

    @field_validator("score_threshold")
    @classmethod
    def validate_threshold(cls, v):
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError("score_threshold 范围：0.0~1.0")
        return v


# ════════════════════════════════════════
# 公开接口（搜索、健康检查）
# ════════════════════════════════════════


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/search")
def search(
    request: Request,
    q: str = Query(..., max_length=SEARCH_MAX_LEN),
    category: str | None = Query(None, max_length=50),
    source_site: str | None = Query(None, max_length=100),
    chapter: str | None = Query(None, max_length=200),
    tags: str | None = Query(None, max_length=200),
    top_k: int = Query(8, ge=1, le=20),
):
    ip = get_client_ip(request)
    check_rate_limit("search", ip, *RATE_LIMITS["search"])

    q = sanitize_search_query(q)
    tag_list = (
        [t.strip()[:50] for t in tags.split(",") if t.strip()][:10] if tags else None
    )
    qfilter = build_filter(category, tag_list, source_site, chapter)

    expanded_q = expand_query(q)
    query_vector = embed(expanded_q)
    query_sparse = text_to_sparse(expanded_q)

    if cfg.get("hybrid_search"):
        hits = qdrant.query_points(
            collection_name=COLLECTION,
            prefetch=[
                Prefetch(
                    query=query_vector,
                    using="dense",
                    filter=qfilter,
                    limit=top_k * 4,
                ),
                Prefetch(
                    query=query_sparse,
                    using="sparse",
                    filter=qfilter,
                    limit=top_k * 4,
                ),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=top_k * 3,
            with_payload=True,
        ).points
    else:
        hits = qdrant.query_points(
            collection_name=COLLECTION,
            query=query_vector,
            using="dense",
            query_filter=qfilter,
            limit=top_k * 3,
            with_payload=True,
            score_threshold=cfg["score_threshold"],
        ).points

    seen: dict[str, SearchResult] = {}
    for h in hits:
        p = h.payload
        if p is None:
            continue
        aid = p["article_id"]
        if aid not in seen:
            seen[aid] = SearchResult(
                article_id=aid,
                title=p["title"],
                excerpt=p["chunk"][:220].rstrip() + "…",
                url=p.get("url"),
                category=p.get("category"),
                source_site=p.get("source_site"),
                chapter=p.get("chapter"),
                tags=p.get("tags", []),
                flags=p.get("flags", []),
                score=round(h.score, 4),
                chunk_index=p["chunk_index"],
            )
        if len(seen) >= top_k:
            break
    results = list(seen.values())
    import json as _json
    return Response(
        content=_json.dumps([r.model_dump() for r in results], ensure_ascii=False),
        media_type="application/json",
        headers={"X-Expanded-Query": expanded_q, "Access-Control-Expose-Headers": "X-Expanded-Query"}
    )

@app.get("/tree")
def get_tree(request: Request):
    ip = get_client_ip(request)
    check_rate_limit("search", ip, *RATE_LIMITS["search"])

    offset, seen_articles, all_payloads = None, set(), []
    while True:
        result, next_offset = qdrant.scroll(
            collection_name=COLLECTION,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in result:
            p = point.payload
            if p is None:
                continue
            aid = p.get("article_id")
            if aid and p.get("chunk_index", 0) == 0 and aid not in seen_articles:
                seen_articles.add(aid)
                all_payloads.append(p)
        if next_offset is None:
            break
        offset = next_offset

    tree: dict = {}
    for p in all_payloads:
        site = p.get("source_site") or "未分类来源"
        cat = p.get("category") or "未分类"
        chapter = p.get("chapter") or "其他"
        tree.setdefault(site, {})
        tree[site].setdefault(cat, {})
        tree[site][cat].setdefault(chapter, [])
        tree[site][cat][chapter].append(
            {
                "article_id": p.get("article_id"),
                "title": p.get("title"),
                "url": p.get("url"),
                "flags": p.get("flags", []),
                "tags": p.get("tags", []),
            }
        )

    result = []
    for site, cats in tree.items():
        site_node = {"name": site, "type": "site", "children": []}
        for cat, chapters in cats.items():
            cat_node = {"name": cat, "type": "category", "children": []}
            for chapter, articles in chapters.items():
                cat_node["children"].append(
                    {
                        "name": chapter,
                        "type": "chapter",
                        "children": [{"type": "article", **a} for a in articles],
                    }
                )
            site_node["children"].append(cat_node)
        result.append(site_node)
    return result


@app.get("/stats")
def stats(request: Request):
    ip = get_client_ip(request)
    check_rate_limit("search", ip, *RATE_LIMITS["search"])
    info = qdrant.get_collection(COLLECTION)
    return {
        "total_chunks": info.points_count,
        "embed_model": cfg["embed_model"],
        "chat_model": cfg["chat_model"],
        "query_expand": cfg["query_expand"],
        "hybrid_search": cfg["hybrid_search"],
        "chunk_size": cfg["chunk_size"],
        "score_threshold": cfg["score_threshold"],
        # 注意：不返回 API Key、Base URL 等敏感配置
    }


# ════════════════════════════════════════
# 管理接口（需要 X-Admin-Key）
# ════════════════════════════════════════


@app.get("/config")
def get_config(request: Request, _=AdminDepends):
    check_rate_limit("config", get_client_ip(request), *RATE_LIMITS["config"])
    # 不返回 API Key
    return {k: v for k, v in cfg.items() if "key" not in k.lower()}


@app.patch("/config")
def update_config(request: Request, update: ConfigUpdate, _=AdminDepends):
    check_rate_limit("config", get_client_ip(request), *RATE_LIMITS["config"])
    changed = {k: v for k, v in update.model_dump().items() if v is not None}
    cfg.update(changed)
    save_config(cfg)
    logger.info(f"配置已更新：{list(changed.keys())}")
    return {"updated": list(changed.keys())}


@app.post("/articles")
def index_article(request: Request, article: ArticleIn, _=AdminDepends):
    check_rate_limit("write", get_client_ip(request), *RATE_LIMITS["write"])

    article_id = article.id or str(uuid.uuid4())
    chunks = split_chunks(article.content)
    prefix = build_context_prefix(article)
    points = []

    for i, chunk in enumerate(chunks):
        input_text = f"{prefix}\n\n{chunk}"
        dense_vector = embed(input_text)
        sparse_vec = text_to_sparse(input_text)
        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector={"dense": dense_vector, "sparse": sparse_vec},
                payload={
                    "article_id": article_id,
                    "chunk_index": i,
                    "title": article.title,
                    "chunk": chunk,
                    "url": article.url,
                    "category": article.category,
                    "source_site": article.source_site,
                    "chapter": article.chapter,
                    "tags": article.tags,
                    "flags": article.flags,
                },
            )
        )

    qdrant.upsert(collection_name=COLLECTION, points=points)
    logger.info(f"文章入库：{article.title}（{len(points)} 块）")
    return {"article_id": article_id, "chunks_indexed": len(points)}


@app.post("/articles/batch")
def index_batch(request: Request, articles: list[ArticleIn], _=AdminDepends):
    if len(articles) > 50:
        raise HTTPException(400, "单次批量最多 50 篇")
    check_rate_limit("write", get_client_ip(request), *RATE_LIMITS["write"])
    results = []
    for a in articles:
        try:
            r = index_article(request, a)
            results.append({"status": "ok", **r})
        except HTTPException as e:
            results.append({"status": "error", "title": a.title, "error": e.detail})
    return results


@app.patch("/articles/{article_id}/meta")
def update_article_meta(
    article_id: str, request: Request, meta: ArticleMeta, _=AdminDepends
):
    check_rate_limit("write", get_client_ip(request), *RATE_LIMITS["write"])

    hits, _ = qdrant.scroll(
        collection_name=COLLECTION,
        scroll_filter=Filter(
            must=[FieldCondition(key="article_id", match=MatchValue(value=article_id))]
        ),
        limit=1,
        with_payload=False,
        with_vectors=False,
    )
    if not hits:
        raise HTTPException(404, "文章不存在")

    update_payload = {k: v for k, v in meta.model_dump().items() if v is not None}
    if not update_payload:
        return {"updated": 0}

    all_ids, offset = [], None
    while True:
        result, next_offset = qdrant.scroll(
            collection_name=COLLECTION,
            scroll_filter=Filter(
                must=[
                    FieldCondition(key="article_id", match=MatchValue(value=article_id))
                ]
            ),
            limit=100,
            with_payload=False,
            with_vectors=False,
            offset=offset,
        )
        all_ids.extend([p.id for p in result])
        if next_offset is None:
            break
        offset = next_offset

    qdrant.set_payload(
        collection_name=COLLECTION, payload=update_payload, points=all_ids
    )
    return {"article_id": article_id, "updated_chunks": len(all_ids)}


@app.delete("/articles/{article_id}")
def delete_article(article_id: str, request: Request, _=AdminDepends):
    check_rate_limit("write", get_client_ip(request), *RATE_LIMITS["write"])
    qdrant.delete(
        collection_name=COLLECTION,
        points_selector=Filter(
            must=[FieldCondition(key="article_id", match=MatchValue(value=article_id))]
        ),
    )
    logger.info(f"文章已删除：{article_id}")
    return {"deleted": article_id}
