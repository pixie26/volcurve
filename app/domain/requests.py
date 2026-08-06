"""Normalized internal request models.

These are the only shapes the rest of the application uses; conversion to
BNP wire format (underscore strike strings, field names) happens here and
nowhere else.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

MATURITY_RE = re.compile(r"^\d{1,3}[WwMmYy]$")  # e.g. 1W, 3M, 120M, 2Y

StrikeRule = Literal["relative_to_forward", "relative_to_spot_ref", "fixed", "delta"]
MaturityRule = Literal["sliding", "fixed", "listed"]
CodeType = Literal["bnpp", "ric"]


def strike_to_api(value: float) -> str:
    """BNP sliding strikes use underscore decimals: 100 -> '100_0', 97.5 -> '97_5'."""
    if float(value).is_integer():
        return f"{int(value)}_0"
    return str(value).replace(".", "_")


class ImpliedVolRequest(BaseModel):
    code: str
    code_type: CodeType = "bnpp"
    maturity_rule: MaturityRule = "sliding"
    strike_rule: StrikeRule = "relative_to_forward"
    volatility_convention: str = "bsVol"
    start_date: date
    end_date: date
    # sliding coordinates
    low_strike: float | None = None
    high_strike: float | None = None
    low_maturity: str | None = None
    high_maturity: str | None = None
    layout: Literal["matrix", "vector"] = "matrix"

    @field_validator("code")
    @classmethod
    def code_reasonable(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 64 or not re.fullmatch(r"[A-Za-z0-9_.\-]+", v):
            raise ValueError("invalid instrument code")
        return v

    @field_validator("low_maturity", "high_maturity")
    @classmethod
    def maturity_format(cls, v: str | None) -> str | None:
        if v is not None and not MATURITY_RE.fullmatch(v):
            raise ValueError(f"maturity must look like 1W/3M/2Y, got {v!r}")
        return v.upper() if v else v

    @model_validator(mode="after")
    def dates_ordered(self) -> "ImpliedVolRequest":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be >= start_date")
        if self.maturity_rule == "sliding":
            if not (self.low_maturity and self.high_maturity):
                raise ValueError("sliding maturity rule requires low/high maturity")
            if self.strike_rule in ("relative_to_forward", "relative_to_spot_ref"):
                if self.low_strike is None or self.high_strike is None:
                    raise ValueError("sliding strike rule requires low/high strike")
        return self

    def to_api_body(self) -> dict:
        body: dict = {
            "code": self.code,
            "codeType": self.code_type,
            "maturityRule": self.maturity_rule,
            "strikeRule": self.strike_rule,
            "volatilityConvention": self.volatility_convention,
            "startDate": self.start_date.isoformat(),
            "endDate": self.end_date.isoformat(),
            "layout": self.layout,
        }
        if self.low_strike is not None:
            body["lowStrike"] = strike_to_api(self.low_strike)
        if self.high_strike is not None:
            body["highStrike"] = strike_to_api(self.high_strike)
        if self.low_maturity:
            body["lowMaturity"] = self.low_maturity
        if self.high_maturity:
            body["highMaturity"] = self.high_maturity
        return body

    def request_hash(self, api_version: str) -> str:
        """Stable cache key: full normalized request + endpoint + API version."""
        canonical = json.dumps(self.to_api_body(), sort_keys=True)
        return hashlib.sha256(
            f"implied-volatility|{api_version}|{canonical}".encode()
        ).hexdigest()[:32]
