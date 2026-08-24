"""Compact native timestamp shard v12 stored as ``timestamps/<chapter>.json.br``."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TsShardPart = tuple[str, int, int, int, int]
TsWordTiming = tuple[int, int]
TsSoundTiming = tuple[int, int]
TsUnitTiming = tuple[int, int, str, int | None, int | None, Literal[0, 1]]
TsColumnTiming = tuple[str | int, int | None, int | None]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TsCompactRender(_Closed):
    v: Literal[1]
    m: tuple[str, str, str]
    p: list[str]
    r: list[str]
    w: list[list[Any]]
    b: list[list[Any]]

    @model_validator(mode="after")
    def _counts(self):
        if len(self.w) != len(self.b):
            raise ValueError("compact word and boundary counts differ")
        return self


class TsShardTiming(_Closed):
    w: list[TsWordTiming]
    s: list[TsSoundTiming]
    l: list[TsUnitTiming]  # noqa: E741 - compact wire key, not a local variable
    c: list[TsColumnTiming]

    @model_validator(mode="after")
    def _ordered(self):
        for label, rows in (("word", self.w), ("sound", self.s)):
            if any(end < start for start, end in rows):
                raise ValueError(f"{label} timing end precedes start")
        for _, _, _, start, end, _ in self.l:
            if (start is None) != (end is None):
                raise ValueError("letter timing has a half-null interval")
            if start is not None and end is not None and end < start:
                raise ValueError("letter timing end precedes start")
        for _, start, end in self.c:
            if (start is None) != (end is None):
                raise ValueError("column timing has a half-null interval")
            if start is not None and end is not None and end < start:
                raise ValueError("column timing end precedes start")
        return self


class TsShardReading(_Closed):
    id: str = Field(min_length=1)
    parts: list[TsShardPart]
    render: TsCompactRender
    timing: TsShardTiming

    @model_validator(mode="after")
    def _closure(self):
        if len(self.timing.w) != len(self.render.w):
            raise ValueError("word timing count differs from compact words")
        if len(self.timing.s) != len(self.render.p):
            raise ValueError("sound timing count differs from compact tokens")
        for ref, start, end, first, count in self.parts:
            if not ref or end < start or first < 0 or count < 1:
                raise ValueError("invalid compact part")
            if first + count > len(self.render.w):
                raise ValueError("compact part references unknown words")
        return self


class TsNativeProfile(_Closed):
    riwayah: str = Field(min_length=1)
    script: str = Field(min_length=1)
    variant: dict[str, str]
    extra_phonemes: list[str]


class TsShardMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal[12]
    chapter: int = Field(ge=1, le=114)
    audio_category: str = Field(min_length=1)
    phonemizer_version: str = Field(min_length=1)
    native_schema_version: Literal[2]
    renderer_codec_version: Literal[1]
    native_profile: TsNativeProfile


class TsShardDoc(_Closed):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    meta: TsShardMeta = Field(alias="_meta")
    readings: list[TsShardReading]


__all__ = [
    "TsColumnTiming",
    "TsCompactRender",
    "TsNativeProfile",
    "TsShardDoc",
    "TsShardMeta",
    "TsShardPart",
    "TsShardReading",
    "TsShardTiming",
    "TsSoundTiming",
    "TsUnitTiming",
    "TsWordTiming",
]
