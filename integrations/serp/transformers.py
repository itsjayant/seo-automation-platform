"""
SerpAPI Result Transformers and Position Extraction

Comprehensive parsing and transformation of SerpAPI responses into structured
ranking data with SERP feature detection, competitor analysis, and position
extraction optimized for rank tracking accuracy.
"""

from datetime import datetime, date
from typing import Dict, List, Optional, Any, Set
from urllib.parse import urlparse
import re

import structlog
from pydantic import ValidationError

from .models import (
    SerpResult, OrganicResult, RankingData, SerpFeatures,
    SearchParams, DeviceType, QuotaInfo
)

logger = structlog.get_logger(__name__)


class PositionExtractor:
    """Utility class for extracting positions from SERP results."""
    
    @staticmethod
    def normalize_domain(url: str) -> str:
        """
        Normalize domain from URL for consistent matching.
        
        Args:
            url: Full URL or domain
            
        Returns:
            Normalized domain (e.g., 'example.com')
        """
        if not url:
            return ""
            
        # Handle cases where URL might be just a domain
        if not url.startswith(('http://', 'https://')):
            url = f"https://{url}"
            
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            # Remove www. prefix for consistency
            if domain.startswith('www.'):
                domain = domain[4:]
                
            return domain
        except Exception as e:
            logger.warning("Failed to parse domain", url=url, error=str(e))
            return url.lower()
    
    @classmethod
    def find_domain_positions(
        cls, 
        organic_results: List[OrganicResult], 
        target_domain: str
    ) -> List[int]:
        """
        Find all positions for a target domain in organic results.
        
        Args:
            organic_results: List of organic search results
            target_domain: Domain to find (will be normalized)
            
        Returns:
            List of positions (1-indexed) where domain appears
        """
        normalized_target = cls.normalize_domain(target_domain)
        positions = []
        
        for result in organic_results:
            result_domain = cls.normalize_domain(str(result.link))
            if result_domain == normalized_target:
                positions.append(result.position)
        
        return sorted(positions)
    
    @classmethod
    def get_best_position(
        cls, 
        organic_results: List[OrganicResult], 
        target_domain: str
    ) -> Optional[int]:
        """
        Get the best (lowest number) position for a domain.
        
        Args:
            organic_results: List of organic search results
            target_domain: Domain to find
            
        Returns:
            Best position (1-indexed) or None if not found
        """
        positions = cls.find_domain_positions(organic_results, target_domain)
        return min(positions) if positions else None
    
    @classmethod
    def get_ranking_url(
        cls, 
        organic_results: List[OrganicResult], 
        target_domain: str
    ) -> Optional[str]:
        """
        Get the URL that achieved the best ranking for a domain.
        
        Args:
            organic_results: List of organic search results
            target_domain: Domain to find
            
        Returns:
            URL string of best ranking result or None if not found
        """
        best_position = cls.get_best_position(organic_results, target_domain)
        if best_position is None:
            return None
        
        normalized_target = cls.normalize_domain(target_domain)
        
        for result in organic_results:
            if result.position == best_position:
                result_domain = cls.normalize_domain(str(result.link))
                if result_domain == normalized_target:
                    return str(result.link)
        
        return None


class SerpFeatureDetector:
    """Utility class for detecting SERP features from SerpAPI responses."""
    
    @staticmethod
    def detect_features(response_data: Dict[str, Any]) -> SerpFeatures:
        """
        Detect SERP features from SerpAPI response.
        
        Args:
            response_data: Raw SerpAPI response
            
        Returns:
            SerpFeatures object with detected features
        """
        features = SerpFeatures()
        
        # Featured snippet detection
        if "answer_box" in response_data:
            features.featured_snippet = True
        elif "featured_snippet" in response_data:
            features.featured_snippet = True
        
        # People Also Ask detection
        if "related_questions" in response_data:
            features.people_also_ask = len(response_data["related_questions"]) > 0
        
        # Image pack detection
        if "images_results" in response_data:
            features.image_pack = len(response_data["images_results"]) > 0
        
        # Video results detection
        if "video_results" in response_data:
            features.video_results = len(response_data["video_results"]) > 0
        
        # Local pack detection
        if "local_results" in response_data:
            features.local_pack = len(response_data["local_results"]) > 0
        elif "local_map" in response_data:
            features.local_pack = True
        
        # Knowledge panel detection
        if "knowledge_graph" in response_data:
            features.knowledge_panel = True
        
        # Shopping results detection
        if "shopping_results" in response_data:
            features.shopping_results = len(response_data["shopping_results"]) > 0
        
        # News results detection
        if "news_results" in response_data:
            features.news_results = len(response_data["news_results"]) > 0
        
        return features


