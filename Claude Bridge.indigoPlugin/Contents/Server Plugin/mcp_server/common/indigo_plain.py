"""Deep-convert arbitrary indigo.* container types to plain JSON-friendly values.

`indigo.Dict` and `indigo.List` are Boost.Python types, NOT dict/list subclasses.
The JSON encoder falls back to `__dict__` on them and serialises the lot to `{}`,
so a nested structure silently comes back EMPTY rather than raising — the failure
mode that made every getDependencies list look empty until v2.10.0.

`_deps_to_plain` in extended_tools_handler solves that for the one known shape of
getDependencies. This handles an arbitrary reply of unknown depth, which is what a
raw server request returns.
"""

from datetime import date, datetime
from typing import Any

MAX_DEPTH = 24


def to_plain(obj: Any, _depth: int = 0) -> Any:
    """Recursively convert indigo containers to dict/list/scalars.

    Anything unrecognised degrades to `str(obj)` rather than raising — a raw
    reply may carry types we have never seen, and losing one leaf's fidelity
    beats losing the whole response.
    """
    if _depth > MAX_DEPTH:
        return "<max depth exceeded>"

    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")

    # Mapping-like: indigo.Dict answers keys()/[] but is not a dict subclass.
    if hasattr(obj, "keys"):
        try:
            return {str(k): to_plain(obj[k], _depth + 1) for k in obj.keys()}
        except Exception:
            return str(obj)

    # Sequence-like, excluding strings (already handled above).
    if hasattr(obj, "__iter__"):
        try:
            return [to_plain(v, _depth + 1) for v in obj]
        except Exception:
            return str(obj)

    return str(obj)
