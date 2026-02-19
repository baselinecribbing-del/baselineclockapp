from sqlalchemy import Column, String, JSON
from sqlalchemy.ext.mutable import MutableList

from app.database import Base


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"

    execution_id = Column(String, primary_key=True, index=True)
    flow_name = Column(String, nullable=False)
    context = Column(JSON, nullable=False)

    status = Column(String, default="in_progress", nullable=False)
    current_step_id = Column(String, nullable=True)

    completed_steps = Column(MutableList.as_mutable(JSON), default=list, nullable=False)
