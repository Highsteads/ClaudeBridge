#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    arg_coercion.py
# Description: Turn string tool arguments into the types a tool's schema asks
#              for — and leave them alone where the schema asks for a string.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

"""
Schema-aware argument coercion, done on the server.

Until v2.27.3 the stdio proxy did this blind. It could not see the tool
schemas, so it converted any string that LOOKED numeric or like JSON, and a
string argument was changed without anyone knowing:

    variable_update(value='{"mode":"away"}')  stored a Python dict repr
    variable_update(value="21.50")             stored "21.5"
    execute_indigo_python(code="42", mode="eval")  arrived as an int and failed

Every one of those reported success. The server knows each property's type,
so it converts only where the schema does not accept a string, and a string
property always receives exactly what was sent.

The token rules are the proxy's conservative ones: "true"/"null" and other
words stay words, a leading-zero or leading-"+" code is never a number, and a
float needs a "." or an exponent (so an IP address is never numeric).
"""

import json
from typing import Any, Dict, Set


def allowed_types(prop_schema: Any) -> Set[str]:
    """Every JSON type a property schema accepts. Empty set = undeclared."""
    if not isinstance(prop_schema, dict):
        return set()
    found: Set[str] = set()
    declared = prop_schema.get("type")
    if isinstance(declared, str):
        found.add(declared)
    elif isinstance(declared, list):
        found.update(t for t in declared if isinstance(t, str))
    for key in ("anyOf", "oneOf"):
        for sub in prop_schema.get(key) or []:
            found |= allowed_types(sub)
    if "enum" in prop_schema and not found:
        if all(isinstance(v, str) for v in prop_schema["enum"]):
            found.add("string")
    return found


def _as_int(text: str):
    digits = text.lstrip("-")
    if (digits.isdigit() and text[:1] != "+"
            and not (len(digits) > 1 and digits[0] == "0")
            and text.count("-") <= 1):
        return int(text)
    return None


def _as_float(text: str):
    if any(c in text for c in (".", "e", "E")):
        try:
            return float(text)
        except ValueError:
            return None
    return None


def coerce_value(value: Any, types: Set[str]) -> Any:
    """Convert one string towards the schema's types; anything that does not
    convert cleanly is returned unchanged for the handler to judge."""
    if not isinstance(value, str):
        return value
    # Every branch below needs the schema to accept a non-string type (or to
    # declare none), so a string-only property falls through all of them and
    # gets back exactly what was sent. An id-or-name property (number|string)
    # still turns plain digits into an id, as the proxy always did.
    undeclared = not types
    text = value.strip()

    if (undeclared or types & {"array", "object"}) and text[:1] in ("[", "{"):
        try:
            parsed = json.loads(text)
            if undeclared or ("array" in types and isinstance(parsed, list)) \
                    or ("object" in types and isinstance(parsed, dict)):
                return parsed
        except (ValueError, TypeError):
            pass

    if undeclared or types & {"integer", "number"}:
        as_int = _as_int(text)
        if as_int is not None:
            return as_int
    if undeclared or "number" in types:
        as_float = _as_float(text)
        if as_float is not None:
            return as_float

    if "boolean" in types and text.lower() in ("true", "false"):
        return text.lower() == "true"
    return value


def coerce_to_schema(args: Dict[str, Any], properties: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce every top-level argument against its property schema."""
    return {k: coerce_value(v, allowed_types((properties or {}).get(k)))
            for k, v in (args or {}).items()}
