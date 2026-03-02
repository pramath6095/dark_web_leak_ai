"""In-memory state for the query-generator service.

Tracks:
- Company information (name, description)
- All generated queries and which have been served
- Search strings derived from company info
- Generation round counter
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class ServiceState:
    """Thread-safe state container for the query generator."""

    company_name: str = ""
    company_description: str = ""

    # Organization profile fields (used by detailed prompts)
    primary_domain: str = ""
    alt_domains: str = ""
    email_suffix: str = ""
    brands: str = ""
    industry: str = ""
    aliases: str = ""
    country: str = ""

    # All queries ever generated (preserves insertion order)
    all_queries: list[str] = field(default_factory=list)

    # Queries that have already been sent via GET /queries
    served_queries: set[str] = field(default_factory=set)

    # Detailed search strings for the analysis service
    search_strings: list[str] = field(default_factory=list)

    # How many times we have asked the LLM for more queries
    generation_round: int = 0

    # Whether the service has exhausted its ability to generate
    exhausted: bool = False

    # Whether the service has been configured at all
    configured: bool = False

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def unserved_queries(self) -> list[str]:
        """Queries that have been generated but not yet served."""
        with self._lock:
            return [q for q in self.all_queries if q not in self.served_queries]

    def mark_served(self, queries: list[str]) -> None:
        """Record that these queries have been sent to the scraper."""
        with self._lock:
            self.served_queries.update(queries)

    def add_queries(self, queries: list[str]) -> int:
        """Add new queries, dedup against all existing.

        Returns the number of genuinely new queries added.
        """
        with self._lock:
            existing = set(self.all_queries)
            new_count = 0
            for q in queries:
                q_clean = q.strip()
                if q_clean and q_clean not in existing:
                    self.all_queries.append(q_clean)
                    existing.add(q_clean)
                    new_count += 1
            return new_count

    def set_search_strings(self, strings: list[str]) -> None:
        with self._lock:
            self.search_strings = list(dict.fromkeys(strings))  # dedup, preserve order


# Module-level singleton
state = ServiceState()
