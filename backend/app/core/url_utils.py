"""
SEO Agent SaaS - URL Utilities
URL normalization, validation, and deduplication utilities
"""
import re
import hashlib
from typing import Optional, Set, List, Tuple
from urllib.parse import urljoin, urlparse, urlunparse, parse_qs, urlencode
from furl import furl
import structlog

logger = structlog.get_logger(__name__)


class URLNormalizer:
    """Handles URL normalization for consistent comparison and deduplication"""
    
    # Common URL parameters that can be safely removed
    STRIP_PARAMS = {
        'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
        'gclid', 'fbclid', 'fb_action_ids', 'fb_action_types', 'fb_source',
        'ref', 'src', 's', 'cx', 'ie', 'oe', 'hl', 'output',
        '_ga', '_gl', 'amp', 'usqp', 'mkt_tok',
        'share_id', 'share', 'spref', 'si', 'mc_cid', 'mc_eid',
        'pk_campaign', 'pk_kwd', 'piwik_campaign', 'piwik_kwd',
        'yclid', 'ymclid', 'openstat',
    }
    
    # URL schemes that are valid for crawling
    VALID_SCHEMES = {'http', 'https'}
    
    @staticmethod
    def normalize_url(
        url: str,
        strip_fragment: bool = True,
        strip_tracking_params: bool = True,
        lowercase_path: bool = False,
        strip_www: bool = False,
        add_trailing_slash: bool = False,
    ) -> Optional[str]:
        """
        Normalize a URL for consistent comparison.
        
        Args:
            url: The URL to normalize
            strip_fragment: Remove URL fragments (#section)
            strip_tracking_params: Remove common tracking parameters
            lowercase_path: Convert path to lowercase
            strip_www: Remove www from domain
            add_trailing_slash: Add trailing slash to path
            
        Returns:
            Normalized URL or None if invalid
        """
        try:
            f = furl(url)
            
            if not f.scheme or f.scheme not in URLNormalizer.VALID_SCHEMES:
                return None
            
            if not f.host:
                return None
            
            # Strip www if requested
            if strip_www and f.host.startswith('www.'):
                f.host = f.host[4:]
            
            # Lowercase scheme and host
            f.scheme = f.scheme.lower()
            f.host = f.host.lower()
            
            # Lowercase path if requested
            if lowercase_path:
                f.path = f.path.lower()
            
            # Remove fragment if requested
            if strip_fragment:
                f.fragment = ''
            
            # Strip tracking parameters
            if strip_tracking_params:
                for param in URLNormalizer.STRIP_PARAMS:
                    if param in f.args:
                        del f.args[param]
            
            # Sort query parameters for consistency
            if f.query:
                sorted_args = sorted(f.args.items())
                f.query = urlencode(sorted_args)
            
            # Add trailing slash if requested and path doesn't have one
            if add_trailing_slash and f.path and not f.path.endswith('/'):
                f.path = f.path + '/'
            
            # Remove empty path segments
            f.path = re.sub(r'/+', '/', str(f.path))
            
            return f.url
            
        except Exception as e:
            logger.warning(f"Failed to normalize URL {url}: {e}")
            return None
    
    @staticmethod
    def get_domain(url: str) -> Optional[str]:
        """Extract the domain from a URL"""
        try:
            f = furl(url)
            if f.host:
                return f.host.lower()
            return None
        except Exception:
            return None
    
    @staticmethod
    def get_base_domain(url: str) -> Optional[str]:
        """Extract the base domain (without subdomains) from a URL"""
        domain = URLNormalizer.get_domain(url)
        if not domain:
            return None
        
        parts = domain.split('.')
        if len(parts) >= 2:
            # Handle common TLDs like .co.uk, .com.au, etc.
            if len(parts) >= 3 and parts[-2] in ['co', 'com', 'co', 'net', 'org']:
                return '.'.join(parts[-3:])
            return '.'.join(parts[-2:])
        return domain
    
    @staticmethod
    def get_subdomain(url: str) -> Optional[str]:
        """Extract the subdomain from a URL"""
        domain = URLNormalizer.get_domain(url)
        if not domain:
            return None
        
        base_domain = URLNormalizer.get_base_domain(url)
        if base_domain and domain != base_domain:
            return domain[:-(len(base_domain) + 1)]
        return None
    
    @staticmethod
    def is_same_domain(url1: str, url2: str, include_subdomains: bool = False) -> bool:
        """Check if two URLs are on the same domain"""
        if include_subdomains:
            return URLNormalizer.get_base_domain(url1) == URLNormalizer.get_base_domain(url2)
        return URLNormalizer.get_domain(url1) == URLNormalizer.get_domain(url2)
    
    @staticmethod
    def is_internal_link(base_url: str, target_url: str, follow_subdomains: bool = False) -> bool:
        """
        Check if a link is internal (same domain as base URL)
        
        Args:
            base_url: The base URL of the site being crawled
            target_url: The target URL to check
            follow_subdomains: Whether to consider subdomains as internal
            
        Returns:
            True if the link is internal
        """
        if not target_url:
            return False
        
        # Handle relative URLs
        if target_url.startswith('/') or target_url.startswith('./') or target_url.startswith('../'):
            return True
        
        # Handle protocol-relative URLs
        if target_url.startswith('//'):
            target_url = 'https:' + target_url
        
        try:
            base_parsed = urlparse(base_url)
            target_parsed = urlparse(target_url)
            
            # Check domain
            if follow_subdomains:
                return URLNormalizer.get_base_domain(base_url) == URLNormalizer.get_base_domain(target_url)
            return base_parsed.netloc.lower() == target_parsed.netloc.lower()
            
        except Exception:
            return False
    
    @staticmethod
    def url_hash(url: str) -> str:
        """Generate a consistent hash for a URL (after normalization)"""
        normalized = URLNormalizer.normalize_url(url)
        if not normalized:
            normalized = url
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    
    @staticmethod
    def is_valid_url(url: str) -> bool:
        """Check if a URL is valid and crawlable"""
        try:
            f = furl(url)
            return (
                f.scheme in URLNormalizer.VALID_SCHEMES and
                bool(f.host) and
                '.' in f.host
            )
        except Exception:
            return False
    
    @staticmethod
    def matches_path_pattern(url: str, patterns: List[str]) -> bool:
        """
        Check if a URL matches any of the given path patterns.
        Patterns can be simple strings or regex patterns.
        
        Args:
            url: URL to check
            patterns: List of path patterns to match against
            
        Returns:
            True if URL matches any pattern
        """
        try:
            parsed = urlparse(url)
            path = parsed.path.lower()
            
            for pattern in patterns:
                pattern = pattern.lower()
                
                # Check if pattern is a regex
                if pattern.startswith('regex:'):
                    regex_pattern = pattern[6:]
                    if re.search(regex_pattern, path):
                        return True
                # Simple string matching
                elif path.startswith(pattern) or path == pattern:
                    return True
                # Wildcard matching
                elif '*' in pattern:
                    regex_pattern = pattern.replace('*', '.*')
                    if re.search(regex_pattern, path):
                        return True
            
            return False
        except Exception:
            return False
    
    @staticmethod
    def resolve_relative_url(base_url: str, relative_url: str) -> str:
        """
        Resolve a relative URL against a base URL
        
        Args:
            base_url: The base URL
            relative_url: The relative URL to resolve
            
        Returns:
            The absolute URL
        """
        try:
            return urljoin(base_url, relative_url)
        except Exception:
            return relative_url


