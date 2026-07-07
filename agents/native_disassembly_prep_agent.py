from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass


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

    def prepare(self, file_path: str) -> NativePreparation:
        abs_target = os.path.abspath(file_path)
        return NativePreparation(
            file_path=file_path,
            abs_target=abs_target,
            file_hash=self._get_file_hash(file_path),
            instruction=f"/hyperagent-malware-analyze @{abs_target}",
        )
