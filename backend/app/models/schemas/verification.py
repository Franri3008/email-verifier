from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class ModelId(StrEnum):
    GPT_TERRA = "openai/gpt-5.6-terra"
    GPT_LUNA = "openai/gpt-6-luna"
    CLAUDE_HAIKU = "anthropic/claude-haiku-5.5"
    CLAUDE_SONNET = "anthropic/claude-sonnet-5.5"
    CLAUDE_OPUS = "anthropic/claude-opus-5.5"


class Quality(StrEnum):
    STANDARD = "Standard"
    HIGH = "High"
    EXTREME = "Extreme"


class Candidate(BaseModel):
    email: str
    confidence: str = "unknown"
    source_url: str | None = None
    rationale: str | None = None


class VerificationResult(BaseModel):
    email: str
    result: str
    classification: str
    status: str
    normalized_email: str | None = None
    is_disposable: bool | None = None
    is_role_account: bool | None = None
    is_free_address: bool | None = None
    suggestions: list[str] = Field(default_factory=list)
    candidate_confidence: str | None = None
    candidate_source_url: str | None = None
    candidate_rationale: str | None = None


class SimpleCheckRequest(BaseModel):
    query: str = Field(min_length=3, max_length=300)
    context: str = Field(default="", max_length=500)
    model: ModelId = ModelId.GPT_LUNA
    quality: Quality = Quality.STANDARD

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        return value.strip()


class SimpleCheckResponse(BaseModel):
    query: str
    lookup_used: bool
    model: str | None
    results: list[VerificationResult]


class BatchSummary(BaseModel):
    total_rows: int
    output_rows: int
    emails_checked: int
    generated_candidates: int
    counts: dict[str, int]


class BatchResponse(BaseModel):
    batch_id: str
    filename: str
    preview: list[dict[str, object]]
    columns: list[str]
    summary: BatchSummary


class ModelOption(BaseModel):
    id: str
    label: str
    note: str


class HealthResponse(BaseModel):
    status: str
    openrouter_configured: bool
    verifalia_configured: bool
