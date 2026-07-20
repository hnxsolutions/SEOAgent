"""Framework-aware SEO patch generators.

Each supported framework has its OWN generator that emits real, SEO-safe code for
the SEO surfaces (metadata, robots, sitemap, schema, Open Graph / Twitter). A
generator NEVER reuses another framework's templates — Next.js emits
generateMetadata()/app/robots.ts, WordPress emits functions.php wp_head hooks,
Shopify emits Liquid, and so on.

Generators are pure: given a small context (site url, page label, framework), they
return code strings. They perform no I/O and touch only SEO surfaces — never UI,
business logic, auth, payments, CRM, or the database.
"""
from app.framework_patches.generators import (
    GeneratedPatchContent,
    PatchContext,
    SUPPORTED_SURFACES,
    generate_patch,
    generator_for,
    supported_frameworks,
)

__all__ = [
    "GeneratedPatchContent",
    "PatchContext",
    "SUPPORTED_SURFACES",
    "generate_patch",
    "generator_for",
    "supported_frameworks",
]
