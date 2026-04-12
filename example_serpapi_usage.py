"""
SerpAPI Integration Example Usage

Demonstrates how to use the SerpAPI integration for rank tracking
with proper error handling, quota management, and caching.
"""

import asyncio
import os
from datetime import date
from typing import List

import structlog

from integrations.serp import (
    SerpAPIClient, RankScheduler, ResultCache, CachePolicy,
    SearchParams, LocationTarget, DeviceType, TrackingJob
)
from task_queue.models import TaskPriority

logger = structlog.get_logger(__name__)


async def example_basic_search():
    """Example: Basic keyword search with SerpAPI."""
    print("\\n=== Basic SerpAPI Search Example ===")
    
    # Initialize client with caching
    cache_policy = CachePolicy(search_ttl=3600)  # 1 hour cache
    
    async with SerpAPIClient(cache_policy=cache_policy) as client:
        # Perform a single search
        search_params = SearchParams(
            query="python seo automation",
            location=LocationTarget(country="US"),
            device=DeviceType.DESKTOP,
            num_results=10
        )
        
        print(f"Searching for: {search_params.query}")
        
        try:
            result = await client.search(search_params)
            
            print(f"✅ Search completed successfully!")
            print(f"   - Total results found: {result.total_results:,}")
            print(f"   - Organic results returned: {len(result.organic_results)}")
            print(f"   - Credits used: {result.credits_used}")
            print(f"   - Time taken: {result.time_taken}s")
            
            print("\\n📊 SERP Features detected:")
            features = result.serp_features
            feature_list = []
            if features.featured_snippet: feature_list.append("Featured Snippet")
            if features.people_also_ask: feature_list.append("People Also Ask")
            if features.image_pack: feature_list.append("Image Pack")
            if features.video_results: feature_list.append("Video Results")
            if features.local_pack: feature_list.append("Local Pack")
            if features.knowledge_panel: feature_list.append("Knowledge Panel")
            
            if feature_list:
                for feature in feature_list:
                    print(f"   ✓ {feature}")
            else:
                print("   (No special SERP features detected)")
            
            print("\\n🔍 Top 5 organic results:")
            for i, organic_result in enumerate(result.organic_results[:5], 1):
                print(f"   {i}. {organic_result.domain}")
                print(f"      Title: {organic_result.title[:60]}{'...' if len(organic_result.title) > 60 else ''}")
                print(f"      URL: {organic_result.link}")
                
        except Exception as e:
            print(f"❌ Search failed: {e}")
            return None
    
    return result


async def example_rank_tracking():
    """Example: Track rankings for multiple keywords."""
    print("\\n=== Rank Tracking Example ===")
    
    async with SerpAPIClient(daily_quota_limit=5) as client:
        # Keywords to track
        keywords = [
            "python automation",
            "seo tools python"
        ]
        
        # Domain to track rankings for
        target_domain = "github.com"  # Example domain that likely ranks
        
        print(f"Tracking rankings for: {target_domain}")
        print(f"Keywords: {', '.join(keywords)}")
        
        try:
            rankings = await client.track_keywords(
                keywords=keywords,
                site_domain=target_domain,
                location="US",
                device=DeviceType.DESKTOP,
                num_results=50
            )
            
            print(f"\\n✅ Rank tracking completed!")
            print(f"   - Keywords tracked: {len(rankings)}")
            
            print("\\n📈 Ranking Results:")
            for ranking in rankings:
                if ranking.is_ranking:
                    print(f"   🎯 '{ranking.keyword}' - Position #{ranking.position}")
                    if ranking.url:
                        print(f"      URL: {ranking.url}")
                    if ranking.all_positions and len(ranking.all_positions) > 1:
                        print(f"      All positions: {ranking.all_positions}")
                else:
                    print(f"   ❌ '{ranking.keyword}' - Not ranking in top {client.RATE_LIMIT_CONFIG.requests}")
                
                # Show SERP features
                features = ranking.serp_features
                if features.featured_snippet or features.people_also_ask or features.image_pack:
                    feature_info = []
                    if features.featured_snippet: feature_info.append("Featured Snippet")
                    if features.people_also_ask: feature_info.append("PAA")
                    if features.image_pack: feature_info.append("Images")
                    print(f"      SERP Features: {', '.join(feature_info)}")
                
                print(f"      Competitors found: {len(ranking.competitor_urls)}")
                
        except Exception as e:
            print(f"❌ Rank tracking failed: {e}")
            return None
    
    return rankings


async def example_quota_management():
    """Example: Quota monitoring and management."""
    print("\\n=== Quota Management Example ===")
    
    async with SerpAPIClient(daily_quota_limit=3) as client:
        print("🔍 Checking API key validation...")
        
        try:
            is_valid = await client.validate_api_key()
            print(f"   API Key Status: {'✅ Valid' if is_valid else '❌ Invalid'}")
        except Exception as e:
            print(f"   API Key Status: ❌ Error - {e}")
            return
        
        print("\\n📊 Current quota status:")
        quota_info = await client.get_quota_info()
        
        print(f"   - Credits used: {quota_info.used_credits}")
        print(f"   - Daily usage: {quota_info.daily_usage}")
        
        # Estimate costs
        test_keywords = ["seo", "python", "automation"]
        cost_estimate = client.get_search_cost_estimate(len(test_keywords))
        print(f"\\n💰 Cost estimate for {len(test_keywords)} keywords: {cost_estimate} credits")
        
        # Check if we can afford the search
        remaining = client.daily_quota_limit - client._session_usage
        print(f"   - Credits remaining in session: {remaining}")
        
        if cost_estimate <= remaining:
            print(f"   ✅ Sufficient quota available")
        else:
            print(f"   ⚠️  Insufficient quota (need {cost_estimate}, have {remaining})")


