from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict


class ApplyConfigReq(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    config: dict
    scope: str = "global"
    reset: Literal["none", "hard"] = "none"


class SaveConfigReq(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    config_name: str
    description: Optional[str] = None
    config: dict
    created_by: Optional[str] = None
    source: str = "ui"


class ApplySavedConfigReq(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    config_id: int
    reset: Literal["none", "hard"] = "none"
    scope: str = "global"
    activated_by: Optional[str] = None
    source: str = "ui"


class AssignModelReq(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    assigned_model: str
    model_settings_json: dict = Field(default_factory=dict)
    actor: str = "ui"
    source: str = "ui"


class SetScoringReq(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    enabled: bool
    actor: str = "ui"
    source: str = "ui"
    reset_runtime_state: bool = True