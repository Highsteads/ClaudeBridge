"""
Centralized vector store management for the MCP server.
Handles initialization, updates, and background synchronization.
"""

import logging
import os
import threading
import time
from typing import Optional, Dict, Any

from ...adapters.data_provider import DataProvider
from ...adapters.vector_store_interface import VectorStoreInterface
from .main import VectorStore


class VectorStoreManager:
    """Manages vector store lifecycle and keeps it synchronized with Indigo entities."""
    
    def __init__(
        self,
        data_provider: DataProvider,
        db_path: str,
        logger: Optional[logging.Logger] = None,
        update_interval: int = 300  # 5 minutes default
    ):
        """
        Initialize the vector store manager.
        
        Args:
            data_provider: Data provider for accessing entity data
            db_path: Path to the vector database
            logger: Optional logger instance
            update_interval: Seconds between automatic updates (0 to disable)
        """
        self.data_provider = data_provider
        self.db_path = db_path
        self.logger = logger or logging.getLogger("Plugin")
        self.update_interval = update_interval
        
        # Vector store instance
        self.vector_store: Optional[VectorStoreInterface] = None
        
        # Background update thread
        self._update_thread = None
        self._stop_updates = threading.Event()
        self._running = False
        
        # Track last update time for optimization
        self._last_update_time = 0
        
        # Progress tracking for initialization
        self._is_initializing = False
    
    def start(self) -> None:
        """Start the vector store manager."""
        if self._running:
            self.logger.debug("Vector store manager already running")
            return

        try:
            self._is_initializing = True

            # Initialize vector store
            self._initialize_vector_store()

            # Perform initial update
            self.update_now()

            # Start background updates if enabled
            if self.update_interval > 0:
                self._start_background_updates()

            self._running = True
            self._is_initializing = False

        except Exception as e:
            self._is_initializing = False
            self.logger.error(f"\t❌ Vector store startup failed: {e}")
            raise
    
    def stop(self) -> None:
        """Stop the vector store manager."""
        if not self._running:
            return

        try:
            self._running = False

            # Stop background updates
            self._stop_background_updates()

            # Close vector store
            if self.vector_store:
                self.vector_store.close()
                self.vector_store = None

        except Exception as e:
            self.logger.error(f"Error stopping vector store: {e}")
    
    def _initialize_vector_store(self) -> None:
        """Initialize the vector store."""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

            # Create vector store instance
            self.logger.info("\t📊 Vector store: initializing...")
            self.vector_store = VectorStore(self.db_path, logger=self.logger)
            self.logger.info("\t📊 Vector store: database connected")

        except Exception as e:
            self.logger.error(f"\t❌ Vector store initialization failed: {e}")
            raise
    
    def update_now(self) -> None:
        """Perform an immediate vector store update with progress tracking."""
        if not self.vector_store:
            self.logger.error("\t❌ Vector store not initialized")
            return

        try:
            update_start = time.time()

            # Get all entity data
            self.logger.info("\t📊 Vector store: synchronizing...")
            entities = self.data_provider.get_all_entities_for_vector_store()

            # Count entities
            device_count = len(entities["devices"])
            variable_count = len(entities["variables"])
            action_count = len(entities["actions"])
            total_entities = device_count + variable_count + action_count

            # Update vector store
            self.vector_store.update_embeddings(
                devices=entities["devices"],
                variables=entities["variables"],
                actions=entities["actions"]
            )

            self._last_update_time = time.time()
            elapsed = self._last_update_time - update_start

            self.logger.info(f"\t📊 Vector store: synchronized {total_entities} entities ({device_count} devices, {variable_count} variables, {action_count} actions) in {elapsed:.1f}s")

        except Exception as e:
            self.logger.error(f"\t❌ Vector store update failed: {e}")
            raise
    
    def _start_background_updates(self) -> None:
        """Start background update thread."""
        if self._update_thread and self._update_thread.is_alive():
            return
        
        self._stop_updates.clear()
        self._update_thread = threading.Thread(
            target=self._background_update_loop,
            daemon=True,
            name="VectorStore-Update-Thread"
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
    
    def get_vector_store(self) -> Optional[VectorStoreInterface]:
        """Get the vector store instance."""
        return self.vector_store
    
    def get_stats(self) -> Dict[str, Any]:
        """Get vector store statistics."""
        stats = {
            "running": self._running,
            "last_update": self._last_update_time,
            "update_interval": self.update_interval,
            "database_path": self.db_path
        }
        
        if self.vector_store:
            try:
                vector_stats = self.vector_store.get_stats()
                stats.update(vector_stats)
            except Exception as e:
                self.logger.error(f"Error getting vector store stats: {e}")
                stats["error"] = str(e)
        
        return stats
    
    @property
    def is_running(self) -> bool:
        """Check if the vector store manager is running."""
        return self._running
    
    
    def set_update_interval(self, interval: int) -> None:
        """
        Change the update interval.
        
        Args:
            interval: New update interval in seconds (0 to disable)
        """
        if interval == self.update_interval:
            return
        
        old_interval = self.update_interval
        self.update_interval = interval
        
        # Restart background updates with new interval
        if self._running:
            self._stop_background_updates()
            if interval > 0:
                self._start_background_updates()
        
        self.logger.info(f"Update interval changed from {old_interval}s to {interval}s")