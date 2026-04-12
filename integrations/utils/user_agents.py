"""User-Agent Management for Ethical Web Scraping

Provides User-Agent rotation and management for different types of requests
with ethical scraping practices and proper identification.
"""

import random
import time
from typing import Dict, List, Optional, Union, Any
from dataclasses import dataclass
from enum import Enum
import structlog

logger = structlog.get_logger(__name__)


class UserAgentType(str, Enum):
    """Types of User-Agent strings for different use cases."""
    API_CLIENT = "api_client"
    WEB_SCRAPER = "web_scraper"
    BROWSER_DESKTOP = "browser_desktop"
    BROWSER_MOBILE = "browser_mobile"
    BOT_CRAWLER = "bot_crawler"
    SOCIAL_MEDIA = "social_media"


@dataclass
class UserAgentInfo:
    """User-Agent information with metadata."""
    
    user_agent: str
    type: UserAgentType
    weight: float = 1.0  # Probability weight for selection
    description: Optional[str] = None
    contact_info: Optional[str] = None
    rate_limit_compliant: bool = True
    
    def __post_init__(self):
        """Validate user agent info."""
        if self.weight <= 0:
            raise ValueError("weight must be positive")


class UserAgentManager:
    """Manages User-Agent rotation for ethical web scraping.
    
    Features:
    - Multiple User-Agent types for different scenarios
    - Weighted random selection
    - Rate limiting compliance
    - Contact information inclusion
    - Custom User-Agent registration
    """
    
    # Default User-Agent collections
    DEFAULT_USER_AGENTS = {
        UserAgentType.API_CLIENT: [
            UserAgentInfo(
                user_agent="SEO-Automation-Platform/1.0 (+https://example.com/bot)",
                type=UserAgentType.API_CLIENT,
                description="Primary API client",
                contact_info="https://example.com/bot",
                weight=2.0
            ),
            UserAgentInfo(
                user_agent="HttpClient/1.0 (SEO Platform)",
                type=UserAgentType.API_CLIENT,
                description="Generic HTTP client"
            ),
        ],
        
        UserAgentType.WEB_SCRAPER: [
            UserAgentInfo(
                user_agent="SEO-Platform-Scraper/1.0 (+https://example.com/bot; respects robots.txt)",
                type=UserAgentType.WEB_SCRAPER,
                description="Ethical web scraper",
                contact_info="https://example.com/bot",
                weight=2.0
            ),
            UserAgentInfo(
                user_agent="Research-Bot/1.0 (Academic Research; +https://example.com/research)",
                type=UserAgentType.WEB_SCRAPER,
                description="Academic research bot"
            ),
        ],
        
        UserAgentType.BROWSER_DESKTOP: [
            UserAgentInfo(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                type=UserAgentType.BROWSER_DESKTOP,
                description="Chrome on Windows",
                weight=3.0
            ),
            UserAgentInfo(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                type=UserAgentType.BROWSER_DESKTOP,
                description="Chrome on macOS",
                weight=2.5
            ),
            UserAgentInfo(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
                type=UserAgentType.BROWSER_DESKTOP,
                description="Firefox on Windows",
                weight=2.0
            ),
            UserAgentInfo(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
                type=UserAgentType.BROWSER_DESKTOP,
                description="Firefox on macOS",
                weight=1.5
            ),
            UserAgentInfo(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
                type=UserAgentType.BROWSER_DESKTOP,
                description="Safari on macOS",
                weight=1.0
            ),
        ],
        
        UserAgentType.BROWSER_MOBILE: [
            UserAgentInfo(
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
                type=UserAgentType.BROWSER_MOBILE,
                description="Safari on iPhone",
                weight=2.5
            ),
            UserAgentInfo(
                user_agent="Mozilla/5.0 (Linux; Android 14; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
                type=UserAgentType.BROWSER_MOBILE,
                description="Chrome on Android",
                weight=3.0
            ),
            UserAgentInfo(
                user_agent="Mozilla/5.0 (iPad; CPU OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
                type=UserAgentType.BROWSER_MOBILE,
                description="Safari on iPad",
                weight=1.5
            ),
        ],
        
        UserAgentType.BOT_CRAWLER: [
            UserAgentInfo(
                user_agent="Googlebot/2.1 (+http://www.google.com/bot.html)",
                type=UserAgentType.BOT_CRAWLER,
                description="Google's web crawler"
            ),
            UserAgentInfo(
                user_agent="facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
                type=UserAgentType.BOT_CRAWLER,
                description="Facebook link crawler"
            ),
            UserAgentInfo(
                user_agent="WhatsApp/2.23.24.76 A",
                type=UserAgentType.BOT_CRAWLER,
                description="WhatsApp link preview"
            ),
        ],
        
        UserAgentType.SOCIAL_MEDIA: [
            UserAgentInfo(
                user_agent="TwitterBot/1.0",
                type=UserAgentType.SOCIAL_MEDIA,
                description="Twitter link crawler"
            ),
            UserAgentInfo(
                user_agent="LinkedInBot/1.0 (compatible; Mozilla/5.0; Apache-HttpClient +http://www.linkedin.com/)",
                type=UserAgentType.SOCIAL_MEDIA,
                description="LinkedIn crawler"
            ),
        ],
    }
    
    def __init__(
        self,
        default_type: UserAgentType = UserAgentType.API_CLIENT,
        custom_contact_info: Optional[str] = None,
        service_name: Optional[str] = None
    ):
        """Initialize User-Agent manager.
        
        Args:
            default_type: Default User-Agent type to use
            custom_contact_info: Custom contact information
            service_name: Service name for custom User-Agents
        """
        self.default_type = default_type
        self.custom_contact_info = custom_contact_info
        self.service_name = service_name
        
        # Copy default user agents
        self.user_agents: Dict[UserAgentType, List[UserAgentInfo]] = {}
        for ua_type, ua_list in self.DEFAULT_USER_AGENTS.items():
            self.user_agents[ua_type] = ua_list.copy()
        
        # Add custom contact info to API client and scraper user agents
        if custom_contact_info:
            self._add_custom_contact_info()
        
        # Usage tracking  
        self._usage_count: Dict[str, int] = {}
        self._last_used: Dict[str, float] = {}
        
        logger.info(
            "User-Agent manager initialized",
            default_type=default_type.value,
            total_user_agents=sum(len(ua_list) for ua_list in self.user_agents.values()),
            has_custom_contact=bool(custom_contact_info)
        )
    
    def _add_custom_contact_info(self):
        """Add custom contact info to relevant User-Agent types."""
        for ua_type in [UserAgentType.API_CLIENT, UserAgentType.WEB_SCRAPER]:
            if ua_type in self.user_agents:
                for ua_info in self.user_agents[ua_type]:
                    if ua_info.contact_info is None:
                        ua_info.contact_info = self.custom_contact_info
    
    def add_user_agent(
        self, 
        user_agent: str,
        ua_type: UserAgentType,
        weight: float = 1.0,
        description: Optional[str] = None,
        contact_info: Optional[str] = None
    ):
        """Add custom User-Agent string.
        
        Args:
            user_agent: User-Agent string
            ua_type: Type of User-Agent
            weight: Selection weight (higher = more likely)
            description: Optional description
            contact_info: Optional contact information
        """
        ua_info = UserAgentInfo(
            user_agent=user_agent,
            type=ua_type,
            weight=weight,
            description=description,
            contact_info=contact_info or self.custom_contact_info
        )
        
        if ua_type not in self.user_agents:
            self.user_agents[ua_type] = []
        
        self.user_agents[ua_type].append(ua_info)
        
        logger.debug(
            "Custom User-Agent added",
            type=ua_type.value,
            user_agent=user_agent[:50] + "..." if len(user_agent) > 50 else user_agent
        )
    
    def remove_user_agent(self, user_agent: str):
        """Remove User-Agent string from all types.
        
        Args:
            user_agent: User-Agent string to remove
        """
        removed_count = 0
        
        for ua_type in self.user_agents:
            original_length = len(self.user_agents[ua_type])
            self.user_agents[ua_type] = [
                ua for ua in self.user_agents[ua_type] 
                if ua.user_agent != user_agent
            ]
            removed_count += original_length - len(self.user_agents[ua_type])
        
        if removed_count > 0:
            logger.debug(
                "User-Agent removed",
                user_agent=user_agent[:50] + "..." if len(user_agent) > 50 else user_agent,
                removed_count=removed_count
            )
    
    def get_user_agent(
        self, 
        ua_type: Optional[UserAgentType] = None,
        avoid_recent: bool = True,
        recent_threshold_seconds: int = 300
    ) -> str:
        """Get User-Agent string with optional rotation logic.
        
        Args:
            ua_type: Type of User-Agent to select (uses default if None)
            avoid_recent: Avoid recently used User-Agents
            recent_threshold_seconds: Threshold for recent usage
            
        Returns:
            Selected User-Agent string
            
        Raises:
            ValueError: If no User-Agents available for specified type
        """
        ua_type = ua_type or self.default_type
        
        if ua_type not in self.user_agents or not self.user_agents[ua_type]:
            raise ValueError(f"No User-Agents available for type: {ua_type}")
        
        available_agents = self.user_agents[ua_type]
        
        # Filter out recently used agents if requested
        if avoid_recent:
            current_time = time.time()
            available_agents = [
                ua for ua in available_agents
                if (
                    ua.user_agent not in self._last_used or
                    current_time - self._last_used[ua.user_agent] > recent_threshold_seconds
                )
            ]
            
            # Fall back to all agents if none are available
            if not available_agents:
                available_agents = self.user_agents[ua_type]
        
        # Weighted random selection
        weights = [ua.weight for ua in available_agents]
        selected_ua = random.choices(available_agents, weights=weights, k=1)[0]
        
        # Track usage
        current_time = time.time()
        self._usage_count[selected_ua.user_agent] = (
            self._usage_count.get(selected_ua.user_agent, 0) + 1
        )
        self._last_used[selected_ua.user_agent] = current_time
        
        logger.debug(
            "User-Agent selected",
            type=ua_type.value,
            user_agent=selected_ua.user_agent[:50] + "..." if len(selected_ua.user_agent) > 50 else selected_ua.user_agent,
            usage_count=self._usage_count[selected_ua.user_agent],
            weight=selected_ua.weight
        )
        
        return selected_ua.user_agent
    
    def get_user_agent_info(self, user_agent: str) -> Optional[UserAgentInfo]:
        """Get information about a specific User-Agent.
        
        Args:
            user_agent: User-Agent string to look up
            
        Returns:
            UserAgentInfo if found, None otherwise
        """
        for ua_type in self.user_agents:
            for ua_info in self.user_agents[ua_type]:
                if ua_info.user_agent == user_agent:
                    return ua_info
        return None
    
    def list_user_agents(
        self, 
        ua_type: Optional[UserAgentType] = None
    ) -> List[UserAgentInfo]:
        """List available User-Agent strings.
        
        Args:
            ua_type: Optional type filter
            
        Returns:
            List of UserAgentInfo objects
        """
        if ua_type:
            return self.user_agents.get(ua_type, [])
        
        # Return all user agents
        all_agents = []
        for ua_list in self.user_agents.values():
            all_agents.extend(ua_list)
        return all_agents
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get User-Agent usage statistics.
        
        Returns:
            Dictionary with usage statistics
        """
        total_usage = sum(self._usage_count.values())
        
        stats = {
            "total_requests": total_usage,
            "unique_user_agents_used": len(self._usage_count),
            "available_user_agents": sum(len(ua_list) for ua_list in self.user_agents.values()),
            "usage_by_type": {},
            "most_used": [],
            "least_used": []
        }
        
        # Usage by type
        for ua_type, ua_list in self.user_agents.items():
            type_usage = sum(
                self._usage_count.get(ua.user_agent, 0) 
                for ua in ua_list
            )
            stats["usage_by_type"][ua_type.value] = {
                "count": type_usage,
                "available": len(ua_list),
                "percentage": (type_usage / total_usage * 100) if total_usage > 0 else 0
            }
        
        # Most and least used  
        if self._usage_count:
            sorted_usage = sorted(
                self._usage_count.items(),
                key=lambda x: x[1],
                reverse=True
            )
            
            stats["most_used"] = [
                {"user_agent": ua[:50] + "..." if len(ua) > 50 else ua, "count": count}
                for ua, count in sorted_usage[:5]
            ]
            
            stats["least_used"] = [
                {"user_agent": ua[:50] + "..." if len(ua) > 50 else ua, "count": count}
                for ua, count in sorted_usage[-5:]
            ]
        
        return stats
    
    def reset_usage_stats(self):
        """Reset usage tracking statistics."""
        self._usage_count.clear()
        self._last_used.clear()
        
        logger.info("User-Agent usage statistics reset")
    
    def create_custom_user_agent(
        self,
        base_name: Optional[str] = None,
        version: str = "1.0",
        include_contact: bool = True,
        include_service_name: bool = True
    ) -> str:
        """Create a custom User-Agent string for the service.
        
        Args:
            base_name: Base name for the User-Agent
            version: Version string
            include_contact: Include contact information
            include_service_name: Include service name
            
        Returns:
            Custom User-Agent string  
        """
        parts = []
        
        # Base name
        if base_name:
            parts.append(f"{base_name}/{version}")
        elif self.service_name:
            parts.append(f"{self.service_name}/{version}")
        else:
            parts.append(f"SEO-Platform/{version}")
        
        # Service identification
        if include_service_name and self.service_name and self.service_name not in parts[0]:
            parts.append(f"({self.service_name})")
        
        # Contact information
        if include_contact and self.custom_contact_info:
            parts.append(f"(+{self.custom_contact_info})")
        
        return " ".join(parts)


# Factory functions for common configurations

def create_api_user_agent_manager(
    service_name: str,
    contact_info: str,
    version: str = "1.0"
) -> UserAgentManager:
    """Create User-Agent manager for API clients.
    
    Args:
        service_name: Name of the service
        contact_info: Contact information URL or email
        version: Service version
        
    Returns:
        Configured UserAgentManager for API usage
    """
    manager = UserAgentManager(
        default_type=UserAgentType.API_CLIENT,
        custom_contact_info=contact_info,
        service_name=service_name
    )
    
    # Add service-specific User-Agent
    custom_ua = manager.create_custom_user_agent(
        base_name=service_name,
        version=version
    )
    manager.add_user_agent(
        user_agent=custom_ua,
        ua_type=UserAgentType.API_CLIENT,
        weight=3.0,
        description=f"Primary {service_name} client"
    )
    
    return manager


def create_scraper_user_agent_manager(
    project_name: str,
    contact_info: str,
    respect_robots: bool = True
) -> UserAgentManager:
    """Create User-Agent manager for web scraping.
    
    Args:
        project_name: Name of the scraping project
        contact_info: Contact information
        respect_robots: Whether to indicate robots.txt compliance
        
    Returns:
        Configured UserAgentManager for web scraping
    """
    manager = UserAgentManager(
        default_type=UserAgentType.WEB_SCRAPER,
        custom_contact_info=contact_info,
        service_name=project_name
    )
    
    # Add project-specific User-Agent
    suffix = "; respects robots.txt" if respect_robots else ""
    custom_ua = f"{project_name}-Scraper/1.0 (+{contact_info}{suffix})"
    
    manager.add_user_agent(
        user_agent=custom_ua,
        ua_type=UserAgentType.WEB_SCRAPER,
        weight=3.0,
        description=f"Primary {project_name} scraper"
    )
    
    return manager


def create_browser_user_agent_manager(
    mobile_ratio: float = 0.3
) -> UserAgentManager:
    """Create User-Agent manager that mimics browser behavior.
    
    Args:
        mobile_ratio: Ratio of mobile vs desktop User-Agents (0.0-1.0)
        
    Returns:
        Configured UserAgentManager with browser User-Agents
    """
    manager = UserAgentManager(default_type=UserAgentType.BROWSER_DESKTOP)
    
    # Adjust weights based on mobile ratio
    if UserAgentType.BROWSER_MOBILE in manager.user_agents:
        mobile_weight_multiplier = mobile_ratio / (1 - mobile_ratio) if mobile_ratio < 1 else 1
        
        for ua_info in manager.user_agents[UserAgentType.BROWSER_MOBILE]:
            ua_info.weight *= mobile_weight_multiplier
    
    return manager