async def example_scheduled_tracking():
    """Example: Scheduled rank tracking with priority management."""
    print("\\n=== Scheduled Tracking Example ===")
    
    # This example shows how the scheduler would work
    # In production, you'd have actual Site and Keyword UUIDs from the database
    
    scheduler = RankScheduler(
        daily_quota_budget=5,
        tracking_mode=scheduler.TrackingMode.PRIORITY
    )
    
    print("🕒 Scheduler initialized")
    print(f"   - Daily budget: {scheduler.daily_quota_budget} credits")
    print(f"   - Tracking mode: {scheduler.tracking_mode.value}")
    print(f"   - Default time: {scheduler.default_tracking_time}")
    
    # Check quota status
    quota_status = scheduler.get_daily_quota_status()
    print("\\n📊 Current quota status:")
    print(f"   - Budget: {quota_status['budget']}")
    print(f"   - Used: {quota_status['used']}")
    print(f"   - Remaining: {quota_status['remaining']}")
    print(f"   - Usage: {quota_status['usage_percentage']:.1f}%")
    
    print("\\n📋 Scheduler features:")
    print("   ✓ Priority-based keyword selection")
    print("   ✓ Daily quota management")
    print("   ✓ Batch processing optimization")
    print("   ✓ Error recovery and retry logic")
    print("   ✓ Integration with approval workflows")


async def example_caching():
    """Example: Result caching for API efficiency."""
    print("\\n=== Caching Example ===")
    
    # Configure cache policy
    cache_policy = CachePolicy(
        default_ttl=7200,  # 2 hours
        strategy=cache_policy.CacheStrategy.COMPRESSED,
        max_size_mb=5.0
    )
    
    cache = ResultCache(policy=cache_policy)
    
    print("🗄️  Cache initialized")
    print(f"   - TTL: {cache_policy.default_ttl}s ({cache_policy.default_ttl//3600}h)")
    print(f"   - Strategy: {cache_policy.strategy.value}")
    print(f"   - Max size: {cache_policy.max_size_mb}MB")
    
    # Example cache operations
    test_key = cache.generate_key(
        "/search",
        {"q": "test query", "location": "US", "device": "desktop"}
    )
    
    print(f"\\n🔑 Generated cache key: {test_key}")
    
    # Check if we can connect to cache
    try:
        cache_stats = await cache.get_cache_stats()
        print("\\n📈 Cache statistics:")
        print(f"   - Memory used: {cache_stats.get('memory_used_mb', 0):.2f}MB")
        print(f"   - Search keys: {cache_stats.get('search_keys', 0)}")
        print(f"   - Total keys: {cache_stats.get('total_keys', 0)}")
    except Exception as e:
        print(f"\\n⚠️  Cache statistics unavailable: {e}")
        print("   (This is normal if Redis is not running)")
    
    await cache.close()


async def main():
    """Run all examples."""
    print("🚀 SerpAPI Integration Examples")
    print("=" * 50)
    
    # Check if API key is configured
    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        print("⚠️  SERPAPI_KEY environment variable not set!")
        print("   Please set your SerpAPI key to run these examples.")
        print("   Example: export SERPAPI_KEY='your_api_key_here'")
        print("\\n   Showing non-API examples only...")
        
        await example_quota_management()  # This will show the error gracefully
        await example_scheduled_tracking()
        await example_caching()
        return
    
    print(f"🔑 Using SerpAPI key: {api_key[:8]}...{api_key[-4:]}")
    print("\\n⚠️  Note: These examples will use real API credits!")
    print("   Make sure you have sufficient quota before running.")
    
    input("\\nPress Enter to continue or Ctrl+C to cancel...")
    
    try:
        # Run examples
        await example_basic_search()
        await example_rank_tracking() 
        await example_quota_management()
        await example_scheduled_tracking()
        await example_caching()
        
        print("\\n✅ All examples completed successfully!")
        
    except KeyboardInterrupt:
        print("\\n🛑 Examples cancelled by user")
    except Exception as e:
        print(f"\\n❌ Examples failed: {e}")
    
    print("\\n📝 Next steps:")
    print("   1. Configure your sites and keywords in the database")
    print("   2. Set up scheduled tracking with RankScheduler") 
    print("   3. Configure Redis for optimal caching")
    print("   4. Set up monitoring for quota usage")
    print("   5. Integrate with approval workflows for automated actions")


if __name__ == "__main__":
    # Configure basic logging
    import logging
    logging.basicConfig(level=logging.INFO)
    
    asyncio.run(main())