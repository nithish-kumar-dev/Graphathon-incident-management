"""0003 run progress: AgentEvent identity and the lookup used to list one run's events.

Additive only (a new label); nothing existing is touched.
"""

VERSION = 3
NAME = "agent_events"

RANGE_INDEXES: list[tuple[str, str]] = [
    ("AgentEvent", "id"),
]

UNIQUE_CONSTRAINTS: list[tuple[str, str]] = [("AgentEvent", "id")]

FULLTEXT_INDEXES: list[tuple[str, str]] = []
