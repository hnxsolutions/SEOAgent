"""
SEO Agent SaaS - Rate Limiter
Rate limiting for web crawling to respect server resources
"""
import asyncio
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger(__name__)


class RateLimiter(ABC):
    """Abstract base class for rate limiters"""
    
    @abstractmethod
    async def acquire(self, domain: str) -> float:
        """
        Acquire permission to make a request to the given domain.
        
        Args:
            domain: The domain to acquire permission for
            
        Returns:
            Time to wait in seconds before making the request
        """
        pass
    
    @abstractmethod
    async def wait(self, domain: str):
        """
        Wait until permission is granted to make a request.
        
        Args:
            domain: The domain to wait for
        """
        pass


class TokenBucketRateLimiter(RateLimiter):
    """
    Token bucket rate limiter for controlling request rates per domain.
    Each domain gets its own bucket with configurable capacity and refill rate.
    """
    
    def __init__(
        self,
        requests_per_second: float = 1.0,
        max_tokens: Optional[int] = None,
        burst_capacity: int = 5,
    ):
        """
        Initialize the token bucket rate limiter.
        
        Args:
            requests_per_second: Average number of requests allowed per second
            max_tokens: Maximum tokens in bucket (defaults to burst_capacity)
            burst_capacity: Maximum burst capacity for new buckets
        """
        self.requests_per_second = requests_per_second
        self.burst_capacity = burst_capacity
        self.max_tokens = max_tokens or burst_capacity
        
        # Token buckets per domain
        self._buckets: Dict[str, Dict] = {}
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
    
    def _get_bucket(self, domain: str) -> Dict:
        """Get or create a token bucket for a domain"""
        if domain not in self._buckets:
            self._buckets[domain] = {
                "tokens": float(self.max_tokens),
                "last_update": time.monotonic(),
            }
        return self._buckets[domain]
    
    def _refill_bucket(self, bucket: Dict) -> None:
        """Refill tokens based on elapsed time"""
        now = time.monotonic()
        elapsed = now - bucket["last_update"]
        
        # Add tokens based on elapsed time
        tokens_to_add = elapsed * self.requests_per_second
        bucket["tokens"] = min(bucket["tokens"] + tokens_to_add, self.max_tokens)
        bucket["last_update"] = now
    
    async def acquire(self, domain: str) -> float:
        """
        Acquire permission to make a request.
        
        Args:
            domain: The domain to acquire permission for
            
        Returns:
            Time to wait in seconds (0 if ready immediately)
        """
        async with self._locks[domain]:
            bucket = self._get_bucket(domain)
            self._refill_bucket(bucket)
            
            if bucket["tokens"] >= 1:
                bucket["tokens"] -= 1
                return 0.0
            else:
                # Calculate wait time
                tokens_needed = 1 - bucket["tokens"]
                wait_time = tokens_needed / self.requests_per_second
                return wait_time
    
    async def wait(self, domain: str):
        """
        Wait until permission is granted to make a request.
        
        Args:
            domain: The domain to wait for
        """
        wait_time = await self.acquire(domain)
        if wait_time > 0:
            await asyncio.sleep(wait_time)


