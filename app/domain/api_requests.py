"""Strict public REST request envelopes for Phase C."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.requests import VolatilityRequest

RV_WINDOW_PRESETS = (5, 10, 20, 40, 60, 90, 120, 250, 500)
RV_WINDOW_MIN = 2
RvWindow = Annotated[int, Field(strict=True, ge=RV_WINDOW_MIN)]
RvAlignment = Literal["trailing", "forward"]


class CompareApiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    volatilityRequest: VolatilityRequest
    rvWindowSessions: RvWindow = 63
    rvAlignment: RvAlignment = "trailing"
    # Callers that only need IV (or spot/forward) can turn RV off. That skips the hidden
    # warm-up range as well, so those observations are not fetched and the warm-up rows
    # are not flagged for history the caller never asked to use.
    includeRealizedVol: bool = True
    availableThrough: date | None = None
    forceRefresh: bool = False

    @model_validator(mode="after")
    def availability_not_before_display(self) -> "CompareApiRequest":
        if (
            self.availableThrough is not None
            and self.availableThrough < self.volatilityRequest.end_date
        ):
            raise ValueError("availableThrough must be >= display end date")
        return self


class SurfaceApiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    volatilityRequest: VolatilityRequest
    forceRefresh: bool = False
