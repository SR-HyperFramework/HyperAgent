from typing import Dict, Any

class UnsortAgent:
    async def analyze(self, file_path: str) -> Dict[str, Any]:
        return {
            "type": "UNSORT",
            "info": "Unsorted analysis not implemented yet."
        }
