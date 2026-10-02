"""Per-run filesystem scope enforcement for HyperAgent tools."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class PathScopeError(ValueError):
    """Raised when a tool path falls outside the allowed analysis scope."""


@dataclass(frozen=True)
class PathScope:
    """Allowed read/write roots for one pipeline run."""

    read_roots: tuple[Path, ...]
    write_roots: tuple[Path, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "read_roots", tuple(_normalize_root(p) for p in self.read_roots))
        object.__setattr__(self, "write_roots", tuple(_normalize_root(p) for p in self.write_roots))
        if not self.read_roots:
            raise ValueError("PathScope requires at least one read root")
        if not self.write_roots:
            raise ValueError("PathScope requires at least one write root")

    def check_read(self, raw_path: str, base_dir: str | Path | None = None) -> Path:
        """Resolve *raw_path* and ensure it stays within the read roots."""
        return self._check(raw_path, self.read_roots, base_dir=base_dir)

    def check_write(self, raw_path: str, base_dir: str | Path | None = None) -> Path:
        """Resolve *raw_path* and ensure it stays within the write roots."""
        return self._check(raw_path, self.write_roots, base_dir=base_dir)

    def _check(
        self,
        raw_path: str,
        roots: tuple[Path, ...],
        *,
        base_dir: str | Path | None = None,
    ) -> Path:
        if not raw_path:
            raise PathScopeError("path is required")

        candidate = Path(raw_path).expanduser()
        if candidate.is_absolute():
            resolved = candidate.resolve(strict=False)
        else:
            base = Path(base_dir) if base_dir is not None else self.write_roots[0]
            resolved = (base.expanduser().resolve(strict=False) / candidate).resolve(strict=False)

        for root in roots:
            if resolved == root or resolved.is_relative_to(root):
                return resolved
        raise PathScopeError("path is outside the allowed analysis scope")



def compute_run_scope(sample_path: Path, report_dir: Path, skills_root: Path) -> PathScope:
    """Return the allowed host-side read/write roots for one sample run."""
    sample_path = sample_path.expanduser().resolve()
    report_dir = report_dir.expanduser().resolve()
    skills_root = skills_root.expanduser().resolve()
    return PathScope(
        read_roots=(sample_path.parent, report_dir, skills_root),
        write_roots=(report_dir,),
    )



def _normalize_root(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)
