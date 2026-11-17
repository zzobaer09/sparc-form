import logging
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

DEFAULT_RATE_LIMIT = 30   # requests per window
DEFAULT_WINDOW = 3600     # 1 hour in seconds


def get_client_ip(request):
    """Extract client IP, preferring X-Forwarded-For if present."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', '')
    return ip or '127.0.0.1'


def is_rate_limited(request, action='apply', limit=None, window=DEFAULT_WINDOW):
    """Check if request exceeds the rate limit.

    Returns True if rate limited (blocked), False if allowed.
    Increments count on each check. Fails open on cache errors so legitimate
    users are not blocked if the cache backend is unavailable.
    """
    if limit is None:
        limit = getattr(settings, 'RATE_LIMIT_APPLY_PER_HOUR', DEFAULT_RATE_LIMIT)

    if limit <= 0:
        return False  # Disabled or bypass in testing

    ip = get_client_ip(request)
    cache_key = f'rl:{action}:{ip}'

    try:
        # cache.add only sets the key if it does not already exist
        added = cache.add(cache_key, 1, timeout=window)
        if not added:
            try:
                current = cache.incr(cache_key)
            except (ValueError, TypeError):
                current = (cache.get(cache_key) or 0) + 1
                cache.set(cache_key, current, timeout=window)
        else:
            current = 1

        if current > limit:
            logger.warning('Rate limit exceeded for IP %s on %s (count: %d, limit: %d)',
                           ip, action, current, limit)
            return True
        return False
    except Exception as exc:
        logger.error('Rate limit cache failure (%s): failing open', exc)
        return False
