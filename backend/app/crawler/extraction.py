"""
Pure extraction helpers for the Playwright crawler.

The browser-facing crawler calls these helpers after collecting DOM data so the
normalization and classification behavior can be unit tested without launching
Chromium.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

from app.core.url_utils import URLNormalizer


SKIPPED_HREF_PREFIXES = ("#", "mailto:", "tel:", "javascript:", "data:")


def normalize_whitespace(value: Optional[str]) -> str:
    """Collapse repeated whitespace while preserving readable text."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def count_words(text: Optional[str]) -> int:
    """Count human-readable words in extracted page text."""
    if not text:
        return 0
    return len(re.findall(r"\b[\w'-]+\b", text))


def content_hash(text: Optional[str]) -> Optional[str]:
    """Hash normalized text for duplicate-content detection."""
    normalized = normalize_whitespace(text)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def parse_json_ld_scripts(scripts: Iterable[Optional[str]]) -> Tuple[Optional[Any], List[str]]:
    """Parse JSON-LD script contents and return markup plus discovered @type values."""
    schemas: List[Any] = []
    schema_types: set[str] = set()

    for script in scripts:
        if not script or not script.strip():
            continue
        try:
            parsed = json.loads(script)
        except json.JSONDecodeError:
            continue

        schemas.append(parsed)
        _collect_schema_types(parsed, schema_types)

    if not schemas:
        return None, []

    markup: Any = schemas[0] if len(schemas) == 1 else schemas
    return markup, sorted(schema_types)


def classify_links(
    base_url: str,
    raw_links: Iterable[Dict[str, Any]],
    allowed_domains: Optional[List[str]] = None,
    follow_subdomains: bool = False,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str], List[str]]:
    """
    Normalize and classify extracted anchor tags as crawl-internal or external.

    When allowed_domains is provided, those domains are considered crawl-internal;
    otherwise same host is internal, with optional base-domain subdomain support.
    """
    internal_links: List[Dict[str, Any]] = []
    external_links: List[Dict[str, Any]] = []
    internal_urls: List[str] = []
    external_urls: List[str] = []
    seen_links: set[str] = set()

    allowed = {domain.lower() for domain in allowed_domains or [] if domain}

    for raw_link in raw_links:
        href = str(raw_link.get("href") or "").strip()
        if not href or href.lower().startswith(SKIPPED_HREF_PREFIXES):
            continue

        absolute_url = URLNormalizer.resolve_relative_url(base_url, href)
        normalized = URLNormalizer.normalize_url(absolute_url)
        if not normalized or normalized in seen_links:
            continue

        rel = str(raw_link.get("rel") or "")
        target_domain = URLNormalizer.get_domain(normalized)
        base_domain = URLNormalizer.get_domain(base_url)

        if allowed:
            is_internal = bool(target_domain and target_domain in allowed)
        elif follow_subdomains:
            is_internal = (
                URLNormalizer.get_base_domain(normalized)
                == URLNormalizer.get_base_domain(base_url)
            )
        else:
            is_internal = bool(target_domain and base_domain and target_domain == base_domain)

        if is_internal:
            normalized = _normalize_internal_scheme(base_url, normalized)
            absolute_url = normalized
            if normalized in seen_links:
                continue

        seen_links.add(normalized)

        link_info = {
            "url": absolute_url,
            "normalized_url": normalized,
            "text": normalize_whitespace(raw_link.get("text")),
            "rel": rel,
            "target": str(raw_link.get("target") or ""),
            "is_nofollow": "nofollow" in rel.lower(),
            "is_sponsored": "sponsored" in rel.lower(),
            "is_ugc": "ugc" in rel.lower(),
        }

        if is_internal:
            internal_links.append(link_info)
            internal_urls.append(normalized)
        else:
            external_links.append(link_info)
            external_urls.append(normalized)

    return internal_links, external_links, internal_urls, external_urls


def _normalize_internal_scheme(base_url: str, target_url: str) -> str:
    """Use the crawl seed scheme for same-domain internal URLs."""
    base = urlparse(base_url)
    target = urlparse(target_url)
    if base.scheme and target.scheme and base.netloc.lower() == target.netloc.lower():
        target = target._replace(scheme=base.scheme)
        return urlunparse(target)
    return target_url


def _collect_schema_types(value: Any, schema_types: set[str]) -> None:
    if isinstance(value, dict):
        raw_type = value.get("@type")
        if isinstance(raw_type, str):
            schema_types.add(raw_type)
        elif isinstance(raw_type, list):
            schema_types.update(str(item) for item in raw_type if item)

        for nested in value.values():
            _collect_schema_types(nested, schema_types)
    elif isinstance(value, list):
        for item in value:
            _collect_schema_types(item, schema_types)
