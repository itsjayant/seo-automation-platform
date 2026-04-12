#!/usr/bin/env python3
import os
from pydantic import Field
from pydantic_settings import BaseSettings

# Test with simplified DatabaseSettings
class SimpleDatabaseSettings(BaseSettings):
    host: str = Field("localhost", env="POSTGRES_HOST")
    port: int = Field(5432, env="POSTGRES_PORT") 
    database: str = Field("seo_platform", env="POSTGRES_DB")
    username: str = Field("seo", env="POSTGRES_USER")
    password: str = Field(..., env="POSTGRES_PASSWORD")  # Simplified - no constr
    
    model_config = {
        "env_file": ".env", 
        "case_sensitive": False,
        "extra": "ignore"
    }

print("Testing simplified database settings...")

try:
    db_settings = SimpleDatabaseSettings()
    print(f"✅ Simple database settings loaded successfully!")
    print(f"   Host: {db_settings.host}")
    print(f"   Port: {db_settings.port}")
    print(f"   Database: {db_settings.database}")
    print(f"   Username: {db_settings.username}")
    print(f"   Password: {db_settings.password}")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()