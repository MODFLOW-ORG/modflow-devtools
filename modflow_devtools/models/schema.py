"""
Pydantic models for registry schema validation.
"""

from datetime import datetime
from os import PathLike
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field, field_validator, model_validator


class BootstrapSource(BaseModel):
    """A single source model repository in the bootstrap file."""

    repo: str = Field(..., description="Repository in format 'owner/name'")
    name: str | None = Field(
        None, description="Override name for model addressing (default: section name)"
    )
    refs: list[str] = Field(
        default_factory=list,
        description="Default refs to sync (branches, tags, or commit hashes)",
    )
    registry_path: str = Field(
        default=".registry",
        description="Path to registry directory in repository",
    )

    @field_validator("repo")
    @classmethod
    def validate_repo(cls, v: str) -> str:
        """Validate repo format is 'owner/name'."""
        if "/" not in v:
            raise ValueError(f"repo must be in format 'owner/name', got: {v}")
        parts = v.split("/")
        if len(parts) != 2:
            raise ValueError(f"repo must be in format 'owner/name', got: {v}")
        owner, name = parts
        if not owner or not name:
            raise ValueError(f"repo owner and name cannot be empty, got: {v}")
        return v


class Bootstrap(BaseModel):
    """Bootstrap metadata file structure."""

    sources: dict[str, BootstrapSource] = Field(
        ..., description="Map of source names to source metadata"
    )

    def get_source_name(self, key: str) -> str:
        """Get the name for a source (uses override if present, else key)."""
        source = self.sources[key]
        return source.name if source.name else key


class RegistryMetadata(BaseModel):
    """Metadata section of a registry file."""

    schema_version: str = Field(..., description="Registry schema version")
    generated_at: datetime = Field(
        ..., description="Timestamp when registry was generated"
    )
    devtools_version: str = Field(
        ..., description="Version of modflow-devtools used to generate"
    )

    class Config:
        # Allow datetime parsing from ISO format strings
        json_encoders: ClassVar = {datetime: lambda v: v.isoformat()}


class FileEntry(BaseModel):
    """A single file entry in the registry - supports both local and remote files."""

    url: str | None = Field(None, description="URL to fetch the file (for remote)")
    path: Path | None = Field(None, description="Local file path (original or cached)")
    hash: str | None = Field(None, description="SHA256 hash of the file")

    @model_validator(mode='after')
    def check_location(self):
        """Ensure at least one of url or path is provided."""
        if not self.url and not self.path:
            raise ValueError("FileEntry must have either url or path")
        return self


class Registry(BaseModel):
    """
    Base class for model registries.

    Defines the common structure for both local and remote registries.
    Can be instantiated directly for data-only registries (e.g., loaded from TOML).
    Subclasses (LocalRegistry, PoochRegistry) override copy_to() for active use.
    """

    meta: RegistryMetadata | None = Field(None, alias="_meta", description="Registry metadata (optional)")
    files: dict[str, FileEntry] = Field(
        default_factory=dict, description="Map of file names to file entries"
    )
    models: dict[str, list[str]] = Field(
        default_factory=dict, description="Map of model names to file lists"
    )
    examples: dict[str, list[str]] = Field(
        default_factory=dict, description="Map of example names to model lists"
    )

    model_config = {"arbitrary_types_allowed": True, "populate_by_name": True}

    def copy_to(
        self, workspace: str | PathLike, model_name: str, verbose: bool = False
    ) -> Path | None:
        """
        Copy a model's input files to the given workspace.

        Subclasses must override this method to provide actual implementation.

        Parameters
        ----------
        workspace : str | PathLike
            Destination workspace directory
        model_name : str
            Name of the model to copy
        verbose : bool
            Print progress messages

        Returns
        -------
        Path | None
            Path to the workspace, or None if model not found

        Raises
        ------
        NotImplementedError
            If called on base Registry class (must use subclass)
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement copy_to(). "
            "Use LocalRegistry or PoochRegistry instead."
        )

    def to_pooch_registry(self) -> dict[str, str | None]:
        """Convert to format expected by Pooch.registry (filename -> hash)."""
        return {name: entry.hash for name, entry in self.files.items()}

    def to_pooch_urls(self) -> dict[str, str]:
        """Convert to format expected by Pooch.urls (filename -> url)."""
        return {
            name: entry.url
            for name, entry in self.files.items()
            if entry.url is not None
        }
