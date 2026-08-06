"""Strict domain requests and BNP wire serialization.

The Cortex endpoint supports several mutually exclusive field combinations.
Each combination has its own model so forbidden fields fail locally instead of
being silently sent upstream.  Domain values stay readable (``p25.0``); only
``to_api_body`` applies BNP's underscore encoding (``p25_0``).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

CodeType = Literal["bnpp", "bbg", "isin", "ric", "sedol"]
Layout = Literal["matrix", "vector"]
VolatilityConvention = Literal["bsVol", "bnppVol"]
MoneynessRule = Literal["relative_to_forward", "relative_to_spot_ref"]

MONEYNESS_LEVELS = (
    5.0,
    10.0,
    20.0,
    30.0,
    40.0,
    50.0,
    55.0,
    60.0,
    65.0,
    70.0,
    75.0,
    80.0,
    85.0,
    90.0,
    95.0,
    97.5,
    100.0,
    102.5,
    105.0,
    110.0,
    115.0,
    120.0,
    125.0,
    130.0,
    135.0,
    140.0,
    145.0,
    150.0,
    160.0,
    170.0,
    180.0,
    190.0,
    200.0,
    225.0,
    250.0,
    275.0,
)

SLIDING_MATURITIES = (
    "1W",
    "2W",
    "3W",
    "1M",
    "2M",
    "3M",
    "4M",
    "5M",
    "6M",
    "7M",
    "8M",
    "9M",
    "10M",
    "11M",
    "12M",
    "15M",
    "18M",
    "21M",
    "24M",
    "27M",
    "30M",
    "33M",
    "36M",
    "42M",
    "48M",
    "54M",
    "60M",
    "72M",
    "84M",
    "96M",
    "108M",
    "120M",
    "180M",
    "240M",
)
DELTA_MATURITIES = SLIDING_MATURITIES[:-2]
MATURITY_ALIASES = {
    "1Y": "12M",
    "2Y": "24M",
    "3Y": "36M",
    "5Y": "60M",
    "10Y": "120M",
    "15Y": "180M",
    "20Y": "240M",
}
DELTA_CODES = (
    "p1.0",
    "p5.0",
    "p10.0",
    "p15.0",
    "p20.0",
    "p25.0",
    "p30.0",
    "p35.0",
    "p40.0",
    "p45.0",
    "p47.5",
    "p50.0",
    "c50.0",
    "c47.5",
    "c45.0",
    "c40.0",
    "c35.0",
    "c30.0",
    "c25.0",
    "c20.0",
    "c15.0",
    "c10.0",
    "c5.0",
    "c1.0",
)


def _ordered_pair(low, high, *, label: str) -> None:
    if low is not None and high is not None and low > high:
        raise ValueError(f"{label}: low must be <= high")


def _validate_moneyness(value: float) -> float:
    if value not in MONEYNESS_LEVELS:
        raise ValueError("unsupported BNP moneyness level")
    return value


class VolatilityRequestBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    code_type: CodeType = "bnpp"
    volatility_convention: VolatilityConvention = "bsVol"
    start_date: date
    end_date: date
    layout: Layout = "matrix"

    @field_validator("code")
    @classmethod
    def code_reasonable(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 64 or not re.fullmatch(r"[A-Za-z0-9_.\-]+", value):
            raise ValueError("invalid instrument code")
        return value

    @model_validator(mode="after")
    def dates_ordered(self) -> "VolatilityRequestBase":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be >= start_date")
        return self

    def to_api_body(self) -> dict:
        """Compatibility facade; BNP wire logic lives in the Cortex adapter."""
        from app.clients.cortex.serializers import serialize_volatility_request

        return serialize_volatility_request(self)

    def request_hash(self, api_version: str) -> str:
        from app.clients.cortex.serializers import volatility_request_hash

        return volatility_request_hash(self, api_version)


class SlidingMoneynessRequest(VolatilityRequestBase):
    maturity_rule: Literal["sliding"] = "sliding"
    strike_rule: MoneynessRule = "relative_to_forward"
    low_strike: float
    high_strike: float
    low_maturity: str
    high_maturity: str

    @field_validator("low_strike", "high_strike")
    @classmethod
    def strike_supported(cls, value: float) -> float:
        return _validate_moneyness(value)

    @field_validator("low_maturity", "high_maturity")
    @classmethod
    def maturity_supported(cls, value: str) -> str:
        value = value.upper()
        value = MATURITY_ALIASES.get(value, value)
        if value not in SLIDING_MATURITIES:
            raise ValueError("unsupported sliding maturity")
        return value

    @model_validator(mode="after")
    def coordinates_ordered(self) -> "SlidingMoneynessRequest":
        _ordered_pair(self.low_strike, self.high_strike, label="strike range")
        if SLIDING_MATURITIES.index(self.low_maturity) > SLIDING_MATURITIES.index(
            self.high_maturity
        ):
            raise ValueError("maturity range: low must be <= high")
        return self


class SlidingDeltaRequest(VolatilityRequestBase):
    maturity_rule: Literal["sliding"] = "sliding"
    strike_rule: Literal["delta"] = "delta"
    low_delta_strike: str | None = None
    high_delta_strike: str | None = None
    low_maturity: str | None = None
    high_maturity: str | None = None

    @field_validator("low_delta_strike", "high_delta_strike")
    @classmethod
    def delta_supported(cls, value: str | None) -> str | None:
        if value is not None and value not in DELTA_CODES:
            raise ValueError("unsupported delta code")
        return value

    @field_validator("low_maturity", "high_maturity")
    @classmethod
    def maturity_supported(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.upper()
        value = MATURITY_ALIASES.get(value, value)
        if value not in DELTA_MATURITIES:
            raise ValueError("unsupported delta maturity")
        return value

    @model_validator(mode="after")
    def coordinates_ordered(self) -> "SlidingDeltaRequest":
        if self.low_delta_strike and self.high_delta_strike:
            if DELTA_CODES.index(self.low_delta_strike) > DELTA_CODES.index(self.high_delta_strike):
                raise ValueError("delta range: low must precede high")
        if self.low_maturity and self.high_maturity:
            if DELTA_MATURITIES.index(self.low_maturity) > DELTA_MATURITIES.index(
                self.high_maturity
            ):
                raise ValueError("maturity range: low must be <= high")
        return self


class FixedStrikeRequest(VolatilityRequestBase):
    maturity_rule: Literal["fixed", "listed"] = "fixed"
    strike_rule: Literal["fixed"] = "fixed"
    low_fixed_strike: float | None = None
    high_fixed_strike: float | None = None
    low_fixed_maturity: date | None = None
    high_fixed_maturity: date | None = None

    @field_validator("low_fixed_strike", "high_fixed_strike")
    @classmethod
    def fixed_strike_positive(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("fixed strike must be positive")
        return value

    @model_validator(mode="after")
    def coordinates_ordered(self) -> "FixedStrikeRequest":
        _ordered_pair(self.low_fixed_strike, self.high_fixed_strike, label="fixed strike range")
        _ordered_pair(
            self.low_fixed_maturity, self.high_fixed_maturity, label="fixed maturity range"
        )
        return self


class ListedMaturityMoneynessRequest(VolatilityRequestBase):
    maturity_rule: Literal["fixed", "listed"]
    strike_rule: MoneynessRule
    low_strike: float
    high_strike: float
    low_fixed_maturity: date | None = None
    high_fixed_maturity: date | None = None

    @field_validator("low_strike", "high_strike")
    @classmethod
    def strike_supported(cls, value: float) -> float:
        return _validate_moneyness(value)

    @model_validator(mode="after")
    def coordinates_ordered(self) -> "ListedMaturityMoneynessRequest":
        _ordered_pair(self.low_strike, self.high_strike, label="strike range")
        _ordered_pair(
            self.low_fixed_maturity, self.high_fixed_maturity, label="fixed maturity range"
        )
        return self


VolatilityRequest = Annotated[
    SlidingMoneynessRequest
    | SlidingDeltaRequest
    | FixedStrikeRequest
    | ListedMaturityMoneynessRequest,
    Field(union_mode="smart"),
]
VOLATILITY_REQUEST_ADAPTER = TypeAdapter(VolatilityRequest)


def parse_volatility_request(data: dict) -> VolatilityRequest:
    return VOLATILITY_REQUEST_ADAPTER.validate_python(data)


# Backwards-compatible name used by the completed Phase 1-3 single-coordinate
# pipeline.  It is intentionally strict and now means sliding K/F or K/S only.
ImpliedVolRequest = SlidingMoneynessRequest
