"""
forge_workspace/docker_workspace.py — Opt-in Docker sandbox workspace.

Implements the Workspace interface using a Docker container as the execution
environment. The container is created once per session and reused. All file
operations are done via `docker exec` and `docker cp`.

Usage (via config):
  workspace_type: docker
  docker_image: forge-sandbox:latest

The docker_sandbox Dockerfile is minimal: Ubuntu + git + python + common tools.
This is opt-in only — LocalWorkspace is the default because the model running
locally can't afford the double process tax of Docker + inference.

Ref: OpenHands "Sandboxing is opt-in" pattern (arXiv:2511.03690).
"""
import os
import uuid
import subprocess
import logging
import tempfile
from typing import Tuple, Optional

from forge_workspace.workspace import Workspace

logger = logging.getLogger(__name__)

SANDBOX_DOCKERFILE = """\
FROM ubuntu:22.04
RUN apt-get update && apt-get install -y \\
    git python3 python3-pip curl wget ripgrep fd-find bash \\
    && rm -rf /var/lib/apt/lists/*
RUN ln -s $(which python3) /usr/local/bin/python
WORKDIR /workspace
"""


class DockerWorkspace(Workspace):
    """
    Opt-in Docker sandbox. Mounts the host project directory read-write into
    the container so edits are visible on the host immediately.

    IMPORTANT: Switching from LocalWorkspace to DockerWorkspace requires only
    changing the config flag — the agent and tool layer never know the difference.
    """

    def __init__(
        self,
        base_dir: str,
        image: str = "forge-sandbox:latest",
        container_name: Optional[str] = None,
        auto_build: bool = True,
    ):
        self.base_dir = os.path.abspath(base_dir)
        self.image = image
        self.container_name = container_name or f"forge-sandbox-{uuid.uuid4().hex[:8]}"
        self._container_id: Optional[str] = None
        self.container_workdir = "/workspace"

        if auto_build:
            self._ensure_image()
        self._start_container()

    # ------------------------------------------------------------------ #
    # Internal container lifecycle                                          #
    # ------------------------------------------------------------------ #

    def _ensure_image(self):
        """Build the sandbox image if it doesn't exist locally."""
        result = subprocess.run(
            ["docker", "image", "inspect", self.image],
            capture_output=True,
        )
        if result.returncode == 0:
            logger.debug(f"Docker image {self.image} already exists.")
            return
        logger.info(f"Building sandbox image {self.image}...")
        with tempfile.TemporaryDirectory() as tmpdir:
            dockerfile_path = os.path.join(tmpdir, "Dockerfile")
            with open(dockerfile_path, "w") as f:
                f.write(SANDBOX_DOCKERFILE)
            subprocess.run(
                ["docker", "build", "-t", self.image, tmpdir],
                check=True,
            )

    def _start_container(self):
        """Start the sandbox container, mounting the project directory."""
        logger.info(f"Starting Docker sandbox: {self.container_name}")
        result = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                self.container_name,
                "-v",
                f"{self.base_dir}:{self.container_workdir}",
                "-w",
                self.container_workdir,
                "--rm",
                self.image,
                "sleep",
                "infinity",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to start Docker sandbox: {result.stderr}"
            )
        self._container_id = result.stdout.strip()
        logger.info(f"Sandbox started: {self._container_id[:12]}")

    def stop(self):
        """Stop and remove the container."""
        if self._container_id:
            subprocess.run(
                ["docker", "stop", self.container_name],
                capture_output=True,
            )
            self._container_id = None

    def __del__(self):
        try:
            self.stop()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Workspace interface                                                   #
    # ------------------------------------------------------------------ #

    def _container_path(self, path: str) -> str:
        """Resolve a relative path to an absolute container path."""
        if os.path.isabs(path):
            return path
        return os.path.join(self.container_workdir, path).replace("\\", "/")

    def read_file(self, path: str) -> str:
        container_path = self._container_path(path)
        result = subprocess.run(
            ["docker", "exec", self.container_name, "cat", container_path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise FileNotFoundError(
                f"Cannot read {container_path} in sandbox: {result.stderr}"
            )
        return result.stdout

    def write_file(self, path: str, content: str) -> None:
        container_path = self._container_path(path)
        # Write to a temp file on host, then docker cp into container
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".tmp", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            # Ensure parent dir exists in container
            parent = os.path.dirname(container_path)
            subprocess.run(
                ["docker", "exec", self.container_name, "mkdir", "-p", parent],
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["docker", "cp", tmp_path, f"{self.container_name}:{container_path}"],
                check=True,
                capture_output=True,
            )
        finally:
            os.unlink(tmp_path)

    def run_command(self, command: str, cwd: str = None) -> Tuple[int, str]:
        work_dir = self._container_path(cwd) if cwd else self.container_workdir
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-w",
                work_dir,
                self.container_name,
                "bash",
                "-c",
                command,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        return result.returncode, output
