"""
Tests for User-Agent management system.

Tests User-Agent rotation, selection logic, ethical scraping features,
and factory functions for different use cases.
"""

import time
from unittest.mock import patch
import pytest

from integrations.utils.user_agents import (
    UserAgentManager, UserAgentType, UserAgentInfo,
    create_api_user_agent_manager, create_scraper_user_agent_manager,
    create_browser_user_agent_manager
)


class TestUserAgentInfo:
    """Test UserAgentInfo data class."""
    
    def test_user_agent_info_creation(self):
        """Test UserAgentInfo creation and validation."""
        ua_info = UserAgentInfo(
            user_agent="Test-Agent/1.0",
            type=UserAgentType.API_CLIENT,
            weight=2.0,
            description="Test agent",
            contact_info="https://example.com/bot"
        )
        
        assert ua_info.user_agent == "Test-Agent/1.0"
        assert ua_info.type == UserAgentType.API_CLIENT
        assert ua_info.weight == 2.0
        assert ua_info.description == "Test agent"
        assert ua_info.contact_info == "https://example.com/bot"
        assert ua_info.rate_limit_compliant is True  # Default
    
    def test_user_agent_info_validation(self):
        """Test UserAgentInfo validation."""
        # Invalid weight should raise error
        with pytest.raises(ValueError, match="weight must be positive"):
            UserAgentInfo(
                user_agent="Test-Agent/1.0",
                type=UserAgentType.API_CLIENT,
                weight=0.0
            )


