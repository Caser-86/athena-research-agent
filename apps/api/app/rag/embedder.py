"""确定性演示 Embedding。

未配置 Embedding API Key 时使用：把文本 token 映射为稳定伪随机向量并归一化，
保证「同一段文本 → 同一向量」，因而无 Key 也能跑通检索全链路并体现语义区分。
配置 OpenAI 兼容 Embedding 端点后将自动切换为真实向量。
"""

from __future__ import annotations

import hashlib
import math
import re

from app.config import get_settings

_DIM = 128


def _tokens(text: str) -> list[str]:
    toks: list[str] = []
    for mobj in re.finditer(r"[a-zA-Z0-9_+-]+|[\u4e00-\u9fff]", text):
        tok = mobj.group(0)
        toks.append(tok.lower())
    return toks


def _hash_unit(seed: bytes) -> list[float]:
    """由一个 seed 派生出一组确定性伪随机分量（murmur 风格，无需依赖）。"""
    unit = []
    digest = seed
    for i in range(_DIM):
        digest = hashlib.sha256(digest).digest()
        val = int.from_bytes(digest[:4], "big") / (2**32 - 1)
        unit.append(val * 2.0 - 1.0)
    return unit


def embed(text: str) -> list[float]:
    settings = get_settings()
    if settings.embedding_api_key:
        return _embed_remote(text)
    return _embed_demo(text)


def _embed_demo(text: str) -> list[float]:
    tokens = _tokens(text)
    if not tokens:
        return [0.0] * _DIM
    vec = [0.0] * _DIM
    for tok in tokens:
        u = _hash_unit(b"tok:" + tok.encode("utf-8"))
        for i in range(_DIM):
            vec[i] += u[i]
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]


_remote_client = None
_remote_dim: int | None = None


def _embed_remote(text: str) -> list[float]:
    """OpenAI 兼容 embedding 调用（懒加载同步客户端）。

    未配置 embedding 端点时回退到 llm_base_url；统一走 OpenAI-compatible
    /embeddings 接口。返回的向量维度从首请求探测并缓存，供校验对齐。
    """
    global _remote_client, _remote_dim
    settings = get_settings()
    if _remote_client is None:
        try:
            import openai
        except ImportError:  # pragma: no cover
            raise RuntimeError("使用远程 embedding 需安装 openai 依赖")
        _remote_client = openai.OpenAI(
            base_url=settings.embedding_base_url or settings.llm_base_url,
            api_key=settings.embedding_api_key,
        )

    model = settings.embedding_model or "text-embedding-3-small"
    resp = _remote_client.embeddings.create(model=model, input=text)
    try:
        vec = resp.data[0].embedding
    except Exception:  # pragma: no cover
        raise RuntimeError(f"embedding 响应解析失败: {resp}")
    if _remote_dim is None:
        _remote_dim = len(vec)
    if len(vec) != _remote_dim:
        raise RuntimeError(f"embedding 维度不稳定: {len(vec)} != {_remote_dim}")
    return vec


def embedding_dim() -> int:
    """当前启用 embedding 的维度（真实取缓存，演示固定 128），供建表使用。"""
    settings = get_settings()
    if settings.embedding_api_key:
        if _remote_dim is not None:
            return _remote_dim
        # 探测一次真实维度
        return len(_embed_remote("probe"))
    return _DIM