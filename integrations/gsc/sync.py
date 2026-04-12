"""
Google Search Console data synchronization logic.

This module provides incremental data synchronization functionality
for GSC metrics, including conflict resolution, batch processing,
and sync state management.
"""

import asyncio
from datetime import date, datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple, Set
from uuid import UUID

import structlog
from sqlalchemy import select, and_, or_, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.connection import get_database_manager
from db.models import GSCMetric, Site, AuditLog, ActionType, EntityType
from .client import GSCClient, GSCAPIError, GSCQuotaExceededError
from .models import GSCSyncConfig, GSCDimension
from .transformers import GSCTransformer, GSCTransformationError

logger = structlog.get_logger(__name__)


class GSCSyncError(Exception):
    """GSC synchronization error."""
    pass


class GSCSync:
    """
    Google Search Console data synchronization manager.
    
    Handles incremental data synchronization, conflict resolution,
    and batch processing for GSC metrics data.
    """
    
    def __init__(
        self,
        gsc_client: GSCClient,
        sync_config: GSCSyncConfig,
        transformer: Optional[GSCTransformer] = None
    ):
        self.client = gsc_client
        self.config = sync_config
        self.transformer = transformer or GSCTransformer(validate_data=True)
        self._db_manager = get_database_manager()
        
        # Sync state tracking
        self._sync_stats = {
            'total_sites': 0,
            'successful_sites': 0,
            'failed_sites': 0,
            'total_records_fetched': 0,
            'total_records_inserted': 0,
            'total_records_updated': 0,
            'sync_start_time': None,
            'sync_end_time': None
        }
    
    async def sync_all_sites(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        site_ids: Optional[List[UUID]] = None
    ) -> Dict[str, Any]:
        """
        Synchronize GSC data for all or specified sites.
        
        Args:
            start_date: Override start date for sync
            end_date: Override end date for sync  
            site_ids: Specific site IDs to sync (None for all)
            
        Returns:
            Sync results and statistics
            
        Raises:
            GSCSyncError: On synchronization errors
        """
        self._sync_stats['sync_start_time'] = datetime.utcnow()
        
        logger.info(
            "Starting GSC data synchronization",
            start_date=start_date,
            end_date=end_date,
            site_filter=site_ids is not None,
            site_count=len(site_ids) if site_ids else "all"
        )
        
        try:
            # Get sites to sync
            sites = await self._get_sites_for_sync(site_ids)
            self._sync_stats['total_sites'] = len(sites)
            
            if not sites:
                logger.warning("No sites found for GSC synchronization")
                return self._get_sync_results()
            
            # Sync sites with concurrency control
            semaphore = asyncio.Semaphore(self.config.concurrent_requests)
            sync_tasks = [
                self._sync_site_with_semaphore(semaphore, site, start_date, end_date)
                for site in sites
            ]
            
            site_results = await asyncio.gather(*sync_tasks, return_exceptions=True)
            
            # Process results
            for i, result in enumerate(site_results):
                if isinstance(result, Exception):
                    self._sync_stats['failed_sites'] += 1
                    logger.error(
                        "Site sync failed",
                        site_id=sites[i]['id'],
                        site_url=sites[i]['primary_domain'],
                        error=str(result)
                    )
                else:
                    self._sync_stats['successful_sites'] += 1
                    if result:
                        self._sync_stats['total_records_fetched'] += result.get('fetched', 0)
                        self._sync_stats['total_records_inserted'] += result.get('inserted', 0)
                        self._sync_stats['total_records_updated'] += result.get('updated', 0)
            
            self._sync_stats['sync_end_time'] = datetime.utcnow()
            
            # Log audit entry
            await self._log_sync_audit()
            
            return self._get_sync_results()
            
        except Exception as e:
            self._sync_stats['sync_end_time'] = datetime.utcnow()
            logger.error(
                "GSC synchronization failed",
                error=str(e),
                sync_stats=self._sync_stats
            )
            raise GSCSyncError(f"GSC sync failed: {e}")
    
    async def _sync_site_with_semaphore(
        self,
        semaphore: asyncio.Semaphore,
        site: Dict[str, Any],
        start_date: Optional[date],
        end_date: Optional[date]
    ) -> Dict[str, Any]:
        """Sync single site with semaphore-controlled concurrency."""
        async with semaphore:
            return await self.sync_site(
                site_id=site['id'],
                site_url=site['primary_domain'],
                start_date=start_date,
                end_date=end_date
            )
    
    async def sync_site(
        self,
        site_id: UUID,
        site_url: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        dimensions: Optional[List[GSCDimension]] = None
    ) -> Dict[str, Any]:
        """
        Synchronize GSC data for a single site.
        
        Args:
            site_id: Site UUID
            site_url: GSC property URL
            start_date: Override start date
            end_date: Override end date
            dimensions: GSC dimensions to fetch
            
        Returns:
            Sync results for the site
            
        Raises:
            GSCSyncError: On synchronization errors
        """
        logger.info(
            "Starting GSC site synchronization",
            site_id=site_id,
            site_url=site_url,
            start_date=start_date,
            end_date=end_date
        )
        
        site_stats = {
            'fetched': 0,
            'inserted': 0,
            'updated': 0,
            'errors': 0
        }
        
        try:
            # Determine sync date range
            sync_start, sync_end = await self._get_sync_date_range(
                site_id, start_date, end_date
            )
            
            logger.info(
                "GSC sync date range determined",
                site_id=site_id,
                sync_start=sync_start,
                sync_end=sync_end
            )
            
            # Verify property access
            has_access = await self.client.verify_property_access(site_url)
            if not has_access:
                raise GSCSyncError(f"No access to GSC property: {site_url}")
            
            # Fetch and process data in date batches
            current_date = sync_start
            while current_date <= sync_end:
                batch_end = min(
                    current_date + timedelta(days=self.config.batch_size_days - 1),
                    sync_end
                )
                
                try:
                    batch_stats = await self._sync_date_batch(
                        site_id=site_id,
                        site_url=site_url,
                        start_date=current_date,
                        end_date=batch_end,
                        dimensions=dimensions
                    )
                    
                    # Update stats
                    for key in batch_stats:
                        site_stats[key] = site_stats.get(key, 0) + batch_stats[key]
                    
                except GSCQuotaExceededError as e:
                    logger.warning(
                        "GSC quota exceeded during site sync",
                        site_id=site_id,
                        current_batch_date=current_date,
                        error=str(e)
                    )
                    # Stop syncing this site, but don't fail completely
                    break
                except Exception as e:
                    site_stats['errors'] += 1
                    logger.error(
                        "Batch sync failed",
                        site_id=site_id,
                        batch_start=current_date,
                        batch_end=batch_end,
                        error=str(e)
                    )
                    
                    if not self.config.skip_invalid_rows:
                        raise
                
                # Move to next batch
                current_date = batch_end + timedelta(days=1)
            
            # Update last sync timestamp
            await self._update_last_sync_time(site_id, sync_end)
            
            logger.info(
                "Completed GSC site synchronization",
                site_id=site_id,
                stats=site_stats
            )
            
            return site_stats
            
        except Exception as e:
            logger.error(
                "GSC site sync failed",
                site_id=site_id,
                site_url=site_url,
                error=str(e)
            )
            raise GSCSyncError(f"Site sync failed for {site_url}: {e}")
    
    async def _sync_date_batch(
        self,
        site_id: UUID,
        site_url: str,
        start_date: date,
        end_date: date,
        dimensions: Optional[List[GSCDimension]] = None
    ) -> Dict[str, int]:
        """
        Synchronize GSC data for a date range batch.
        
        Args:
            site_id: Site UUID
            site_url: GSC property URL
            start_date: Batch start date
            end_date: Batch end date
            dimensions: GSC dimensions
            
        Returns:
            Batch sync statistics
        """
        logger.debug(
            "Processing GSC date batch",
            site_id=site_id,
            start_date=start_date,
            end_date=end_date
        )
        
        batch_stats = {'fetched': 0, 'inserted': 0, 'updated': 0, 'errors': 0}
        
        # Fetch data from GSC API
        metrics_batch = []
        async for metric_data in self.client.fetch_search_analytics(
            site_id=site_id,
            site_url=site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=dimensions
        ):
            metrics_batch.append(metric_data)
            batch_stats['fetched'] += 1
            
            # Process in smaller batches for memory efficiency
            if len(metrics_batch) >= self.config.batch_insert_size:
                insert_stats = await self._process_metrics_batch(
                    site_id, metrics_batch
                )
                batch_stats['inserted'] += insert_stats['inserted']
                batch_stats['updated'] += insert_stats['updated']
                batch_stats['errors'] += insert_stats['errors']
                metrics_batch.clear()
        
        # Process remaining metrics
        if metrics_batch:
            insert_stats = await self._process_metrics_batch(
                site_id, metrics_batch
            )
            batch_stats['inserted'] += insert_stats['inserted']
            batch_stats['updated'] += insert_stats['updated'] 
            batch_stats['errors'] += insert_stats['errors']
        
        logger.debug(
            "Completed GSC date batch",
            site_id=site_id,
            start_date=start_date,
            end_date=end_date,
            stats=batch_stats
        )
        
        return batch_stats
    
    async def _process_metrics_batch(
        self,
        site_id: UUID,
        metrics_data: List[Any]
    ) -> Dict[str, int]:
        """
        Process and store a batch of GSC metrics in the database.
        
        Args:
            site_id: Site UUID
            metrics_data: List of GSCMetricData objects
            
        Returns:
            Processing statistics
        """
        if not metrics_data:
            return {'inserted': 0, 'updated': 0, 'errors': 0}
        
        stats = {'inserted': 0, 'updated': 0, 'errors': 0}
        
        try:
            # Transform to GSCMetric models
            gsc_metrics = []
            for metric_data in metrics_data:
                try:
                    # Note: The metric_data should already have site_id, date, url, etc.
                    # This is a simplified version - in practice you'd extract these
                    # from the metric_data appropriately
                    gsc_metric = self.transformer.transform_to_gsc_metric(
                        metric_data=metric_data,
                        site_id=site_id,
                        date=metric_data.date,  # Assuming these fields exist
                        url=metric_data.url,
                        query=getattr(metric_data, 'query', None),
                        country=getattr(metric_data, 'country', None),
                        device=getattr(metric_data, 'device', None)
                    )
                    gsc_metrics.append(gsc_metric)
                    
                except GSCTransformationError as e:
                    stats['errors'] += 1
                    logger.error(
                        "Metric transformation failed",
                        error=str(e),
                        site_id=site_id
                    )
                    if not self.config.skip_invalid_rows:
                        raise
            
            if not gsc_metrics:
                return stats
            
            # Perform upsert operation
            upsert_stats = await self._upsert_metrics_batch(gsc_metrics)
            stats['inserted'] = upsert_stats['inserted']
            stats['updated'] = upsert_stats['updated']
            
        except Exception as e:
            logger.error(
                "Metrics batch processing failed",
                error=str(e),
                site_id=site_id,
                batch_size=len(metrics_data)
            )
            stats['errors'] += len(metrics_data)
            if not self.config.skip_invalid_rows:
                raise
        
        return stats
    
    async def _upsert_metrics_batch(
        self,
        gsc_metrics: List[GSCMetric]
    ) -> Dict[str, int]:
        """
        Perform batch upsert of GSC metrics with conflict resolution.
        
        Args:
            gsc_metrics: List of GSCMetric model instances
            
        Returns:
            Upsert statistics (inserted/updated counts)
        """
        if not gsc_metrics:
            return {'inserted': 0, 'updated': 0}
        
        stats = {'inserted': 0, 'updated': 0}
        
        async with self._db_manager.get_session() as session:
            try:
                # Prepare data for upsert
                metric_dicts = []
                for metric in gsc_metrics:
                    metric_dict = metric.__dict__.copy()
                    # Remove SQLAlchemy instance state
                    metric_dict.pop('_sa_instance_state', None)
                    # Ensure UUID fields are properly handled
                    if 'id' in metric_dict and metric_dict['id'] is None:
                        metric_dict.pop('id')  # Let database generate
                    metric_dicts.append(metric_dict)
                
                # PostgreSQL upsert with conflict resolution
                stmt = insert(GSCMetric).values(metric_dicts)
                
                # Define conflict resolution (update on unique constraint violation)
                conflict_columns = ['site_id', 'date', 'url', 'query', 'country', 'device']
                update_dict = {
                    'clicks': stmt.excluded.clicks,
                    'impressions': stmt.excluded.impressions,
                    'ctr': stmt.excluded.ctr,
                    'position': stmt.excluded.position,
                    'updated_at': text('CURRENT_TIMESTAMP')
                }
                
                upsert_stmt = stmt.on_conflict_do_update(
                    index_elements=conflict_columns,
                    set_=update_dict
                )
                
                # Execute upsert and get affected row counts
                result = await session.execute(upsert_stmt)
                await session.commit()
                
                # Note: PostgreSQL doesn't directly return insert/update counts
                # This is a simplified approach - in practice you might want to
                # track this more precisely
                total_processed = len(metric_dicts)
                stats['inserted'] = total_processed  # Approximate
                
                logger.debug(
                    "Batch upsert completed",
                    total_metrics=total_processed,
                    stats=stats
                )
                
            except Exception as e:
                await session.rollback()
                logger.error(
                    "Batch upsert failed",
                    error=str(e),
                    batch_size=len(gsc_metrics)
                )
                raise
        
        return stats
    
    async def _get_sites_for_sync(
        self, 
        site_ids: Optional[List[UUID]] = None
    ) -> List[Dict[str, Any]]:
        """Get sites that should be synchronized."""
        async with self._db_manager.get_session() as session:
            query = select(
                Site.id,
                Site.primary_domain, 
                Site.cms_type,
                Site.status
            ).where(
                Site.status == 'active'  # Only sync active sites
            )
            
            if site_ids:
                query = query.where(Site.id.in_(site_ids))
            
            result = await session.execute(query)
            sites = [dict(row._mapping) for row in result]
            
            logger.info(
                "Retrieved sites for GSC sync",
                total_sites=len(sites),
                filtered=site_ids is not None
            )
            
            return sites
    
    async def _get_sync_date_range(
        self,
        site_id: UUID,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> Tuple[date, date]:
        """
        Determine the date range for synchronization.
        
        Args:
            site_id: Site UUID
            start_date: Override start date
            end_date: Override end date
            
        Returns:
            Tuple of (start_date, end_date)
        """
        if end_date is None:
            # GSC data has 2-3 day delay
            end_date = date.today() - timedelta(days=self.client.config.data_delay_days)
        
        if start_date is None and self.config.incremental_sync:
            # Get last successful sync date
            last_sync_date = await self._get_last_sync_date(site_id)
            
            if last_sync_date:
                # Start from last sync with overlap for data updates
                start_date = last_sync_date - timedelta(days=self.config.backfill_days)
            else:
                # First sync - start with recent data
                start_date = end_date - timedelta(days=30)  # Last 30 days
        elif start_date is None:
            # Full historical sync
            max_days = self.client.config.max_historical_days
            start_date = end_date - timedelta(days=max_days)
        
        # Ensure date range is valid
        if start_date > end_date:
            start_date = end_date
        
        return start_date, end_date
    
    async def _get_last_sync_date(self, site_id: UUID) -> Optional[date]:
        """Get the last successful sync date for a site."""
        async with self._db_manager.get_session() as session:
            # Get the most recent GSC metric date for this site
            query = select(GSCMetric.date).where(
                GSCMetric.site_id == site_id
            ).order_by(GSCMetric.date.desc()).limit(1)
            
            result = await session.execute(query)
            last_date = result.scalar_one_or_none()
            
            return last_date
    
    async def _update_last_sync_time(self, site_id: UUID, sync_date: date) -> None:
        """Update the last sync timestamp for a site."""
        # This could be stored in a separate sync_status table
        # For now, we'll log it in the audit log
        async with self._db_manager.get_session() as session:
            audit_entry = AuditLog(
                action_type=ActionType.DATA_SYNC,
                entity_type=EntityType.SITE,
                entity_id=site_id,
                details={
                    'sync_type': 'gsc_search_analytics',
                    'sync_date': sync_date.isoformat(),
                    'sync_timestamp': datetime.utcnow().isoformat()
                },
                status='completed'
            )
            
            session.add(audit_entry)
            await session.commit()
    
    async def _log_sync_audit(self) -> None:
        """Log sync operation in audit log."""
        async with self._db_manager.get_session() as session:
            audit_entry = AuditLog(
                action_type=ActionType.DATA_SYNC,
                entity_type=EntityType.SITE,
                entity_id=None,  # Global sync operation
                details={
                    'sync_type': 'gsc_bulk_sync',
                    'stats': self._sync_stats
                },
                status='completed' if self._sync_stats['failed_sites'] == 0 else 'partial_failure'
            )
            
            session.add(audit_entry)
            await session.commit()
    
    def _get_sync_results(self) -> Dict[str, Any]:
        """Get formatted sync results."""
        stats = self._sync_stats.copy()
        
        # Calculate duration
        if stats['sync_start_time'] and stats['sync_end_time']:
            duration = stats['sync_end_time'] - stats['sync_start_time']
            stats['duration_seconds'] = duration.total_seconds()
        
        # Calculate rates
        if stats['total_sites'] > 0:
            stats['success_rate'] = (
                stats['successful_sites'] / stats['total_sites'] * 100
            )
        else:
            stats['success_rate'] = 0.0
        
        return stats
    
    async def cleanup(self):
        """Cleanup sync resources."""
        # Close database connections if needed
        logger.info("GSC sync cleanup completed")