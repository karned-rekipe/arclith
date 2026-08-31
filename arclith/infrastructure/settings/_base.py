from pydantic import BaseModel, ConfigDict


class SettingsModel(BaseModel):
    """Base model for configuration sections loaded from YAML."""

    model_config = ConfigDict(extra="forbid")
