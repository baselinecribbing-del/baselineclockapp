from dataclasses import dataclass
from typing import List


@dataclass
class WorkflowStep:
    id: str
    label: str
    required: bool = True
    read_only: bool = False


@dataclass
class WorkflowDefinition:
    name: str
    steps: List[WorkflowStep]