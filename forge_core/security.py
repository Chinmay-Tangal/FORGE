from typing import Dict, Any

class SecurityAnalyzer:
    """Evaluates the risk of an action and determines if confirmation is needed."""
    
    def __init__(self, policy: str = "auto"):
        self.policy = policy # auto, strict
        
    def assess_risk(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Returns risk level: low, medium, high."""
        if tool_name in ["read_file", "memory_search"]:
            return "low"
        if tool_name in ["write_file", "memory_insert", "memory_evict"]:
            return "medium"
        if tool_name == "shell":
            command = args.get("command", "").lower()
            if any(cmd in command for cmd in ["rm", "force", "sudo", "pip install"]):
                return "high"
            if any(cmd in command for cmd in ["ls", "cat", "echo", "pwd", "grep", "git status", "git diff"]):
                return "low"
            return "medium"
        return "medium"
        
    def requires_confirmation(self, tool_name: str, args: Dict[str, Any]) -> bool:
        risk = self.assess_risk(tool_name, args)
        if self.policy == "strict":
            return risk in ["medium", "high"]
        # auto policy
        return risk == "high"
