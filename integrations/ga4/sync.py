"""
Google Analytics 4 incremental synchronization.

This module provides functionality for incremental GA4 data synchronization,
handling data processing delays, upsert operations, and sync state tracking.
"""

import asyncio
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple, AsyncGenerator
from uuid import UUID

import structlog
from sqlalchemy import select, and_, or_, desc, func, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.connection import get_database_manager
from db.models import GA4Metric, Site, AuditLog, ActionType, EntityType

from .client import GA4Client
from .models import GA4Config, GA4SyncConfig, GA4MetricData
from .transformers import GA4DataTransformer

logger = structlog.get_logger(__name__)


class GA4SyncError(Exception):
    """GA4 synchronization specific errors."""
    pass


class GA4Sync:
    """
    GA4 data synchronization with incremental updates and state tracking.
    
    Handles the complexities of GA4 data processing delays (24-48h),
    provides upsert functionality, and tracks sync state per property.
    """
    
    def __init__(
        self,
        client: GA4Client,
        transformer: Optional[GA4DataTransformer] = None
    ):
        self.client = client
        self.transformer = transformer or GA4DataTransformer()
        
        # GA4 data processing delays
        self.processing_delay_days = 2  # GA4 data is typically 24-48h delayed
        self.lookback_days = 7  # How many days to re-sync for corrections
    
    async def sync_property_data(
        self,
        config: GA4SyncConfig,
        session: Optional[AsyncSession] = None
    ) -> Dict[str, int]:
        """
        Synchronize GA4 data for a property with incremental updates.
        
        Args:
            config: Sync configuration
            session: Database session (creates new if None)
            
        Returns:
            Dict with sync statistics
            
        Raises:
            GA4SyncError: If synchronization fails
        """
        logger.info("Starting GA4 property data sync",
                  property_id=config.property_id, 
                  site_id=str(config.site_id),
                  organic_only=config.organic_only)
        
        stats = {
            'fetched': 0,
            'inserted': 0,
            'updated': 0,
            'skipped': 0,
            'errors': 0
        }
        
        async with get_async_session() if session is None else session as db_session:
            try:
                # Determine date range for sync
                start_date, end_date = await self._determine_sync_date_range(
                    config, db_session
                )
                
                logger.info("Determined GA4 sync date range",
                          property_id=config.property_id,
                          start_date=start_date,
                          end_date=end_date)
                
                # Fetch data from GA4 API
                raw_metrics = await self.client.fetch_organic_sessions(
                    property_id=config.property_id,
                    site_id=config.site_id,
                    start_date=start_date,
                    end_date=end_date
                )
                
                stats['fetched'] = len(raw_metrics)
                
                if not raw_metrics:
                    logger.info("No GA4 data found for date range",
                              property_id=config.property_id)
                    return stats
                
                # Apply filtering if requested
                if config.organic_only:
                    raw_metrics = self.transformer.filter_organic_traffic(raw_metrics)
                    logger.info("Filtered for organic traffic only",
                              organic_count=len(raw_metrics))
                
                # Filter by minimum sessions
                if config.min_sessions > 0:
                    raw_metrics = [m for m in raw_metrics if m.sessions >= config.min_sessions]
                    logger.info("Filtered by minimum sessions",
                              min_sessions=config.min_sessions,
                              remaining_count=len(raw_metrics))
                
                # Aggregate data if needed
                aggregated_metrics = self.transformer.aggregate_daily_metrics(raw_metrics)
                
                # Batch upsert data
                batch_stats = await self._upsert_metrics_batch(
                    aggregated_metrics, config.batch_size, db_session
                )
                
                stats.update(batch_stats)
                
                # Update sync state
                await self._update_sync_state(config, end_date, db_session)
                
                # Log audit entry
                await self._log_sync_audit(config, stats, db_session)
                
                await db_session.commit()
                
                logger.info("GA4 property sync completed successfully",
                          property_id=config.property_id,
                          stats=stats)
                
                return stats
            
            except Exception as e:
                await db_session.rollback()
                logger.error("GA4 property sync failed",
                           property_id=config.property_id,
                           error=str(e),
                           error_type=type(e).__name__)
                stats['errors'] = 1
                raise GA4SyncError(f"Sync failed for property {config.property_id}: {e}")
    
    async def _determine_sync_date_range(
        self,
        config: GA4SyncConfig,
        session: AsyncSession
    ) -> Tuple[date, date]:
        """Determine the date range for incremental sync."""
        
        # Use config dates if provided
        if config.start_date and config.end_date:
            return config.start_date, config.end_date
        
        # Calculate default end date (account for processing delay)
        max_end_date = date.today() - timedelta(days=self.processing_delay_days)
        
        if config.end_date:
            end_date = min(config.end_date, max_end_date)
        else:
            end_date = max_end_date
        
        # Determine start date based on last sync or config
        if config.start_date:
            start_date = config.start_date
        else:
            # Find last successful sync date
            last_sync_date = await self._get_last_sync_date(
                config.property_id, config.site_id, session
            )
            
            if last_sync_date:
                # Start from lookback period before last sync
                start_date = last_sync_date - timedelta(days=self.lookback_days)
            else:
                # First sync - go back 90 days or GA4 retention limit
                start_date = end_date - timedelta(days=90)
        
        # Ensure start_date is not before end_date
        if start_date > end_date:
            start_date = end_date
        
        return start_date, end_date
    
    async def _get_last_sync_date(
        self,
        property_id: str,
        site_id: UUID,
        session: AsyncSession
    ) -> Optional[date]:
        """Get the last successful sync date for a property."""
        
        query = (
            select(func.max(GA4Metric.date))
            .where(
                and_(
                    GA4Metric.site_id == site_id,
                    GA4Metric.source_medium.ilike('%organic%')
                )
            )
        )
        
        result = await session.execute(query)
        return result.scalar_one_or_none()
    
    async def _upsert_metrics_batch(
        self,
        metrics: List[GA4MetricData],
        batch_size: int,
        session: AsyncSession
    ) -> Dict[str, int]:
        """Upsert metrics in batches with conflict resolution."""
        
        stats = {'inserted': 0, 'updated': 0, 'skipped': 0}
        
        logger.info("Starting batch upsert of GA4 metrics",
                  total_metrics=len(metrics), batch_size=batch_size)
        
        # Process in batches
        for i in range(0, len(metrics), batch_size):
            batch = metrics[i:i + batch_size]
            batch_stats = await self._upsert_single_batch(batch, session)
            
            for key in stats:
                stats[key] += batch_stats.get(key, 0)
            
            logger.debug("Processed GA4 batch",
                       batch_num=i // batch_size + 1,
                       batch_size=len(batch),
                       **batch_stats)
        
        logger.info("Completed GA4 metrics batch upsert", **stats)
        return stats
    
    async def _upsert_single_batch(
        self,
        metrics: List[GA4MetricData],
        session: AsyncSession
    ) -> Dict[str, int]:
        """Upsert a single batch of metrics."""
        
        if not metrics:
            return {'inserted': 0, 'updated': 0, 'skipped': 0}
        
        # Convert to database records
        records = []
        for metric in metrics:
            record = {
                'site_id': metric.site_id,
                'date': metric.date,
                'page_path': metric.page_path,
                'landing_page': metric.landing_page,
                'source_medium': metric.source_medium,
                'country': metric.country,
                'device_category': metric.device_category,
                'sessions': metric.sessions,
                'page_views': metric.page_views,
                'unique_page_views': metric.unique_page_views,
                'bounce_rate': metric.bounce_rate,
                'avg_session_duration': metric.avg_session_duration,
                'conversions': metric.conversions,
                'revenue': metric.revenue,
                'created_at': datetime.utcnow(),
                'updated_at': datetime.utcnow()
            }
            records.append(record)
        
        try:
            # Use PostgreSQL UPSERT (ON CONFLICT DO UPDATE)
            stmt = insert(GA4Metric).values(records)
            
            # Define conflict resolution - update most fields except created_at
            update_fields = {
                'sessions': stmt.excluded.sessions,
                'page_views': stmt.excluded.page_views,
                'unique_page_views': stmt.excluded.unique_page_views,
                'bounce_rate': stmt.excluded.bounce_rate,
                'avg_session_duration': stmt.excluded.avg_session_duration,
                'conversions': stmt.excluded.conversions,
                'revenue': stmt.excluded.revenue,
                'updated_at': stmt.excluded.updated_at
            }
            
            # Conflict on unique constraint (site_id, date, page_path, source_medium, country, device_category)
            upsert_stmt = stmt.on_conflict_do_update(
                constraint='uq_ga4_metric_daily',
                set_=update_fields
            )
            
            # Add a RETURNING clause to count operations
            upsert_stmt = upsert_stmt.returning(
                text("CASE xmax WHEN 0 THEN 'insert'::text ELSE 'update'::text END as operation")
            )
            
            result = await session.execute(upsert_stmt)
            operations = result.fetchall()
            
            # Count operations
            inserted = sum(1 for op in operations if op.operation == 'insert')
            updated = sum(1 for op in operations if op.operation == 'update')
            
            return {
                'inserted': inserted,
                'updated': updated,
                'skipped': 0
            }
        
        except Exception as e:
            logger.error("Failed to upsert GA4 metrics batch",
                       batch_size=len(records),
                       error=str(e))
            return {
                'inserted': 0,
                'updated': 0,
                'skipped': len(records)
            }
    
    async def _update_sync_state(
        self,
        config: GA4SyncConfig,
        last_sync_date: date,
        session: AsyncSession
    ) -> None:
        """Update sync state tracking (could be stored in a separate table)."""
        
        # For now, we rely on the max date in GA4Metric table
        # In future, we could add a sync_state table for more detailed tracking
        logger.info("Sync state updated",
                  property_id=config.property_id,
                  site_id=str(config.site_id),
                  last_sync_date=last_sync_date)
    
    async def _log_sync_audit(
        self,
        config: GA4SyncConfig,
        stats: Dict[str, int],
        session: AsyncSession
    ) -> None:
        """Log sync operation to audit log."""
        
        audit_data = {
            'property_id': config.property_id,
            'site_id': str(config.site_id),
            'organic_only': config.organic_only,
            'stats': stats
        }
        
        audit_entry = AuditLog(
            action_type=ActionType.GA4_SYNC,
            entity_type=EntityType.SITE,
            entity_id=config.site_id,
            action_data=audit_data,
            status=EntityType.APPROVED.value if stats['errors'] == 0 else 'failed',  # type: ignore
            performed_by="system",
            performed_at=datetime.utcnow()
        )
        
        session.add(audit_entry)
        
        logger.info("GA4 sync audit entry created",
                  property_id=config.property_id,
                  stats=stats)
    
    async def sync_multiple_properties(
        self,
        configs: List[GA4SyncConfig],
        max_concurrent: int = 3
    ) -> Dict[str, Dict[str, int]]:
        """
        Synchronize multiple GA4 properties concurrently.
        
        Args:
            configs: List of sync configurations
            max_concurrent: Maximum concurrent sync operations
            
        Returns:
            Dict mapping property_id to sync stats
        """
        logger.info("Starting multi-property GA4 sync",
                  num_properties=len(configs),
                  max_concurrent=max_concurrent)
        
        semaphore = asyncio.Semaphore(max_concurrent)
        results = {}
        
        async def sync_single_property(config: GA4SyncConfig) -> Tuple[str, Dict[str, int]]:
            async with semaphore:
                try:
                    stats = await self.sync_property_data(config)
                    return config.property_id, stats
                except Exception as e:
                    logger.error("Failed to sync GA4 property",
                               property_id=config.property_id,
                               error=str(e))
                    return config.property_id, {'errors': 1}
        
        # Execute all syncs concurrently
        tasks = [sync_single_property(config) for config in configs]
        sync_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Collect results
        for result in sync_results:
            if isinstance(result, Exception):
                logger.error("GA4 sync task failed", error=str(result))
                continue
            
            property_id, stats = result
            results[property_id] = stats
        
        logger.info("Multi-property GA4 sync completed",
                  properties_synced=len(results))
        
        return results
    
    async def validate_data_freshness(
        self,
        property_id: str,
        site_id: UUID,
        session: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """
        Validate data freshness and identify gaps.
        
        Args:
            property_id: GA4 property ID
            site_id: Site UUID
            session: Database session
            
        Returns:
            Dict with freshness validation results
        """
        async with get_async_session() if session is None else session as db_session:
            
            # Expected latest date (accounting for processing delay)
            expected_latest = date.today() - timedelta(days=self.processing_delay_days)
            
            # Query actual latest date
            query = (
                select(func.max(GA4Metric.date), func.count(GA4Metric.id))
                .where(GA4Metric.site_id == site_id)
            )
            
            result = await db_session.execute(query)
            actual_latest, total_records = result.one()
            
            # Calculate data lag
            data_lag_days = None
            if actual_latest:
                data_lag_days = (expected_latest - actual_latest).days
            
            # Check for date gaps in recent data
            gaps = await self._find_date_gaps(site_id, expected_latest, db_session)
            
            freshness_info = {
                'property_id': property_id,
                'site_id': str(site_id),
                'expected_latest_date': expected_latest.isoformat(),
                'actual_latest_date': actual_latest.isoformat() if actual_latest else None,
                'data_lag_days': data_lag_days,
                'total_records': total_records,
                'recent_gaps': gaps,
                'is_fresh': data_lag_days is not None and data_lag_days <= 1,
                'needs_sync': data_lag_days is None or data_lag_days > 1 or len(gaps) > 0
            }
            
            logger.info("GA4 data freshness validation completed",
                      property_id=property_id,
                      **freshness_info)
            
            return freshness_info
    
    async def _find_date_gaps(
        self,
        site_id: UUID,
        end_date: date,
        session: AsyncSession,
        lookback_days: int = 14
    ) -> List[str]:
        """Find missing dates in recent GA4 data."""
        
        start_date = end_date - timedelta(days=lookback_days)
        
        # Get dates with data
        query = (
            select(GA4Metric.date)
            .where(
                and_(
                    GA4Metric.site_id == site_id,
                    GA4Metric.date >= start_date,
                    GA4Metric.date <= end_date
                )
            )
            .distinct()
        )
        
        result = await session.execute(query)
        dates_with_data = {row.date for row in result}
        
        # Find gaps
        gaps = []
        current_date = start_date
        
        while current_date <= end_date:
            if current_date not in dates_with_data:
                gaps.append(current_date.isoformat())
            current_date += timedelta(days=1)
        
        return gaps