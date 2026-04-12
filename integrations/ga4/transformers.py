"""
Google Analytics 4 data transformation utilities.

This module provides functions for transforming GA4 API responses
into normalized data structures for database storage and analysis.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse, parse_qs, urljoin
from uuid import UUID

import structlog

from .models import GA4MetricData, GA4Row, GA4DimensionMetadata, GA4MetricMetadata

logger = structlog.get_logger(__name__)


class GA4DataTransformer:
    """Transformer for GA4 API response data to internal formats."""
    
    def __init__(self):
        # URL normalization patterns
        self.query_params_to_remove = {
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
            'gclid', 'fbclid', 'msclkid', '_ga', '_gl', 'ref', 'source'
        }
        
        # Common page path normalizations
        self.path_normalizations = [
            (re.compile(r'/page/\d+/?$'), '/'),  # Pagination
            (re.compile(r'/\d{4}/\d{2}/\d{2}/'), '/'),  # Date-based URLs
            (re.compile(r'[#].*$'), ''),  # Fragments
            (re.compile(r'/+'), '/'),  # Multiple slashes
        ]
    
    def transform_api_response(
        self,
        rows: List[GA4Row],
        dimension_headers: List[GA4DimensionMetadata],
        metric_headers: List[GA4MetricMetadata],
        site_id: UUID,
        property_id: str
    ) -> List[GA4MetricData]:
        """
        Transform GA4 API response to GA4MetricData objects.
        
        Args:
            rows: GA4 API response rows
            dimension_headers: Dimension metadata
            metric_headers: Metric metadata  
            site_id: Internal site UUID
            property_id: GA4 property ID
            
        Returns:
            List of transformed GA4MetricData objects
        """
        logger.info("Transforming GA4 API response",
                  total_rows=len(rows), property_id=property_id)
        
        # Create mappings from headers
        dimension_map = {i: header.api_name for i, header in enumerate(dimension_headers)}
        metric_map = {i: header.api_name for i, header in enumerate(metric_headers)}
        
        transformed_data = []
        skipped_count = 0
        
        for row in rows:
            try:
                metric_data = self._transform_single_row(
                    row, dimension_map, metric_map, site_id, property_id
                )
                
                if metric_data:
                    transformed_data.append(metric_data)
                else:
                    skipped_count += 1
            
            except Exception as e:
                logger.warning("Failed to transform GA4 row",
                             error=str(e), error_type=type(e).__name__)
                skipped_count += 1
                continue
        
        logger.info("GA4 data transformation completed",
                  transformed=len(transformed_data),
                  skipped=skipped_count,
                  property_id=property_id)
        
        return transformed_data
    
    def _transform_single_row(
        self,
        row: GA4Row,
        dimension_map: Dict[int, str],
        metric_map: Dict[int, str],
        site_id: UUID,
        property_id: str
    ) -> Optional[GA4MetricData]:
        """Transform a single GA4 API row to GA4MetricData."""
        
        # Extract dimensions
        dimensions = {}
        for i, dim_value in enumerate(row.dimension_values):
            if i in dimension_map:
                dimensions[dimension_map[i]] = (dim_value.value or dim_value.one_value or "").strip()
        
        # Extract metrics
        metrics = {}
        for i, metric_value in enumerate(row.metric_values):
            if i in metric_map:
                metrics[metric_map[i]] = (metric_value.value or metric_value.one_value or "0").strip()
        
        # Parse and validate required dimensions
        page_path = dimensions.get('pagePath', '')
        if not page_path or page_path == '(not set)':
            return None  # Skip rows without valid page paths
        
        # Normalize page path
        normalized_page_path = self.normalize_page_path(page_path)
        
        # Parse date
        date_str = dimensions.get('date', '')
        if not date_str or len(date_str) != 8:
            logger.warning("Invalid date format in GA4 data", date_str=date_str)
            return None
        
        try:
            row_date = datetime.strptime(date_str, '%Y%m%d').date()
        except ValueError:
            logger.warning("Failed to parse GA4 date", date_str=date_str)
            return None
        
        # Parse metrics with safe conversion
        sessions = self._safe_int(metrics.get('sessions', '0'))
        page_views = self._safe_int(metrics.get('screenPageViews', '0'))
        new_users = self._safe_int(metrics.get('newUsers', '0'))
        
        # Skip rows with no sessions (likely noise)
        if sessions <= 0:
            return None
        
        # Parse optional metrics
        bounce_rate = self._safe_decimal(metrics.get('bounceRate'))
        avg_session_duration = self._safe_int(metrics.get('averageSessionDuration'))
        conversions = self._safe_int(metrics.get('conversions', '0')) or 0
        revenue = self._safe_decimal(metrics.get('totalRevenue'))
        
        # Normalize dimension values
        source_medium = self.normalize_source_medium(dimensions.get('sourceMedium', ''))
        country = self.normalize_country_code(dimensions.get('country', ''))
        device_category = self.normalize_device_category(dimensions.get('deviceCategory', ''))
        
        return GA4MetricData(
            site_id=site_id,
            date=row_date,
            property_id=property_id,
            page_path=normalized_page_path,
            landing_page=normalized_page_path,  # Same as page_path for now
            source_medium=source_medium,
            channel_group=dimensions.get('sessionDefaultChannelGroup'),
            country=country,
            device_category=device_category,
            sessions=sessions,
            page_views=page_views,
            unique_page_views=page_views,  # GA4 doesn't distinguish, use same value
            bounce_rate=bounce_rate,
            avg_session_duration=avg_session_duration,
            new_users=new_users,
            conversions=conversions,
            revenue=revenue
        )
    
    def normalize_page_path(self, page_path: str) -> str:
        """
        Normalize page path by removing query parameters and fragments.
        
        Args:
            page_path: Raw page path from GA4
            
        Returns:
            Normalized page path
        """
        if not page_path:
            return '/'
        
        # Parse URL to remove query params and fragments
        try:
            parsed = urlparse(page_path)
            
            # Start with the path
            normalized = parsed.path or '/'
            
            # Apply normalization patterns
            for pattern, replacement in self.path_normalizations:
                normalized = pattern.sub(replacement, normalized)
            
            # Ensure path starts with /
            if not normalized.startswith('/'):
                normalized = '/' + normalized
            
            # Remove trailing slash unless it's root
            if len(normalized) > 1 and normalized.endswith('/'):
                normalized = normalized[:-1]
            
            return normalized
        
        except Exception:
            # Fallback to basic cleaning
            return page_path.split('?')[0].split('#')[0] or '/'
    
    def normalize_source_medium(self, source_medium: str) -> Optional[str]:
        """Normalize source/medium values."""
        if not source_medium or source_medium == '(not set)':
            return None
        
        # Common normalizations
        normalized = source_medium.lower().strip()
        
        # Handle Google organic variations
        if 'google' in normalized and 'organic' in normalized:
            return 'google / organic'
        
        return normalized
    
    def normalize_country_code(self, country: str) -> Optional[str]:
        """Normalize country codes to ISO 3166-1 alpha-2."""
        if not country or country == '(not set)':
            return None
        
        # GA4 uses ISO codes, but clean up common issues
        normalized = country.upper().strip()
        
        # Handle special cases
        country_mappings = {
            'UK': 'GB',  # United Kingdom
            'USA': 'US',  # United States
        }
        
        return country_mappings.get(normalized, normalized)
    
    def normalize_device_category(self, device_category: str) -> Optional[str]:
        """Normalize device category values."""
        if not device_category or device_category == '(not set)':
            return None
        
        # Standardize case
        normalized = device_category.lower().strip()
        
        # Map to consistent values
        device_mappings = {
            'desktop': 'desktop',
            'mobile': 'mobile',
            'tablet': 'tablet',
            'smart tv': 'tablet',  # Group smart TV with tablet
        }
        
        return device_mappings.get(normalized, normalized)
    
    def _safe_int(self, value: str) -> int:
        """Safely convert string to int."""
        if not value or value == '(not set)':
            return 0
        
        try:
            # Handle scientific notation and decimals
            float_val = float(value)
            return max(0, int(round(float_val)))
        except (ValueError, TypeError):
            return 0
    
    def _safe_decimal(self, value: str) -> Optional[Decimal]:
        """Safely convert string to Decimal."""
        if not value or value == '(not set)':
            return None
        
        try:
            decimal_val = Decimal(str(value))
            # Clamp bounce rate to valid range
            if 0 <= decimal_val <= 1:
                return decimal_val
            return None
        except (ValueError, TypeError, InvalidOperation):
            return None
    
    def aggregate_daily_metrics(
        self, 
        metrics: List[GA4MetricData], 
        group_by_device: bool = False
    ) -> List[GA4MetricData]:
        """
        Aggregate metrics by page and date, optionally by device.
        
        Args:
            metrics: List of GA4MetricData to aggregate
            group_by_device: Whether to keep device-level granularity
            
        Returns:
            List of aggregated GA4MetricData
        """
        logger.info("Aggregating GA4 metrics",
                  total_metrics=len(metrics), group_by_device=group_by_device)
        
        # Group metrics by aggregation key
        grouped = {}
        
        for metric in metrics:
            # Create grouping key
            key_parts = [
                str(metric.site_id),
                metric.date.isoformat(),
                metric.page_path,
                metric.country or 'unknown'
            ]
            
            if group_by_device:
                key_parts.append(metric.device_category or 'unknown')
            
            key = '|'.join(key_parts)
            
            if key not in grouped:
                grouped[key] = []
            
            grouped[key].append(metric)
        
        # Aggregate each group
        aggregated = []
        for group_metrics in grouped.values():
            aggregated_metric = self._aggregate_metric_group(group_metrics)
            if aggregated_metric:
                aggregated.append(aggregated_metric)
        
        logger.info("GA4 metrics aggregation completed",
                  original_count=len(metrics),
                  aggregated_count=len(aggregated))
        
        return aggregated
    
    def _aggregate_metric_group(self, metrics: List[GA4MetricData]) -> Optional[GA4MetricData]:
        """Aggregate a group of metrics with the same key."""
        if not metrics:
            return None
        
        # Use first metric as base
        base = metrics[0]
        
        # Sum numeric metrics
        total_sessions = sum(m.sessions for m in metrics)
        total_page_views = sum(m.page_views for m in metrics)
        total_new_users = sum(m.new_users for m in metrics)
        total_conversions = sum(m.conversions for m in metrics)
        
        # Calculate weighted averages for rates
        weighted_bounce_rate = None
        weighted_avg_duration = None
        total_revenue = None
        
        if total_sessions > 0:
            # Bounce rate weighted by sessions
            bounce_sum = 0
            bounce_weight = 0
            duration_sum = 0
            duration_weight = 0
            
            for m in metrics:
                if m.bounce_rate is not None and m.sessions > 0:
                    bounce_sum += float(m.bounce_rate) * m.sessions
                    bounce_weight += m.sessions
                
                if m.avg_session_duration is not None and m.sessions > 0:
                    duration_sum += m.avg_session_duration * m.sessions
                    duration_weight += m.sessions
            
            if bounce_weight > 0:
                weighted_bounce_rate = Decimal(str(bounce_sum / bounce_weight))
            
            if duration_weight > 0:
                weighted_avg_duration = int(duration_sum / duration_weight)
        
        # Sum revenue
        revenue_values = [m.revenue for m in metrics if m.revenue is not None]
        if revenue_values:
            total_revenue = sum(revenue_values)
        
        return GA4MetricData(
            site_id=base.site_id,
            date=base.date,
            property_id=base.property_id,
            page_path=base.page_path,
            landing_page=base.landing_page,
            source_medium=base.source_medium,
            channel_group=base.channel_group,
            country=base.country,
            device_category=base.device_category if len(set(m.device_category for m in metrics)) == 1 else None,
            sessions=total_sessions,
            page_views=total_page_views,
            unique_page_views=total_page_views,  # Use same as page views
            bounce_rate=weighted_bounce_rate,
            avg_session_duration=weighted_avg_duration,
            new_users=total_new_users,
            conversions=total_conversions,
            revenue=total_revenue
        )
    
    def filter_organic_traffic(self, metrics: List[GA4MetricData]) -> List[GA4MetricData]:
        """Filter metrics to include only organic search traffic."""
        organic_patterns = ['google / organic', 'bing / organic', 'yahoo / organic', 'duckduckgo / organic']
        
        filtered = []
        for metric in metrics:
            # Check source/medium
            if metric.source_medium:
                source_medium_lower = metric.source_medium.lower()
                if any(pattern in source_medium_lower for pattern in organic_patterns):
                    filtered.append(metric)
            
            # Also check channel group
            elif metric.channel_group == 'Organic Search':
                filtered.append(metric)
        
        logger.info("Filtered GA4 metrics for organic traffic",
                  original_count=len(metrics),
                  organic_count=len(filtered))
        
        return filtered