class SlidingWindowRateLimiter(RateLimiter):
    """
    Sliding window rate limiter for controlling request rates per domain.
    Tracks request timestamps and ensures rate is not exceeded within any window.
    """
    
    def __init__(
        self,
        requests_per_window: int = 10,
        window_size_seconds: int = 60,
    ):
        """
        Initialize the sliding window rate limiter.
        
        Args:
            requests_per_window: Maximum requests allowed per window
            window_size_seconds: Size of the sliding window in seconds
        """
        self.requests_per_window = requests_per_window
        self.window_size = window_size_seconds
        
        # Request timestamps per domain
        self._timestamps: Dict[str, list] = defaultdict(list)
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
    
    def _cleanup_old_timestamps(self, domain: str, current_time: float):
        """Remove timestamps outside the current window"""
        cutoff = current_time - self.window_size
        self._timestamps[domain] = [
            ts for ts in self._timestamps[domain] if ts > cutoff
        ]
    
    async def acquire(self, domain: str) -> float:
        """
        Acquire permission to make a request.
        
        Args:
            domain: The domain to acquire permission for
            
        Returns:
            Time to wait in seconds (0 if ready immediately)
        """
        async with self._locks[domain]:
            current_time = time.monotonic()
            self._cleanup_old_timestamps(domain, current_time)
            
            if len(self._timestamps[domain]) < self.requests_per_window:
                self._timestamps[domain].append(current_time)
                return 0.0
            else:
                # Calculate wait time until oldest request expires
                oldest = self._timestamps[domain][0]
                wait_time = oldest + self.window_size - current_time
                return max(0, wait_time)
    
    async def wait(self, domain: str):
        """
        Wait until permission is granted to make a request.
        
        Args:
            domain: The domain to wait for
        """
        wait_time = await self.acquire(domain)
        if wait_time > 0:
            await asyncio.sleep(wait_time)


class AdaptiveRateLimiter(RateLimiter):
    """
    Adaptive rate limiter that adjusts based on server response.
    Starts with a conservative rate and adjusts based on response times and status codes.
    """
    
    def __init__(
        self,
        initial_delay: float = 1.0,
        min_delay: float = 0.1,
        max_delay: float = 30.0,
        increase_factor: float = 1.5,
        decrease_factor: float = 0.9,
        slow_threshold_ms: float = 2000,
    ):
        """
        Initialize the adaptive rate limiter.
        
        Args:
            initial_delay: Starting delay between requests
            min_delay: Minimum delay between requests
            max_delay: Maximum delay between requests
            increase_factor: Factor to increase delay on slow responses
            decrease_factor: Factor to decrease delay on fast responses
            slow_threshold_ms: Response time threshold for "slow" responses
        """
        self.initial_delay = initial_delay
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.increase_factor = increase_factor
        self.decrease_factor = decrease_factor
        self.slow_threshold_ms = slow_threshold_ms
        
        # Current delay per domain
        self._delays: Dict[str, float] = {}
        self._last_request: Dict[str, float] = {}
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
    
    def _get_delay(self, domain: str) -> float:
        """Get current delay for a domain"""
        if domain not in self._delays:
            self._delays[domain] = self.initial_delay
        return self._delays[domain]
    
    async def acquire(self, domain: str) -> float:
        """
        Acquire permission to make a request.
        
        Args:
            domain: The domain to acquire permission for
            
        Returns:
            Time to wait in seconds
        """
        async with self._locks[domain]:
            current_time = time.monotonic()
            delay = self._get_delay(domain)
            
            if domain in self._last_request:
                elapsed = current_time - self._last_request[domain]
                wait_time = max(0, delay - elapsed)
            else:
                wait_time = 0
            
            self._last_request[domain] = current_time + wait_time
            return wait_time
    
    async def wait(self, domain: str):
        """
        Wait until permission is granted to make a request.
        
        Args:
            domain: The domain to wait for
        """
        wait_time = await self.acquire(domain)
        if wait_time > 0:
            await asyncio.sleep(wait_time)
    
    async def report_response(
        self,
        domain: str,
        status_code: int,
        response_time_ms: float,
    ):
        """
        Report a response to adjust the rate.
        
        Args:
            domain: The domain of the response
            status_code: HTTP status code
            response_time_ms: Response time in milliseconds
        """
        async with self._locks[domain]:
            current_delay = self._get_delay(domain)
            
            # Server errors - slow down significantly
            if status_code >= 500:
                new_delay = min(current_delay * self.increase_factor * 2, self.max_delay)
                self._delays[domain] = new_delay
                logger.warning(f"Server error from {domain}, increasing delay to {new_delay:.2f}s")
            
            # Rate limited - slow down significantly
            elif status_code == 429:
                new_delay = min(current_delay * self.increase_factor * 3, self.max_delay)
                self._delays[domain] = new_delay
                logger.warning(f"Rate limited by {domain}, increasing delay to {new_delay:.2f}s")
            
            # Slow response - slow down
            elif response_time_ms > self.slow_threshold_ms:
                new_delay = min(current_delay * self.increase_factor, self.max_delay)
                self._delays[domain] = new_delay
                logger.debug(f"Slow response from {domain}, increasing delay to {new_delay:.2f}s")
            
            # Fast successful response - speed up slightly
            elif status_code < 400 and response_time_ms < self.slow_threshold_ms * 0.5:
                new_delay = max(current_delay * self.decrease_factor, self.min_delay)
                self._delays[domain] = new_delay


