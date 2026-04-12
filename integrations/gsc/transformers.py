"""
Data transformation utilities for GSC integration.

This module provides functions to transform GSC API response data
into SQLAlchemy models for database storage, including validation
and data cleaning.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any, Optional
from uuid import UUID

import structlog
from pydantic import ValidationError

from db.models import GSCMetric
from .models import GSCMetricData, GSCDimension

logger = structlog.get_logger(__name__)


class GSCTransformationError(Exception):
    """Error during GSC data transformation."""
    pass


class GSCTransformer:
    """
    Transforms GSC API data to database models.
    
    Handles data validation, cleaning, and conversion from GSC API
    response format to SQLAlchemy GSCMetric models.
    """
    
    def __init__(self, validate_data: bool = True):
        self.validate_data = validate_data
        self._transformation_stats = {
            'total_processed': 0,
            'successful_transforms': 0,
            'validation_errors': 0,
            'data_cleaning_applied': 0
        }
    
    def transform_to_gsc_metric(
        self,
        metric_data: GSCMetricData,
        site_id: UUID,
        date: date,
        url: str,
        query: Optional[str] = None,
        country: Optional[str] = None,
        device: Optional[str] = None
    ) -> GSCMetric:
        """
        Transform GSCMetricData to SQLAlchemy GSCMetric model.
        
        Args:
            metric_data: GSC metric data from API
            site_id: Site UUID
            date: Date of the metrics
            url: Page URL
            query: Search query (optional)
            country: Country code (optional)
            device: Device type (optional)
            
        Returns:
            GSCMetric model instance
            
        Raises:
            GSCTransformationError: On transformation or validation errors
        """
        self._transformation_stats['total_processed'] += 1
        
        try:
            # Data cleaning and validation
            cleaned_data = self._clean_metric_data(metric_data)
            
            # Validate required fields
            if not url:
                raise GSCTransformationError("URL is required for GSC metrics")
            
            # Clean and validate dimensions
            cleaned_url = self._clean_url(url)
            cleaned_query = self._clean_query(query)
            cleaned_country = self._clean_country(country)
            cleaned_device = self._clean_device(device)
            
            # Create GSCMetric instance
            gsc_metric = GSCMetric(
                site_id=site_id,
                date=date,
                url=cleaned_url,
                query=cleaned_query,
                country=cleaned_country,
                device=cleaned_device,
                clicks=cleaned_data['clicks'],
                impressions=cleaned_data['impressions'],
                ctr=cleaned_data['ctr'],
                position=cleaned_data['position']
            )
            
            # Additional validation if enabled
            if self.validate_data:
                self._validate_gsc_metric(gsc_metric)
            
            self._transformation_stats['successful_transforms'] += 1
            
            logger.debug(
                "Transformed GSC metric data",
                site_id=site_id,
                date=date,
                url=cleaned_url[:50],
                clicks=cleaned_data['clicks'],
                impressions=cleaned_data['impressions']
            )
            
            return gsc_metric
            
        except Exception as e:
            self._transformation_stats['validation_errors'] += 1
            logger.error(
                "GSC metric transformation failed",
                error=str(e),
                site_id=site_id,
                date=date,
                url=url[:50] if url else None,
                metric_data=metric_data.model_dump() if metric_data else None
            )
            raise GSCTransformationError(f"Failed to transform GSC metric: {e}")
    
    def _clean_metric_data(self, metric_data: GSCMetricData) -> Dict[str, Any]:
        """
        Clean and validate GSC metric values.
        
        Args:
            metric_data: Raw metric data from API
            
        Returns:
            Dictionary with cleaned metric values
        """
        cleaned = {}
        data_modified = False
        
        # Clean clicks (must be non-negative integer)
        clicks = metric_data.clicks
        if clicks < 0:
            logger.warning(f"Negative clicks value {clicks}, setting to 0")
            clicks = 0
            data_modified = True
        cleaned['clicks'] = clicks
        
        # Clean impressions (must be non-negative integer)  
        impressions = metric_data.impressions
        if impressions < 0:
            logger.warning(f"Negative impressions value {impressions}, setting to 0")
            impressions = 0
            data_modified = True
        cleaned['impressions'] = impressions
        
        # Clean CTR (must be between 0 and 1)
        ctr = metric_data.ctr
        if ctr < Decimal('0'):
            logger.warning(f"Negative CTR value {ctr}, setting to 0")
            ctr = Decimal('0')
            data_modified = True
        elif ctr > Decimal('1'):
            logger.warning(f"CTR value {ctr} > 1, capping at 1")
            ctr = Decimal('1')
            data_modified = True
            
        # Ensure CTR precision (4 decimal places max)
        try:
            ctr = ctr.quantize(Decimal('0.0001'))
        except InvalidOperation:
            logger.warning(f"Invalid CTR decimal {ctr}, setting to 0")
            ctr = Decimal('0')
            data_modified = True
        cleaned['ctr'] = ctr
        
        # Clean position (must be non-negative)
        position = metric_data.position  
        if position < Decimal('0'):
            logger.warning(f"Negative position value {position}, setting to 0")
            position = Decimal('0')
            data_modified = True
            
        # Ensure position precision (2 decimal places max)
        try:
            position = position.quantize(Decimal('0.01'))
        except InvalidOperation:
            logger.warning(f"Invalid position decimal {position}, setting to 0")
            position = Decimal('0')
            data_modified = True
        cleaned['position'] = position
        
        # Validate CTR consistency with clicks/impressions
        if impressions > 0:
            calculated_ctr = Decimal(str(clicks)) / Decimal(str(impressions))
            calculated_ctr = calculated_ctr.quantize(Decimal('0.0001'))
            
            # Allow small differences due to rounding
            ctr_diff = abs(ctr - calculated_ctr)
            if ctr_diff > Decimal('0.001'):  # 0.1% tolerance
                logger.warning(
                    f"CTR mismatch: reported {ctr}, calculated {calculated_ctr}, "
                    f"using calculated value"
                )
                cleaned['ctr'] = calculated_ctr
                data_modified = True
        
        if data_modified:
            self._transformation_stats['data_cleaning_applied'] += 1
        
        return cleaned
    
    def _clean_url(self, url: str) -> str:
        """
        Clean and normalize URL.
        
        Args:
            url: Raw URL from GSC
            
        Returns:
            Cleaned URL (max 500 characters)
        """
        if not url:
            raise GSCTransformationError("URL cannot be empty")
        
        # Remove leading/trailing whitespace
        cleaned = url.strip()
        
        # Ensure URL is not too long for database
        if len(cleaned) > 500:
            logger.warning(f"URL too long ({len(cleaned)} chars), truncating: {cleaned[:50]}...")
            cleaned = cleaned[:500]
        
        return cleaned
    
    def _clean_query(self, query: Optional[str]) -> Optional[str]:
        """
        Clean and normalize search query.
        
        Args:
            query: Raw search query from GSC
            
        Returns:
            Cleaned query (max 500 characters) or None
        """
        if not query:
            return None
        
        # Remove leading/trailing whitespace
        cleaned = query.strip()
        
        if not cleaned:
            return None
        
        # Ensure query is not too long for database
        if len(cleaned) > 500:
            logger.warning(f"Query too long ({len(cleaned)} chars), truncating: {cleaned[:50]}...")
            cleaned = cleaned[:500]
        
        return cleaned
    
    def _clean_country(self, country: Optional[str]) -> Optional[str]:
        """
        Clean and validate country code.
        
        Args:
            country: Raw country code from GSC
            
        Returns:
            Validated 2-character country code or None
        """
        if not country:
            return None
        
        # Remove whitespace and convert to uppercase
        cleaned = country.strip().upper()
        
        if not cleaned:
            return None
        
        # Validate country code format (should be 2 characters)
        if len(cleaned) != 2:
            logger.warning(f"Invalid country code length: '{cleaned}', expected 2 chars")
            return None
        
        # Basic validation (only letters)
        if not cleaned.isalpha():
            logger.warning(f"Invalid country code format: '{cleaned}', expected letters only")
            return None
        
        return cleaned
    
    def _clean_device(self, device: Optional[str]) -> Optional[str]:
        """
        Clean and normalize device type.
        
        Args:
            device: Raw device type from GSC
            
        Returns:
            Normalized device type or None
        """
        if not device:
            return None
        
        # Remove whitespace and convert to uppercase
        cleaned = device.strip().upper()
        
        if not cleaned:
            return None
        
        # Normalize common device types
        device_mapping = {
            'DESKTOP': 'desktop',
            'MOBILE': 'mobile', 
            'TABLET': 'tablet'
        }
        
        normalized = device_mapping.get(cleaned)
        if normalized:
            return normalized
        
        # If not a standard device type, truncate and lowercase
        if len(cleaned) > 10:
            logger.warning(f"Device type too long: '{cleaned}', truncating")
            cleaned = cleaned[:10]
        
        return cleaned.lower()
    
    def _validate_gsc_metric(self, gsc_metric: GSCMetric) -> None:
        """
        Perform additional validation on GSCMetric instance.
        
        Args:
            gsc_metric: GSCMetric model instance to validate
            
        Raises:
            GSCTransformationError: On validation failures
        """
        # Check required fields
        if not gsc_metric.site_id:
            raise GSCTransformationError("site_id is required")
        
        if not gsc_metric.date:
            raise GSCTransformationError("date is required")
        
        if not gsc_metric.url:
            raise GSCTransformationError("url is required")
        
        # Validate date is not in future (GSC has data delay)
        from datetime import date as date_class, timedelta
        max_date = date_class.today() - timedelta(days=1)
        if gsc_metric.date > max_date:
            raise GSCTransformationError(
                f"Date {gsc_metric.date} is too recent for GSC data"
            )
        
        # Validate metric ranges
        if gsc_metric.clicks < 0:
            raise GSCTransformationError(f"Invalid clicks: {gsc_metric.clicks}")
        
        if gsc_metric.impressions < 0:
            raise GSCTransformationError(f"Invalid impressions: {gsc_metric.impressions}")
        
        if not (Decimal('0') <= gsc_metric.ctr <= Decimal('1')):
            raise GSCTransformationError(f"Invalid CTR: {gsc_metric.ctr}")
        
        if gsc_metric.position < Decimal('0'):
            raise GSCTransformationError(f"Invalid position: {gsc_metric.position}")
    
    def transform_batch(
        self,
        metric_data_list: List[Dict[str, Any]],
        site_id: UUID
    ) -> List[GSCMetric]:
        """
        Transform a batch of GSC metric data to GSCMetric models.
        
        Args:
            metric_data_list: List of metric data dictionaries
            site_id: Site UUID
            
        Returns:
            List of GSCMetric model instances
            
        Raises:
            GSCTransformationError: On transformation errors
        """
        if not metric_data_list:
            return []
        
        results = []
        errors = []
        
        logger.info(
            "Starting batch GSC transformation",
            batch_size=len(metric_data_list),
            site_id=site_id
        )
        
        for i, data in enumerate(metric_data_list):
            try:
                # Validate required fields
                required_fields = ['date', 'url', 'clicks', 'impressions', 'ctr', 'position']
                missing_fields = [field for field in required_fields if field not in data]
                
                if missing_fields:
                    raise GSCTransformationError(f"Missing required fields: {missing_fields}")
                
                # Create metric data object
                metric_data = GSCMetricData(
                    clicks=data['clicks'],
                    impressions=data['impressions'],
                    ctr=Decimal(str(data['ctr'])),
                    position=Decimal(str(data['position']))
                )
                
                # Transform to GSCMetric
                gsc_metric = self.transform_to_gsc_metric(
                    metric_data=metric_data,
                    site_id=site_id,
                    date=data['date'],
                    url=data['url'],
                    query=data.get('query'),
                    country=data.get('country'),
                    device=data.get('device')
                )
                
                results.append(gsc_metric)
                
            except Exception as e:
                error_info = {
                    'index': i,
                    'error': str(e),
                    'data': data
                }
                errors.append(error_info)
                
                logger.error(
                    "Failed to transform GSC metric in batch",
                    index=i,
                    error=str(e),
                    site_id=site_id,
                    data_sample=str(data)[:200]
                )
        
        # Log batch transformation results
        logger.info(
            "Completed batch GSC transformation",
            total_items=len(metric_data_list),
            successful=len(results),
            errors=len(errors),
            site_id=site_id
        )
        
        if errors and len(errors) == len(metric_data_list):
            # All transformations failed
            raise GSCTransformationError(
                f"All {len(errors)} transformations in batch failed"
            )
        
        return results
    
    def get_transformation_stats(self) -> Dict[str, Any]:
        """Get transformation statistics."""
        stats = self._transformation_stats.copy()
        
        if stats['total_processed'] > 0:
            stats['success_rate'] = (
                stats['successful_transforms'] / stats['total_processed'] * 100
            )
        else:
            stats['success_rate'] = 0.0
        
        return stats
    
    def reset_stats(self) -> None:
        """Reset transformation statistics."""
        self._transformation_stats = {
            'total_processed': 0,
            'successful_transforms': 0,
            'validation_errors': 0,
            'data_cleaning_applied': 0
        }