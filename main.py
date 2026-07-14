import asyncio
import argparse
import os
import uuid
import yaml
from dotenv import load_dotenv

from core.artifact_registry import ArtifactRegistry
from core.die_handler import DIEHandler, AnalysisType
from core.finding_store import FindingStore
from core.orchestration import ArtifactGraphOrchestrator
from core.pipeline_logger import PipelineLogger
from core.task_runtime import bind_process_scope
from agents.dotnet_agent import DotNetAgent
from agents.file_classifier_agent import FileClassifierAgent
from agents.native_agent import NativeAgent
from agents.script_agent import ScriptAgent
from agents.unsort_agent import UnsortAgent

# Load environment variables (API Key)
load_dotenv()

class HyperAgentOrchestrator:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = self._load_config(config_path)
        self.die_handler = DIEHandler(config_path)
        self.file_classifier = FileClassifierAgent(config_path, die_handler=self.die_handler)

    def _load_config(self, path: str):
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Missing config file: {path}. Run bootstrap.ps1 or copy config.yaml.template to config.yaml first."
            )
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _select_agent(self, analysis_type: AnalysisType):
        if analysis_type == AnalysisType.NATIVE:
            return NativeAgent(self.config_path)
        if analysis_type == AnalysisType.DOTNET:
            return DotNetAgent(self.config_path)
        if analysis_type == AnalysisType.PYTHON_SCRIPT:
            return ScriptAgent(self.config_path)
        return ScriptAgent(self.config_path)

    async def analyze(
        self,
        file_path: str,
        run_id: str | None = None,
        _depth: int = 0,
        _seen: set[str] | None = None,
        pipeline_logger: PipelineLogger | None = None,
    ) -> dict:
        """Analyze a file and return a JSON-serializable result."""
        run_id = run_id or uuid.uuid4().hex
        pipeline_logger = pipeline_logger or PipelineLogger(run_id)
        artifact_registry = ArtifactRegistry()
        finding_store = FindingStore()
        engine = ArtifactGraphOrchestrator(
            config_path=self.config_path,
            die_handler=self.die_handler,
            pipeline_logger=pipeline_logger,
            artifact_registry=artifact_registry,
            finding_store=finding_store,
            agent_factory=self._select_agent,
        )

        try:
            with bind_process_scope(pipeline_logger=pipeline_logger):
                return await engine.analyze(
                    file_path,
                    run_id=run_id,
                    initial_depth=_depth,
                    seen=_seen,
                )
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
