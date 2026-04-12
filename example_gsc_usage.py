#!/usr/bin/env python3
"""
Example usage of GSC integration.

This script demonstrates how to use the Google Search Console integration
to fetch search analytics data and store it in the database.
"""

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import structlog

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config import get_settings
from integrations.gsc import (
    GSCClient, GSCConfig, GSCSync, GSCSyncConfig,
    GSCDimension, ServiceAccountConfig
)
from db import initialize_database, get_database_manager

logger = structlog.get_logger(__name__)


async def example_gsc_usage():
    """
    Example of using GSC integration to fetch and sync data.
    """
    logger.info("🚀 Starting GSC Integration Example")
    
    # Initialize database
    logger.info("📊 Initializing database connection")
    await initialize_database()
    
    try:
        # Configuration (in practice, load from environment variables)
        gsc_config = GSCConfig(
            service_account=ServiceAccountConfig(
                # In production, load from environment variable:
                # service_account_path=os.getenv("GSC_SERVICE_ACCOUNT_PATH")
                service_account_path="/path/to/service-account.json",  # Update this path
                scopes=["https://www.googleapis.com/auth/webmasters.readonly"]
            ),
            property_url="https://example.com",  # Update this URL
            requests_per_day=200,  # GSC free tier limit
            requests_per_minute=10
        )
        
        sync_config = GSCSyncConfig(
            incremental_sync=True,
            backfill_days=7,
            max_retries=3,
            concurrent_requests=2,
            batch_insert_size=1000
        )
        
        # Create GSC client
        logger.info("🔧 Creating GSC client")
        gsc_client = GSCClient(gsc_config)
        
        # Verify access to GSC property
        logger.info("🔐 Verifying GSC property access")
        has_access = await gsc_client.verify_property_access(gsc_config.property_url)
        
        if not has_access:
            logger.error("❌ No access to GSC property", property_url=gsc_config.property_url)
            return False
        
        logger.info("✅ GSC property access verified")
        
        # List all available properties
        logger.info("📋 Listing GSC properties")
        properties = await gsc_client.list_properties()
        
        logger.info("Available GSC properties:", count=len(properties))
        for prop in properties:
            logger.info(f"  - {prop.get('siteUrl')} ({prop.get('permissionLevel')})")
        
        # Example 1: Fetch search analytics data for a date range
        logger.info("📈 Example 1: Fetching search analytics data")
        
        site_id = uuid4()  # In practice, get from database
        start_date = date.today() - timedelta(days=10)
        end_date = date.today() - timedelta(days=3)  # GSC has 2-3 day delay
        
        logger.info(
            "Fetching GSC data",
            site_id=site_id,
            start_date=start_date,
            end_date=end_date
        )
        
        total_rows = 0
        sample_data = []
        
        async for metric_data in gsc_client.fetch_search_analytics(
            site_id=site_id,
            site_url=gsc_config.property_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=[GSCDimension.PAGE, GSCDimension.QUERY],
            max_rows=100  # Limit for example
        ):
            total_rows += 1
            
            # Collect first few samples for logging
            if len(sample_data) < 3:
                sample_data.append(metric_data)
        
        logger.info(f"📊 Fetched {total_rows} rows of GSC data")
        
        for i, sample in enumerate(sample_data):
            logger.info(
                f"Sample row {i + 1}",
                clicks=sample.clicks,
                impressions=sample.impressions,
                ctr=float(sample.ctr),
                position=float(sample.position)
            )
        
        # Example 2: Check quota usage
        logger.info("📉 Example 2: Checking GSC quota usage")
        
        quota_info = await gsc_client.get_quota_usage()
        logger.info("GSC quota status", quota_info=quota_info)
        
        # Example 3: Full sync using GSCSync (commented out to avoid database writes)
        logger.info("🔄 Example 3: GSC Data Synchronization (simulation)")
        
        # gsc_sync = GSCSync(gsc_client, sync_config)
        # 
        # # Simulate sync for single site
        # sync_results = await gsc_sync.sync_site(
        #     site_id=site_id,
        #     site_url=gsc_config.property_url,
        #     start_date=start_date,
        #     end_date=end_date
        # )
        # 
        # logger.info("Sync results", results=sync_results)
        
        logger.info("📝 Note: Full sync commented out to avoid database modifications")
        logger.info("📝 To run full sync, uncomment the sync code and ensure proper database setup")
        
        # Example 4: Error handling demonstration
        logger.info("⚠️  Example 4: Error handling demonstration")
        
        try:
            # Try to access a property that doesn't exist
            fake_access = await gsc_client.verify_property_access("https://nonexistent-domain.com")
            logger.info(f"Fake property access result: {fake_access}")
            
        except Exception as e:
            logger.info(f"Expected error for fake property: {e}")
        
        logger.info("✅ GSC Integration Example completed successfully")
        return True
        
    except Exception as e:
        logger.error("❌ GSC Integration Example failed", error=str(e))
        return False
        
    finally:
        # Cleanup
        logger.info("🧹 Cleaning up resources")
        await gsc_client.close()


