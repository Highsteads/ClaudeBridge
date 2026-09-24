"""
Lifecycle of the in-memory entity index: the first load, the periodic
rebuild (every 300 s by default), the out-of-band refresh after a tool
changes entity structure, and the rebuild-on-next-search after Indigo tells
the plugin that a device, variable or action group was added, removed or
renamed (mark_dirty / refresh_if_dirty).
"""

import logging
import threading
import time
from typing import Optional, Dict, Any

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # type hint only — importing it here would be circular
    from ...adapters.indigo_data_provider import IndigoDataProvider
from .main import EntityIndex

# The attributes of each Indigo object the index searches or reports. A change
# to any of them makes the index stale; any other change (a device's states, a
# variable's value) does not, and must not cost a rebuild.
INDEX_FIELDS = {
    "device":       ("name", "folderId", "enabled", "description", "model",
                     "deviceTypeId", "pluginId"),
    "variable":     ("name", "folderId", "readOnly"),
    "action_group": ("name", "folderId", "description"),
}


def index_fields_changed(kind: str, orig: Any, new: Any) -> bool:
    """True when an update to an Indigo object touched something the entity
    index holds. Reads attributes only, so it is cheap enough for a callback
    that fires on every sensor event."""
    for field in INDEX_FIELDS[kind]:
        if getattr(orig, field, None) != getattr(new, field, None):
            return True
    return False


