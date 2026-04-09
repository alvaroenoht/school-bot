from abc import ABC, abstractmethod
from typing import List, Dict, Any

class SchoolModuleBase(ABC):
    """Base interface for school portal integrations (e.g. Seduca, PowerSchool, etc.)"""
    
    @abstractmethod
    async def sync_classroom(self, classroom_id: int, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """Sync subjects, assignments, and students from the portal."""
        pass

    @abstractmethod
    async def get_summary(self, student_id: int) -> str:
        """Generate a weekly/daily summary for a specific student."""
        pass
