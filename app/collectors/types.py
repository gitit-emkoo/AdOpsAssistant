from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class AdMetrics:
    platform: str
    metric_date: str
    spend: float
    impressions: int
    clicks: int
    conversions: float
    conversion_value: float
    installs: float = 0.0
    source: str = "live"

    @property
    def ctr(self) -> float:
        return (self.clicks / self.impressions * 100) if self.impressions else 0.0

    @property
    def cpc(self) -> float:
        return (self.spend / self.clicks) if self.clicks else 0.0

    @property
    def cpa(self) -> float:
        return (self.spend / self.conversions) if self.conversions else 0.0

    @property
    def cpi(self) -> float:
        return (self.spend / self.installs) if self.installs else 0.0

    @property
    def install_rate(self) -> float:
        return (self.installs / self.clicks * 100) if self.clicks else 0.0

    @property
    def roas(self) -> float:
        return (self.conversion_value / self.spend) if self.spend else 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.update(
            {
                "ctr": round(self.ctr, 2),
                "cpc": round(self.cpc, 2),
                "cpa": round(self.cpa, 2),
                "cpi": round(self.cpi, 2),
                "install_rate": round(self.install_rate, 2),
                "roas": round(self.roas, 2),
            }
        )
        return data
