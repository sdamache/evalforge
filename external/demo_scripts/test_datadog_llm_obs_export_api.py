#!/usr/bin/env python3
"""Test Datadog LLM Observability Search API for full trace content."""
import os
import json
import requests
from datetime import datetime, timedelta, timezone

# Load credentials
from dotenv import load_dotenv
load_dotenv('.env.local')

api_key = os.getenv('DATADOG_API_KEY')
app_key = os.getenv('DATADOG_APP_KEY')
site = os.getenv('DATADOG_SITE', 'us5.datadoghq.com')

print(f"Using Datadog site: {site}")

# Build time range (last 24 hours)
now = datetime.now(timezone.utc)
from_time = now - timedelta(hours=24)

# Test 1: GET endpoint (current implementation)
print("\n=== TEST 1: GET /spans/events ===")
get_url = f"https://api.{site}/api/v2/llm-obs/v1/spans/events"
headers = {
    "DD-API-KEY": api_key,
    "DD-APPLICATION-KEY": app_key,
}
params = {
    "filter[from]": from_time.isoformat(),
    "filter[to]": now.isoformat(),
    "filter[status]": "error",
    "page[limit]": 3,
}

response = requests.get(get_url, headers=headers, params=params)
print(f"Status: {response.status_code}")
if response.status_code == 200:
    data = response.json()
    spans = data.get('data', [])
    print(f"Spans returned: {len(spans)}")
    if spans:
        span = spans[0]
        attrs = span.get('attributes', {})
        print(f"First span keys: {list(attrs.keys())}")
        print(f"  input: {type(attrs.get('input'))} - {str(attrs.get('input'))[:100] if attrs.get('input') else 'NONE'}...")
        print(f"  output: {type(attrs.get('output'))} - {str(attrs.get('output'))[:100] if attrs.get('output') else 'NONE'}...")
else:
    print(f"Error: {response.text[:200]}")

# Test 2: POST /search endpoint
print("\n=== TEST 2: POST /spans/events/search ===")
search_url = f"https://api.{site}/api/v2/llm-obs/v1/spans/events/search"

search_body = {
    "data": {
        "type": "spans",
        "attributes": {
            "filter": {
                "from": from_time.isoformat(),
                "to": now.isoformat()
            },
            "page": {
                "limit": 3
            },
            "sort": "-timestamp"
        }
    }
}

response = requests.post(search_url, headers=headers, json=search_body)
print(f"Status: {response.status_code}")
if response.status_code == 200:
    data = response.json()
    spans = data.get('data', [])
    print(f"Spans returned: {len(spans)}")
    if spans:
        span = spans[0]
        attrs = span.get('attributes', {})
        print(f"First span keys: {list(attrs.keys())}")
        print(f"  input: {type(attrs.get('input'))} - {str(attrs.get('input'))[:200] if attrs.get('input') else 'NONE'}...")
        print(f"  output: {type(attrs.get('output'))} - {str(attrs.get('output'))[:200] if attrs.get('output') else 'NONE'}...")
else:
    print(f"Error: {response.text[:500]}")

# Test 3: Check if there's a specific span with content
print("\n=== TEST 3: Check for any span with input/output ===")
params_all = {
    "filter[from]": from_time.isoformat(),
    "filter[to]": now.isoformat(),
    "page[limit]": 20,
}

response = requests.get(get_url, headers=headers, params=params_all)
if response.status_code == 200:
    data = response.json()
    spans = data.get('data', [])
    spans_with_input = [s for s in spans if s.get('attributes', {}).get('input')]
    spans_with_output = [s for s in spans if s.get('attributes', {}).get('output')]
    print(f"Total spans: {len(spans)}")
    print(f"Spans with input: {len(spans_with_input)}")
    print(f"Spans with output: {len(spans_with_output)}")

    if spans_with_input:
        print(f"\nExample span with input:")
        attrs = spans_with_input[0].get('attributes', {})
        print(f"  trace_id: {attrs.get('trace_id')}")
        print(f"  input: {json.dumps(attrs.get('input'))[:300]}...")
