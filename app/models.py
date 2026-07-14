from dataclasses import dataclass, field
from typing import Optional

@dataclass
class RawRecord:
    id: str
    name: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    source: Optional[str] = None

@dataclass
class NormalizedRecord:
    id: str
    name: str = ""       # normalized; "" means absent/too-short
    address: str = ""
    domain: str = ""     # registrable domain, e.g. "acme.com"; "" means absent
    raw: Optional[RawRecord] = None

@dataclass
class CanonicalRecord:
    group_id: int
    name: str = ""
    address: str = ""
    domain: str = ""
    confidence: int = 100
    member_ids: list[str] = field(default_factory=list)

@dataclass
class PairDecision:
    score: float
    decision: str        # "merge" | "review" | "no_merge"
    confidence: int
    reason: str