class URLDeduplicator:
    """Handles URL deduplication for crawl operations"""
    
    def __init__(self):
        self.seen_hashes: Set[str] = set()
        self.seen_urls: Set[str] = set()
    
    def is_duplicate(self, url: str, use_normalization: bool = True) -> bool:
        """
        Check if a URL has been seen before
        
        Args:
            url: URL to check
            use_normalization: Whether to normalize before checking
            
        Returns:
            True if URL is a duplicate
        """
        if use_normalization:
            normalized = URLNormalizer.normalize_url(url)
            if not normalized:
                return True  # Invalid URL treated as duplicate
            
            url_hash = URLNormalizer.url_hash(url)
            if url_hash in self.seen_hashes:
                return True
            
            self.seen_hashes.add(url_hash)
            self.seen_urls.add(normalized)
        else:
            if url in self.seen_urls:
                return True
            self.seen_urls.add(url)
        
        return False
    
    def add(self, url: str, use_normalization: bool = True) -> bool:
        """
        Add a URL to the deduplicator
        
        Args:
            url: URL to add
            use_normalization: Whether to normalize before adding
            
        Returns:
            True if URL was added (not a duplicate), False if duplicate
        """
        if self.is_duplicate(url, use_normalization):
            return False
        return True
    
    def add_batch(self, urls: List[str], use_normalization: bool = True) -> Tuple[List[str], List[str]]:
        """
        Add multiple URLs and return unique vs duplicate
        
        Args:
            urls: List of URLs to add
            use_normalization: Whether to normalize before checking
            
        Returns:
            Tuple of (unique_urls, duplicate_urls)
        """
        unique = []
        duplicates = []
        
        for url in urls:
            if self.add(url, use_normalization):
                unique.append(url)
            else:
                duplicates.append(url)
        
        return unique, duplicates
    
    def clear(self):
        """Clear all tracked URLs"""
        self.seen_hashes.clear()
        self.seen_urls.clear()
    
    def count(self) -> int:
        """Get count of unique URLs tracked"""
        return len(self.seen_urls)


