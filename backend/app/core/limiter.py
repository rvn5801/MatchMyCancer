"""Shared rate limiter.

One instance app-wide so every endpoint shares the same counters and
`app.state.limiter` matches the decorators.

ponytail: in-memory storage — counters reset when the container cold-starts
(ACA scales to zero). Point `storage_uri` at settings.redis_url if limits
need to survive restarts or span replicas.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
