"""Timestamps-tab report wire shapes.

Backs the categorized, cell-addressable Report flow on the Timestamps tab. A
report names a ``category`` with an optional per-category ``subtype`` and points
at a flexible ``target`` — the whole verse, a word, a letter/grapheme cell, a
phoneme, a grapheme↔phoneme column, or a co-timed cell-group.

Served by ``inspector/routes/timestamps/reports.py``:
- ``GET    /api/ts/<slug>/reports``               → ``TsReciterReports`` (per-verse counts)
- ``GET    /api/ts/<slug>/reports/<verse_key>``   → ``TsVerseReports`` (a verse's reports)
- ``GET    /api/ts/<slug>/reports/mine``          → caller's own reports
- ``POST   /api/ts/<slug>/reports``               ← ``TsReportCreateRequest`` → ``TsReport``
- ``POST   /api/ts/<slug>/reports/<id>/resolve``  ← ``TsReportResolveRequest`` → ``TsReport``
- ``DELETE /api/ts/<slug>/reports/<id>``

``author`` on a report is populated only when the caller holds
``timestamps.see_reporter_identity`` (owner-default); everyone else sees the
report but no author. ``mine`` marks the caller's own report (matched by
``hf_user_id`` when signed in, else by the ``anon_token`` query param). ``stale``
is set when a timestamp regeneration changed the targeted content.

Per-category rules (enforced by ``TsReportCreateRequest`` validators):
- ``audio``   — comment mandatory; target verse|word.
- ``timing``  — subtype too_long|too_short|other; comment mandatory iff subtype
                is ``other``; target word|cell|phoneme|column|cell_group.
- ``tajweed`` — subtype wrong_rule|missing_rule|should_be_silent|should_not_be_silent;
                comment optional; target cell|phoneme|cell_group.
- ``mapping`` — no subtype; comment mandatory; target column.
- ``other``   — no subtype; comment mandatory; any target.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ReportCategory = Literal["audio", "timing", "mapping", "tajweed", "other"]
TargetKind = Literal["verse", "word", "cell", "phoneme", "column", "cell_group"]

#: Union of every per-category subtype. The owning category constrains which
#: values are valid (see ``TsReportCreateRequest._check``).
ReportSubtype = Literal[
    "too_long",
    "too_short",
    "other",
    "wrong_rule",
    "missing_rule",
    "should_be_silent",
    "should_not_be_silent",
]

_TIMING_SUBTYPES = frozenset({"too_long", "too_short", "other"})
_TAJWEED_SUBTYPES = frozenset(
    {"wrong_rule", "missing_rule", "should_be_silent", "should_not_be_silent"}
)
#: target_kind values allowed per category.
_ALLOWED_KINDS: dict[str, frozenset[str]] = {
    "audio": frozenset({"verse", "word"}),
    "timing": frozenset({"word", "cell", "phoneme", "column", "cell_group"}),
    "tajweed": frozenset({"cell", "phoneme", "cell_group"}),
    "mapping": frozenset({"column"}),
    "other": frozenset({"verse", "word", "cell", "phoneme", "column", "cell_group"}),
}
#: categories whose comment is always mandatory (timing.other is handled inline).
_COMMENT_REQUIRED = frozenset({"audio", "mapping", "other"})


def _verse_key_ok(verse_key: str) -> bool:
    parts = verse_key.split(":")
    return len(parts) == 2 and all(p.isdigit() and 1 <= len(p) <= 3 for p in parts)


class TsReportTarget(BaseModel):
    """What a report points at within a verse.

    Indices are word-scoped (``word_index`` 0-based in the verse;
    ``source_letter_index`` the anchoring letter; ``cell_index`` into the word's
    ``cells[]``; ``phoneme_flat_index`` a word-local indexable-phone index;
    ``share_group`` a co-timed cell-group id). Required fields per ``kind`` are
    enforced below — a ``verse`` target leaves them all unset.
    """

    model_config = ConfigDict(extra="forbid")

    kind: TargetKind
    word_index: int | None = None
    source_letter_index: int | None = None
    cell_index: int | None = None
    phoneme_flat_index: int | None = None
    share_group: int | None = None

    @model_validator(mode="after")
    def _check(self) -> TsReportTarget:
        k = self.kind
        if k == "verse":
            return self
        if self.word_index is None:
            raise ValueError(f"target kind {k!r} requires word_index")
        if k == "cell" and self.cell_index is None and self.source_letter_index is None:
            raise ValueError("target kind 'cell' requires cell_index or source_letter_index")
        if k == "phoneme" and self.phoneme_flat_index is None:
            raise ValueError("target kind 'phoneme' requires phoneme_flat_index")
        if k == "column" and self.source_letter_index is None:
            raise ValueError("target kind 'column' requires source_letter_index")
        if k == "cell_group" and self.share_group is None:
            raise ValueError("target kind 'cell_group' requires share_group")
        return self


class TsReportSnapshot(BaseModel):
    """Denormalized snapshot of the targeted shard content at create time.

    Informational + the drift fingerprint used to detect staleness on a
    re-stamp. ``rule_tags`` collapses the cell ``tag`` + ``secondary_tags``;
    ``phoneme_rule_tags`` parallels the cell's phoneme indices; ``phones`` is the
    mapped phone list (column binding).
    """

    model_config = ConfigDict(extra="forbid")

    chars: str | None = None
    role: str | None = None
    status: str | None = None
    rule_tags: list[str] = Field(default_factory=list)
    phoneme_rule_tags: list[str | None] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    share_group: int | None = None
    word_text: str | None = None
    verse_text: str | None = None
    schema_version: int | None = None


class TsReportAuthor(BaseModel):
    """Report author identity — only disclosed to identity-capable callers."""

    model_config = ConfigDict(extra="forbid")

    hf_user_id: str | None = None
    login: str | None = None
    role: str | None = None


class TsReport(BaseModel):
    """One report (verse list item / POST echo)."""

    model_config = ConfigDict(extra="forbid")

    id: int
    verse_key: str
    category: ReportCategory
    subtype: ReportSubtype | None = None
    target: TsReportTarget
    snapshot: TsReportSnapshot | None = None
    comment: str | None = None
    status: Literal["open", "resolved"]
    stale: bool = False
    resolver_comment: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    #: True when this is the caller's own report (deletable).
    mine: bool = False
    #: Author identity, present only when the caller can see reporter identity.
    author: TsReportAuthor | None = None


class TsVerseReports(BaseModel):
    """All reports on a single verse (``GET .../reports/<verse_key>``)."""

    model_config = ConfigDict(extra="forbid")

    verse_key: str
    reports: list[TsReport] = Field(default_factory=list)


class TsReportVerseCount(BaseModel):
    """A reported verse + its open / resolved counts (accordion pill)."""

    model_config = ConfigDict(extra="forbid")

    verse_key: str
    open_count: int
    resolved_count: int


class TsReciterReports(BaseModel):
    """Every reported verse for a reciter (``GET .../reports``)."""

    model_config = ConfigDict(extra="forbid")

    reports: list[TsReportVerseCount] = Field(default_factory=list)


class TsReportCreateRequest(BaseModel):
    """Create the caller's report on a verse (``POST .../reports``)."""

    model_config = ConfigDict(extra="forbid")

    verse_key: str
    category: ReportCategory
    subtype: ReportSubtype | None = None
    target: TsReportTarget
    comment: str | None = None
    #: Anonymous browser token (omitted/ignored when the caller is signed in).
    anon_token: str | None = None

    @field_validator("verse_key")
    @classmethod
    def _verse_key(cls, v: str) -> str:
        if not _verse_key_ok(v):
            raise ValueError("verse_key must be 'surah:ayah' (e.g. '2:45')")
        return v

    @field_validator("comment")
    @classmethod
    def _trim_comment(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None

    @model_validator(mode="after")
    def _check(self) -> TsReportCreateRequest:
        cat = self.category
        # subtype ↔ category
        if cat == "timing":
            if self.subtype not in _TIMING_SUBTYPES:
                raise ValueError("timing reports require subtype too_long|too_short|other")
        elif cat == "tajweed":
            if self.subtype not in _TAJWEED_SUBTYPES:
                raise ValueError(
                    "tajweed reports require subtype "
                    "wrong_rule|missing_rule|should_be_silent|should_not_be_silent"
                )
        elif self.subtype is not None:
            raise ValueError(f"{cat} reports take no subtype")
        # target kind ↔ category
        if self.target.kind not in _ALLOWED_KINDS[cat]:
            raise ValueError(
                f"{cat} reports cannot target {self.target.kind!r}; "
                f"allowed: {sorted(_ALLOWED_KINDS[cat])}"
            )
        # mandatory comment
        needs_comment = cat in _COMMENT_REQUIRED or (cat == "timing" and self.subtype == "other")
        if needs_comment and not self.comment:
            raise ValueError(f"{cat} reports require a comment")
        return self


class TsReportResolveRequest(BaseModel):
    """Resolve a report (``POST .../reports/<id>/resolve``). Owner-gated."""

    model_config = ConfigDict(extra="forbid")

    comment: str | None = None

    @field_validator("comment")
    @classmethod
    def _trim_comment(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip() or None
