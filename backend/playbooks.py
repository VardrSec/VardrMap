"""Original, versioned guidance shared by the UI and Runner MCP over HTTP."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ApiPlaybook(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^API-[0-9]{2}$")
    title: str
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+$")
    use_when: str
    expected_artifacts: str
    prerequisites: list[str] = Field(min_length=1)
    steps: list[str] = Field(min_length=1)
    common_traps: str
    manual_remainder: str


def load_playbooks() -> dict[str, ApiPlaybook]:
    items = [
        ApiPlaybook.model_validate(item)
        for item in json.loads(
            Path(__file__).with_name("api_playbooks.json").read_text(encoding="utf-8")
        )
    ]
    if len({item.id for item in items}) != len(items):
        raise ValueError("Duplicate playbook identifier")
    return {item.id: item for item in items}


CATALOG = load_playbooks()
