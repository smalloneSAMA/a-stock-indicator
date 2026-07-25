"""
HTTP data fetcher with retry, backoff, rate limiting, and UA rotation.
"""

import random
import time
from urllib.parse import urlparse

import requests


# ── User-Agent pool ──────────────────────────────────────────────────
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
]


def random_ua() -> str:
    return random.choice(_UA_POOL)


# ── Rate limiter per domain ──────────────────────────────────────────
class RateLimiter:
    """Track last request time per domain to enforce minimum intervals."""

    def __init__(self):
        self._last: dict[str, float] = {}

    def wait(self, domain: str, min_interval: float = 1.0):
        """Block until minimum interval has elapsed since last request to this domain."""
        now = time.time()
        elapsed = now - self._last.get(domain, 0)
        wait = min_interval - elapsed
        if wait > 0:
            time.sleep(wait + random.uniform(0, 0.5))
        self._last[domain] = time.time()

    def throttle(self, domain: str, min_interval: float = 1.0):
        """Decorator-friendly wrapper."""
        self.wait(domain, min_interval)


_limiter = RateLimiter()


# ── Domain-specific rate limits ──────────────────────────────────────
DOMAIN_RATE_LIMITS = {
    "push2.eastmoney.com": 2.0,               # Eastmoney: conservative to avoid 403
    "datacenter-web.eastmoney.com": 2.0,
    "reportapi.eastmoney.com": 2.0,
    "search-api-web.eastmoney.com": 2.0,
    "np-weblist.eastmoney.com": 1.5,
    "qt.gtimg.cn": 0.3,                       # Tencent: no blocking, mild politeness
    "data.stats.gov.cn": 1.5,                  # NBS: be polite to government server
    "vip.stock.finance.sina.com.cn": 0.5,
}


def _get_domain(url: str) -> str:
    return urlparse(url).netloc


def _min_interval(url: str) -> float:
    domain = _get_domain(url)
    for known, interval in DOMAIN_RATE_LIMITS.items():
        if known in domain:
            return interval
    return 1.0  # default


# ── Fetcher ──────────────────────────────────────────────────────────
class Fetcher:
    """HTTP GET/POST with retry, backoff, UA rotation, and rate limiting."""

    def __init__(self, max_retries: int = 2, base_timeout: int = 15):
        self.max_retries = max_retries
        self.base_timeout = base_timeout
        self.session = requests.Session()
        # Track consecutive failures per domain for circuit breaking
        self._failures: dict[str, int] = {}
        self._circuit_open: dict[str, float] = {}

    def _check_circuit(self, url: str):
        """Raise if circuit breaker is open for this domain."""
        domain = _get_domain(url)
        if domain in self._circuit_open:
            if time.time() < self._circuit_open[domain]:
                raise ConnectionError(
                    f"Circuit breaker open for {domain} — too many consecutive failures. "
                    f"Will retry after {int(self._circuit_open[domain] - time.time())}s."
                )
            else:
                # Reset after cooldown
                del self._circuit_open[domain]
                self._failures[domain] = 0

    def _record_failure(self, url: str):
        domain = _get_domain(url)
        self._failures[domain] = self._failures.get(domain, 0) + 1
        # Open circuit after just 2 failures (connection resets are severe signals)
        if self._failures[domain] >= 2:
            self._circuit_open[domain] = time.time() + 120  # 2 min cooldown

    def _record_success(self, url: str):
        domain = _get_domain(url)
        self._failures[domain] = 0

    def get(self, url: str, params: dict | None = None, headers: dict | None = None,
            timeout: int | None = None, **kwargs) -> requests.Response:
        """
        HTTP GET with full resilience:
        - Rate limiting per domain
        - Exponential backoff retry (1s → 2s → 4s)
        - UA rotation
        - Circuit breaker after 5 consecutive failures
        """
        timeout = timeout or self.base_timeout
        domain = _get_domain(url)
        _limiter.wait(domain, _min_interval(url))

        if headers is None:
            headers = {}
        headers.setdefault("User-Agent", random_ua())

        last_exc = None
        for attempt in range(self.max_retries + 1):
            self._check_circuit(url)
            try:
                resp = self.session.get(url, params=params, headers=headers,
                                        timeout=timeout, **kwargs)
                # Treat 5xx as retryable; 403/429 as circuit-breaking
                if resp.status_code >= 500:
                    raise requests.HTTPError(f"Server error {resp.status_code}")
                if resp.status_code in (403, 429):
                    self._record_failure(url)
                    raise requests.HTTPError(f"Rate limited: {resp.status_code}")
                if resp.status_code == 404:
                    # Not retryable but don't break circuit
                    return resp
                self._record_success(url)
                return resp
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
                last_exc = e
                if attempt < self.max_retries:
                    backoff = 2 ** attempt + random.uniform(0, 1)
                    time.sleep(backoff)
                    headers["User-Agent"] = random_ua()  # rotate UA on retry
                else:
                    self._record_failure(url)

        raise ConnectionError(
            f"Failed to fetch {url} after {self.max_retries + 1} attempts. "
            f"Last error: {last_exc}"
        )

    def post(self, url: str, data: dict | None = None, json: dict | None = None,
             headers: dict | None = None, timeout: int | None = None, **kwargs) -> requests.Response:
        """HTTP POST with same resilience as GET."""
        timeout = timeout or self.base_timeout
        domain = _get_domain(url)
        _limiter.wait(domain, _min_interval(url))

        if headers is None:
            headers = {}
        headers.setdefault("User-Agent", random_ua())

        last_exc = None
        for attempt in range(self.max_retries + 1):
            self._check_circuit(url)
            try:
                resp = self.session.post(url, data=data, json=json, headers=headers,
                                         timeout=timeout, **kwargs)
                if resp.status_code >= 500:
                    raise requests.HTTPError(f"Server error {resp.status_code}")
                if resp.status_code in (403, 429):
                    self._record_failure(url)
                    raise requests.HTTPError(f"Rate limited: {resp.status_code}")
                self._record_success(url)
                return resp
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
                last_exc = e
                if attempt < self.max_retries:
                    backoff = 2 ** attempt + random.uniform(0, 1)
                    time.sleep(backoff)
                    headers["User-Agent"] = random_ua()
                else:
                    self._record_failure(url)

        raise ConnectionError(
            f"Failed to POST {url} after {self.max_retries + 1} attempts. "
            f"Last error: {last_exc}"
        )


# ── Global shared fetcher instance ───────────────────────────────────
_fetcher = Fetcher()


def http_get(url: str, **kwargs) -> requests.Response:
    """Convenience: resilient HTTP GET via shared Fetcher."""
    return _fetcher.get(url, **kwargs)


def http_post(url: str, **kwargs) -> requests.Response:
    """Convenience: resilient HTTP POST via shared Fetcher."""
    return _fetcher.post(url, **kwargs)
