"""
RAG context retriever — calls a Dify App (with knowledge base) for retrieval.
"""
import os
import re
import httpx


RAG_DIFY_BASE_URL = os.getenv("RAG_DIFY_BASE_URL", "").strip().rstrip("/")
RAG_API_KEY = os.getenv("RAG_API_KEY", "")


async def get_rag_context(rag_tag: str, query: str) -> str:
    """
    调用带知识库的 Dify App，用关键信息检索相关文档片段。

    Args:
        rag_tag: 知识库标识（预留扩展，当前未用）
        query: 检索文本（metadata + issue_description）

    Returns:
        检索结果文本；未配置时返回空字符串（不影响现有流程）
    """
    if not RAG_API_KEY or not RAG_DIFY_BASE_URL:
        return ""

    url = f"{RAG_DIFY_BASE_URL}/chat-messages"
    headers = {
        "Authorization": f"Bearer {RAG_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "inputs": {},
        "query": query,
        "response_mode": "blocking",
        "user": "rag-retriever",
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()

        answer = data.get("answer", "").strip()
        # 清理 think 标签
        answer = re.sub(r"<think>[\s\S]*?</think>", "", answer).strip()
        return answer

    except Exception:
        return ""
