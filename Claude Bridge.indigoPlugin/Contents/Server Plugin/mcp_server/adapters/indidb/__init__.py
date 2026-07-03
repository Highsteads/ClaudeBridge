"""
Read-only adapter over Indigo's .indiDb database file.

Gives ClaudeBridge access to the automation internals the IOM never exposes
— action steps, conditions, embedded scripts — via a streaming parser and an
mtime-cached store. Strictly read-only: editing the file while the server
runs is unsafe (the server flushes its in-memory model over it).
"""

from .parser import ParsedDb, parse_indidb, decode_typed_element
from .reverse_index import ReverseIndex, Reference, build_reverse_index
from .store import IndiDbStructureStore, FRESHNESS_NOTE

__all__ = [
    "ParsedDb", "parse_indidb", "decode_typed_element",
    "ReverseIndex", "Reference", "build_reverse_index",
    "IndiDbStructureStore", "FRESHNESS_NOTE",
]
