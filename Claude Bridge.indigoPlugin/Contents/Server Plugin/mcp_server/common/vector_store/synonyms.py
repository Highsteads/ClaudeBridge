#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    synonyms.py
# Description: Word-level synonym groups for the search store. Complements
#              type_aliases.py (deviceTypeId -> vocabulary) with QUERY-time
#              expansion: when a query word belongs to a group, its siblings
#              are tried against entity text too — so "telly" finds the Sony
#              TV Plug, "lounge" finds Living Room devices, and "rad" finds
#              the TRVs. The synonym-recall benefit of semantic search with
#              no embeddings, no network calls, no dependencies.
#              Vocabulary freshly authored for this estate (UK-flavoured);
#              growing it is a one-line edit — tune on real miss patterns.
# Author:      CliveS & Claude Opus 4.8
# Date:        23-07-2026
# Version:     1.0

from typing import List, Set, Tuple

# Groups of interchangeable words/phrases. Multi-word phrases allowed —
# matching is on space-normalised lower-case text. Keep groups TIGHT: an
# over-broad group ("kitchen" ~ "cooking") costs precision estate-wide.
SYNONYM_GROUPS: Tuple[Set[str], ...] = (
    # Rooms / places (estate folder + naming reality: Living Room, En Suite,
    # Conservatory, Drive, Garage, Hall, Study, Loft, Utility)
    {"lounge", "living room", "sitting room", "front room"},
    {"bathroom", "washroom", "en suite", "ensuite"},
    {"toilet", "loo", "wc", "cloakroom"},
    {"garden", "outside", "outdoor", "exterior", "yard"},
    {"hallway", "hall", "landing", "corridor"},
    {"study", "office", "den"},
    {"loft", "attic"},
    {"conservatory", "sunroom"},
    {"driveway", "drive"},
    {"utility", "laundry"},

    # Heating / climate
    {"radiator", "trv", "rad"},
    {"boiler", "central heating"},
    {"thermostat", "stat"},
    {"hot water", "cylinder", "immersion"},

    # Lighting
    {"lamp", "light", "bulb"},
    {"spotlight", "spots", "downlight", "downlighter"},
    {"strip", "led strip", "lightstrip"},

    # Media / appliances
    {"tv", "telly", "television"},
    {"fridge", "refrigerator"},
    {"washing machine", "washer"},
    {"tumble dryer", "dryer"},
    {"hoover", "vacuum"},

    # Openings / security
    {"curtains", "blinds", "shades", "shutters"},
    {"doorbell", "bell", "chime"},
    {"cctv", "camera", "cam"},
    {"alarm", "siren", "sounder"},

    # Power / energy
    {"socket", "plug", "outlet", "power point"},
    {"meter", "consumption", "usage"},
    {"solar", "pv", "panels"},
    {"battery", "batteries", "soc"},
    {"inverter", "sigen", "sigenergy"},

    # Water / outdoors
    {"leak", "flood", "moisture"},
    {"weather", "ecowitt"},

    # Occupancy
    {"presence", "occupancy", "motion", "pir"},

    # Vehicles (Qashqai lives on the hub as a favourite)
    {"car", "qashqai", "vehicle"},
)


def variants_for_query(query: str) -> List[str]:
    """
    Alternative query strings implied by synonym membership.

    For each group containing a word (or phrase) of the query, produce one
    variant per sibling with that word swapped. "telly in the lounge" →
    ["tv in the lounge", "television in the lounge", "living room ...", ...].
    The original query is NOT included. Deterministic order (group order,
    sorted siblings) so scoring is stable. Empty list when nothing matches —
    the common case, kept cheap: one normalised containment check per group.
    """
    normalised = " ".join(str(query).lower().split())
    if not normalised:
        return []
    padded = f" {normalised} "

    variants: List[str] = []
    seen: Set[str] = set()
    for group in SYNONYM_GROUPS:
        matched = [term for term in group if f" {term} " in padded]
        for term in matched:
            for sibling in sorted(group):
                if sibling == term:
                    continue
                variant = f" {normalised} ".replace(
                    f" {term} ", f" {sibling} ").strip()
                if variant != normalised and variant not in seen:
                    seen.add(variant)
                    variants.append(variant)
    return variants
