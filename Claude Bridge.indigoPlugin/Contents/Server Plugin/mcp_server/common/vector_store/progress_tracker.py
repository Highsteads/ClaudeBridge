"""
Progress tracking utility for vector operations and batch processing.
Provides structured progress reporting with percentages, ETA, and status indicators.
"""

import logging
import time
from typing import Optional

logger = logging.getLogger("Plugin")


class ProgressTracker:
    """Handles progress tracking and reporting for vector operations."""

    def __init__(self, stage: str, total: int, threshold: int = 10):
        """
        Initialize progress tracker.

        Args:
            stage: Name of the processing stage
            total: Total number of items to process
            threshold: Minimum items before showing progress (default 10)
        """
        self.stage = stage
        self.total = total
        self.threshold = threshold
        self.current = 0
        self.start_time = time.time()
        self.last_reported_percent = 0
        self.should_report_progress = total >= threshold

        if self.should_report_progress:
            logger.info(f"🚀 Starting {stage}: processing {total} items. Updates will be displayed every 10% until finished.")

    def update(self, current: int, operation: str = ""):
        """
        Update progress and report if needed.

        Args:
            current: Current item count
            operation: Optional description of current operation
        """
        self.current = current

        if not self.should_report_progress:
            return

        # Calculate progress percentage
        percent = int((current / self.total) * 100)

        # Report every 10% increment
        if percent >= self.last_reported_percent + 10 and percent <= 100:
            elapsed = time.time() - self.start_time
            rate = current / elapsed if elapsed > 0 else 0
            eta = (self.total - current) / rate if rate > 0 else 0

            progress_msg = f"📊 {self.stage} progress: {percent}% complete ({current}/{self.total})"
            if operation:
                progress_msg += f" - {operation}"
            if eta > 0 and eta < 300:  # Show ETA if less than 5 minutes
                progress_msg += f" (ETA: {eta:.0f}s)"
            elif rate > 0:
                progress_msg += f" ({rate:.1f} items/sec)"

            logger.info(progress_msg)
            self.last_reported_percent = percent

    def complete(self, operation: str = ""):
        """
        Mark stage as complete and show final summary.

        Args:
            operation: Optional description of completion
        """
        elapsed = time.time() - self.start_time

        if self.should_report_progress:
            rate = self.total / elapsed if elapsed > 0 else 0
            final_msg = (
                f"✅ {self.stage} completed: {self.total} items in {elapsed:.2f}s"
            )
            if rate > 0:
                final_msg += f" ({rate:.1f} items/sec)"
            if operation:
                final_msg += f" - {operation}"
            logger.info(final_msg)
        elif self.total > 0:
            # Single info notification for small datasets
            logger.info(
                f"✅ {self.stage}: processed {self.total} items ({elapsed:.2f}s)"
            )

    def error(self, message: str):
        """Report an error during processing."""
        elapsed = time.time() - self.start_time
        logger.error(f"❌ {self.stage} failed after {elapsed:.2f}s: {message}")


def create_progress_tracker(
    stage: str, total: int, threshold: int = 10
) -> ProgressTracker:
    """
    Create a progress tracker for vector operations.

    Args:
        stage: Name of the processing stage
        total: Total number of items to process
        threshold: Minimum items before showing progress updates

    Returns:
        ProgressTracker instance
    """
    return ProgressTracker(stage, total, threshold)