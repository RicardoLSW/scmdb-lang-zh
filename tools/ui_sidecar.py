#!/usr/bin/env python3
"""Migrate reviewed SCMDB UI strings into a traceable language sidecar."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from uuid import uuid4

try:
    from tools import release
except ModuleNotFoundError:
    import release

build_migration = release.build_ui_migration
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    return parser


def _windows_path_key(path: Path) -> str:
    raw = str(path.absolute())
    parts = re.split(r"[\\/]", raw)
    normalized = []
    for part in parts:
        trimmed = part.rstrip(" .")
        stem = trimmed.split(".", 1)[0].upper()
        if stem in WINDOWS_RESERVED_NAMES:
            raise release.ReleaseError(f"reserved Windows path name: {part}")
        normalized.append(trimmed)
    return os.path.normcase("\\".join(normalized))


def _resolve_paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path]:
    raw_paths = (args.template, args.source, args.sidecar, args.coverage)
    for path in raw_paths:
        if path.name.endswith((" ", ".")):
            raise release.ReleaseError(f"path name cannot end with a space or dot: {path.name}")
    template = args.template.resolve()
    source = args.source.resolve()
    sidecar = args.sidecar.resolve()
    coverage = args.coverage.resolve()
    if _windows_path_key(sidecar) == _windows_path_key(coverage):
        raise release.ReleaseError("sidecar and coverage outputs must be different files")
    input_keys = {_windows_path_key(template), _windows_path_key(source)}
    for output in (sidecar, coverage):
        if _windows_path_key(output) in input_keys:
            raise release.ReleaseError("output paths must not overwrite template or source inputs")
    return template, source, sidecar, coverage


def _write_outputs(outputs: list[tuple[Path, dict]]) -> None:
    staged = []
    backups = []
    committed = []
    try:
        for target, data in outputs:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
            release.write_json(temporary, data)
            staged.append((temporary, target))
        for _temporary, target in staged:
            if target.exists():
                backup = target.with_name(f".{target.name}.{uuid4().hex}.bak")
                target.replace(backup)
                backups.append((backup, target))
        for temporary, target in staged:
            temporary.replace(target)
            committed.append(target)
        for backup, _target in backups:
            try:
                backup.unlink(missing_ok=True)
            except OSError:
                pass
    except OSError:
        for target in committed:
            target.unlink(missing_ok=True)
        restore_failed = False
        for backup, target in reversed(backups):
            if not backup.exists():
                continue
            try:
                backup.replace(target)
            except OSError:
                restore_failed = True
        if restore_failed:
            raise release.ReleaseError("failed to restore one or more UI output backups")
        raise
    finally:
        for temporary, _target in staged:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        template_path, source_path, sidecar_path, coverage_path = _resolve_paths(args)
        template = release.validate_template(template_path)
        source = release.load_json(source_path)
        sidecar, coverage = build_migration(template, source)
        _write_outputs([(sidecar_path, sidecar), (coverage_path, coverage)])
        print(json.dumps(coverage["summary"], ensure_ascii=False))
        return 0
    except (release.ReleaseError, OSError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
