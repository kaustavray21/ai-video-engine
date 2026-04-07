"""Quick smoke test — connect to Temporal Cloud and list namespaces."""
import asyncio
import os
import sys

sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.conf import settings

async def test():
    from temporalio.client import Client

    print(f"Endpoint : {settings.TEMPORAL_ENDPOINT}")
    print(f"Namespace: {settings.TEMPORAL_NAMESPACE}")
    print(f"TLS      : {settings.TEMPORAL_TLS}")
    print(f"API key  : {'set' if settings.TEMPORAL_API_KEY else 'NOT SET'}")
    print()

    connect_kwargs = {
        'target_host': settings.TEMPORAL_ENDPOINT,
        'namespace': settings.TEMPORAL_NAMESPACE,
    }
    if settings.TEMPORAL_API_KEY:
        connect_kwargs['api_key'] = settings.TEMPORAL_API_KEY
    if settings.TEMPORAL_TLS:
        connect_kwargs['tls'] = True

    print("Connecting...")
    client = await Client.connect(**connect_kwargs)
    print("Connected OK")

    # Try listing a workflow (will return empty list, just proves auth works)
    workflows = [w async for w in client.list_workflows(query='', page_size=1)]
    print(f"Workflow query OK (found {len(workflows)} recent workflows)")
    print()
    print("SUCCESS — Temporal Cloud connection is working.")

asyncio.run(test())