class ResultTransformer:
    """
    Main transformer class for converting SerpAPI responses to structured data.
    
    Handles parsing of organic results, SERP feature detection, and conversion
    to internal data models for rank tracking and storage.
    """
    
    def __init__(self):
        self.position_extractor = PositionExtractor()
        self.feature_detector = SerpFeatureDetector()
    
    async def transform_response(
        self,
        response_data: Dict[str, Any],
        search_params: SearchParams,
        request_time: datetime
    ) -> SerpResult:
        """
        Transform SerpAPI response to SerpResult model.
        
        Args:
            response_data: Raw SerpAPI response
            search_params: Original search parameters
            request_time: When the request was made
            
        Returns:
            Parsed SerpResult object
            
        Raises:
            ValidationError: If response data is invalid
        """
        try:
            # Parse organic results
            organic_results = await self._parse_organic_results(
                response_data.get("organic_results", [])
            )
            
            # Detect SERP features
            serp_features = self.feature_detector.detect_features(response_data)
            
            # Extract search metadata
            search_info = response_data.get("search_information", {})
            total_results = self._safe_int(search_info.get("total_results"))
            time_taken = self._safe_float(search_info.get("time_taken_displayed"))
            
            # Extract SerpAPI metadata
            credits_info = response_data.get("search_metadata", {})
            credits_used = 1  # SerpAPI typically uses 1 credit per search
            
            result = SerpResult(
                search_params=search_params,
                timestamp=request_time,
                search_id=credits_info.get("id"),
                credits_used=credits_used,
                total_results=total_results,
                time_taken=time_taken,
                organic_results=organic_results,
                serp_features=serp_features,
                featured_snippet_result=response_data.get("answer_box"),
                people_also_ask=response_data.get("related_questions", []),
                local_results=response_data.get("local_results", [])
            )
            
            logger.debug(
                "Transformed SerpAPI response",
                query=search_params.query,
                organic_count=len(organic_results),
                features=serp_features.dict(),
                total_results=total_results
            )
            
            return result
            
        except Exception as e:
            logger.error(
                "Failed to transform SerpAPI response",
                query=search_params.query if search_params else 'unknown',
                error=str(e)
            )
            raise ValidationError(f"Response transformation failed: {str(e)}")
    
    async def _parse_organic_results(
        self, 
        organic_data: List[Dict[str, Any]]
    ) -> List[OrganicResult]:
        """Parse organic results from SerpAPI response."""
        results = []
        
        for i, result_data in enumerate(organic_data, 1):
            try:
                # Extract core fields with fallbacks
                title = result_data.get("title", "")
                link = result_data.get("link", "")
                displayed_link = result_data.get("displayed_link", link)
                snippet = result_data.get("snippet", "")
                
                # Validate required fields
                if not link or not title:
                    logger.warning("Skipping result with missing required fields", position=i)
                    continue
                
                # Check for sitelinks
                has_sitelinks = bool(result_data.get("sitelinks"))
                
                # Extract cached page link if available
                cached_link = result_data.get("cached_page_link")
                
                result = OrganicResult(
                    position=i,
                    title=title,
                    link=link,
                    displayed_link=displayed_link,
                    snippet=snippet,
                    sitelinks=has_sitelinks,
                    cached_page_link=cached_link
                    # domain and path will be auto-calculated by validator
                )
                
                results.append(result)
                
            except (ValidationError, KeyError, ValueError) as e:
                logger.warning(
                    "Skipping invalid organic result", 
                    position=i, 
                    error=str(e),
                    result_data=result_data
                )
                continue
        
        return results
    
    async def extract_ranking_data(
        self,
        serp_result: SerpResult,
        target_domain: str,
        site_id: Optional[str] = None,
        keyword_id: Optional[str] = None
    ) -> RankingData:
        """
        Extract ranking data for a specific domain from SerpResult.
        
        Args:
            serp_result: Parsed SERP result
            target_domain: Domain to extract ranking for
            site_id: Site UUID (optional, for database storage)
            keyword_id: Keyword UUID (optional, for database storage)
            
        Returns:
            RankingData object ready for storage
        """
        # Extract positions for target domain
        all_positions = self.position_extractor.find_domain_positions(
            serp_result.organic_results, target_domain
        )
        
        best_position = min(all_positions) if all_positions else None
        ranking_url = self.position_extractor.get_ranking_url(
            serp_result.organic_results, target_domain
        )
        
        # Extract top 10 competitor URLs (excluding target domain)
        competitor_urls = []
        normalized_target = self.position_extractor.normalize_domain(target_domain)
        
        for result in serp_result.organic_results[:10]:  # Top 10 only
            result_domain = self.position_extractor.normalize_domain(str(result.link))
            if result_domain != normalized_target:
                competitor_urls.append(str(result.link))
        
        # Build ranking data
        ranking_data = RankingData(
            site_id=site_id,
            keyword_id=keyword_id,
            keyword=serp_result.search_params.query,
            date=date.today(),
            location=serp_result.search_params.location.country,
            device=serp_result.search_params.device,
            position=best_position,
            url=ranking_url,
            all_positions=all_positions,
            serp_features=serp_result.serp_features,
            competitor_urls=competitor_urls,
            total_results=serp_result.total_results,
            credits_used=serp_result.credits_used or 1
        )
        
        logger.info(
            "Extracted ranking data",
            keyword=serp_result.search_params.query,
            domain=target_domain,
            position=best_position,
            all_positions=all_positions,
            competitors_found=len(competitor_urls)
        )
        
        return ranking_data
    
    async def extract_competitor_analysis(
        self,
        serp_result: SerpResult,
        target_domain: str,
        top_n: int = 10
    ) -> Dict[str, Any]:
        """
        Extract competitor analysis from SERP results.
        
        Args:
            serp_result: Parsed SERP result
            target_domain: Target domain for comparison
            top_n: Number of top results to analyze
            
        Returns:
            Competitor analysis data
        """
        normalized_target = self.position_extractor.normalize_domain(target_domain)
        
        # Analyze top N results
        top_results = serp_result.organic_results[:top_n]
        competitor_domains = set()
        domain_positions = {}
        
        for result in top_results:
            domain = self.position_extractor.normalize_domain(str(result.link))
            
            if domain != normalized_target:
                competitor_domains.add(domain)
                
                if domain not in domain_positions:
                    domain_positions[domain] = []
                domain_positions[domain].append({
                    'position': result.position,
                    'url': str(result.link),
                    'title': result.title,
                    'has_sitelinks': result.sitelinks
                })
        
        # Calculate competitor metrics
        analysis = {
            'query': serp_result.search_params.query,
            'target_domain': target_domain,
            'target_positions': self.position_extractor.find_domain_positions(
                serp_result.organic_results, target_domain
            ),
            'total_competitors': len(competitor_domains),
            'competitor_domains': list(competitor_domains),
            'domain_positions': domain_positions,
            'serp_features': serp_result.serp_features.dict(),
            'analysis_date': date.today().isoformat()
        }
        
        return analysis
    
    def _safe_int(self, value: Any) -> Optional[int]:
        """Safely convert value to int."""
        if value is None:
            return None
        try:
            # Handle string numbers with commas
            if isinstance(value, str):
                value = re.sub(r'[,\s]', '', value)
            return int(float(value))
        except (ValueError, TypeError):
            return None
    
    def _safe_float(self, value: Any) -> Optional[float]:
        """Safely convert value to float."""
        if value is None:
            return None
        try:
            # Handle string numbers with commas
            if isinstance(value, str):
                value = re.sub(r'[,\s]', '', value) 
                # Handle time strings like "0.34 seconds"
                value = re.sub(r'\s*(seconds?|s)\s*$', '', value, flags=re.IGNORECASE)
            return float(value)
        except (ValueError, TypeError):
            return None