from abc import ABC, abstractmethod
from typing import Tuple

class Workspace(ABC):
    """Abstract interface for a sandboxed or local filesystem workspace."""
    
    @abstractmethod
    def read_file(self, path: str) -> str:
        pass
        
    @abstractmethod
    def write_file(self, path: str, content: str) -> None:
        pass
        
    @abstractmethod
    def run_command(self, command: str, cwd: str = None) -> Tuple[int, str]:
        """Returns (exit_code, output)"""
        pass