async def check_gsc_requirements():
    """
    Check if GSC integration requirements are met.
    """
    logger.info("🔍 Checking GSC integration requirements")
    
    requirements_met = True
    
    # Check if service account file exists (example path)
    service_account_path = "/path/to/service-account.json"
    
    if not Path(service_account_path).exists():
        logger.warning(
            "❌ Service account file not found",
            path=service_account_path,
            note="Update the path in this example script"
        )
        requirements_met = False
    
    # Check environment settings
    try:
        settings = get_settings()
        logger.info("✅ Settings loaded successfully")
    except Exception as e:
        logger.error("❌ Failed to load settings", error=str(e))
        requirements_met = False
    
    # Check database connection
    try:
        db_manager = get_database_manager()
        logger.info("✅ Database manager accessible")
    except Exception as e:
        logger.error("❌ Database connection issue", error=str(e))
        requirements_met = False
    
    return requirements_met


def print_setup_instructions():
    """Print setup instructions for GSC integration."""
    print("\n" + "=" * 60)
    print("GSC Integration Setup Instructions")
    print("=" * 60)
    print()
    print("1. Create a Google Cloud Project:")
    print("   - Go to https://console.cloud.google.com/")
    print("   - Create or select a project")
    print()
    print("2. Enable Search Console API:")
    print("   - Go to APIs & Services > Library")
    print("   - Search for 'Search Console API'")
    print("   - Click 'Enable'")
    print()
    print("3. Create Service Account:")
    print("   - Go to IAM & Admin > Service Accounts")
    print("   - Click 'Create Service Account'")
    print("   - Download JSON key file")
    print()
    print("4. Grant Search Console Access:")
    print("   - Go to https://search.google.com/search-console/")
    print("   - Add the service account email as a property owner")
    print("   - Email format: name@project.iam.gserviceaccount.com")
    print()
    print("5. Update Configuration:")
    print("   - Set GSC_SERVICE_ACCOUNT_PATH environment variable")
    print("   - Or update service_account_path in this script")
    print("   - Set GSC_PROPERTY_URL environment variable")
    print()
    print("6. Run the Example:")
    print("   python example_gsc_usage.py")
    print()
    print("=" * 60)


async def main():
    """Main example function."""
    print("🔍 Google Search Console Integration Example")
    print()
    
    # Check requirements
    requirements_ok = await check_gsc_requirements()
    
    if not requirements_ok:
        print("\n❌ Some requirements are not met.")
        print("📋 Here are the setup instructions:")
        print_setup_instructions()
        return 1
    
    print("✅ Requirements check passed")
    print()
    
    # Run the example
    success = await example_gsc_usage()
    
    if success:
        print("\n🎉 GSC Integration Example completed successfully!")
        print("📊 Check the logs above for detailed results")
        return 0
    else:
        print("\n❌ GSC Integration Example failed")
        print("🔍 Check the error logs above")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)