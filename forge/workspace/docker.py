"""
forge/workspace/docker.py — Opt-in Docker sandbox workspace.

Implements the Workspace interface using a long-running Docker container as the
execution environment. The container is created once per session and reused.
All file operations go through ``docker exec`` / ``docker cp``.

Usage (via config):

    workspace_type = "docker"
    docker_image   = "forge-sandbox:latest"

The sandbox image is minimal: Ubuntu + git + python + common CLI tools.
This is strictly opt-in — LocalWorkspace is the default because the local
model cannot afford the overhead of Docker on top of inference.

Reference: OpenHands "Sandboxing is opt-in" pattern (arXiv:2511.03690).
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import uuid
from typing import Optional, Tuple

from forge.workspace.base import Workspace

logger = logging.getLogger(__name__)

_SANDBOX_DOCKERFILE = """\
FROM ubuntu:22.04
RUN apt-get update && apt-get install -y \\
    git python3 python3-pip curl wget ripgrep fd-find bash \\
    patch \\
    && rm -rf /var/lib/apt/lists/*
RUN ln -s $(which python3) /usr/local/bin/python
WORKDIR /workspace
"""


class DockerWorkspace(Workspace):
    """
    Docker-sandboxed workspace. Mounts the host project directory read-write
    into the container so edits appear on the host immediately.

    Switching from LocalWorkspace requires only changing the config flag —
    the agent and tool layers are completely unaware of the difference.
    """

    def __init__(
        self,
        base_dir: str,
        image: str = "forge-sandbox:latest",
        container_name: Optional[str] = None,
        auto_build: bool = True,
    ) -> None:
        self.base_dir = os.path.abspath(base_dir)
        self.image = image
        self.container_name = container_name or f"forge-sandbox-{uuid.uuid4().hex[:8]}"
        self._container_id: Optional[str] = None
        self.container_workdir = "/workspace"

        if auto_build:
            self._ensure_image()
        self._start_container()

    # Container lifecycle
    def _ensure_image(self) -> None:
        """Build the sandbox image if it doesn't exist locally."""
        result = subprocess.run(
            ["docker", "image", "inspect", self.image],
            capture_output=True,
        )
        if result.returncode == 0:
            logger.debug("Docker image %s already exists.", self.image)
            return
        logger.info("Building sandbox image %s …", self.image)
        with tempfile.TemporaryDirectory() as tmpdir:
            dockerfile_path = os.path.join(tmpdir, "Dockerfile")
            with open(dockerfile_path, "w") as fh:
                fh.write(_SANDBOX_DOCKERFILE)
            subprocess.run(["docker", "build", "-t", self.image, tmpdir], check=True)

    def _start_container(self) -> None:
        """Start the sandbox container, mounting the project directory."""
        logger.info("Starting Docker sandbox: %s", self.container_name)
        result = subprocess.run(
            [
                "docker", "run", "-d",
                "--name", self.container_name,
                "-v", f"{self.base_dir}:{self.container_workdir}",
                "-w", self.container_workdir,
                "--rm", self.image,
                "sleep", "infinity",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to start Docker sandbox: {result.stderr}")
        self._container_id = result.stdout.strip()
        logger.info("Sandbox running: %s", self._container_id[:12])

    def stop(self) -> None:
        """Stop and remove the container."""
        if self._container_id:
            subprocess.run(
                ["docker", "stop", self.container_name],
                capture_output=True,
            )
            self._container_id = None

    def __del__(self) -> None:
        try:
            self.stop()
        except Exception:
            pass

    # Workspace interface
    def _container_path(self, path: str) -> str:
        if os.path.isabs(path):
            return path
        return os.path.join(self.container_workdir, path).replace("\\", "/")

    def read_file(self, path: str) -> str:
        result = subprocess.run(
            ["docker", "exec", self.container_name, "cat", self._container_path(path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise FileNotFoundError(
                f"Cannot read {path} in sandbox: {result.stderr}"
            )
        return result.stdout

    def write_file(self, path: str, content: str) -> None:
        container_path = self._container_path(path)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".tmp", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            parent = os.path.dirname(container_path)
            subprocess.run(
                ["docker", "exec", self.container_name, "mkdir", "-p", parent],
                capture_output=True, check=True,
            )
            subprocess.run(
                ["docker", "cp", tmp_path, f"{self.container_name}:{container_path}"],
                check=True, capture_output=True,
            )
        finally:
            os.unlink(tmp_path)

    def run_command(self, command: str, cwd: str | None = None) -> Tuple[int, str]:
        work_dir = self._container_path(cwd) if cwd else self.container_workdir
        result = subprocess.run(
            ["docker", "exec", "-w", work_dir, self.container_name, "bash", "-c", command],
            capture_output=True, text=True, timeout=60,
        )
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        return result.returncode, output
