from __future__ import annotations

from dataclasses import dataclass, field

from core.result_models import ArtifactNode


@dataclass
class ArtifactRegistry:
    by_id: dict[str, ArtifactNode] = field(default_factory=dict)
    by_path: dict[str, str] = field(default_factory=dict)
    by_sha256: dict[str, list[str]] = field(default_factory=dict)
    children_by_parent: dict[str, list[str]] = field(default_factory=dict)

    def add(self, artifact: ArtifactNode) -> ArtifactNode:
        self.by_id[artifact.id] = artifact
        self.by_path[artifact.path] = artifact.id
        if artifact.sha256:
            sha_matches = self.by_sha256.setdefault(artifact.sha256, [])
            if artifact.id not in sha_matches:
                sha_matches.append(artifact.id)
        if artifact.parent_id:
            self._append_child(artifact.parent_id, artifact.id)
        return artifact

    def _append_child(self, parent_id: str, child_id: str) -> None:
        children = self.children_by_parent.setdefault(parent_id, [])
        if child_id not in children:
            children.append(child_id)

    def set_parent(self, artifact_id: str, parent_id: str) -> ArtifactNode | None:
        artifact = self.by_id.get(artifact_id)
        if artifact is None:
            return None
        if artifact.parent_id and artifact.parent_id != parent_id:
            old_children = self.children_by_parent.get(artifact.parent_id, [])
            self.children_by_parent[artifact.parent_id] = [child_id for child_id in old_children if child_id != artifact_id]
        artifact.parent_id = parent_id
        self._append_child(parent_id, artifact_id)
        return artifact

    def get_children(self, parent_id: str) -> list[ArtifactNode]:
        return [self.by_id[artifact_id] for artifact_id in self.children_by_parent.get(parent_id, []) if artifact_id in self.by_id]

    def get(self, artifact_id: str) -> ArtifactNode | None:
        return self.by_id.get(artifact_id)

    def get_by_path(self, path: str) -> ArtifactNode | None:
        artifact_id = self.by_path.get(path)
        if not artifact_id:
            return None
        return self.by_id.get(artifact_id)

    def get_by_sha256(self, sha256: str) -> list[ArtifactNode]:
        return [self.by_id[artifact_id] for artifact_id in self.by_sha256.get(sha256, []) if artifact_id in self.by_id]

    def all(self) -> list[ArtifactNode]:
        return list(self.by_id.values())
