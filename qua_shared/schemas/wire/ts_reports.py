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
- ``POST   /api/ts/<slug>/reports/batch``         ← ``TsReportBatchCreateRequest`` → ``TsReportBatchResult``
- ``POST   /api/ts/<slug>/reports/<id>/resolve``  ← ``TsReportResolveRequest`` → ``TsReport``
- ``POST   /api/ts/<slug>/reports/<verse>/word/<wi>/<cat>/resolve`` ← ``TsReportResolveRequest`` → ``TsVerseReports``
- ``DELETE /api/ts/<slug>/reports/<id>``

``author`` on a report is populated only when the caller holds
``timestamps.see_reporter_identity`` (owner-default); everyone else sees the
report but no author. ``mine`` marks the caller's own report (matched by
``hf_user_id`` when signed in, else by the ``anon_token`` query param). ``stale``
is set when a timestamp regeneration changed the targeted content.

Per-category rules (enforced by ``TsReportCreateRequest`` validators):
- ``audio``   — comment mandatory; target verse|word.
- ``timing``  — two boundary axes ``onset``/``offset`` (each early|late, ≥1 set),
                no subtype; comment optional; target word|cell|phoneme|column|cell_group.
                The human label is derived via ``timing_label``.
- ``tajweed`` — subtype wrong_rule|missing_rule|should_be_silent|should_not_be_silent;
                comment optional; target cell|phoneme|cell_group.
- ``mapping`` — no subtype; comment mandatory; target column.
- ``other``   — no subtype; comment mandatory; any target.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ReportCategory = Literal["audio", "timing", "mapping", "tajweed", "phonemes", "other"]
TargetKind = Literal["verse", "word", "cell", "phoneme", "column", "cell_group"]

#: Per-category subtype — tajweed only. The owning category constrains which
#: values are valid (see ``TsReportCreateRequest._check``). Timing does NOT use
#: a subtype; it carries the ``onset``/``offset`` boundary axes instead.
ReportSubtype = Literal[
    "wrong_rule",
    "missing_rule",
    "should_be_silent",
    "should_not_be_silent",
]

#: A timing boundary's error direction. A timing report sets ``onset`` and/or
#: ``offset`` (≥1); ``None`` on an axis means that boundary is fine.
TimingDir = Literal["early", "late"]

_TAJWEED_SUBTYPES = frozenset(
    {"wrong_rule", "missing_rule", "should_be_silent", "should_not_be_silent"}
)
#: target_kind values allowed per category.
_ALLOWED_KINDS: dict[str, frozenset[str]] = {
    "audio": frozenset({"verse", "word"}),
    "timing": frozenset({"word", "cell", "phoneme", "column", "cell_group"}),
    "tajweed": frozenset({"cell", "phoneme", "cell_group"}),
    "phonemes": frozenset({"phoneme"}),
    "mapping": frozenset({"column"}),
    "other": frozenset({"verse", "word", "cell", "phoneme", "column", "cell_group"}),
}
#: categories whose comment is always mandatory.
_COMMENT_REQUIRED = frozenset({"audio", "mapping", "other"})


def _verse_key_ok(verse_key: str) -> bool:
    parts = verse_key.split(":")
    return len(parts) == 2 and all(p.isdigit() and 1 <= len(p) <= 3 for p in parts)


def _validate_report_item(
    category: str,
    subtype: str | None,
    target: TsReportTarget,
    comment: str | None,
    selected_rule_tags: list[str] | None,
    onset: str | None = None,
    offset: str | None = None,
) -> None:
    """Per-item rules shared by single + batch create (keeps them from drifting):
    classification↔category, target-kind↔category, mandatory comment, and the
    ``selected_rule_tags`` gate. Raises ``ValueError``.

    Timing carries the ``onset``/``offset`` boundary axes (≥1 set) and no
    ``subtype``; tajweed carries a ``subtype`` and no axes; audio/mapping/other
    carry neither.
    """
    if category == "timing":
        if subtype is not None:
            raise ValueError("timing reports use onset/offset, not subtype")
        if onset is None and offset is None:
            raise ValueError("timing reports require at least one of onset/offset")
    elif category == "tajweed":
        if subtype not in _TAJWEED_SUBTYPES:
            raise ValueError(
                "tajweed reports require subtype "
                "wrong_rule|missing_rule|should_be_silent|should_not_be_silent"
            )
        if onset is not None or offset is not None:
            raise ValueError("onset/offset are timing-only")
    else:
        if subtype is not None:
            raise ValueError(f"{category} reports take no subtype")
        if onset is not None or offset is not None:
            raise ValueError("onset/offset are timing-only")
    if target.kind not in _ALLOWED_KINDS[category]:
        raise ValueError(
            f"{category} reports cannot target {target.kind!r}; "
            f"allowed: {sorted(_ALLOWED_KINDS[category])}"
        )
    if category in _COMMENT_REQUIRED and not comment:
        raise ValueError(f"{category} reports require a comment")
    if selected_rule_tags and not (category == "tajweed" and subtype == "wrong_rule"):
        raise ValueError("selected_rule_tags is only valid on tajweed wrong_rule reports")


