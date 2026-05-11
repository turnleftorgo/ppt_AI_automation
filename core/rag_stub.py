"""
RAG context retriever -- stub implementation.

Replace with actual vector DB retrieval when RAG infrastructure is ready.
The system works fully without RAG (use_rag: false or when this returns empty).
"""


async def get_rag_context(rag_tag: str, query: str) -> str:
    """
    Retrieve relevant context from knowledge base.

    Args:
        rag_tag: Knowledge base identifier (e.g. "containment_kb")
        query: The rendered prompt to search against

    Returns:
        Context string to inject into system prompt. Empty string = no RAG context.
    """
    # STUB: return empty string (no RAG yet)
    # Future: query vector DB with rag_tag filter
    return ""
