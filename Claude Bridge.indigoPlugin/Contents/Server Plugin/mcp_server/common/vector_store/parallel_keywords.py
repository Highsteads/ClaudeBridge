"""
Parallel keyword generation utilities for improved performance.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional, Callable

logger = logging.getLogger("Plugin")


def generate_keywords_parallel(
    entities: List[Dict[str, Any]], 
    batch_size: int,
    collection_name: str = "devices",
    progress_callback: Optional[Callable] = None,
    max_concurrent_batches: int = 3  # Conservative for keyword generation (completion API has lower limits)
) -> Dict[str, List[str]]:
    """
    Generate keywords using parallel batch processing for improved performance.
    
    Args:
        entities: List of entity dictionaries
        batch_size: Batch size for each LLM call
        collection_name: Type of entities being processed
        progress_callback: Optional progress callback function
        max_concurrent_batches: Maximum number of concurrent API calls
        
    Returns:
        Dictionary mapping entity IDs to lists of semantic keywords
    """
    if collection_name != "devices":
        # Only parallelize device keyword generation for now
        # Use sequential processing for non-devices
        return _generate_keywords_sequential_batch(entities, batch_size, collection_name, progress_callback)
    
    if len(entities) < 100:
        # For smaller sets, sequential might be faster due to setup overhead
        # Use sequential for small sets
        return _generate_keywords_sequential_batch(entities, batch_size, collection_name, progress_callback)
    
    # Start parallel keyword generation
    
    # Calculate total batches for progress tracking
    total_batches = (len(entities) + batch_size - 1) // batch_size
    
    # Prepare batch jobs
    batch_jobs = []
    for batch_num, batch_start in enumerate(range(0, len(entities), batch_size), 1):
        batch_end = min(batch_start + batch_size, len(entities))
        batch_entities = entities[batch_start:batch_end]
        
        batch_jobs.append({
            'batch_num': batch_num,
            'batch_entities': batch_entities,
            'collection_name': collection_name,
            'batch_size': batch_size
        })
    
    # Progress tracking for concurrent operations
    progress_lock = threading.Lock()
    all_keywords = {}
    
    def process_keyword_batch(batch_job):
        """Process a single batch of keyword generation."""
        from .semantic_keywords import _generate_llm_keywords_batch_with_fallback
        
        batch_num = batch_job['batch_num']
        batch_entities = batch_job['batch_entities']
        collection_name = batch_job['collection_name']
        batch_size = batch_job['batch_size']
        
        batch_start_time = time.time()
        # Process batch
        
        try:
            # Generate LLM keywords for this batch with fallback
            batch_keywords = _generate_llm_keywords_batch_with_fallback(batch_entities, collection_name, batch_size)
            
            batch_time = time.time() - batch_start_time
            success_count = len(batch_keywords)
            # Batch completed
            
            return {
                'success': True, 
                'batch_num': batch_num, 
                'keywords': batch_keywords,
                'success_count': success_count
            }
            
        except Exception as e:
            logger.error(f"❌ Parallel keyword batch {batch_num}/{total_batches} failed: {e}")
            return {
                'success': False, 
                'batch_num': batch_num, 
                'keywords': {},
                'error': str(e)
            }
    
    # Execute batches in parallel with error handling
    max_retries = 2  # Fewer retries for keyword generation
    base_delay = 2.0
    
    for attempt in range(max_retries):
        try:
            with ThreadPoolExecutor(max_workers=max_concurrent_batches) as executor:
                # Submit all batch jobs
                future_to_batch = {executor.submit(process_keyword_batch, batch_job): batch_job for batch_job in batch_jobs}
                
                # Collect results as they complete
                successful_batches = 0
                failed_batches = 0
                
                for future in as_completed(future_to_batch):
                    result = future.result()
                    
                    # Merge keywords from this batch
                    all_keywords.update(result['keywords'])
                    
                    # Update progress tracking
                    if result['success']:
                        successful_batches += 1
                    else:
                        failed_batches += 1
                    
                    # Report progress to callback
                    if progress_callback:
                        completed_count = successful_batches + failed_batches
                        # Keyword generation takes the first half of progress (0-50%)
                        keyword_progress = int((completed_count / total_batches) * 50)
                        progress_callback(keyword_progress, f"Parallel keyword generation - batch {completed_count}/{total_batches}")
                
                # Check if we had too many failures
                if failed_batches > total_batches // 2:  # More than 50% failed
                    raise Exception(f"Too many keyword batch failures: {failed_batches}/{total_batches} batches failed")
                
                # Parallel processing completed
                return all_keywords
                
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                # Retry on failure
                time.sleep(delay)
                # Reset progress for retry
                all_keywords = {}
            else:
                logger.error(f"❌ All {max_retries} parallel keyword attempts failed: {e}")
                # Fallback to sequential processing
                logger.info("🔄 Falling back to sequential keyword processing...")
                return _generate_keywords_sequential_batch(entities, batch_size, collection_name, progress_callback)
    
    return {}


def _generate_keywords_sequential_batch(
    entities: List[Dict[str, Any]], 
    batch_size: int,
    collection_name: str,
    progress_callback: Optional[Callable] = None
) -> Dict[str, List[str]]:
    """
    Generate keywords using sequential batch processing (fallback implementation).
    
    This is essentially the optimized batch processing from the original implementation.
    """
    from .semantic_keywords import _generate_llm_keywords_batch_with_fallback
    
    all_llm_keywords = {}
    total_batches = (len(entities) + batch_size - 1) // batch_size
    
    for batch_num, batch_start in enumerate(range(0, len(entities), batch_size), 1):
        batch_end = min(batch_start + batch_size, len(entities))
        batch_entities = entities[batch_start:batch_end]
        
        logger.debug(f"⚡ Processing sequential LLM batch {batch_num}/{total_batches} ({len(batch_entities)} devices)")
        
        # Generate LLM keywords for this batch with fallback
        batch_llm_keywords = _generate_llm_keywords_batch_with_fallback(batch_entities, collection_name, batch_size)
        all_llm_keywords.update(batch_llm_keywords)
        
        # Update progress for this batch with detailed messaging
        if progress_callback:
            # Keyword generation takes the first half of progress (0-50%)
            keyword_progress = int((batch_end / len(entities)) * 50)  # 50% max for keywords
            progress_callback(keyword_progress, f"Sequential keyword generation - batch {batch_num}/{total_batches}")
    
    return all_llm_keywords


def should_use_parallel_keywords(entity_count: int, min_threshold: int = 100) -> bool:
    """
    Determine if parallel keyword processing should be used.
    
    Args:
        entity_count: Number of entities to process
        min_threshold: Minimum number of entities to warrant parallel processing
        
    Returns:
        True if parallel processing should be used
    """
    # Use parallel processing for larger entity sets
    if entity_count < min_threshold:
        return False
    
    # Could add more logic here:
    # - Check current API rate limits
    # - Check system resources
    # - Check time of day (lower during peak hours)
    
    return True


def get_optimal_keyword_concurrency(entity_count: int, batch_count: int, max_concurrent: int = 3) -> int:
    """
    Calculate optimal concurrency level for keyword generation.
    
    Args:
        entity_count: Number of entities to process
        batch_count: Number of batches that will be created
        max_concurrent: Maximum allowed concurrent batches
        
    Returns:
        Optimal number of concurrent batches
    """
    # Conservative approach for keyword generation (completion API has stricter rate limits)
    if batch_count <= 2:
        return 1  # No need for parallel processing
    elif batch_count <= 5:
        return 2
    elif batch_count <= 10:
        return 3
    else:
        return min(max_concurrent, max(2, batch_count // 3))  # Scale with batch count but be conservative