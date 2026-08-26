"""Safe, deterministic runbook discovery and matching."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.errors import CloudWardError
from app.runbooks.schema import RunbookDocument

logger = logging.getLogger(__name__)
MAX_RUNBOOK_BYTES = 256 * 1024
FORBIDDEN_KEYS = frozenset({"shell", "command", "commands", "exec", "script", "kubectl"})


class UniqueKeyLoader(yaml.SafeLoader):  # type: ignore[misc]
    pass


def _construct_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> Any:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key: {key!s}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def _reject_executable_content(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in FORBIDDEN_KEYS:
                raise CloudWardError(
                    "INVALID_RUNBOOK",
                    f"Executable field {path}.{key!s} is forbidden in declarative runbooks",
                    status_code=422,
                )
            _reject_executable_content(child, f"{path}.{key!s}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_executable_content(child, f"{path}[{index}]")


class RunbookLoader:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._runbooks: dict[tuple[str, int], RunbookDocument] = {}

    @property
    def runbooks(self) -> tuple[RunbookDocument, ...]:
        return tuple(
            sorted(self._runbooks.values(), key=lambda runbook: (runbook.id, runbook.version))
        )

    def load(self) -> tuple[RunbookDocument, ...]:
        if not self.path.exists() or not self.path.is_dir():
            raise CloudWardError(
                "RUNBOOK_PATH_UNAVAILABLE",
                f"Runbook directory does not exist: {self.path}",
                status_code=503,
            )
        loaded: dict[tuple[str, int], RunbookDocument] = {}
        for path in sorted((*self.path.glob("*.yaml"), *self.path.glob("*.yml"))):
            if path.stat().st_size > MAX_RUNBOOK_BYTES:
                raise CloudWardError("INVALID_RUNBOOK", f"Runbook too large: {path.name}")
            try:
                raw = yaml.load(
                    path.read_text(encoding="utf-8"),
                    Loader=UniqueKeyLoader,  # noqa: S506
                )
                if not isinstance(raw, dict):
                    raise ValueError("document root must be an object")
                _reject_executable_content(raw)
                document = RunbookDocument.model_validate(raw)
            except CloudWardError:
                raise
            except (OSError, ValueError, ValidationError, yaml.YAMLError) as exc:
                raise CloudWardError(
                    "INVALID_RUNBOOK", f"Invalid runbook {path.name}: {exc}", status_code=422
                ) from exc
            key = (document.id, document.version)
            if key in loaded:
                raise CloudWardError(
                    "DUPLICATE_RUNBOOK", f"Duplicate runbook {document.id} v{document.version}"
                )
            loaded[key] = document
        self._runbooks = loaded
        logger.info("runbooks_loaded", extra={"fields": {"count": len(loaded)}})
        return self.runbooks

    def match(
        self, *, incident_type: str, conditions: set[str], environment: str
    ) -> RunbookDocument:
        candidates = [
            runbook
            for runbook in self._runbooks.values()
            if runbook.match.incident_type == incident_type
            and set(runbook.match.conditions).issubset(conditions)
            and environment in {item.value for item in runbook.environments}
        ]
        if not candidates:
            raise CloudWardError(
                "RUNBOOK_NOT_FOUND",
                "No deterministic runbook matches the incident evidence",
                status_code=422,
            )
        candidates.sort(key=lambda runbook: (runbook.version, runbook.id), reverse=True)
        return candidates[0]