class EntityIndexManager:
    """Manages the entity index lifecycle and keeps it in step with Indigo."""
    
    def __init__(
        self,
        data_provider: "IndigoDataProvider",
        logger: Optional[logging.Logger] = None,
        update_interval: int = 300  # 5 minutes default
    ):
        """
        Initialise the entity index manager.

        Args:
            data_provider: Data provider for accessing entity data
            logger: Optional logger instance
            update_interval: Seconds between automatic updates (0 to disable)
        """
        self.data_provider = data_provider
        self.logger = logger or logging.getLogger("Plugin")
        self.update_interval = update_interval
        
        # Entity index instance
        self.entity_index: Optional[EntityIndex] = None
        
        # Background update thread
        self._update_thread = None
        self._warmup_thread = None
        self._stop_updates = threading.Event()
        self._running = False

        # Guards start/stop transitions so set()/clear() of _stop_updates
        # cannot interleave (a stop() landing mid-warmup must not have its
        # signal wiped by a concurrent clear()).
        self._lifecycle_lock = threading.Lock()
        
        # Track last update time for optimization
        self._last_update_time = 0

        # Coalesces out-of-band refreshes (refresh_async) so a burst of structural
        # mutations triggers at most one in-flight rebuild.
        self._refresh_lock = threading.Lock()
        self._refresh_pending = False
        # Handles for out-of-band refreshes, so stop() can join them before
        # closing the store rather than pulling it out from under them.
        self._refresh_threads = []
        # Set when a structural change lands during warmup, when there is no
        # store to refresh yet. Honoured once warmup completes.
        self._refresh_requested_during_warmup = False

        # Set from Indigo's own change callbacks (deviceCreated, a rename and
        # so on) and honoured by the next search. A plain bool: the callbacks
        # fire constantly on a busy estate, so marking must cost nothing.
        # Cleared at the START of every rebuild, so any rebuild that begins
        # after the change covers it, and a change landing mid-rebuild marks
        # the index again rather than being lost.
        self._dirty = False
        self._dirty_lock = threading.Lock()

        # One rebuild at a time. Warmup, the interval loop, refresh_async and
        # refresh_if_dirty all call update_now, and two of them overlapping
        # could finish out of order: the rebuild that read Indigo FIRST loaded
        # LAST and put the older picture back. Serialising them makes the
        # load order the read order.
        self._rebuild_lock = threading.Lock()
        # Generation numbers: _gen_started counts rebuilds begun, _gen_ok is
        # the number of the last one that succeeded. A caller that queued
        # behind a rebuild which STARTED after it asked has nothing left to do
        # (that rebuild read Indigo later than its request), unless the index
        # has been marked dirty since.
        self._gen_started = 0
        self._gen_ok = 0
    
    def start_async(self) -> None:
        """
        Create the index and run the initial load (an IOM walk of every
        device/variable/action) on a daemon thread, so MCPHandler.__init__
        does not block on it.

        After this returns, get_entity_index() returns a usable instance — but
        it may be empty until the background warmup completes. `is_running`
        stays False until then.

        Added in Claude Bridge v2.6.2 to fix the post-restart MCP latency where
        the IWS endpoint was routable but all calls timed out until the
        initial load completed.
        """
        if self._running:
            self.logger.debug("Entity index manager already running")
            return

        # Clear the stop flag before spawning the warmup worker — otherwise a
        # manager reused after stop() (which leaves the flag SET) would have
        # its warmup worker bail immediately and the index would silently stay
        # empty. Done under the lifecycle lock so it cannot race a stop().
        with self._lifecycle_lock:
            self._stop_updates.clear()

        try:
            # FAST: create the empty index. After this the entity_index
            # reference is live so SearchEntitiesHandler wiring works.
            self._initialize_entity_index()
        except Exception as e:
            self.logger.error(f"\t❌ Entity index async startup failed (init): {e}")
            raise

        def _worker() -> None:
            try:
                # Bail immediately if shutdown was requested before we started.
                if self._stop_updates.is_set():
                    return
                # SLOW: initial load. Runs in the background so
                # IWS requests are served immediately by the rest of the
                # plugin.
                self.update_now()
                if self._stop_updates.is_set():
                    return
                if self.update_interval > 0:
                    self._start_background_updates()
                self._running = True
                self.logger.info("\t📊 Entity index: initial warmup complete")
                # A structural change landed while we were warming up — the
                # index we just built is already behind. Rebuild once now
                # rather than leaving search wrong until the next interval.
                if self._refresh_requested_during_warmup:
                    self._refresh_requested_during_warmup = False
                    self.logger.debug("\t📊 Entity index: replaying a refresh "
                                      "requested during warmup")
                    self.refresh_async()
            except Exception as exc:
                self.logger.error(f"\t❌ Entity index warmup failed: {exc}")
                # Do NOT give up here. Without this, one failed rebuild left
                # search permanently empty and silent for the life of the plugin:
                # _running stayed False, no interval loop was ever started, and
                # any later refresh_async() just set a flag that nothing would
                # replay. The interval loop already guards each tick, so letting
                # it run means the next tick retries.
                if self.update_interval > 0 and not self._stop_updates.is_set():
                    try:
                        self._start_background_updates()
                        self._running = True
                        self.logger.warning(
                            f"\t📊 Entity index: warmup failed, retrying in "
                            f"{self.update_interval}s — search results will be "
                            f"incomplete until one succeeds"
                        )
                    except Exception as retry_exc:
                        self.logger.error(
                            f"\t❌ Entity index: could not schedule a retry after "
                            f"a failed warmup: {retry_exc}"
                        )

        # Store the handle on self so stop() can join it. Previously this was a
        # local, so a restart during warmup orphaned the thread (see stop()).
        self._warmup_thread = threading.Thread(
            target=_worker,
            name="EntityIndex-AsyncWarm",
            daemon=True,
        )
        self._warmup_thread.start()

    def stop(self) -> None:
        """Stop the entity index manager.

        Safe to call at ANY point, including while the async warmup thread is
        still in flight. The old `if not self._running: return` guard meant a
        restart that landed mid-warmup (the usual restart case, since _running
        is only set True AFTER warmup finishes) returned here without stopping
        anything — orphaning the EntityIndex-AsyncWarm daemon thread mid
        IOM-walk. Now we always signal then join, regardless of _running.
        """
        # Signal warmup AND the periodic loop to stop first, before checking
        # any running flag.
        self._stop_updates.set()
        self._running = False

        try:
            # Join the async warmup thread if still running. Bounded at 3s.
            # The IOM walk normally finishes well inside that, but it could
            # exceed the timeout on a very large install — so leave a
            # breadcrumb if the join expires (matching the project's
            # threaded-shutdown convention).
            if self._warmup_thread and self._warmup_thread.is_alive():
                self._warmup_thread.join(timeout=3.0)
                if self._warmup_thread.is_alive():
                    self.logger.warning(
                        "EntityIndex warmup did not stop within 3s during shutdown"
                    )

            # Stop the periodic background update thread.
            self._stop_background_updates()

            # Join any in-flight out-of-band refresh BEFORE closing the index —
            # otherwise entity_index is set to None underneath a thread that is
            # still inside update_now().
            with self._refresh_lock:
                refreshers = list(getattr(self, "_refresh_threads", []))
                self._refresh_threads = []
                self._refresh_pending = False
            for t in refreshers:
                if t.is_alive():
                    t.join(timeout=3.0)
                    if t.is_alive():
                        self.logger.warning(
                            "EntityIndex refresh did not stop within 3s during shutdown"
                        )

            # Close the index.
            if self.entity_index:
                self.entity_index.close()
                self.entity_index = None

        except Exception as e:
            self.logger.error(f"Error stopping entity index: {e}")
    
    def _initialize_entity_index(self) -> None:
        """Create the (empty) entity index."""
        try:
            self.entity_index = EntityIndex(logger=self.logger)
        except Exception as e:
            self.logger.error(f"\t❌ Entity index initialisation failed: {e}")
            raise
    
    def update_now(self) -> None:
        """Reload the index from Indigo now. Serialised (see _rebuild_lock);
        on any failure the index is marked dirty again so the next search
        retries rather than trusting it."""
        if not self.entity_index:
            self.logger.error("\t❌ Entity index not initialised")
            return

        ticket = self._gen_started
        with self._rebuild_lock:
            if self._gen_ok > ticket and not self._dirty:
                return          # a rebuild begun after this request already covered it
            self._gen_started += 1
            generation = self._gen_started
            try:
                self._rebuild()
            except Exception:
                self._dirty = True
                raise
            self._gen_ok = generation

    def _rebuild(self) -> None:
        """One rebuild. Call only with _rebuild_lock held."""
        index = self.entity_index
        if not index:
            raise RuntimeError("entity index closed during rebuild")
        try:
            self._dirty = False
            update_start = time.time()

            # Get all entity data
            self.logger.debug("\t📊 Entity index: synchronising...")
            entities = self.data_provider.get_all_entities_for_index()

            # Count entities
            device_count = len(entities["devices"])
            variable_count = len(entities["variables"])
            action_count = len(entities["actions"])
            total_entities = device_count + variable_count + action_count

            # Load the index
            index.load_entities(
                devices=entities["devices"],
                variables=entities["variables"],
                actions=entities["actions"]
            )

            self._last_update_time = time.time()
            elapsed = self._last_update_time - update_start

            self.logger.debug(f"\t📊 Entity index: synchronised {total_entities} entities ({device_count} devices, {variable_count} variables, {action_count} actions) in {elapsed:.1f}s")

        except Exception as e:
            self.logger.error(f"\t❌ Entity index update failed: {e}")
            raise
    
    def mark_dirty(self) -> None:
        """Note that the index no longer matches Indigo. O(1) and never raises:
        it runs on the plugin's device and variable callbacks."""
        self._dirty = True

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def refresh_if_dirty(self) -> bool:
        """Rebuild now if something changed since the last rebuild. Called by
        search before it reads the index, so a search never answers from an
        index Indigo has told us is out of date. Returns True when it rebuilt.

        Concurrent searches share one rebuild: the second waits on the lock
        and then finds the flag already clear. Before warmup has finished
        there is nothing to rebuild yet; warmup reads everything anyway."""
        if not self._dirty or not self._running or not self.entity_index:
            return False
        with self._dirty_lock:
            if not self._dirty:
                return False
            try:
                self.update_now()
            except Exception:
                # update_now logged it. Mark again so the next search retries
                # instead of trusting an index that failed to rebuild.
                self._dirty = True
                return False
            return True

    def refresh_async(self) -> None:
        """Trigger an out-of-band search-index rebuild WITHOUT blocking the caller.

        Called after a tool changes entity structure (create/delete/rename a
        device/variable/action) so search reflects the change immediately
        instead of waiting up to update_interval seconds. A
        whole-index rebuild is simple and cheap. Coalesced: a burst of
        mutations spawns at most one in-flight rebuild.
        """
        # A refresh requested DURING warmup used to be dropped outright
        # (_running only goes True after warmup completes), so a device created
        # in that window stayed invisible to search until the next periodic
        # rebuild. Remember it instead and let warmup pick it up.
        if self._stop_updates.is_set():
            return
        if not self._running or not self.entity_index:
            self._refresh_requested_during_warmup = True
            return
        with self._refresh_lock:
            if self._refresh_pending:
                return
            self._refresh_pending = True

        def _run():
            try:
                if self._stop_updates.is_set():
                    return
                self.update_now()
            except Exception:
                self.logger.exception("async search refresh failed (contained)")
            finally:
                with self._refresh_lock:
                    self._refresh_pending = False

        # Track the handle. It used to be discarded, so stop() could set
        # entity_index = None while this thread was still inside update_now().
        t = threading.Thread(target=_run, daemon=True, name="EntityIndex-Refresh")
        with self._refresh_lock:
            self._refresh_threads = [x for x in getattr(self, "_refresh_threads", [])
                                     if x.is_alive()]
            self._refresh_threads.append(t)
        t.start()

    def _start_background_updates(self) -> None:
        """Start background update thread."""
        # Never clear _stop_updates here — that would wipe a shutdown signal
        # set by a stop() that landed during warmup, resurrecting the periodic
        # loop the stop was meant to kill. The flag is cleared only in
        # start_async() under the lifecycle lock. If a stop has already
        # been requested, do not spawn the loop at all.
        if self._stop_updates.is_set():
            return

        if self._update_thread and self._update_thread.is_alive():
            return

        self._update_thread = threading.Thread(
            target=self._background_update_loop,
            daemon=True,
            name="EntityIndex-Update-Thread"
        )
        self._update_thread.start()
        
        # Background updates scheduled
    
    def _stop_background_updates(self) -> None:
        """Stop background update thread."""
        if not self._update_thread:
            return

        # Signal thread to stop
        self._stop_updates.set()

        # Wait for thread to finish
        if self._update_thread.is_alive():
            self._update_thread.join(timeout=5.0)
    
    def _background_update_loop(self) -> None:
        """Background update loop that runs in a separate thread."""
        while not self._stop_updates.is_set():
            try:
                # Wait for the update interval or stop signal
                if self._stop_updates.wait(timeout=self.update_interval):
                    break  # Stop signal received
                
                # Perform update
                self.update_now()
                
            except Exception as e:
                self.logger.error(f"Background update error: {e}")
                # Continue loop even if update fails
    
    def get_entity_index(self) -> Optional[EntityIndex]:
        """Get the entity index instance."""
        return self.entity_index
    
    def get_stats(self) -> Dict[str, Any]:
        """Get entity index statistics."""
        stats = {
            "running": self._running,
            "last_update": self._last_update_time,
            "update_interval": self.update_interval,
            "dirty": self._dirty,
        }

        if self.entity_index:
            try:
                stats.update(self.entity_index.get_stats())
            except Exception as e:
                self.logger.error(f"Error getting entity index stats: {e}")
                stats["error"] = str(e)
        
        return stats
    
    @property
    def is_running(self) -> bool:
        """Check if the entity index manager is running."""
        return self._running
