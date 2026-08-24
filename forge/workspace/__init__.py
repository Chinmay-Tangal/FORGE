"""forge.workspace — Workspace backends (local filesystem and Docker sandbox)."""
from forge.workspace.base import Workspace
from forge.workspace.local import LocalWorkspace
from forge.workspace.docker import DockerWorkspace

__all__ = ["Workspace", "LocalWorkspace", "DockerWorkspace"]
