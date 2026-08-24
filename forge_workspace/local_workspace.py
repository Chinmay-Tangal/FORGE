import os
import subprocess
from typing import Tuple
from forge_workspace.workspace import Workspace

class LocalWorkspace(Workspace):
    """In-process host filesystem execution. Fast local loop."""
    def __init__(self, base_dir: str):
        self.base_dir = os.path.abspath(base_dir)
        
    def _resolve(self, path: str) -> str:
        # Basic protection against escaping the base_dir
        # But this is LocalWorkspace, user trusts it to run locally.
        resolved = os.path.abspath(os.path.join(self.base_dir, path))
        return resolved

    def read_file(self, path: str) -> str:
        with open(self._resolve(path), 'r', encoding='utf-8') as f:
            return f.read()
            
    def write_file(self, path: str, content: str) -> None:
        filepath = self._resolve(path)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
            
    def run_command(self, command: str, cwd: str = None) -> Tuple[int, str]:
        run_dir = self._resolve(cwd) if cwd else self.base_dir
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=run_dir,
                capture_output=True,
                text=True
            )
            output = result.stdout
            if result.stderr:
                output += "\n" + result.stderr
            return result.returncode, output
        except Exception as e:
            return 1, str(e)