class TestUserAgentManager:
    """Test UserAgentManager functionality."""
    
    def test_manager_initialization(self):
        """Test UserAgentManager initialization."""
        manager = UserAgentManager(
            default_type=UserAgentType.WEB_SCRAPER,
            custom_contact_info="https://example.com/contact",
            service_name="TestService"
        )
        
        assert manager.default_type == UserAgentType.WEB_SCRAPER
        assert manager.custom_contact_info == "https://example.com/contact"
        assert manager.service_name == "TestService"
        
        # Should have default user agents for all types
        assert UserAgentType.API_CLIENT in manager.user_agents
        assert UserAgentType.WEB_SCRAPER in manager.user_agents
        assert UserAgentType.BROWSER_DESKTOP in manager.user_agents
        assert UserAgentType.BROWSER_MOBILE in manager.user_agents
        assert UserAgentType.BOT_CRAWLER in manager.user_agents
        assert UserAgentType.SOCIAL_MEDIA in manager.user_agents
    
    def test_get_user_agent_default_type(self):
        """Test getting User-Agent with default type."""
        manager = UserAgentManager(default_type=UserAgentType.API_CLIENT)
        
        user_agent = manager.get_user_agent()
        
        # Should return a User-Agent from the default type
        api_client_agents = [ua.user_agent for ua in manager.user_agents[UserAgentType.API_CLIENT]]
        assert user_agent in api_client_agents
        
        # Should track usage
        assert user_agent in manager._usage_count
        assert manager._usage_count[user_agent] == 1
    
    def test_get_user_agent_specific_type(self):
        """Test getting User-Agent for specific type."""
        manager = UserAgentManager()
        
        # Get browser desktop User-Agent
        user_agent = manager.get_user_agent(UserAgentType.BROWSER_DESKTOP)
        
        desktop_agents = [ua.user_agent for ua in manager.user_agents[UserAgentType.BROWSER_DESKTOP]]
        assert user_agent in desktop_agents
    
    def test_get_user_agent_invalid_type(self):
        """Test getting User-Agent for type with no agents."""
        manager = UserAgentManager()
        
        # Clear all agents for API_CLIENT type
        manager.user_agents[UserAgentType.API_CLIENT] = []
        
        with pytest.raises(ValueError, match="No User-Agents available"):
            manager.get_user_agent(UserAgentType.API_CLIENT)
    
    def test_weighted_selection(self):
        """Test weighted User-Agent selection."""
        manager = UserAgentManager()
        
        # Add custom User-Agent with very high weight
        high_weight_ua = "HighWeight-Agent/1.0"
        manager.add_user_agent(
            user_agent=high_weight_ua,
            ua_type=UserAgentType.API_CLIENT,
            weight=100.0  # Much higher than default weights
        )
        
        # Request many User-Agents and check distribution
        selections = []
        for _ in range(100):
            ua = manager.get_user_agent(UserAgentType.API_CLIENT, avoid_recent=False)
            selections.append(ua)
        
        # High weight User-Agent should be selected more often
        high_weight_count = selections.count(high_weight_ua)
        assert high_weight_count > 50  # Should be selected majority of time
    
    def test_avoid_recent_usage(self):
        """Test avoiding recently used User-Agents."""
        manager = UserAgentManager()
        
        # Get a User-Agent
        first_ua = manager.get_user_agent(UserAgentType.API_CLIENT, avoid_recent=True)
        
        # Get another User-Agent immediately - should be different if possible
        second_ua = manager.get_user_agent(
            UserAgentType.API_CLIENT, 
            avoid_recent=True, 
            recent_threshold_seconds=300  # 5 minutes
        )
        
        # If there are multiple User-Agents available, should get different one
        api_agents = manager.user_agents[UserAgentType.API_CLIENT]
        if len(api_agents) > 1:
            assert first_ua != second_ua
    
    def test_add_custom_user_agent(self):
        """Test adding custom User-Agent."""
        manager = UserAgentManager()
        
        initial_count = len(manager.user_agents[UserAgentType.WEB_SCRAPER])
        
        custom_ua = "CustomScraper/2.0 (+https://custom.example.com)"
        manager.add_user_agent(
            user_agent=custom_ua,
            ua_type=UserAgentType.WEB_SCRAPER,
            weight=3.0,
            description="Custom scraper",
            contact_info="https://custom.example.com"
        )
        
        # Should increase count
        assert len(manager.user_agents[UserAgentType.WEB_SCRAPER]) == initial_count + 1
        
        # Should be able to select the custom User-Agent
        scraper_agents = [ua.user_agent for ua in manager.user_agents[UserAgentType.WEB_SCRAPER]]
        assert custom_ua in scraper_agents
    
    def test_remove_user_agent(self):
        """Test removing User-Agent."""
        manager = UserAgentManager()
        
        # Get a User-Agent to remove
        agents_before = manager.user_agents[UserAgentType.API_CLIENT].copy()
        ua_to_remove = agents_before[0].user_agent
        
        manager.remove_user_agent(ua_to_remove)
        
        # Should be removed from all types
        all_agents = []
        for ua_list in manager.user_agents.values():
            all_agents.extend([ua.user_agent for ua in ua_list])
        
        assert ua_to_remove not in all_agents
    
    def test_list_user_agents(self):
        """Test listing User-Agents.""" 
        manager = UserAgentManager()
        
        # List all User-Agents
        all_agents = manager.list_user_agents()
        assert len(all_agents) > 0
        
        # List specific type
        api_agents = manager.list_user_agents(UserAgentType.API_CLIENT)
        assert len(api_agents) > 0
        assert all(ua.type == UserAgentType.API_CLIENT for ua in api_agents)
    
    def test_get_user_agent_info(self):
        """Test getting User-Agent information."""
        manager = UserAgentManager()
        
        # Get a known User-Agent
        api_agents = manager.user_agents[UserAgentType.API_CLIENT]
        known_ua = api_agents[0].user_agent
        
        ua_info = manager.get_user_agent_info(known_ua)
        
        assert ua_info is not None
        assert ua_info.user_agent == known_ua
        assert ua_info.type == UserAgentType.API_CLIENT
        
        # Test unknown User-Agent
        unknown_info = manager.get_user_agent_info("Unknown-Agent/1.0")
        assert unknown_info is None
    
    def test_usage_statistics(self):
        """Test usage statistics collection."""
        manager = UserAgentManager()
        
        # Make some requests
        for _ in range(10):
            manager.get_user_agent(UserAgentType.API_CLIENT, avoid_recent=False)
        
        for _ in range(5):
            manager.get_user_agent(UserAgentType.BROWSER_DESKTOP, avoid_recent=False)
        
        stats = manager.get_usage_stats()
        
        assert stats["total_requests"] == 15
        assert stats["unique_user_agents_used"] > 0
        assert stats["available_user_agents"] > 0
        
        # Check usage by type
        assert UserAgentType.API_CLIENT.value in stats["usage_by_type"]
        assert UserAgentType.BROWSER_DESKTOP.value in stats["usage_by_type"]
        
        # Check most/least used
        assert len(stats["most_used"]) > 0
        assert len(stats["least_used"]) > 0
    
    def test_reset_usage_stats(self):
        """Test resetting usage statistics."""
        manager = UserAgentManager()
        
        # Generate some usage
        manager.get_user_agent(UserAgentType.API_CLIENT)
        assert len(manager._usage_count) > 0
        
        # Reset stats
        manager.reset_usage_stats()
        
        assert len(manager._usage_count) == 0
        assert len(manager._last_used) == 0
    
    def test_create_custom_user_agent(self):
        """Test creating custom User-Agent string."""
        manager = UserAgentManager(
            service_name="TestService",
            custom_contact_info="https://test.example.com"
        )
        
        # Basic custom User-Agent
        custom_ua = manager.create_custom_user_agent()
        assert "TestService/1.0" in custom_ua
        
        # Custom with specific name and version
        custom_ua2 = manager.create_custom_user_agent(
            base_name="CustomBot",
            version="2.1",
            include_contact=True
        )
        assert "CustomBot/2.1" in custom_ua2
        assert "https://test.example.com" in custom_ua2
        
        # Without contact info
        custom_ua3 = manager.create_custom_user_agent(include_contact=False)
        assert "https://test.example.com" not in custom_ua3


