"""Executable contracts, not HTTP routes or a production review engine."""
from datetime import date
from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ReviewStatus(str, Enum):
    pending = 'pending'
    running = 'running'
    pending_review = 'pending_review'
    reviewed = 'reviewed'
    issued = 'issued'
    failed = 'failed'


TRANSITIONS = {
    ReviewStatus.pending: {ReviewStatus.running, ReviewStatus.failed},
    ReviewStatus.running: {ReviewStatus.pending_review, ReviewStatus.failed},
    ReviewStatus.pending_review: {ReviewStatus.reviewed},
    ReviewStatus.reviewed: {ReviewStatus.issued},
    ReviewStatus.issued: set(), ReviewStatus.failed: set(),
}


def can_transition(current: ReviewStatus, target: ReviewStatus) -> bool:
    return target in TRANSITIONS[current]


class Location(Contract):
    segment_id: str = Field(min_length=1, max_length=100)
    start: int = Field(ge=0, strict=True)
    end: int = Field(gt=0, strict=True)

    @model_validator(mode='after')
    def ordered(self):
        if self.end <= self.start:
            raise ValueError('end must be greater than start')
        return self


RiskType = Literal['misleading', 'return_promise', 'disclosure', 'choice', 'privacy', 'other']
Severity = Literal['high', 'medium', 'low']


class AIssue(Contract):
    issue_id: str = Field(min_length=1, max_length=100)
    risk_type: RiskType
    severity: Severity
    original_text: str = Field(min_length=1, max_length=10000)
    location: Location
    reason: str = Field(min_length=1, max_length=4000)
    regulation_ids: list[str] = Field(max_length=20)
    suggestion: str = Field(min_length=1, max_length=4000)
    review_status: Literal['pending'] = 'pending'


class AIReviewResult(Contract):
    schema_version: Literal['1.0'] = '1.0'
    issues: list[AIssue] = Field(max_length=200)

    @model_validator(mode='after')
    def unique_ids(self):
        if len({i.issue_id for i in self.issues}) != len(self.issues):
            raise ValueError('duplicate issue_id')
        return self


class Regulation(Contract):
    regulation_id: str
    regulator: str
    name: str
    document_number: str
    article_number: str
    text: str
    published_at: date
    effective_at: date
    expires_at: date | None = None
    source_url: HttpUrl
    verified_at: date | None = None
    verification_status: Literal['verified', 'unverified']
    applicable_material_types: list[str]
    applicable_channels: list[str]
    scope_note: str

    @model_validator(mode='after')
    def dates(self):
        if self.verification_status == 'verified' and self.verified_at is None:
            raise ValueError('verified source needs verification date')
        if self.effective_at < self.published_at:
            raise ValueError('invalid effective date')
        if self.expires_at and self.expires_at <= self.effective_at:
            raise ValueError('invalid expiry date')
        return self


class Detection(Contract):
    operator: Literal['contains_any']
    patterns: list[str] = Field(min_length=1)
    context_note: str


class Rule(Contract):
    rule_id: str
    risk_type: RiskType
    severity: Severity
    applicable_material_types: list[str]
    applicable_channels: list[str]
    detection: Detection
    explanation: str
    regulation_ids: list[str]
    basis_type: Literal['heuristic', 'regulatory_assisted']
    verification_status: Literal['unverified', 'verified']
    enabled: bool = False

    @model_validator(mode='after')
    def heuristic_boundary(self):
        if self.verification_status == 'unverified' and self.basis_type != 'heuristic':
            raise ValueError('unverified rule must be heuristic')
        return self


class KnowledgeBase(Contract):
    schema_version: Literal['1.0']
    version: str
    regulations: list[Regulation]
    rules: list[Rule]

    @model_validator(mode='after')
    def integrity(self):
        ids = [r.regulation_id for r in self.regulations]
        if len(ids) != len(set(ids)) or len({r.rule_id for r in self.rules}) != len(self.rules):
            raise ValueError('duplicate knowledge base IDs')
        for rule in self.rules:
            if not set(rule.regulation_ids).issubset(ids):
                raise ValueError('unknown rule regulation ID')
        return self


