"""Pydantic models for API request/response."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


# ----- User -----


class UserCreate(BaseModel):
    email: str
    name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    student_number: Optional[str] = None
    gender: Optional[str] = None
    appointment_at: Optional[datetime] = None


class UserUpdate(BaseModel):
    name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    student_number: Optional[str] = None
    gender: Optional[str] = None
    appointment_at: Optional[datetime] = None


class UserResponse(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    student_number: Optional[str] = None
    gender: Optional[str] = None
    appointment_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


# ----- Jump test submit (same shape as run_analysis input) -----


class JumpTestSubmit(BaseModel):
    """Request body for POST /jump-tests. Matches run_analysis() input. user_id links to a user; athlete_id optional."""

    athlete_id: Optional[str] = Field(None, description="Optional athlete identifier (defaults to user_id or 'unknown')")
    test_type: str = Field(..., description="CMJ, SJ, or DJ")
    test_duration: float = Field(..., gt=0, description="Duration in seconds")
    sample_count: Optional[int] = None
    force: Optional[List[float]] = None
    total_force: Optional[List[float]] = None
    left_force: List[float] = Field(..., description="Left force plate samples (N)")
    right_force: List[float] = Field(..., description="Right force plate samples (N)")
    name: Optional[str] = None
    started_at: Optional[str] = None
    user_id: Optional[str] = None

    @model_validator(mode="after")
    def require_force_or_total_force(self) -> "JumpTestSubmit":
        if not self.force and not self.total_force:
            raise ValueError("Either 'force' or 'total_force' is required")
        return self

    def to_analysis_payload(self) -> Dict[str, Any]:
        """Convert to dict for run_analysis(); use force or total_force; default athlete_id from user_id or 'unknown'."""
        d = self.model_dump(exclude={"user_id"}, exclude_none=True)
        if "athlete_id" not in d or d.get("athlete_id") is None:
            d["athlete_id"] = self.user_id or "unknown"
        if "total_force" in d and "force" not in d:
            d["force"] = d.pop("total_force")
        elif "force" not in d and "total_force" in d:
            d["force"] = d["total_force"]
        if "sample_count" not in d and "force" in d:
            d["sample_count"] = len(d["force"])
        return d


# ----- Jump test response -----


class JumpTestDetail(BaseModel):
    """Single jump test document (GET /jump-tests/{id})."""

    id: str
    user_id: Optional[str] = None
    athlete_id: str
    test_type: str
    result: Dict[str, Any] = Field(..., description="Full run_analysis output")
    created_at: datetime
    raw: Optional[Dict[str, Any]] = None


class JumpTestSummary(BaseModel):
    """Compact list item for GET /jump-tests (historical)."""

    id: str
    athlete_id: str
    test_type: str
    created_at: datetime
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Key metrics from result")


class JumpTestListResponse(BaseModel):
    items: List[JumpTestSummary]
    total: int
    limit: int
    offset: int
