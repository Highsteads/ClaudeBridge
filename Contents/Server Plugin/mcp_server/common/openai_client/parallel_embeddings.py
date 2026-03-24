"""
Parallel embedding generation utilities for improved performance.
"""

import logging
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Callable

logger = logging.getLogger("Plugin")


def emb_texts_batch_parallel(texts: List[str], entity_names: List[str] = None, progress_callback: Callable = None, max_concurrent_batches: int = 4) -> List[List[float]]:
    """
    Get embeddings using parallel batch processing for improved performance.
    
    Args:
        texts: List of texts to embed
        entity_names: Optional entity names for logging
        progress_callback: Optional progress callback function
        max_concurrent_batches: Maximum number of concurrent API calls
        
    Returns:
        List of embedding vectors (empty list for failed embeddings)
    """
    from .main import _get_embedding_client
    
    if not texts or len(texts) == 0:
        logger.warning("⚠️ Empty text list provided for parallel batch embedding, returning empty list")
        return []

    # Filter out empty texts and keep track of original indices
    valid_texts = []
    valid_indices = []
    for i, text in enumerate(texts):
        if text and text.strip():
            valid_texts.append(text.strip())
            valid_indices.append(i)
    
    if not valid_texts:
        logger.warning("⚠️ No valid texts provided for parallel batch embedding, returning empty list")
        return [[] for _ in texts]

    batch_size = min(len(valid_texts), 100)  # Conservative batch size
    embeddings_result = [[] for _ in texts]  # Initialize with empty embeddings
    
    # Calculate total batches for progress tracking
    total_batches = (len(valid_texts) + batch_size - 1) // batch_size
    
    # Prepare batch data
    batch_jobs = []
    for batch_num, i in enumerate(range(0, len(valid_texts), batch_size), 1):
        batch_texts = valid_texts[i:i + batch_size]
        batch_indices = valid_indices[i:i + batch_size]
        
        # Get entity names for this batch if provided
        batch_entity_names = []
        if entity_names:
            for idx in batch_indices:
                if idx < len(entity_names) and entity_names[idx]:
                    batch_entity_names.append(entity_names[idx])
        
        batch_jobs.append({
            'batch_num': batch_num,
            'batch_texts': batch_texts,
            'batch_indices': batch_indices,
            'batch_entity_names': batch_entity_names
        })
    
    # Start parallel embedding processing
    
    # Progress tracking for concurrent operations
    progress_lock = threading.Lock()
    
    def process_batch(batch_job):
        """Process a single batch of embeddings."""
        batch_num = batch_job['batch_num']
        batch_texts = batch_job['batch_texts']
        batch_indices = batch_job['batch_indices']
        batch_entity_names = batch_job['batch_entity_names']
        
        batch_start_time = time.time()
        
        # Debug log before API call
        if batch_entity_names:
            entity_list = ", ".join(batch_entity_names[:5])
            if len(batch_entity_names) > 5:
                entity_list += f" (+{len(batch_entity_names) - 5} more)"
            # Process parallel batch
        else:
            # Process parallel batch
            pass
        try:
            client = _get_embedding_client()
            model = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
            
            # Add timeout to prevent hanging
            response = client.embeddings.create(
                model=model, 
                input=batch_texts, 
                timeout=60.0
            )

            # Validate response structure
            if not response or not response.data or len(response.data) != len(batch_texts):
                raise ValueError(f"Invalid response: expected {len(batch_texts)} embeddings, got {len(response.data) if response.data else 0}")

            # Prepare results for this batch
            batch_results = []
            for j, embedding_data in enumerate(response.data):
                original_index = batch_indices[j]
                embedding = embedding_data.embedding
                if not embedding or len(embedding) == 0:
                    logger.warning(f"Empty embedding returned for text at index {original_index}")
                    batch_results.append((original_index, []))
                else:
                    batch_results.append((original_index, embedding))
            
            batch_time = time.time() - batch_start_time
            # Batch completed
            
            return {'success': True, 'batch_num': batch_num, 'results': batch_results}
            
        except Exception as e:
            logger.error(f"❌ Parallel batch {batch_num}/{total_batches} failed: {e}")
            # Return empty embeddings for failed batch
            empty_results = [(idx, []) for idx in batch_indices]
            return {'success': False, 'batch_num': batch_num, 'results': empty_results, 'error': str(e)}
    
    # Execute batches in parallel with error handling
    max_retries = 3
    base_delay = 1.0
    
    for attempt in range(max_retries):
        try:
            with ThreadPoolExecutor(max_workers=max_concurrent_batches) as executor:
                # Submit all batch jobs
                future_to_batch = {executor.submit(process_batch, batch_job): batch_job for batch_job in batch_jobs}
                
                # Collect results as they complete
                successful_batches = 0
                failed_batches = 0
                
                for future in as_completed(future_to_batch):
                    result = future.result()
                    
                    # Map results back to original indices
                    for original_index, embedding in result['results']:
                        embeddings_result[original_index] = embedding
                    
                    # Update progress tracking
                    if result['success']:
                        successful_batches += 1
                    else:
                        failed_batches += 1
                    
                    # Report progress to callback
                    if progress_callback:
                        completed_count = successful_batches + failed_batches
                        progress_callback(completed_count, total_batches, len(result['results']))
                
                # Check if we had too many failures
                if failed_batches > total_batches // 2:  # More than 50% failed
                    raise Exception(f"Too many batch failures: {failed_batches}/{total_batches} batches failed")
                
                logger.debug(f"✅ Parallel embedding processing completed: {successful_batches} successful, {failed_batches} failed out of {total_batches} batches")
                return embeddings_result
                
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"⚠️ Parallel embedding attempt {attempt + 1}/{max_retries} failed: {e}, retrying in {delay:.1f}s...")
                time.sleep(delay)
                # Reset progress for retry
                embeddings_result = [[] for _ in texts]
            else:
                logger.error(f"❌ All {max_retries} parallel embedding attempts failed: {e}")
                # Return empty embeddings - caller can fallback to sequential
                return [[] for _ in texts]
    
    return [[] for _ in texts]


def should_use_parallel_processing(text_count: int, min_threshold: int = 50) -> bool:
    """
    Determine if parallel processing should be used based on text count and system conditions.
    
    Args:
        text_count: Number of texts to process
        min_threshold: Minimum number of texts to warrant parallel processing
        
    Returns:
        True if parallel processing should be used
    """
    # Use parallel processing for larger batches
    if text_count < min_threshold:
        return False
    
    # Could add more sophisticated logic here:
    # - Check system resources
    # - Check API rate limits
    # - Check current load
    
    return True


def get_optimal_concurrency(text_count: int, max_concurrent: int = 6) -> int:
    """
    Calculate optimal concurrency level based on text count and constraints.
    
    Args:
        text_count: Number of texts to process
        max_concurrent: Maximum allowed concurrent batches
        
    Returns:
        Optimal number of concurrent batches
    """
    # Scale concurrency with data size but respect limits
    if text_count < 100:
        return 2
    elif text_count < 500:
        return 3
    elif text_count < 1000:
        return 4
    else:
        return min(max_concurrent, max(2, text_count // 200))