class TestUserAgentFactories:
    """Test User-Agent manager factory functions."""
    
    def test_create_api_user_agent_manager(self):
        """Test API User-Agent manager factory."""
        manager = create_api_user_agent_manager(
            service_name="APIService",
            contact_info="https://api.example.com/bot",
            version="1.2"
        )
        
        assert manager.default_type == UserAgentType.API_CLIENT
        assert manager.service_name == "APIService"
        assert manager.custom_contact_info == "https://api.example.com/bot"
        
        # Should have added service-specific User-Agent
        api_agents = [ua.user_agent for ua in manager.user_agents[UserAgentType.API_CLIENT]]
        service_agents = [ua for ua in api_agents if "APIService" in ua]
        assert len(service_agents) > 0
    
    def test_create_scraper_user_agent_manager(self):
        """Test scraper User-Agent manager factory."""
        manager = create_scraper_user_agent_manager(
            project_name="DataScraper",
            contact_info="https://scraper.example.com/about",
            respect_robots=True
        )
        
        assert manager.default_type == UserAgentType.WEB_SCRAPER
        assert manager.service_name == "DataScraper"
        
        # Should have added project-specific User-Agent with robots.txt compliance
        scraper_agents = [ua.user_agent for ua in manager.user_agents[UserAgentType.WEB_SCRAPER]]
        project_agents = [ua for ua in scraper_agents if "DataScraper" in ua and "robots.txt" in ua]
        assert len(project_agents) > 0
    
    def test_create_browser_user_agent_manager(self):
        """Test browser User-Agent manager factory."""
        # Test with default mobile ratio
        manager = create_browser_user_agent_manager(mobile_ratio=0.4)
        
        assert manager.default_type == UserAgentType.BROWSER_DESKTOP
        
        # Test that mobile agents exist and have adjusted weights
        if UserAgentType.BROWSER_MOBILE in manager.user_agents:
            mobile_agents = manager.user_agents[UserAgentType.BROWSER_MOBILE]
            assert len(mobile_agents) > 0
            # Weights should be adjusted based on mobile_ratio


