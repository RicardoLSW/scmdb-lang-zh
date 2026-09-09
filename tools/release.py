#!/usr/bin/env python3
"""Repeatable SCMDB upstream sync, template diff, build, and release checks."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_REPOSITORY = "https://github.com/KrovaxCode/SCMDB_LANG"
TEMPLATE_RE = re.compile(r"^lang-template-(.+)\.json$")
PINNED_FILES = {"UPSTREAM_README.md", "build_lang_template.py"}


class ReleaseError(RuntimeError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            data = json.load(handle, object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ReleaseError(f"JSON root must be an object: {path}")
    return data


def json_bytes(data: Any) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(data))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_info(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {"byteLength": len(data), "sha256": sha256_bytes(data)}


def validate_template(path: Path) -> dict[str, Any]:
    match = TEMPLATE_RE.fullmatch(path.name)
    if not match:
        raise ReleaseError(f"invalid template filename: {path.name}")
    template = load_json(path)
    version = template.get("version")
    keys = template.get("keys")
    if version != match.group(1):
        raise ReleaseError(f"template filename/version mismatch: {path.name} != {version!r}")
    if not isinstance(keys, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in keys.items()
    ):
        raise ReleaseError(f"template keys must be string-to-string: {path}")
    if template.get("keyCount") != len(keys):
        raise ReleaseError(
            f"template keyCount mismatch: {path.name} declares "
            f"{template.get('keyCount')}, contains {len(keys)}"
        )
    return template


def validate_upstream(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    manifest_path = repo_root / "upstream" / "manifest.json"
    upstream_dir = repo_root / "upstream" / "SCMDB_LANG"
    manifest = load_json(manifest_path)
    if manifest.get("repository") != UPSTREAM_REPOSITORY:
        raise ReleaseError("upstream repository is not the approved SCMDB_LANG source")
    commit = manifest.get("upstreamCommit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ReleaseError("upstreamCommit must be a full lowercase Git SHA")
    if manifest.get("redistributionPermissionConfirmed") is not True:
        raise ReleaseError("upstream redistribution permission is not confirmed")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ReleaseError("upstream manifest files must be an array of objects")
    expected_names = {entry.get("path") for entry in entries}
    actual_names = {path.name for path in upstream_dir.iterdir() if path.is_file()}
    if expected_names != actual_names:
        raise ReleaseError(
            f"upstream file set mismatch: manifest={sorted(expected_names)}, "
            f"directory={sorted(actual_names)}"
        )
    if not PINNED_FILES.issubset(actual_names):
        raise ReleaseError("upstream snapshot must include README and builder")
    template_names = sorted(name for name in actual_names if TEMPLATE_RE.fullmatch(name))
    unexpected = actual_names - PINNED_FILES - set(template_names)
    if unexpected:
        raise ReleaseError(f"unapproved upstream files: {sorted(unexpected)}")
    if not template_names:
        raise ReleaseError("upstream snapshot has no language templates")
    checked_files = []
    entries_by_name = {entry["path"]: entry for entry in entries}
    for name in sorted(actual_names):
        path = upstream_dir / name
        info = file_info(path)
        declared = entries_by_name[name]
        if declared.get("byteLength") != info["byteLength"]:
            raise ReleaseError(f"byteLength mismatch for upstream file {name}")
        if declared.get("sha256") != info["sha256"]:
            raise ReleaseError(f"SHA-256 mismatch for upstream file {name}")
        checked = {"path": name, **info}
        if name in template_names:
            template = validate_template(path)
            checked.update(version=template["version"], keyCount=template["keyCount"])
        checked_files.append(checked)
    return {
        "repository": manifest["repository"],
        "upstreamCommit": commit,
        "syncedAt": manifest.get("syncedAt"),
        "files": checked_files,
    }


def _git_output(source_dir: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(source_dir), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseError(f"cannot verify upstream Git checkout: {' '.join(args)}") from exc
    return completed.stdout.strip()


def _normalize_repository_url(url: str) -> str:
    return url.removesuffix(".git").rstrip("/")


def sync_upstream(source_dir: Path, commit: str, synced_at: str, repo_root: Path) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ReleaseError("--commit must be a full lowercase Git SHA")
    _parse_datetime(synced_at)
    if not source_dir.is_dir():
        raise ReleaseError(f"source directory not found: {source_dir}")
    actual_commit = _git_output(source_dir, "rev-parse", "HEAD").lower()
    if actual_commit != commit:
        raise ReleaseError(f"source checkout is {actual_commit}, expected pinned commit {commit}")
    repository = _normalize_repository_url(_git_output(source_dir, "remote", "get-url", "origin"))
    if repository != UPSTREAM_REPOSITORY:
        raise ReleaseError(f"source remote is not the approved repository: {repository}")
    _git_output(source_dir, "fetch", "--no-tags", "origin", commit)
    fetched_commit = _git_output(source_dir, "rev-parse", "FETCH_HEAD").lower()
    if fetched_commit != commit:
        raise ReleaseError(f"approved remote returned {fetched_commit}, expected {commit}")
    if _git_output(source_dir, "status", "--porcelain", "--untracked-files=all"):
        raise ReleaseError("source checkout must be clean before syncing")

    selected: list[tuple[str, Path]] = []
    readme = source_dir / "README.md"
    builder = source_dir / "build_lang_template.py"
    if not readme.is_file() or not builder.is_file():
        raise ReleaseError("source must contain README.md and build_lang_template.py")
    selected.extend((("UPSTREAM_README.md", readme), ("build_lang_template.py", builder)))
    for path in sorted(source_dir.glob("lang-template-*.json")):
        validate_template(path)
        selected.append((path.name, path))
    if len(selected) == 2:
        raise ReleaseError("source contains no valid lang-template-*.json")

    upstream_parent = repo_root / "upstream"
    repo_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=repo_root) as temp_name:
        staged_root = Path(temp_name) / "snapshot"
        staged_upstream = staged_root / "upstream"
        staged_dir = staged_upstream / "SCMDB_LANG"
        staged_manifest = staged_upstream / "manifest.json"
        staged_dir.mkdir(parents=True)
        entries = []
        for target_name, source_path in selected:
            target = staged_dir / target_name
            shutil.copyfile(source_path, target)
            entries.append({"path": target_name, **file_info(target)})
        manifest = {
            "repository": UPSTREAM_REPOSITORY,
            "upstreamCommit": commit,
            "syncedAt": synced_at,
            "redistributionPermissionConfirmed": True,
            "files": entries,
        }
        write_json(staged_manifest, manifest)
        validate_upstream(staged_root)
        _replace_output_directory(staged_upstream, upstream_parent)
    validate_upstream(repo_root)
    return manifest


def diff_templates(
    old_path: Path,
    new_path: Path,
    previous_translation_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    old = validate_template(old_path)
    new = validate_template(new_path)
    old_keys = old["keys"]
    new_keys = new["keys"]
    old_set = set(old_keys)
    new_set = set(new_keys)
    added = sorted(new_set - old_set)
    removed = sorted(old_set - new_set)
    common = old_set & new_set
    source_changed = sorted(key for key in common if old_keys[key] != new_keys[key])
    unchanged = sorted(key for key in common if old_keys[key] == new_keys[key])
    report = {
        "schemaVersion": 1,
        "oldVersion": old["version"],
        "newVersion": new["version"],
        "counts": {
            "added": len(added),
            "removed": len(removed),
            "sourceChanged": len(source_changed),
            "unchanged": len(unchanged),
        },
        "addedKeys": added,
        "removedKeys": removed,
        "sourceChangedKeys": source_changed,
        "unchangedKeys": unchanged,
    }
    carryover = None
    if previous_translation_path:
        previous = load_json(previous_translation_path)
        previous_keys = previous.get("keys")
        if previous.get("version") != old["version"]:
            raise ReleaseError("previous translation version does not match the old template")
        if not isinstance(previous_keys, dict):
            raise ReleaseError("previous translation has no keys object")
        inherited = {}
        unsafe = []
        for key in unchanged:
            value = previous_keys.get(key)
            if (
                isinstance(value, dict)
                and value.get("en") == old_keys[key]
                and isinstance(value.get("tr"), str)
            ):
                inherited[key] = {"en": new_keys[key], "tr": value["tr"]}
            elif value is not None:
                unsafe.append(key)
        carryover = {
            "schemaVersion": 1,
            "oldVersion": old["version"],
            "newVersion": new["version"],
            "targetLanguage": previous.get("targetLanguage", "unknown"),
            "keyCount": len(inherited),
            "keys": inherited,
        }
        report["inheritedCount"] = len(inherited)
        report["unsafeCarryoverCount"] = len(unsafe)
        report["unsafeCarryoverKeys"] = sorted(unsafe)
    return report, carryover


def _parse_datetime(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ReleaseError("date metadata is required")
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ReleaseError(f"invalid date metadata: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_builder(path: Path):
    spec = importlib.util.spec_from_file_location("scmdb_pinned_builder", path)
    if spec is None or spec.loader is None:
        raise ReleaseError(f"cannot load pinned builder: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_translation_artifact(artifact: dict[str, Any], build: str) -> None:
    if artifact.get("version") != build:
        raise ReleaseError("artifact version does not match requested build")
    keys = artifact.get("keys")
    if not isinstance(keys, dict) or artifact.get("keyCount") != len(keys):
        raise ReleaseError("artifact keyCount does not match keys")
    for key, value in keys.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise ReleaseError("artifact keys must map to objects")
        if not isinstance(value.get("en"), str) or not isinstance(value.get("tr"), str):
            raise ReleaseError(f"artifact entry is invalid: {key}")


def _source_age_days(last_modified: str, synced_at: str) -> float:
    return (_parse_datetime(synced_at) - _parse_datetime(last_modified)).total_seconds() / 86400


def evaluate_gates(
    stats: dict[str, Any], source: dict[str, Any], build: str, synced_at: str, policy: dict[str, Any]
) -> list[dict[str, str]]:
    failures = []
    if source.get("version") != build:
        failures.append({
            "code": "untrusted_source_version",
            "message": "source version is missing or does not match the template build",
        })
    try:
        age_days = _source_age_days(source.get("lastModified"), synced_at)
        if age_days > float(policy.get("maxSourceAgeDays", 120)):
            failures.append({
                "code": "source_too_old",
                "message": f"source is {age_days:.1f} days older than the pinned template sync",
            })
    except ReleaseError:
        failures.append({
            "code": "untrusted_source_date",
            "message": "source lastModified metadata is missing or invalid",
        })
    keyed = max(1, int(stats.get("total", 0)) - int(stats.get("noLocKey", 0)))
    missing = int(stats.get("missing", 0))
    ratio = missing / keyed
    if missing > int(policy.get("maxMissingCount", 100)) or ratio > float(policy.get("maxMissingRatio", 0.05)):
        failures.append({
            "code": "abnormal_missing_rate",
            "message": f"missing {missing} of {keyed} keyed entries ({ratio:.2%})",
        })
    return failures


def generate_variant(
    template: dict[str, Any], builder: Any, ini_path: Path, ui_sidecar: dict[str, str], target_language: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    artifact, raw_stats = builder.build_translation(
        template, str(ini_path), template["version"], {}, ui_sidecar
    )
    artifact["targetLanguage"] = target_language
    builder_stats = copy.deepcopy(raw_stats)
    risk_keys = sorted(set(raw_stats.get("mismatchKeys", [])))
    for key in risk_keys:
        artifact["keys"][key]["tr"] = artifact["keys"][key]["en"]
    published_stats = copy.deepcopy(raw_stats)
    published_stats["translated"] = max(0, published_stats["translated"] - len(risk_keys))
    published_stats["mismatch"] = 0
    published_stats["mismatchKeys"] = []
    published_stats["safetyFallback"] = len(risk_keys)
    published_stats["safetyFallbackKeys"] = risk_keys
    artifact["stats"] = published_stats
    validate_translation_artifact(artifact, template["version"])
    return artifact, builder_stats, published_stats


def _resolve_config_path(config: dict[str, Any], name: str, repo_root: Path) -> Path:
    value = config.get(name)
    if not isinstance(value, str) or not value:
        raise ReleaseError(f"config field {name} is required")
    return (repo_root / value).resolve()


def _parse_sources(values: list[str]) -> dict[str, Path]:
    parsed = {}
    for value in values:
        if "=" not in value:
            raise ReleaseError("--source must use VARIANT=PATH")
        variant, raw_path = value.split("=", 1)
        if variant in parsed:
            raise ReleaseError(f"duplicate --source variant: {variant}")
        parsed[variant] = Path(raw_path).expanduser().resolve()
    return parsed


def _check_raw_url(url: str, expected_sha256: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Origin": "https://scmdb.net"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            allow_origin = response.headers.get("Access-Control-Allow-Origin")
            actual_hash = sha256_bytes(body)
            ok = allow_origin in ("*", "https://scmdb.net") and actual_hash == expected_sha256
            return {
                "url": url,
                "status": "passed" if ok else "failed",
                "accessControlAllowOrigin": allow_origin,
                "sha256": actual_hash,
                "expectedSha256": expected_sha256,
            }
    except Exception as exc:
        return {"url": url, "status": "failed", "error": str(exc)}


def _safe_output_name(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in (".", "..")
        or Path(value).name != value
        or "/" in value
        or "\\" in value
    ):
        raise ReleaseError(f"{field} must be a plain relative filename")
    return value


def _replace_output_directory(staged: Path, target: Path) -> None:
    backup = target.with_name(f"{target.name}.previous")
    if backup.exists():
        shutil.rmtree(backup)
    try:
        if target.exists():
            target.replace(backup)
        staged.replace(target)
    except OSError:
        if target.exists():
            shutil.rmtree(target)
        if backup.exists():
            backup.replace(target)
        raise
    finally:
        if backup.exists():
            shutil.rmtree(backup)


def _build_release_into(
    config_path: Path,
    source_paths: dict[str, Path],
    output_root: Path,
    repo_root: Path = REPO_ROOT,
    check_cors: bool = False,
) -> tuple[dict[str, Any], bool]:
    upstream = validate_upstream(repo_root)
    config = load_json(config_path)
    build = config.get("build")
    channel = config.get("channel")
    target_language = config.get("targetLanguage", "zh-CN")
    variants = config.get("variants")
    source_metadata = config.get("sources")
    policy = config.get("policy", {})
    if not isinstance(build, str) or not isinstance(channel, str):
        raise ReleaseError("config build and channel are required")
    if not isinstance(variants, dict) or not isinstance(source_metadata, dict):
        raise ReleaseError("config variants and sources must be objects")
    expected_variants = set(variants)
    for variant, variant_config in variants.items():
        if not isinstance(variant_config, dict):
            raise ReleaseError(f"variant config must be an object: {variant}")
        _safe_output_name(variant_config.get("artifact"), f"artifact for {variant}")
        aliases = variant_config.get("aliases", [])
        if not isinstance(aliases, list):
            raise ReleaseError(f"aliases must be an array: {variant}")
        for alias in aliases:
            _safe_output_name(alias, f"alias for {variant}")
    if set(source_paths) != expected_variants:
        raise ReleaseError(
            f"source variants must be exactly {sorted(expected_variants)}; got {sorted(source_paths)}"
        )
    template_path = _resolve_config_path(config, "template", repo_root)
    template = validate_template(template_path)
    if template["version"] != build:
        raise ReleaseError("config build does not match template version")
    builder = _load_builder(repo_root / "upstream" / "SCMDB_LANG" / "build_lang_template.py")
    sidecar_path = _resolve_config_path(config, "uiSidecar", repo_root)
    ui_sidecar = builder.load_ui_sidecar(str(sidecar_path))
    generated_artifacts = []
    validation_sources = []
    all_publishable = True
    alias_specs: list[tuple[str, bytes, str]] = []
    dist_root = output_root / "dist"
    reports_root = output_root / "reports" / build
    for variant in variants:
        metadata = source_metadata.get(variant)
        if not isinstance(metadata, dict):
            raise ReleaseError(f"source metadata missing for {variant}")
        ini_path = source_paths[variant]
        if not ini_path.is_file():
            raise ReleaseError(f"source INI not found for {variant}: {ini_path}")
        info = file_info(ini_path)
        if metadata.get("sha256") != info["sha256"]:
            raise ReleaseError(f"source SHA-256 mismatch for {variant}")
        artifact, builder_stats, published_stats = generate_variant(
            template, builder, ini_path, ui_sidecar, target_language
        )
        failures = evaluate_gates(builder_stats, metadata, build, upstream["syncedAt"], policy)
        publishable = not failures
        all_publishable = all_publishable and publishable
        artifact_name = variants[variant].get("artifact")
        if not isinstance(artifact_name, str):
            raise ReleaseError(f"artifact name missing for variant {variant}")
        artifact_bytes = json_bytes(artifact)
        artifact_path = dist_root / build / artifact_name
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_bytes(artifact_bytes)
        artifact_info = {
            "variant": variant,
            "path": f"dist/{build}/{artifact_name}",
            "sha256": sha256_bytes(artifact_bytes),
            "byteLength": len(artifact_bytes),
        }
        generated_artifacts.append(artifact_info)
        report = {
            "schemaVersion": 2,
            "status": "publishable_with_english_fallbacks" if publishable else "blocked",
            "variant": variant,
            "build": build,
            "source": {
                "url": metadata.get("url"),
                "sha256": info["sha256"],
                "lastModified": metadata.get("lastModified"),
                "version": metadata.get("version"),
            },
            "upstreamCommit": upstream["upstreamCommit"],
            "builderStats": builder_stats,
            "publishedStats": published_stats,
            "gates": {"status": "passed" if publishable else "failed", "failures": failures},
            "artifact": artifact_info,
        }
        write_json(reports_root / f"{variant}.json", report)
        validation_sources.append(
            {"variant": variant, "sha256": info["sha256"], "gates": report["gates"]}
        )
        for alias in variants[variant].get("aliases", []):
            if not isinstance(alias, str):
                raise ReleaseError(f"invalid alias for variant {variant}")
            alias_specs.append((alias, artifact_bytes, variant))
    aliases = []
    for alias, content, variant in alias_specs:
        alias_path = dist_root / alias
        alias_path.parent.mkdir(parents=True, exist_ok=True)
        alias_path.write_bytes(content)
        aliases.append({
            "path": f"dist/{alias}",
            "variant": variant,
            "sha256": sha256_bytes(content),
            "byteLength": len(content),
        })
    raw_checks = []
    raw_urls = config.get("rawUrls", {})
    artifact_hash_by_variant = {item["variant"]: item["sha256"] for item in generated_artifacts}
    for alias in aliases:
        url = raw_urls.get(alias["path"])
        if check_cors and isinstance(url, str):
            raw_checks.append(_check_raw_url(url, artifact_hash_by_variant[alias["variant"]]))
        else:
            raw_checks.append({"url": url, "path": alias["path"], "status": "not_checked"})
    if check_cors and any(check.get("status") != "passed" for check in raw_checks):
        all_publishable = False
    manifest = {
        "schemaVersion": 2,
        "upstreamCommit": upstream["upstreamCommit"],
        "build": build,
        "channel": channel,
        "defaultVariant": config.get("defaultVariant", "full"),
        "status": "candidate" if all_publishable else "blocked",
        "artifacts": generated_artifacts,
        "aliases": aliases,
    }
    write_json(dist_root / "manifest.json", manifest)
    validation = {
        "schemaVersion": 1,
        "status": "passed" if all_publishable else "failed",
        "upstream": upstream,
        "sources": validation_sources,
        "artifacts": generated_artifacts,
        "aliases": aliases,
        "rawCors": raw_checks,
    }
    write_json(reports_root / "validation.json", validation)
    return validation, all_publishable


def build_release(
    config_path: Path,
    source_paths: dict[str, Path],
    output_root: Path,
    repo_root: Path = REPO_ROOT,
    check_cors: bool = False,
) -> tuple[dict[str, Any], bool]:
    candidate_root = (repo_root / "build" / "candidates").resolve()
    target = output_root.resolve()
    if target == candidate_root or candidate_root not in target.parents:
        raise ReleaseError(f"candidate output must stay under {candidate_root}")
    candidate_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=candidate_root) as temp_name:
        staged = Path(temp_name) / "candidate"
        validation, publishable = _build_release_into(
            config_path, source_paths, staged, repo_root, check_cors
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        _replace_output_directory(staged, target)
    return validation, publishable


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-upstream", help="validate pinned upstream snapshot")
    validate.add_argument("--report", type=Path)
    sync = sub.add_parser("sync-upstream", help="copy an explicitly pinned upstream checkout")
    sync.add_argument("--source-dir", type=Path, required=True)
    sync.add_argument("--commit", required=True)
    sync.add_argument("--synced-at", required=True)
    diff = sub.add_parser("diff", help="compare templates and optionally carry translations")
    diff.add_argument("--old", type=Path, required=True)
    diff.add_argument("--new", type=Path, required=True)
    diff.add_argument("--previous-translation", type=Path)
    diff.add_argument("--report", type=Path, required=True)
    diff.add_argument("--carryover", type=Path)
    build = sub.add_parser("build", help="build deterministic release candidates")
    build.add_argument("--config", type=Path, required=True)
    build.add_argument("--source", action="append", default=[], metavar="VARIANT=PATH")
    build.add_argument("--output", type=Path)
    build.add_argument("--check-cors", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "validate-upstream":
            report = {"schemaVersion": 1, "status": "passed", "upstream": validate_upstream()}
            if args.report:
                write_json(args.report.resolve(), report)
            print(json.dumps(report, ensure_ascii=False))
            return 0
        if args.command == "sync-upstream":
            manifest = sync_upstream(args.source_dir.resolve(), args.commit, args.synced_at, REPO_ROOT)
            print(json.dumps(manifest, ensure_ascii=False))
            return 0
        if args.command == "diff":
            report, carryover = diff_templates(
                args.old.resolve(),
                args.new.resolve(),
                args.previous_translation.resolve() if args.previous_translation else None,
            )
            write_json(args.report.resolve(), report)
            if args.carryover:
                if carryover is None:
                    raise ReleaseError("--carryover requires --previous-translation")
                write_json(args.carryover.resolve(), carryover)
            print(json.dumps(report, ensure_ascii=False))
            return 0
        if args.command == "build":
            config_path = args.config.resolve()
            config = load_json(config_path)
            output = (
                args.output.resolve()
                if args.output
                else REPO_ROOT / "build" / "candidates" / str(config.get("channel", "release"))
            )
            validation, passed = build_release(
                config_path, _parse_sources(args.source), output, REPO_ROOT, args.check_cors
            )
            print(json.dumps(validation, ensure_ascii=False))
            return 0 if passed else 2
    except (ReleaseError, OSError, subprocess.CalledProcessError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
