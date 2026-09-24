"""
Search entities handler for natural language search of Indigo entities.
"""

import logging
from typing import Any, Callable, Dict, List, Optional

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # type hint only — importing it here would be circular
    from ...adapters.indigo_data_provider import IndigoDataProvider
from ...common.entity_index import EntityIndex
from ...common.indigo_device_types import DeviceClassifier
from ...common.state_filter import StateFilter
from ..base_handler import BaseToolHandler
from .query_parser import QueryParser
from .result_formatter import ResultFormatter


class SearchEntitiesHandler(BaseToolHandler):
    """Handler for searching Indigo entities with semantic search."""
    
    def __init__(
        self, 
        data_provider: "IndigoDataProvider",
        entity_index: EntityIndex,
        logger: Optional[logging.Logger] = None,
        freshen: Optional[Callable[[], Any]] = None,
    ):
        """
        Initialize the search entities handler.
        
        Args:
            data_provider: Data provider for accessing entity data
            entity_index: In-memory entity index to search
            logger: Optional logger instance
            freshen: Called before every search; rebuilds the index when
                Indigo has reported an added, removed or renamed entity
                (EntityIndexManager.refresh_if_dirty)
        """
        super().__init__(tool_name="search_entities", logger=logger)
        self.data_provider = data_provider
        self.entity_index = entity_index
        self._freshen = freshen
        self.query_parser = QueryParser()
        self.result_formatter = ResultFormatter()
    
    def search(
        self,
        query: str,
        device_types: Optional[List[str]] = None,
        entity_types: Optional[List[str]] = None,
        state_filter: Optional[Dict[str, Any]] = None,
        detail: str = "slim",
        top_k: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Search for Indigo entities using natural language with optional filtering.
        
        Args:
            query: Natural language search query
            device_types: Optional list of device types to filter by
            entity_types: Optional list of entity types to search
            state_filter: Optional state conditions to apply after semantic search
            top_k: Fixed result count, overriding the one QueryParser reads
                from words in the query. Device resolution passes a NAME
                here, and a name such as "Landing One" must not shrink the
                result to one hit (the word "one") and hide the device that
                is called exactly that.
            
        Returns:
            Dictionary with formatted search results
        """
        try:
            # An EMPTY device_types list means "no filter", as it does in the
            # wrapper and in QueryParser, which both test truthiness. This method
            # tested `is not None`, so an empty list skipped the validation and
            # the top_k over-fetch yet still reached the filter — where matching
            # nothing discarded every device from the results.
            if not device_types:
                device_types = None

            # Concise query logging
            query_short = query[:50] + "..." if len(query) > 50 else query
            self.debug_log(f"Searching: '{query_short}'")

            # Rebuild first if Indigo has told us the index is out of date.
            if self._freshen is not None:
                self._freshen()

            # Parse query to determine search parameters
            search_params = self.query_parser.parse(query, device_types, entity_types)
            if top_k is not None:
                search_params["top_k"] = max(1, int(top_k))

            # Text search works best with the original query — LLM expansion
            # turns "conservatory lamp" into long descriptions that break substring matching
            raw_results, search_metadata = self.entity_index.search(
                query=query,
                entity_types=search_params["entity_types"],
                top_k=search_params["top_k"],
                similarity_threshold=search_params["threshold"]
            )

            # The index finds WHICH entities match; what they say now comes
            # from Indigo. The index is rebuilt on renames and every 300 s, so
            # its copy of a light's state or a variable's value can be minutes
            # old. Refreshed before the filters run, so a state filter judges
            # the live value too. At most top_k (<= 50) cheap reads.
            raw_results = self._with_live_values(raw_results)

            # Short-circuit: strong exact match — return only the top result.
            # Rewrite the metadata to match the final set, otherwise the store's
            # pre-truncation counts make the summary claim a truncation that did
            # not happen (and spuriously suggest list_devices for "more").
            #
            # NOT when a post-search filter is coming. QueryParser deliberately
            # over-fetches (top_k >= 50) so the type and state filters below see a
            # full candidate set; truncating to one first throws those candidates
            # away, and if that single hit then fails the filter the answer is
            # empty even though matching devices were in the set.
            #
            # AND only for a name that EQUALS the query. Any name merely
            # containing the query also scores 1.0, so the old ">= 0.95" test
            # made "kitchen" return one of fourteen kitchen devices (2.27.3).
            exact = self._exact_name_matches(raw_results, query)
            if (device_types is None and state_filter is None
                    and len(exact) == 1):
                raw_results = exact
                if search_metadata:
                    search_metadata = {**search_metadata,
                                       "total_found": 1, "total_returned": 1, "truncated": False}
            elif exact:
                # Several share the name, or a filter follows: keep them all,
                # exact ones first (they tie at 1.0 with every name that
                # merely contains the query).
                exact_ids = {id(r) for r in exact}
                raw_results.sort(key=lambda r: id(r) not in exact_ids)

            # Apply device type filtering if specified
            if device_types is not None and "devices" in search_params["entity_types"]:
                raw_results = self._filter_devices_by_type(raw_results, device_types)

            # Group results by entity type
            grouped_results = self._group_results_by_type(raw_results)

            # Apply state filtering if specified
            if state_filter is not None and grouped_results.get("devices"):
                filtered_devices = StateFilter.filter_by_state(grouped_results["devices"], state_filter)
                grouped_results["devices"] = filtered_devices

            # Log results summary
            device_count = len(grouped_results.get("devices", []))
            variable_count = len(grouped_results.get("variables", []))
            action_count = len(grouped_results.get("actions", []))
            self.debug_log(f"\t✅ Found: {device_count} devices, {variable_count} variables, {action_count} actions")

            # slim by default; full only when explicitly requested
            use_minimal = (detail != "full")

            # Format results
            formatted_results = self.result_formatter.format_search_results(
                grouped_results,
                query,
                minimal_fields=use_minimal,
                search_metadata=search_metadata,
                state_detected=search_params.get("state_detected", False)
            )

            return formatted_results
            
        except Exception as e:
            return self.handle_exception(e, f"searching for '{query}'")
    
    def _with_live_values(self, raw_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Replace each hit's indexed data with Indigo's current data, keeping
        the search's own bookkeeping keys. A hit Indigo no longer has (deleted
        since the last rebuild) is dropped rather than reported as present."""
        live: List[Dict[str, Any]] = []
        for hit in raw_results:
            kind = hit.get("_entity_type")
            keep = {k: v for k, v in hit.items() if k.startswith("_")}
            try:
                if kind == "device":
                    fresh = self.data_provider.get_device(hit.get("id"))
                    if fresh is None:
                        continue
                    live.append({**fresh, **keep} if isinstance(fresh, dict) else hit)
                elif kind == "variable":
                    fresh = self.data_provider.get_variable(hit.get("id"))
                    if fresh is None:
                        continue
                    live.append({**hit, "value": fresh.get("value", hit.get("value")), **keep}
                                if isinstance(fresh, dict) else hit)
                else:
                    live.append(hit)
            except Exception:
                live.append(hit)   # a failed read keeps the indexed copy, never loses the hit
        return live

    @staticmethod
    def _exact_name_matches(raw_results: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        """Results whose name equals the query, ignoring case and outer spaces."""
        q = (query or "").strip().lower()
        if not q:
            return []
        return [r for r in raw_results
                if str(r.get("name", "")).strip().lower() == q]

    def _group_results_by_type(self, raw_results: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group search results by entity type.
        
        Args:
            raw_results: Flat list of search results from the entity index
            
        Returns:
            Dictionary with entity types as keys and lists of entities as values
        """
        grouped = {
            "devices": [],
            "variables": [],
            "actions": []
        }
        
        for result in raw_results:
            # Extract entity type from result
            entity_type = result.pop("_entity_type", "")
            
            # Map singular to plural
            if entity_type == "device":
                grouped["devices"].append(result)
            elif entity_type == "variable":
                grouped["variables"].append(result)
            elif entity_type == "action":
                grouped["actions"].append(result)
            else:
                # Log unknown entity type but don't fail
                self.warning_log(f"Unknown entity type: {entity_type}")
        
        return grouped
    
    def _filter_devices_by_type(self, raw_results: List[Dict[str, Any]], device_types: List[str]) -> List[Dict[str, Any]]:
        """
        Filter device results by device type.
        
        Args:
            raw_results: Raw search results from the entity index
            device_types: List of device types to filter by
            
        Returns:
            Filtered results containing only devices matching the specified types
        """
        filtered_results = []
        device_type_set = set(device_types)
        
        for result in raw_results:
            # Only filter device entities
            if result.get("_entity_type") == "device":
                # Use the classifier to determine the logical device type
                classified_type = DeviceClassifier.classify_device(result)
                if classified_type in device_type_set:
                    filtered_results.append(result)
            else:
                # Keep non-device entities unchanged
                filtered_results.append(result)
        
        return filtered_results
    
