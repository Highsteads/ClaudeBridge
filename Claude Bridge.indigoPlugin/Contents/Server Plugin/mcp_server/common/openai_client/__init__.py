"""
OpenAI client library for consistent API usage.
"""

from .main import emb_text, perform_completion, select_optimal_model

__all__ = ["emb_text", "perform_completion", "select_optimal_model"]