def timing_label(onset: str | None, offset: str | None) -> str:
    """Human label for a timing report's boundary axes (the report matrix).

    onset/offset each ``early`` | ``late`` | ``None`` (fine). Both-None is not a
    valid timing report (the validator rejects it) and maps to ``"Timing"`` here
    defensively. Single source of truth for the derived label — BE notification
    copy and the FE both call this rather than hardcoding."""
    both: dict[tuple[str | None, str | None], str] = {
        ("early", "late"): "Too long",
        ("late", "early"): "Too short",
        ("early", "early"): "Shifted earlier",
        ("late", "late"): "Shifted later",
    }
    pair_label = both.get((onset, offset))
    if pair_label is not None:
        return pair_label
    if onset and offset is None:
        return "Starts early" if onset == "early" else "Starts late"
    if offset and onset is None:
        return "Finishes early" if offset == "early" else "Finishes late"
    return "Timing"


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
    #: Timing boundary axes (timing only); ``None`` on an axis = that boundary is fine.
    onset: TimingDir | None = None
    offset: TimingDir | None = None
    target: TsReportTarget
    snapshot: TsReportSnapshot | None = None
    comment: str | None = None
    #: Internal tajweed tag id(s) the reporter marked wrong (wrong_rule only).
    selected_rule_tags: list[str] = Field(default_factory=list)
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
    #: Timing boundary axes (timing only; ≥1 set). ``None`` = that boundary is fine.
    onset: TimingDir | None = None
    offset: TimingDir | None = None
    target: TsReportTarget
    comment: str | None = None
    #: Internal tajweed tag id(s) marked wrong (wrong_rule only).
    selected_rule_tags: list[str] = Field(default_factory=list)
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
        _validate_report_item(
            self.category,
            self.subtype,
            self.target,
            self.comment,
            self.selected_rule_tags,
            self.onset,
            self.offset,
        )
        return self


class TsReportResolveRequest(BaseModel):
    """Resolve a report (``POST .../reports/<id>/resolve``, or a timing
    word-group via ``.../word/<word_index>/<category>/resolve``). Owner-gated."""

    model_config = ConfigDict(extra="forbid")

    comment: str | None = None

    @field_validator("comment")
    @classmethod
    def _trim_comment(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip() or None


class TsReportBatchItem(BaseModel):
    """One staged cell-annotation in a batch submit. Verse + identity are
    batch-level, so an item carries only its own category/subtype/target/comment
    (+ ``selected_rule_tags`` for tajweed wrong_rule). Same per-category rules as
    a single create (shared ``_validate_report_item``)."""

    model_config = ConfigDict(extra="forbid")

    category: ReportCategory
    subtype: ReportSubtype | None = None
    #: Timing boundary axes (timing only; ≥1 set). ``None`` = that boundary is fine.
    onset: TimingDir | None = None
    offset: TimingDir | None = None
    target: TsReportTarget
    comment: str | None = None
    selected_rule_tags: list[str] = Field(default_factory=list)

    @field_validator("comment")
    @classmethod
    def _trim_comment(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip() or None

    @model_validator(mode="after")
    def _check(self) -> TsReportBatchItem:
        _validate_report_item(
            self.category,
            self.subtype,
            self.target,
            self.comment,
            self.selected_rule_tags,
            self.onset,
            self.offset,
        )
        return self


class TsReportBatchCreateRequest(BaseModel):
    """Submit many staged annotations on ONE verse in a single transaction
    (``POST .../reports/batch``). Items may mix categories (timing + tajweed)."""

    model_config = ConfigDict(extra="forbid")

    verse_key: str
    items: list[TsReportBatchItem] = Field(min_length=1, max_length=200)
    #: Anonymous browser token (ignored when the caller is signed in).
    anon_token: str | None = None

    @field_validator("verse_key")
    @classmethod
    def _verse_key(cls, v: str) -> str:
        if not _verse_key_ok(v):
            raise ValueError("verse_key must be 'surah:ayah' (e.g. '2:45')")
        return v


class TsReportBatchResult(BaseModel):
    """Echo of a batch submit: the created/updated reports in input order, plus
    insert vs upsert counts."""

    model_config = ConfigDict(extra="forbid")

    verse_key: str
    reports: list[TsReport] = Field(default_factory=list)
    created_count: int
    updated_count: int
