#!/usr/bin/env python3
import os
from dotenv import load_dotenv

print("Debugging environment variable loading...")

# Load .env file explicitly
load_dotenv(".env")

print(f"POSTGRES_PASSWORD from os.getenv: {repr(os.getenv('POSTGRES_PASSWORD'))}")
print(f"POSTGRES_HOST from os.getenv: {repr(os.getenv('POSTGRES_HOST'))}")
print(f"POSTGRES_PORT from os.getenv: {repr(os.getenv('POSTGRES_PORT'))}")
print(f"POSTGRES_USER from os.getenv: {repr(os.getenv('POSTGRES_USER'))}")

# Show first few lines of .env file to check format
print("\nFirst few lines of .env file:")
with open('.env') as f:
    for i, line in enumerate(f):
        if i < 50:
            print(f"{i+1:3d}: {repr(line.strip())}")
        else:
            break