"""Shared level-name → logging-int map for indigo.server.log().

`indigo.server.log(msg, level=...)` wants a Python `logging` INT. Passing a
STRING (e.g. "WARNING") does NOT raise — it is silently ignored and the line
logs as plain Info. That makes it a diagnosis-quality bug rather than a
cosmetic one: every WARNING and ERROR raised through such a call never renders
as one, so nobody filtering the Event Log by severity ever sees it.

This map lives here, in common/, because it had previously been defined inside
adapters/indigo_data_provider.py next to a log_message() that no caller ever
reached — so the fix sat in dead code while the live tool path kept passing the
string. One shared home, one import, no second copy to drift.

Use `resolve(level)` rather than indexing the dict directly: it handles None,
non-string input and unknown names by falling back to INFO, which is what the
caller almost always wants.
"""

import logging

LOG_LEVELS = {
    "DEBUG":    logging.DEBUG,
    "INFO":     logging.INFO,
    "WARNING":  logging.WARNING,
    "WARN":     logging.WARNING,
    "ERROR":    logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def resolve(level) -> int:
    """Return the logging int for a level name, defaulting to INFO.

    Accepts an int unchanged (already resolved), a name in any case, and
    tolerates None or junk without raising.
    """
    if isinstance(level, int) and not isinstance(level, bool):
        return level
    return LOG_LEVELS.get(str(level or "INFO").upper(), logging.INFO)