class RobotsTxtParser:
    """Parser for robots.txt files"""
    
    def __init__(self, content: str):
        self.content = content
        self.rules: dict = {}
        self.sitemaps: List[str] = []
        self.crawl_delay: Optional[float] = None
        self._parse()
    
    def _parse(self):
        """Parse the robots.txt content"""
        current_user_agents = []
        
        for line in self.content.splitlines():
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            
            # Parse directive
            if ':' in line:
                directive, value = line.split(':', 1)
                directive = directive.strip().lower()
                value = value.strip()
                
                if directive == 'user-agent':
                    if value == '*':
                        current_user_agents = ['*']
                    else:
                        current_user_agents = [value.lower()]
                    
                    for ua in current_user_agents:
                        if ua not in self.rules:
                            self.rules[ua] = {'allow': [], 'deny': []}
                
                elif directive == 'disallow':
                    for ua in current_user_agents:
                        if value:  # Empty disallow means allow all
                            self.rules[ua]['deny'].append(value)
                
                elif directive == 'allow':
                    for ua in current_user_agents:
                        if value:
                            self.rules[ua]['allow'].append(value)
                
                elif directive == 'crawl-delay':
                    try:
                        self.crawl_delay = float(value)
                    except ValueError:
                        pass
                
                elif directive == 'sitemap':
                    if value and value not in self.sitemaps:
                        self.sitemaps.append(value)
    
    def can_crawl(self, url: str, user_agent: str = '*') -> bool:
        """
        Check if a URL can be crawled based on robots.txt rules
        
        Args:
            url: URL to check
            user_agent: User agent string to check rules for
            
        Returns:
            True if URL can be crawled
        """
        from urllib.parse import urlparse
        
        parsed = urlparse(url)
        path = parsed.path
        if parsed.query:
            path += '?' + parsed.query
        
        # Get rules for specific user agent first, then fallback to '*'
        ua_lower = user_agent.lower()
        rules = self.rules.get(ua_lower, self.rules.get('*', {'allow': [], 'deny': []}))
        
        # Check for matching allow rules (longest match wins)
        allow_matches = []
        for pattern in rules['allow']:
            if path.startswith(pattern):
                allow_matches.append(pattern)
        
        # Check for matching deny rules
        deny_matches = []
        for pattern in rules['deny']:
            if path.startswith(pattern):
                deny_matches.append(pattern)
        
        # If both have matches, longest match wins
        if allow_matches and deny_matches:
            longest_allow = max(allow_matches, key=len)
            longest_deny = max(deny_matches, key=len)
            return len(longest_allow) > len(longest_deny)
        
        # If only deny matches, deny
        if deny_matches:
            return False
        
        # If only allow matches or no matches, allow
        return True
    
    def get_crawl_delay(self, user_agent: str = '*') -> Optional[float]:
        """Get crawl delay for a user agent"""
        return self.crawl_delay
    
    def get_sitemaps(self) -> List[str]:
        """Get list of sitemap URLs"""
        return self.sitemaps.copy()
