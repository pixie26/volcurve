"""Instrument domain model (fields verified against /v1/instruments response)."""

from __future__ import annotations

from pydantic import BaseModel


class Instrument(BaseModel):
    code: str  # BNP code, e.g. US_QQQ
    type: str | None = None  # stock | tracker | index
    bbgCode: str | None = None
    isin: str | None = None
    ric: str | None = None
    sedol: str | None = None
    countryCode: str | None = None
    currencyCode: str | None = None
    region: str | None = None
    marketPlaceCode: str | None = None
    marketName: str | None = None
    companyName: str | None = None
    status: str | None = None
    intraday: bool | None = None
    volVarSwap: bool | None = None
