from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from core.task_runtime import create_child_task_scope


@dataclass
class NativePreparation:
    file_path: str
    abs_target: str
    file_hash: str
    instruction: str


class NativeDisassemblyPrepAgent:
    @staticmethod
    def _get_file_hash(file_path: str) -> str:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def prepare(self, file_path: str, pipeline_logger=None) -> NativePreparation:
        logger = pipeline_logger
        if pipeline_logger:
            _, logger = create_child_task_scope(
                pipeline_logger,
                stage_key="native_agent.prepare",
                title="Prepare native target",
            )
            logger.log(
                "native_agent.prepare",
                "started",
                "Preparing native target for Claude analysis",
                file_path=os.path.abspath(file_path),
            )

        abs_target = os.path.abspath(file_path)
        preparation = NativePreparation(
            file_path=file_path,
            abs_target=abs_target,
            file_hash=self._get_file_hash(file_path),
            instruction=f"/hyperagent-malware-analyze @{abs_target}",
        )

        if logger:
            logger.log(
                "native_agent.prepare",
                "completed",
                "Prepared native target for Claude analysis",
                file_path=abs_target,
                file_hash=preparation.file_hash,
            )
        return preparation
