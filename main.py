import asyncio
import argparse
import yaml
from dotenv import load_dotenv
import os

from core.die_handler import DIEHandler, AnalysisType
from core.yara_handler import YaraHandler
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
        
        # Initialize YaraHandler
        yara_rules_path = self.config.get("tools", {}).get("yara_rules", "../HyperScope/yara/rules")
        if not os.path.isabs(yara_rules_path):
             # Resolve relative to config location or project root
             base_dir = os.path.dirname(os.path.abspath(config_path))
             yara_rules_path = os.path.normpath(os.path.join(base_dir, yara_rules_path))
             
        self.yara_handler = YaraHandler(yara_rules_path)

    def _load_config(self, path: str):
        with open(path, "r") as f:
            return yaml.safe_load(f)

    async def analyze(self, file_path: str) -> dict:
        """Analyze a file and return a JSON-serializable result."""
        # 1. Static Analysis (DIE & YARA)
        die_data, analysis_type = self.die_handler.identify(file_path)
        yara_matches = self.yara_handler.match(file_path)

        # 2. Select Agent
        agent = None
        if analysis_type == AnalysisType.NATIVE:
            agent = NativeAgent(self.config_path)
        elif analysis_type == AnalysisType.DOTNET:
            agent = DotNetAgent()
        elif analysis_type == AnalysisType.PYTHON_SCRIPT:
            agent = ScriptAgent()
        else:  # UNKNOWN, treat as Script or fallback
            agent = ScriptAgent()

        # 3. AI Analysis
        analysis_data = await agent.analyze(file_path)
        
        return {
            "file_path": file_path,
            "detected_type": analysis_type.name,
            "die": die_data,
            "yara": [m["rule"] for m in yara_matches], # Simplify for summary
            "yara_details": yara_matches,
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
