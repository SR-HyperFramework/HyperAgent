import asyncio
import argparse
import yaml
from dotenv import load_dotenv

from core.die_handler import DIEHandler, AnalysisType
from agents.native_agent import NativeAgent
from agents.dotnet_agent import DotNetAgent
from agents.script_agent import ScriptAgent

# Load environment variables (API Key)
load_dotenv()

class HyperAgentOrchestrator:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = self._load_config(config_path)
        self.die_handler = DIEHandler(config_path)

    def _load_config(self, path: str):
        with open(path, "r") as f:
            return yaml.safe_load(f)

    async def analyze(self, file_path: str) -> dict:
        """Analyze a file and return a JSON-serializable result."""
        die_data, analysis_type = self.die_handler.identify(file_path)

        agent = None
        if analysis_type == AnalysisType.NATIVE:
            agent = NativeAgent(self.config_path)
        elif analysis_type == AnalysisType.DOTNET:
            agent = DotNetAgent()
        elif analysis_type == AnalysisType.PYTHON_SCRIPT:
            agent = ScriptAgent()
        else:  # UNKNOWN, treat as Script or fallback
            agent = ScriptAgent()

        analysis_data = await agent.analyze(file_path)
        return {
            "file_path": file_path,
            "detected_type": analysis_type.name,
            "die": die_data,
            "result": analysis_data,
        }

    async def run(self, file_path: str):
        print(f"[*] Starting analysis for: {file_path}")
        result = await self.analyze(file_path)
        print("[INFO] Phase 4: Exporting Results...")
        print(result)
            

def main():
    parser = argparse.ArgumentParser(description="HyperAgent MCP Orchestrator")
    parser.add_argument("file", help="Path to file to analyze")
    args = parser.parse_args()

    orchestrator = HyperAgentOrchestrator()
    asyncio.run(orchestrator.run(args.file))

if __name__ == "__main__":
    main()
