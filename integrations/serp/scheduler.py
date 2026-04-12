"""
SerpAPI Rank Tracking Scheduler

Automated daily keyword rank tracking with intelligent job scheduling,
priority queues, quota management, and failure recovery optimized for
SerpAPI's micro plan constraints.
"""

import asyncio
from datetime import datetime, date, time, timedelta, timezone
from typing import Dict, List, Optional, Union, Set, Callable
from dataclasses import dataclass, field
from enum import Enum
from uuid import UUID, uuid4

import structlog
from pydantic import BaseModel, Field

from db.models import Site, Keyword, Ranking, KeywordPriority, ApprovalStatus
from db.connection import get_database_manager
from task_queue.producer import TaskProducer
from task_queue.models import TaskData, TaskStatus, TaskPriority
from notifications.publisher import NotificationPublisher

from .client import SerpAPIClient, SerpAPIQuotaError
from .models import SearchParams, LocationTarget, DeviceType, RankingData
from .cache import ResultCache, CachePolicy

logger = structlog.get_logger(__name__)


class TrackingMode(str, Enum):
    """Keyword tracking modes."""
    DAILY = "daily"           # Track once per day
    WEEKLY = "weekly"         # Track once per week  
    PRIORITY = "priority"     # Track based on keyword priority
    MANUAL = "manual"         # Manual tracking only


class JobStatus(str, Enum):
    """Tracking job status."""
    PENDING = "pending"       # Waiting to be processed
    RUNNING = "running"       # Currently being processed
    COMPLETED = "completed"   # Successfully completed
    FAILED = "failed"        # Failed with error
    CANCELLED = "cancelled"   # Manually cancelled
    QUOTA_EXCEEDED = "quota_exceeded"  # Stopped due to quota limits


@dataclass
class TrackingJob:
    """Individual keyword tracking job."""
    
    job_id: UUID = field(default_factory=uuid4)
    site_id: UUID = field(...)
    keyword_ids: List[UUID] = field(default_factory=list)
    
    # Scheduling
    scheduled_date: date = field(default_factory=date.today)
    scheduled_time: Optional[time] = None
    priority: TaskPriority = TaskPriority.NORMAL
    
    # Search parameters
    location: LocationTarget = field(default_factory=lambda: LocationTarget(country="US"))
    device: DeviceType = DeviceType.DESKTOP
    num_results: int = 100
    
    # Status tracking
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Results
    rankings_tracked: int = 0
    credits_used: int = 0
    error_message: Optional[str] = None
    
    @property
    def is_ready(self) -> bool:
        """Check if job is ready to run."""
        if self.status != JobStatus.PENDING:
            return False
        
        now = datetime.now()
        job_datetime = datetime.combine(
            self.scheduled_date,
            self.scheduled_time or time(6, 0)  # Default to 6 AM
        )
        
        return now >= job_datetime
    
    @property
    def estimated_credits(self) -> int:
        """Estimate credits needed for this job."""
        return len(self.keyword_ids)


