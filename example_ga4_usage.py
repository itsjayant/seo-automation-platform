#!/usr/bin/env python3
"""
Example usage of GA4 Integration.

This script demonstrates how to use the GA4 integration to fetch
organic traffic data from Google Analytics 4 properties.
"""

import asyncio
import os
from datetime import date, timedelta
from uuid import uuid4

from integrations.ga4 import (
    GA4Client,
    GA4Config,
    ServiceAccountConfig,
    GA4SyncConfig,
    GA4Sync,
    GA4DataTransformer
)


async def example_ga4_usage():
    """Example of GA4 integration usage."""
    
    print("GA4 Integration Example")
    print("="*40)
    
    # Configuration example using environment variables
    service_account_config = ServiceAccountConfig(
        # Option 1: Use JSON file
        json_file_path=os.getenv("GA4_SERVICE_ACCOUNT_JSON_PATH")
        
        # Option 2: Use individual fields (uncomment if not using JSON file)
        # project_id=os.getenv("GA4_PROJECT_ID"),
        # private_key_id=os.getenv("GA4_PRIVATE_KEY_ID"),
        # private_key=os.getenv("GA4_PRIVATE_KEY"),
        # client_email=os.getenv("GA4_CLIENT_EMAIL"),
        # client_id=os.getenv("GA4_CLIENT_ID")
    )
    
    # GA4 client configuration
    ga4_config = GA4Config(
        service_account=service_account_config,
        default_property_id=os.getenv("GA4_PROPERTY_ID", "123456789"),
        requests_per_minute=150,  # Conservative rate limiting
        requests_per_day=20000
    )
    
    # Create GA4 client
    client = GA4Client(ga4_config)
    
    try:
        # Test connection
        property_id = ga4_config.default_property_id
        print(f"Testing connection to GA4 property {property_id}...")
        
        connection_ok = await client.test_connection(property_id)
        if connection_ok:
            print("✅ GA4 connection successful")
        else:
            print("❌ GA4 connection failed")
            return
        
        # Get property metadata
        print("\nFetching property metadata...")
        metadata = await client.get_property_metadata(property_id)
        print(f"Property accessible: {metadata.get('accessible', False)}")
        
        # Fetch organic sessions for last 7 days
        end_date = date.today() - timedelta(days=2)  # Account for processing delay
        start_date = end_date - timedelta(days=7)
        
        print(f"\nFetching organic sessions from {start_date} to {end_date}...")
        
        site_id = uuid4()  # In real usage, this would be from your database
        
        organic_metrics = await client.fetch_organic_sessions(
            property_id=property_id,
            site_id=site_id,
            start_date=start_date,
            end_date=end_date
        )
        
        print(f"Retrieved {len(organic_metrics)} metric records")
        
        # Display sample metrics
        if organic_metrics:
            print("\nSample metrics:")
            for i, metric in enumerate(organic_metrics[:3]):  # Show first 3
                print(f"  {i+1}. {metric.date} | {metric.page_path}")
                print(f"     Sessions: {metric.sessions}, Views: {metric.page_views}")
                print(f"     Bounce Rate: {metric.bounce_rate}, Device: {metric.device_category}")
            
            if len(organic_metrics) > 3:
                print(f"     ... and {len(organic_metrics) - 3} more")
        
        # Example of data transformation
        print("\nTesting data transformation...")
        transformer = GA4DataTransformer()
        
        # Test aggregation
        aggregated = transformer.aggregate_daily_metrics(organic_metrics, group_by_device=False)
        print(f"Aggregated to {len(aggregated)} records (from {len(organic_metrics)})")
        
        # Test organic filtering
        organic_only = transformer.filter_organic_traffic(organic_metrics)
        print(f"Organic traffic filtering: {len(organic_only)} records")
        
        # Example sync configuration
        print("\nSync configuration example:")
        sync_config = GA4SyncConfig(
            property_id=property_id,
            site_id=site_id,
            start_date=start_date,
            end_date=end_date,
            organic_only=True,
            include_bounce_rate=True,
            batch_size=1000,
            max_concurrent_requests=3
        )
        
        print(f"  Property: {sync_config.property_id}")
        print(f"  Date range: {sync_config.start_date} to {sync_config.end_date}")
        print(f"  Organic only: {sync_config.organic_only}")
        print(f"  Batch size: {sync_config.batch_size}")
        
        print("\n✅ GA4 integration example completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Clean up
        await client.close()


if __name__ == "__main__":
    # Set up example environment variables (replace with actual values)
    if not os.getenv("GA4_SERVICE_ACCOUNT_JSON_PATH"):
        print("Environment setup required:")
        print("  GA4_SERVICE_ACCOUNT_JSON_PATH=/path/to/service-account.json")
        print("  GA4_PROPERTY_ID=your-property-id")
        print("\nAlternatively, set individual service account fields:")
        print("  GA4_PROJECT_ID, GA4_PRIVATE_KEY, GA4_CLIENT_EMAIL, etc.")
        print("\nThis example will use mock credentials for demonstration.")
    
    asyncio.run(example_ga4_usage())