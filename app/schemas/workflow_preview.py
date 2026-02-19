from typing import Optional, Union

from pydantic import BaseModel


class StartExecutionRequest(BaseModel):
    flow_name: str
    company_id: int
    employee_id: int
    job_id: int
    scope_id: int


class SubmitStepRequest(BaseModel):
    value: Optional[Union[str, int, bool, float]] = None
    notes: Optional[str] = None