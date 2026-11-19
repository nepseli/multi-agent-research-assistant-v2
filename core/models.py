from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Budget(BaseModel):
    max_searches: int = Field(ge=0)
    max_pages: int = Field(ge=0)
    max_pdfs: int = Field(ge=0)
    firecrawl_credits: int = Field(ge=0)
    timeout_s: int = Field(gt=0)


class ResearchPlan(BaseModel):
    topic: str
    domain: str = "general"
    tier: int = Field(ge=0, le=3)
    rationale: str = ""
    subqueries: list[str] = Field(default_factory=list)
    use_academic: bool = False
    use_pdf_parsing: bool = False
    budget: Budget
    warnings: list[str] = Field(default_factory=list)


class Source(BaseModel):
    id: str
    url: str
    title: str
    kind: str
    tool: str
    doi: str | None = None
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    retrieved_at: str
    content_path: str | None = None


class FigureSpec(BaseModel):
    kind: Literal["bar", "line", "pie"]
    title: str
    data_ref: str
    x: str
    y: str
    caption: str
    source_ids: list[str] = Field(default_factory=list)

    @field_validator("data_ref")
    @classmethod
    def _data_ref_required(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("data_ref is required")
        return v
