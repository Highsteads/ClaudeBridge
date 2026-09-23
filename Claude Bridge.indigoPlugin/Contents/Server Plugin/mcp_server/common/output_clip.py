#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    output_clip.py
# Description: Shorten captured output for a tool reply and SAY that it was
#              shortened, so a cut-off result is never read as the whole one.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

from typing import Any, Dict


def clip_into(result: Dict[str, Any], key: str, text: str, limit: int,
              keep: str = "head") -> None:
    """Put `text` into result[key], cut to `limit` characters. When cut, add
    result[key + "_truncated"] with the full length. keep="tail" keeps the
    end instead (a traceback's last line is the exception itself)."""
    text = text or ""
    if len(text) <= limit:
        result[key] = text
        return
    if keep == "tail":
        result[key] = "...[truncated]\n" + text[-limit:]
    else:
        result[key] = text[:limit] + "\n...[truncated]"
    result[key + "_truncated"] = {"shown": limit, "total": len(text)}
