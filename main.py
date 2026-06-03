import asyncio
import argparse
import os
import uuid
import yaml
from dotenv import load_dotenv

from core.die_handler import DIEHandler, AnalysisType
from core.pipeline_logger import PipelineLogger
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
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Missing config file: {path}. Run bootstrap.ps1 or copy config.yaml.template to config.yaml first."
            )
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    async def analyze(self, file_path: str, run_id: str | None = None) -> dict:
        """Analyze a file and return a JSON-serializable result."""
        run_id = run_id or uuid.uuid4().hex
        pipeline_logger = PipelineLogger(run_id)
        pipeline_logger.log("request", "started", "Analysis request accepted", file_path=file_path)

        try:
            pipeline_logger.log("identify", "started", "Detecting file type")
            die_data, analysis_type = self.die_handler.identify(file_path)
            pipeline_logger.log(
                "identify",
                "completed",
                "File type detected",
                detected_type=analysis_type.name,
            )

            if analysis_type == AnalysisType.NATIVE:
                agent = NativeAgent(self.config_path)
            elif analysis_type == AnalysisType.DOTNET:
                agent = DotNetAgent(self.config_path)
            elif analysis_type == AnalysisType.PYTHON_SCRIPT:
                agent = ScriptAgent(self.config_path)
            else:
                agent = ScriptAgent(self.config_path)

            pipeline_logger.log(
                "route",
                "completed",
                "Agent selected",
                agent=agent.__class__.__name__,
            )
            pipeline_logger.log("agent", "started", "Agent analysis started")
            analysis_data = await agent.analyze(file_path, pipeline_logger=pipeline_logger)
            pipeline_logger.log("agent", "completed", "Agent analysis completed")

            result = {
                "run_id": run_id,
                "file_path": file_path,
                "detected_type": analysis_type.name,
                "die": die_data,
                "result": analysis_data,
                "pipeline_log": pipeline_logger.snapshot(),
            }
            pipeline_logger.log("response", "completed", "Final response assembled")
            result["pipeline_log"] = pipeline_logger.snapshot()
            return result
        except Exception as e:
            pipeline_logger.log("request", "failed", "Analysis request failed", error=str(e))
            raise

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