class Issue(Contract):
    issue_id: str
    risk_type: RiskType
    severity: Severity
    original_text: str
    location: Location
    reason: str
    regulation_ids: list[str]
    suggestion: str
    review_status: Literal['pending','accepted','rejected','edited','added'] = 'pending'
    source: Literal['ai','rule','manual']
    location_status: Literal['verified','needs_verification']
    reference_status: Literal['verified','needs_verification']
    unverified_regulation_ids: list[str] = Field(default_factory=list)
    decision_reason: str | None = None
    # Original candidate and subsequent decisions are stored separately in immutable audit events.


class IssuePatch(Contract):
    expected_version: int = Field(ge=1, strict=True)
    review_status: Literal['accepted','rejected','edited']
    decision_reason: str = Field(min_length=1, max_length=4000, pattern=r'\S')
    suggestion: str | None = Field(default=None, min_length=1, max_length=4000)
    reason: str | None = Field(default=None, min_length=1, max_length=4000)
    severity: Severity | None = None
    regulation_ids: list[str] | None = None
    location: Location | None = None
    original_text: str | None = Field(default=None, min_length=1,max_length=10000)


    @model_validator(mode='after')
    def edit_contract(self):
        editable = {'suggestion','reason','severity','regulation_ids','location','original_text'}
        supplied = self.model_fields_set & editable
        if self.review_status == 'edited':
            if not supplied or any(getattr(self, name) is None for name in supplied):
                raise ValueError('edit requires non-null content')
            if ('location' in supplied) != ('original_text' in supplied):
                raise ValueError('location and original_text must be edited together')
        elif supplied:
            raise ValueError('accept/reject cannot modify content')
        return self


class ReviewCreate(Contract):
    document_id: str
    material_type: Literal['marketing','product_intro','notice']
    channel: Literal['online','offline','unknown']
    product_type: str = Field(min_length=1, max_length=100)
    audience: str = Field(min_length=1, max_length=200)
    use_ai: bool = False
    external_processing_authorized: bool = False

    @model_validator(mode='after')
    def ai_permission(self):
        if self.use_ai and not self.external_processing_authorized:
            raise ValueError('external AI processing requires explicit authorization')
        return self


class FinalizeRequest(Contract):
    expected_version: int = Field(ge=1, strict=True)
    coverage_confirmed: bool
    limitations_acknowledged: bool


def validate_issue(candidate: AIssue, segments: dict[str,str], kb: KnowledgeBase,
                   review_date: date, material_type: str, channel: str) -> Issue:
    """Server derives trust flags; an existing ID alone is insufficient evidence."""
    loc = candidate.location
    text = segments.get(loc.segment_id)
    located = text is not None and loc.end <= len(text) and text[loc.start:loc.end] == candidate.original_text
    library = {r.regulation_id:r for r in kb.regulations}
    valid, invalid = [], []
    for rid in dict.fromkeys(candidate.regulation_ids):
        r = library.get(rid)
        applicable = (r is not None and r.verification_status == 'verified'
                      and r.effective_at <= review_date
                      and (r.expires_at is None or review_date < r.expires_at)
                      and material_type in r.applicable_material_types
                      and channel in r.applicable_channels)
        (valid if applicable else invalid).append(rid)
    data = candidate.model_dump(exclude={'regulation_ids'})
    return Issue(**data, regulation_ids=valid, source='ai',
                 location_status='verified' if located else 'needs_verification',
                 reference_status='verified' if valid and not invalid else 'needs_verification',
                 unverified_regulation_ids=invalid)


def can_finalize(issues: list[Issue], *, coverage_confirmed: bool,
                 limitations_acknowledged: bool) -> bool:
    if not coverage_confirmed or not limitations_acknowledged:
        return False
    for issue in issues:
        if issue.review_status == 'pending' or not (issue.decision_reason or '').strip():
            return False
        if issue.review_status != 'rejected' and (issue.location_status != 'verified'
                                                   or issue.reference_status != 'verified'):
            return False
    return True


class ReportFields(Contract):
    applicant_department: str = Field(min_length=1, max_length=200, pattern=r'\S')
    reviewer: str = Field(min_length=1, max_length=100, pattern=r'\S')
    review_date: date
    review_scope: str = Field(min_length=1, max_length=2000, pattern=r'\S')
    final_conclusion: str = Field(min_length=1, max_length=4000, pattern=r'\S')
    remediation_notes: str = Field(min_length=1, max_length=4000, pattern=r'\S')


class ReportFieldsPatch(Contract):
    expected_version: int = Field(ge=1, strict=True)
    fields: ReportFields


class RetryRequest(Contract):
    expected_version: int = Field(ge=1, strict=True)