class RankScheduler:
    """
    Automated rank tracking scheduler with quota management and priority queues.
    
    Features:
    - Daily/weekly scheduling with configurable times
    - Priority-based job queuing (critical keywords first)
    - Quota management and budget allocation
    - Failure recovery with exponential backoff
    - Batch processing for efficiency
    - Integration with approval workflows for publishes
    """
    
    def __init__(
        self,
        serpapi_client: Optional[SerpAPIClient] = None,
        task_producer: Optional[TaskProducer] = None,
        notification_publisher: Optional[NotificationPublisher] = None,
        daily_quota_budget: int = 3,  # Conservative for micro plan
        tracking_mode: TrackingMode = TrackingMode.PRIORITY
    ):
        """
        Initialize rank scheduler.
        
        Args:
            serpapi_client: SerpAPI client instance
            task_producer: Task queue producer
            notification_publisher: Notification publisher
            daily_quota_budget: Max keywords to track per day
            tracking_mode: Default tracking mode
        """
        self.serpapi_client = serpapi_client
        self.task_producer = task_producer
        self.notification_publisher = notification_publisher
        self.daily_quota_budget = daily_quota_budget
        self.tracking_mode = tracking_mode
        
        # Job management
        self._pending_jobs: List[TrackingJob] = []
        self._running_jobs: Dict[UUID, TrackingJob] = {}
        self._completed_jobs: List[TrackingJob] = []
        
        # Quota tracking
        self._daily_credits_used = 0
        self._last_quota_reset = date.today()
        
        # Scheduling configuration
        self.default_tracking_time = time(6, 0)  # 6 AM default
        self.max_concurrent_jobs = 1  # Process jobs sequentially for quota control
        
        logger.info(
            "Rank scheduler initialized",
            daily_budget=daily_quota_budget,
            tracking_mode=tracking_mode.value,
            default_time=self.default_tracking_time
        )
    
    async def schedule_site_tracking(
        self,
        site_id: UUID,
        keywords: Optional[List[UUID]] = None,
        scheduled_date: Optional[date] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        location: Union[LocationTarget, str] = "US",
        device: DeviceType = DeviceType.DESKTOP
    ) -> TrackingJob:
        """
        Schedule rank tracking for a site's keywords.
        
        Args:
            site_id: Site to track
            keywords: Specific keywords to track (defaults to all active)
            scheduled_date: When to run tracking (defaults to today)
            priority: Job priority level
            location: Geographic location for tracking
            device: Device type for search
            
        Returns:
            Created tracking job
            
        Raises:
            ValueError: If invalid parameters provided
        """
        if isinstance(location, str):
            location = LocationTarget(country=location)
        
        # Get keywords if not specified
        if keywords is None:
            db_manager = get_database_manager()
            async with db_manager.async_connection() as conn:
                # Get active keywords for the site
                query = """
                    SELECT id FROM keywords 
                    WHERE site_id = $1 AND status = 'active'
                """
                rows = await conn.fetch(query, site_id)
                keywords = [row['id'] for row in rows]
        
        if not keywords:
            raise ValueError(f"No active keywords found for site {site_id}")
        
        # Check quota before scheduling
        estimated_credits = len(keywords)
        if self._daily_credits_used + estimated_credits > self.daily_quota_budget:
            raise SerpAPIQuotaError(
                f"Insufficient daily quota for {estimated_credits} keywords. "
                f"Used: {self._daily_credits_used}, Budget: {self.daily_quota_budget}",
                used_credits=self._daily_credits_used,
                total_credits=self.daily_quota_budget
            )
        
        job = TrackingJob(
            site_id=site_id,
            keyword_ids=keywords,
            scheduled_date=scheduled_date or date.today(),
            scheduled_time=self.default_tracking_time,
            priority=priority,
            location=location,
            device=device
        )
        
        # Add to pending jobs queue
        self._pending_jobs.append(job)
        self._sort_pending_jobs()
        
        logger.info(
            "Scheduled site tracking",
            job_id=job.job_id,
            site_id=site_id,
            keyword_count=len(keywords),
            scheduled_date=job.scheduled_date,
            priority=priority.value
        )
        
        return job
    
    async def schedule_daily_tracking(self) -> List[TrackingJob]:
        """
        Schedule daily tracking for all active sites with priority-based selection.
        
        Returns:
            List of scheduled jobs
        """
        jobs = []
        remaining_budget = self.daily_quota_budget - self._daily_credits_used
        
        if remaining_budget <= 0:
            logger.warning("No remaining quota for daily tracking", 
                         used=self._daily_credits_used, budget=self.daily_quota_budget)
            return jobs
        
        async with get_database_manager().async_connection() as conn:
            # Get sites with active keywords, prioritized by critical keywords
            query = """
                SELECT s.id, s.name, 
                       COUNT(k.id) as keyword_count,
                       SUM(
                           CASE k.priority
                               WHEN 'critical' THEN 3
                               WHEN 'high' THEN 2
                               WHEN 'medium' THEN 1
                               ELSE 0
                           END
                       ) as priority_score
                FROM sites s
                JOIN keywords k ON s.id = k.site_id
                WHERE s.status = 'active' AND k.status = 'active'
                GROUP BY s.id, s.name
                ORDER BY priority_score DESC
            """
            
            sites_data = await conn.fetch(query)
        
        # Allocate budget based on priority
        for site_row in sites_data:
            site_id = site_row['id']
            site_name = site_row['name']
            keyword_count = site_row['keyword_count']
            priority_score = site_row['priority_score']
            
            if remaining_budget <= 0:
                break
            
            # Select keywords based on priority and budget
            keywords_to_track = await self._select_priority_keywords(
                site_id, min(keyword_count, remaining_budget)
            )
            
            if keywords_to_track:
                try:
                    job = await self.schedule_site_tracking(
                        site_id=site_id,
                        keywords=keywords_to_track,
                        priority=TaskPriority.HIGH if priority_score > keyword_count else TaskPriority.NORMAL
                    )
                    jobs.append(job)
                    remaining_budget -= len(keywords_to_track)
                    
                except SerpAPIQuotaError:
                    logger.warning("Quota exceeded while scheduling daily tracking")
                    break
        
        logger.info(
            "Daily tracking scheduled",
            jobs_created=len(jobs),
            budget_used=self.daily_quota_budget - remaining_budget,
            remaining_budget=remaining_budget
        )
        
        return jobs
    
    async def _select_priority_keywords(
        self,
        site_id: UUID,
        max_keywords: int
    ) -> List[UUID]:
        """Select highest priority keywords for tracking within budget."""
        async with get_database_manager().async_connection() as conn:
            query = """
                SELECT id FROM keywords
                WHERE site_id = $1 AND status = 'active'
                ORDER BY 
                    CASE priority
                        WHEN 'critical' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3
                        WHEN 'low' THEN 4
                        ELSE 5
                    END,
                    monthly_search_volume DESC NULLS LAST,
                    created_at DESC
                LIMIT $2
            """
            
            rows = await conn.fetch(query, site_id, max_keywords)
            return [row['id'] for row in rows]
    
    def _sort_pending_jobs(self):
        """Sort pending jobs by priority and scheduled time."""
        self._pending_jobs.sort(key=lambda job: (
            job.priority.value,  # Higher priority first (enum values are ordered)
            job.scheduled_date,
            job.scheduled_time or self.default_tracking_time
        ))
    
    async def process_pending_jobs(self, max_jobs: Optional[int] = None) -> List[TrackingJob]:
        """
        Process pending jobs that are ready to run.
        
        Args:
            max_jobs: Maximum number of jobs to process (None for all ready)
            
        Returns:
            List of processed jobs
        """
        processed_jobs = []
        jobs_to_process = []
        
        # Find ready jobs
        for job in self._pending_jobs:
            if job.is_ready and len(jobs_to_process) < (max_jobs or float('inf')):
                if len(self._running_jobs) >= self.max_concurrent_jobs:
                    break  # Don't exceed concurrent limit
                jobs_to_process.append(job)
        
        # Process jobs
        for job in jobs_to_process:
            try:
                await self._execute_tracking_job(job)
                processed_jobs.append(job)
            except Exception as e:
                logger.error(
                    "Failed to start tracking job",
                    job_id=job.job_id,
                    error=str(e)
                )
                job.status = JobStatus.FAILED
                job.error_message = str(e)
        
        # Remove processed jobs from pending
        for job in jobs_to_process:
            if job in self._pending_jobs:
                self._pending_jobs.remove(job)
        
        return processed_jobs
    
    async def _execute_tracking_job(self, job: TrackingJob):
        """Execute a single tracking job."""
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        self._running_jobs[job.job_id] = job
        
        try:
            # Get keywords and site info
            keywords_data = await self._get_keywords_data(job.keyword_ids)
            site_data = await self._get_site_data(job.site_id)
            
            if not keywords_data or not site_data:
                raise ValueError("Failed to load job data")
            
            # Initialize SerpAPI client if needed
            if not self.serpapi_client:
                self.serpapi_client = SerpAPIClient()
            
            # Track keywords
            rankings_data = []
            for keyword_data in keywords_data:
                try:
                    # Create search parameters
                    search_params = SearchParams(
                        query=keyword_data['keyword'],
                        location=job.location,
                        device=job.device,
                        num_results=job.num_results
                    )
                    
                    # Perform search
                    serp_result = await self.serpapi_client.search(search_params)
                    
                    # Extract ranking data
                    ranking_data = await self.serpapi_client._transformer.extract_ranking_data(
                        serp_result, site_data['primary_domain'], job.site_id, keyword_data['id']
                    )
                    
                    rankings_data.append(ranking_data)
                    job.credits_used += 1
                    
                    # Update quota tracking
                    self._daily_credits_used += 1
                    
                    # Small delay between requests
                    await asyncio.sleep(0.5)
                    
                except SerpAPIQuotaError as e:
                    logger.warning("Quota exceeded during job execution", job_id=job.job_id)
                    job.status = JobStatus.QUOTA_EXCEEDED
                    job.error_message = str(e)
                    break
                    
                except Exception as e:
                    logger.error(
                        "Failed to track keyword",
                        job_id=job.job_id,
                        keyword=keyword_data['keyword'],
                        error=str(e)
                    )
                    # Continue with other keywords
                    continue
            
            # Store results in database
            await self._store_ranking_results(rankings_data)
            
            job.rankings_tracked = len(rankings_data)
            if job.status == JobStatus.RUNNING:  # Not cancelled by quota
                job.status = JobStatus.COMPLETED
            
            logger.info(
                "Tracking job completed",
                job_id=job.job_id,
                rankings_tracked=job.rankings_tracked,
                credits_used=job.credits_used,
                status=job.status.value
            )
            
        except Exception as e:
            logger.error("Tracking job failed", job_id=job.job_id, error=str(e))
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            
        finally:
            job.completed_at = datetime.now(timezone.utc)
            self._running_jobs.pop(job.job_id, None)
            self._completed_jobs.append(job)
    
    async def _get_keywords_data(self, keyword_ids: List[UUID]) -> List[Dict]:
        """Get keyword data from database."""
        async with get_database_manager().async_connection() as conn:
            query = """
                SELECT id, keyword, priority
                FROM keywords 
                WHERE id = ANY($1) AND status = 'active'
            """
            rows = await conn.fetch(query, keyword_ids)
            
            return [
                {'id': row['id'], 'keyword': row['keyword'], 'priority': row['priority']}
                for row in rows
            ]
    
    async def _get_site_data(self, site_id: UUID) -> Optional[Dict]:
        """Get site data from database."""
        async with get_database_manager().async_connection() as conn:
            query = """
                SELECT id, primary_domain, target_country, target_language
                FROM sites 
                WHERE id = $1
            """
            row = await conn.fetchrow(query, site_id)
            
            if row:
                return {
                    'id': row['id'],
                    'primary_domain': row['primary_domain'],
                    'target_country': row['target_country'],
                    'target_language': row['target_language']
                }
            return None
    
    async def _store_ranking_results(self, rankings_data: List[RankingData]):
        """Store ranking results in database."""
        if not rankings_data:
            return
        
        async with get_database_manager().async_connection() as conn:
            for ranking_data in rankings_data:
                # Check if ranking already exists for today
                check_query = """
                    SELECT id FROM rankings
                    WHERE site_id = $1 AND keyword_id = $2 AND date = $3
                """
                existing = await conn.fetchrow(
                    check_query, 
                    ranking_data.site_id, 
                    ranking_data.keyword_id, 
                    ranking_data.date
                )
                
                if existing:
                    # Update existing ranking
                    update_query = """
                        UPDATE rankings 
                        SET position = $1, url = $2, 
                            featured_snippet = $3, image_pack = $4, local_pack = $5,
                            updated_at = NOW()
                        WHERE id = $6
                    """
                    await conn.execute(
                        update_query,
                        ranking_data.position,
                        str(ranking_data.url) if ranking_data.url else None,
                        ranking_data.serp_features.featured_snippet,
                        ranking_data.serp_features.image_pack,
                        ranking_data.serp_features.local_pack,
                        existing['id']
                    )
                else:
                    # Insert new ranking
                    import uuid
                    insert_query = """
                        INSERT INTO rankings (
                            id, site_id, keyword_id, date, position, url,
                            featured_snippet, image_pack, local_pack,
                            created_at, updated_at
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), NOW())
                    """
                    await conn.execute(
                        insert_query,
                        uuid.uuid4(),
                        ranking_data.site_id,
                        ranking_data.keyword_id,
                        ranking_data.date,
                        ranking_data.position,
                        str(ranking_data.url) if ranking_data.url else None,
                        ranking_data.serp_features.featured_snippet,
                        ranking_data.serp_features.image_pack,
                        ranking_data.serp_features.local_pack
                    )
    
    def get_job_status(self, job_id: UUID) -> Optional[TrackingJob]:
        """Get status of a tracking job."""
        # Check running jobs
        if job_id in self._running_jobs:
            return self._running_jobs[job_id]
        
        # Check pending jobs
        for job in self._pending_jobs:
            if job.job_id == job_id:
                return job
        
        # Check completed jobs
        for job in self._completed_jobs:
            if job.job_id == job_id:
                return job
        
        return None
    
    def get_daily_quota_status(self) -> Dict[str, Any]:
        """Get current daily quota status."""
        return {
            'date': date.today().isoformat(),
            'budget': self.daily_quota_budget,
            'used': self._daily_credits_used,
            'remaining': self.daily_quota_budget - self._daily_credits_used,
            'usage_percentage': (self._daily_credits_used / self.daily_quota_budget) * 100,
            'pending_jobs': len(self._pending_jobs),
            'running_jobs': len(self._running_jobs),
            'completed_jobs': len(self._completed_jobs)
        }
    
    def reset_daily_quota(self):
        """Reset daily quota tracking (called automatically at midnight)."""
        self._daily_credits_used = 0
        self._last_quota_reset = date.today()
        
        # Clean up old completed jobs (keep last 100)
        self._completed_jobs = self._completed_jobs[-100:]
        
        logger.info("Daily quota reset", budget=self.daily_quota_budget)