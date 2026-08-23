"""Native timestamp shard v12 stored at ``timestamps/<chapter>.json.gz``."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TsShardPart(_Closed):
    ref: str = Field(min_length=1)
    t: tuple[int, int]
    word_ids: list[int]

    @model_validator(mode="after")
    def _ordered(self):
        if self.t[1] < self.t[0]:
            raise ValueError("part end precedes start")
        return self


class _Timed(_Closed):
    start_ms: int
    end_ms: int

    @model_validator(mode="after")
    def _ordered(self):
        if self.end_ms < self.start_ms:
            raise ValueError("timing end precedes start")
        return self


class TsWordTiming(_Timed):
    word_id: int


class TsSoundTiming(_Timed):
    sound_id: int


class TsUnitTiming(_Closed):
    source_unit_id: int
    start_ms: int | None
    end_ms: int | None


class TsBoundaryTiming(_Timed):
    boundary_id: int


class TsShardTiming(_Closed):
    words: list[TsWordTiming]
    sounds: list[TsSoundTiming]
    units: list[TsUnitTiming]
    boundaries: list[TsBoundaryTiming]


class TsShardReading(_Closed):
    id: str = Field(min_length=1)
    parts: list[TsShardPart]
    analysis: dict[str, Any]
    source: dict[str, Any]
    cells: dict[str, Any]
    timing: TsShardTiming

    @model_validator(mode="after")
    def _native_versions(self):
        for name in ("analysis", "source", "cells"):
            if getattr(self, name).get("schema_version") != 2:
                raise ValueError(f"{name} is not native schema 2")
        return self


class TsShardMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal[12]
    chapter: int = Field(ge=1, le=114)
    audio_category: str = Field(min_length=1)
    phonemizer_version: str = Field(min_length=1)
    native_schema_version: Literal[2]


class TsShardDoc(_Closed):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    meta: TsShardMeta = Field(alias="_meta")
    readings: list[TsShardReading]


__all__ = [
    "TsBoundaryTiming",
    "TsShardDoc",
    "TsShardMeta",
    "TsShardPart",
    "TsShardReading",
    "TsShardTiming",
    "TsSoundTiming",
    "TsUnitTiming",
    "TsWordTiming",
]