class CombinedRateLimiter(RateLimiter):
    """
    Combines multiple rate limiters for comprehensive rate control.
    Uses both per-domain and global rate limiting.
    """
    
    def __init__(
        self,
        per_domain_limiter: Optional[RateLimiter] = None,
        global_limiter: Optional[RateLimiter] = None,
    ):
        """
        Initialize the combined rate limiter.
        
        Args:
            per_domain_limiter: Rate limiter for per-domain control
            global_limiter: Rate limiter for global control
        """
        self.per_domain_limiter = per_domain_limiter or TokenBucketRateLimiter(
            requests_per_second=2.0,
            burst_capacity=10,
        )
        self.global_limiter = global_limiter or SlidingWindowRateLimiter(
            requests_per_window=60,
            window_size_seconds=60,
        )
    
    async def acquire(self, domain: str) -> float:
        """
        Acquire permission to make a request.
        Returns the maximum wait time from both limiters.
        """
        domain_wait = await self.per_domain_limiter.acquire(domain)
        global_wait = await self.global_limiter.acquire("_global")
        return max(domain_wait, global_wait)
    
    async def wait(self, domain: str):
        """
        Wait until permission is granted to make a request.
        """
        wait_time = await self.acquire(domain)
        if wait_time > 0:
            await asyncio.sleep(wait_time)


def get_domain_from_url(url: str) -> str:
    """Extract domain from URL for rate limiting"""
    parsed = urlparse(url)
    return parsed.netloc or parsed.path.split('/')[0]


class CrawlRateLimiter:
    """
    High-level rate limiter for crawl operations.
    Automatically handles domain extraction and provides a simple interface.
    """
    
    def __init__(
        self,
        requests_per_second: float = 2.0,
        requests_per_minute: int = 60,
        burst_capacity: int = 10,
        adaptive: bool = True,
    ):
        """
        Initialize the crawl rate limiter.
        
        Args:
            requests_per_second: Average requests per second per domain
            requests_per_minute: Global requests per minute
            burst_capacity: Burst capacity per domain
            adaptive: Whether to use adaptive rate limiting
        """
        self.per_domain = TokenBucketRateLimiter(
            requests_per_second=requests_per_second,
            burst_capacity=burst_capacity,
        )
        
        self.global_limiter = SlidingWindowRateLimiter(
            requests_per_window=requests_per_minute,
            window_size_seconds=60,
        )
        
        self.adaptive = None
        if adaptive:
            self.adaptive = AdaptiveRateLimiter()
    
    async def wait(self, url: str):
        """
        Wait until it's okay to crawl the given URL.
        
        Args:
            url: The URL to be crawled
        """
        domain = get_domain_from_url(url)
        
        # Wait for both per-domain and global limits
        domain_wait = await self.per_domain.acquire(domain)
        global_wait = await self.global_limiter.acquire("_global")
        
        wait_time = max(domain_wait, global_wait)
        
        if wait_time > 0:
            await asyncio.sleep(wait_time)
    
    async def report_response(
        self,
        url: str,
        status_code: int,
        response_time_ms: float,
    ):
        """
        Report a response for adaptive rate limiting.
        
        Args:
            url: The URL that was crawled
            status_code: HTTP status code
            response_time_ms: Response time in milliseconds
        """
        if self.adaptive:
            domain = get_domain_from_url(url)
            await self.adaptive.report_response(domain, status_code, response_time_ms)