class TestUserAgentSelection:
    """Test User-Agent selection logic and edge cases."""
    
    def test_selection_with_empty_type(self):
        """Test selection when a type has no User-Agents."""
        manager = UserAgentManager()
        
        # Remove all agents from a type
        manager.user_agents[UserAgentType.SOCIAL_MEDIA] = []
        
        with pytest.raises(ValueError):
            manager.get_user_agent(UserAgentType.SOCIAL_MEDIA)
    
    def test_selection_consistency_with_avoid_recent(self):
        """Test that avoid_recent logic works correctly."""
        manager = UserAgentManager()
        
        # Add only one User-Agent to ensure predictable selection
        single_ua = "SingleAgent/1.0"
        manager.user_agents[UserAgentType.API_CLIENT] = [
            UserAgentInfo(
                user_agent=single_ua,
                type=UserAgentType.API_CLIENT,
                weight=1.0
            )
        ]
        
        # First selection
        ua1 = manager.get_user_agent(UserAgentType.API_CLIENT, avoid_recent=True)
        assert ua1 == single_ua
        
        # Second selection right after - should still return same since it's the only one
        ua2 = manager.get_user_agent(UserAgentType.API_CLIENT, avoid_recent=True)
        assert ua2 == single_ua
    
    def test_recent_threshold_behavior(self):
        """Test recent threshold behavior."""
        manager = UserAgentManager()
        
        # Add two User-Agents
        ua1 = "Agent1/1.0"
        ua2 = "Agent2/1.0"
        manager.user_agents[UserAgentType.API_CLIENT] = [
            UserAgentInfo(user_agent=ua1, type=UserAgentType.API_CLIENT, weight=1.0),
            UserAgentInfo(user_agent=ua2, type=UserAgentType.API_CLIENT, weight=1.0)
        ]
        
        # Select first agent
        selected1 = manager.get_user_agent(UserAgentType.API_CLIENT, avoid_recent=True)
        
        # With very short threshold, should avoid the first agent
        with patch('time.time', return_value=time.time() + 0.1):
            selected2 = manager.get_user_agent(
                UserAgentType.API_CLIENT, 
                avoid_recent=True,
                recent_threshold_seconds=0.05  # Very short threshold
            )
            
            # Should get different agent
            assert selected1 != selected2


class TestUserAgentDefaultCollections:
    """Test the default User-Agent collections."""
    
    def test_default_collections_exist(self):
        """Test that default User-Agent collections are properly defined."""
        manager = UserAgentManager()
        
        # All types should have at least one User-Agent
        for ua_type in UserAgentType:
            assert ua_type in manager.user_agents
            assert len(manager.user_agents[ua_type]) > 0
    
    def test_api_client_user_agents(self):
        """Test API client User-Agents."""
        manager = UserAgentManager()
        api_agents = manager.user_agents[UserAgentType.API_CLIENT]
        
        # Should contain SEO platform User-Agent
        platform_agents = [ua for ua in api_agents if "SEO-Automation-Platform" in ua.user_agent]
        assert len(platform_agents) > 0
        
        # Should have contact info
        contact_agents = [ua for ua in api_agents if ua.contact_info is not None]
        assert len(contact_agents) > 0
    
    def test_browser_user_agents(self):
        """Test browser User-Agents."""
        manager = UserAgentManager()
        
        desktop_agents = manager.user_agents[UserAgentType.BROWSER_DESKTOP]
        mobile_agents = manager.user_agents[UserAgentType.BROWSER_MOBILE]
        
        # Should have popular browsers
        desktop_ua_strings = [ua.user_agent for ua in desktop_agents]
        chrome_agents = [ua for ua in desktop_ua_strings if "Chrome" in ua]
        firefox_agents = [ua for ua in desktop_ua_strings if "Firefox" in ua]
        
        assert len(chrome_agents) > 0
        assert len(firefox_agents) > 0
        assert len(mobile_agents) > 0
    
    def test_scraper_user_agents(self):
        """Test web scraper User-Agents."""
        manager = UserAgentManager()
        scraper_agents = manager.user_agents[UserAgentType.WEB_SCRAPER]
        
        # Should contain ethical scraping indicators
        ethical_agents = [
            ua for ua in scraper_agents 
            if "robots.txt" in ua.user_agent or "respects" in ua.user_agent.lower()
        ]
        assert len(ethical_agents) > 0
    
    def test_bot_crawler_user_agents(self):
        """Test bot/crawler User-Agents."""
        manager = UserAgentManager()
        bot_agents = manager.user_agents[UserAgentType.BOT_CRAWLER]
        
        # Should contain known bot User-Agents
        bot_ua_strings = [ua.user_agent for ua in bot_agents]
        google_bots = [ua for ua in bot_ua_strings if "Googlebot" in ua]
        facebook_bots = [ua for ua in bot_ua_strings if "facebook" in ua]
        
        assert len(google_bots) > 0
        assert len(facebook_bots) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])