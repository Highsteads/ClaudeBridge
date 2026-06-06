"""
Parallel embedding generation utilities.

Stubbed out after the Anthropic rewrite: Claude has no embeddings API, and the
previous implementation imported a nonexistent `_get_embedding_client` and called
the OpenAI embeddings endpoint, neither of which exist on the Claude backend.

These functions are kept as no-op stubs (mirroring `main.emb_texts_batch`) so any
future caller degrades gracefully to empty vectors rather than raising ImportError.
If real embeddings are ever needed, route them to a dedicated embeddings provider.
"""

import logging
from typing import List, Callable

logger = logging.getLogger("Plugin")


def emb_texts_batch_parallel(
    texts: List[str],
    entity_names: List[str] = None,
    progress_callback: Callable = None,
    max_concurrent_batches: int = 4,
) -> List[List[float]]:
    """Stub — embeddings not available with Claude. Returns empty vectors."""
    if not texts:
        return []
    logger.debug(
        "emb_texts_batch_parallel called but embeddings are not available on the "
        "Claude backend; returning empty vectors"
    )
    return [[] for _ in texts]


def should_use_parallel_processing(text_count: int, min_threshold: int = 50) -> bool:
    """
    Determine if parallel processing should be used based on text count.

    Args:
        text_count: Number of texts to process
        min_threshold: Minimum number of texts to warrant parallel processing

    Returns:
        True if parallel processing should be used
    """
    return text_count >= min_threshold


def get_optimal_concurrency(text_count: int, max_concurrent: int = 6) -> int:
    """
    Calculate optimal concurrency level based on text count and constraints.

    Args:
        text_count: Number of texts to process
        max_concurrent: Maximum allowed concurrent batches

    Returns:
        Optimal number of concurrent batches
    """
    # Scale concurrency with data size but respect limits
    if text_count < 100:
        return 2
    elif text_count < 500:
        return 3
    elif text_count < 1000:
        return 4
    else:
        return min(max_concurrent, max(2, text_count // 200))
