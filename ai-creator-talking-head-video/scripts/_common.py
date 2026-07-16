#!/usr/bin/env python3
"""Shared helpers for ai-creator-talking-head-video scripts."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = SKILL_ROOT / "assets" / "templates" / "model-config.example.json"
KEY_ENV_NAMES = (
    "AI_CREATOR_TALKING_HEAD_VIDEO_API_KEY",
    "AI_TALKING_HEAD_VIDEO_API_KEY",
    "YUNWU_API_KEY",
    "XAI_API_KEY",
)
ENV_FILE_ENV = "AI_CREATOR_TALKING_HEAD_VIDEO_ENV_FILE"
DEFAULT_ENV_FILES = (
    Path.home() / ".codex" / "ai-creator-talking-head-video.env",
    SKILL_ROOT / ".env.local",
)
MINIMUM_MULTI_SEGMENT_SPOKEN_FILL_RATIO = 0.75
SECRET_PATTERN = re.compile(r"(sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,}|[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,})")


class ScriptError(RuntimeError):
    pass


def load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ScriptError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ScriptError(f"Invalid JSON in {path}: {exc}") from exc


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip().strip('"').strip("'")
    if not key:
        return None
    return key, value


def load_env_file(path: Path) -> bool:
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = parse_env_line(line)
        if parsed:
            key, value = parsed
            if not os.environ.get(key):
                os.environ[key] = value
    return True


def load_runtime_env() -> list[str]:
    loaded: list[str] = []
    explicit = os.getenv(ENV_FILE_ENV)
    candidates = [Path(explicit).expanduser()] if explicit else list(DEFAULT_ENV_FILES)
    for path in candidates:
        resolved = path.expanduser().resolve()
        if load_env_file(resolved):
            loaded.append(str(resolved))
    return loaded


def load_config(config_path: Optional[str]) -> Dict[str, Any]:
    load_runtime_env()
    path = Path(config_path).expanduser().resolve() if config_path else DEFAULT_CONFIG
    return load_json(path)


def normalize_base_url(base_url: str) -> str:
    if not base_url:
        raise ScriptError("Model base_url is empty")
    cleaned = base_url.rstrip("/")
    parsed = urlparse(cleaned)
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    needs_v1 = host in {"api.119337.xyz", "api.x.ai", "yunwu.ai", "api.yunwu.ai"} and not path.endswith("/v1")
    if needs_v1:
        path = f"{path}/v1" if path else "/v1"
        cleaned = urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
    return cleaned.rstrip("/")


def join_url(base_url: str, path: str) -> str:
    suffix = path if path.startswith("/") else f"/{path}"
    return normalize_base_url(base_url) + suffix


def model_env_name(model_key: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in model_key.upper()).strip("_")
    return f"AI_CREATOR_TALKING_HEAD_VIDEO_MODEL_{safe}"


def model_base_url_env_name(model_key: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in model_key.upper()).strip("_")
    return f"AI_CREATOR_TALKING_HEAD_VIDEO_BASE_URL_{safe}"


def get_model_config(config: Dict[str, Any], model_key: Optional[str]) -> Dict[str, Any]:
    load_runtime_env()
    requested_key = model_key
    key = model_key or config.get("default_model")
    models = config.get("models") or {}
    if not key or key not in models:
        raise ScriptError(f"Unknown model key: {key!r}")
    model = dict(models[key])
    model["key"] = key
    key_specific_base_url = os.getenv(model_base_url_env_name(key))
    if key_specific_base_url:
        model["base_url"] = key_specific_base_url
    elif os.getenv("AI_CREATOR_TALKING_HEAD_VIDEO_BASE_URL") and (requested_key is None or key == config.get("default_model")):
        model["base_url"] = os.environ["AI_CREATOR_TALKING_HEAD_VIDEO_BASE_URL"]
    key_specific_model = os.getenv(model_env_name(key))
    if key_specific_model:
        model["model"] = key_specific_model
    elif os.getenv("AI_CREATOR_TALKING_HEAD_VIDEO_MODEL") and (requested_key is None or key == config.get("default_model")):
        model["model"] = os.environ["AI_CREATOR_TALKING_HEAD_VIDEO_MODEL"]
    if model.get("base_url"):
        model["base_url"] = normalize_base_url(model["base_url"])
    return model


def model_api_key_names(model: dict) -> list[str] | None:
    names = model.get("api_key_env_names")
    if isinstance(names, list) and names:
        return [str(name) for name in names if str(name).strip()]
    return None


def find_api_key(required: bool = True, names: list[str] | tuple[str, ...] | None = None) -> Optional[str]:
    loaded = load_runtime_env()
    key_names = tuple(names or KEY_ENV_NAMES)
    for name in key_names:
        value = os.getenv(name)
        if value:
            return value
    if required:
        names_text = ", ".join(key_names)
        loaded_hint = f" Loaded env files: {', '.join(loaded)}." if loaded else " No private env file was loaded."
        hint = "Create ~/.codex/ai-creator-talking-head-video.env with this skill's own video API config."
        raise ScriptError(f"Missing API key. Set one of: {names_text}. {hint}{loaded_hint}")
    return None


def redact(value: Optional[str]) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://") or value.startswith("data:")


def sanitize_name(name: str) -> str:
    allowed = []
    for ch in name.strip().lower().replace(" ", "-"):
        if ch.isalnum() or ch in ("-", "_"):
            allowed.append(ch)
    cleaned = "".join(allowed).strip("-_")
    return cleaned or f"talking-head-video-{int(time.time())}"


def safe_asset_folder(name: str) -> str:
    return sanitize_name(name or "asset") or "asset"


def file_to_data_uri(path: Path) -> str:
    if not path.exists():
        raise ScriptError(f"File not found: {path}")
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        mime = "application/octet-stream"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def asset_value(asset: dict | None) -> str:
    if not isinstance(asset, dict):
        return ""
    return str(asset.get("value") or asset.get("path") or asset.get("url") or "")


def media_url(asset: dict | str) -> str:
    value = asset_value(asset) if isinstance(asset, dict) else str(asset)
    if not value:
        raise ScriptError("Missing media value")
    if is_url(value):
        return value
    return file_to_data_uri(Path(value).expanduser().resolve())


def copy_or_record_asset(value: str, assets_dir: Path, folder: str, role: str | None = None) -> dict:
    if is_url(value):
        return {"kind": "url", "value": value, "role": role or folder}
    src = Path(value).expanduser().resolve()
    if not src.exists():
        raise ScriptError(f"Asset not found: {src}")
    dest = assets_dir / safe_asset_folder(folder) / src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return {"kind": "file", "value": str(dest), "role": role or folder, "source": str(src)}


def split_role_value(value: str, default_role: str = "reference") -> tuple[str, str]:
    if "=" in value:
        role, raw = value.split("=", 1)
        return role.strip() or default_role, raw.strip()
    return default_role, value.strip()


def model_allowed_durations(model: Dict[str, Any]) -> List[int]:
    """Return the request durations a model accepts, in ascending order.

    Providers with fixed duration slots must declare ``allowed_durations_seconds``.
    Models without that field retain the older continuous integer-range behavior.
    """
    minimum = int(model.get("min_duration_seconds") or 1)
    maximum = int(model.get("max_duration_seconds") or 0)
    if maximum <= 0 or minimum <= 0 or minimum > maximum:
        raise ScriptError(f"Invalid model duration range {minimum}-{maximum}s")
    configured = model.get("allowed_durations_seconds")
    if configured is None:
        return list(range(minimum, maximum + 1))
    if not isinstance(configured, list) or not configured:
        raise ScriptError("allowed_durations_seconds must be a non-empty list")
    values: List[int] = []
    for raw in configured:
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ScriptError("allowed_durations_seconds must contain integers")
        value = raw
        if value < minimum or value > maximum:
            raise ScriptError(
                f"allowed duration {value}s is outside model range {minimum}-{maximum}s"
            )
        values.append(value)
    if len(set(values)) != len(values):
        raise ScriptError("allowed_durations_seconds must not contain duplicates")
    return sorted(values)


def quantize_request_duration(required_seconds: float, model: Dict[str, Any]) -> int:
    """Round required speech capacity up to the next provider-supported slot."""
    allowed = model_allowed_durations(model)
    for value in allowed:
        if value + 1e-9 >= required_seconds:
            return value
    raise ScriptError(
        f"Required {required_seconds:.2f}s exceeds the model's largest allowed duration {allowed[-1]}s"
    )


def plan_request_durations(total: int, model: Dict[str, Any]) -> List[int]:
    """Plan the fewest paid requests whose supported slots cover ``total``.

    The chosen combination minimizes request-time overshoot, then prefers longer
    earlier clips. Final delivery remains capped separately by the user target.
    """
    if total <= 0:
        raise ScriptError("Duration must be greater than 0 seconds")
    allowed = model_allowed_durations(model)
    maximum = allowed[-1]
    count = max(1, math.ceil(total / maximum))
    states: Dict[int, tuple[int, ...]] = {0: ()}
    descending = sorted(allowed, reverse=True)
    for _ in range(count):
        next_states: Dict[int, tuple[int, ...]] = {}
        for current_sum, current_values in states.items():
            for value in descending:
                new_sum = current_sum + value
                candidate = current_values + (value,)
                existing = next_states.get(new_sum)
                if existing is None or candidate > existing:
                    next_states[new_sum] = candidate
        states = next_states
    covering_sums = [value for value in states if value >= total]
    if not covering_sums:
        raise ScriptError(f"Cannot cover {total}s with model duration slots {allowed}")
    selected_sum = min(covering_sums)
    return list(states[selected_sum])


def minimum_paid_segment_count(total: int, model: Dict[str, Any]) -> int:
    return len(plan_request_durations(total, model))


def semantic_boundary_issue(text: str) -> str:
    """Return a conservative reason when strong punctuation still ends a fragment.

    This is intentionally structural rather than a claim of full language
    understanding. It closes common high-risk splice patterns that punctuation
    alone cannot validate, while leaving ordinary complete sentences unchanged.
    """
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if not cleaned:
        return "missing script"
    if not re.search(r"[。！？!?；;]$", cleaned):
        return "missing strong terminal punctuation"
    body = re.sub(r"[。！？!?；;]+$", "", cleaned).strip()
    if not body:
        return "empty sentence body"
    sentence_parts = [item.strip() for item in re.split(r"[。！？!?；;]+", body) if item.strip()]
    final_sentence = sentence_parts[-1] if sentence_parts else body

    if re.match(r"^从", final_sentence) and "到" in final_sentence:
        tail = final_sentence.rsplit("到", 1)[1]
        predicate = re.search(
            r"(?:都|也|均)?(?:可以|可|能|能够|会|将|已|正在|应该|必须|需要|让|使|由|交给|用于|"
            r"覆盖|包括|形成|实现|完成|处理|提升|降低|负责|支持|成为|属于|是|有|带来|帮助|解决|"
            r"选择|发生|变化|增加|减少|增长|下降|获得|提供|呈现|保持|进入|连接|适合|影响|改变)",
            tail,
        )
        if not predicate:
            return "dangling 从…到… structure without a predicate"

    if re.search(r"(?:以及|并且|而且|但是|不过|因为|所以|如果|虽然|不仅|从|到|把|被|让|给|为|对|在|向|与|和|或)$", final_sentence):
        return "sentence ends with an unfinished connector or preposition"
    return ""


def is_semantically_complete_strong_boundary(text: str) -> bool:
    return not semantic_boundary_issue(text)


def canonical_duration_plan_payload(
    model: Dict[str, Any],
    delivery_max_seconds: int,
    request_durations: List[int],
    scripts: List[str],
) -> Dict[str, Any]:
    """Build the exact cross-stage duration/segmentation contract payload."""
    durations = [int(value) for value in request_durations]
    exact_scripts = [str(value) for value in scripts]
    if len(durations) != len(exact_scripts):
        raise ScriptError("duration plan digest requires one exact script per request duration")
    return {
        "schema_version": 1,
        "model": {
            "key": str(model.get("key") or ""),
            "model": str(model.get("model") or ""),
            "provider_route": str(model.get("provider_route") or ""),
        },
        "delivery_max_seconds": int(delivery_max_seconds),
        "allowed_durations_seconds": model_allowed_durations(model),
        "segment_count": len(durations),
        "request_duration_seconds": durations,
        "segments": [
            {
                "index": index,
                "request_duration_seconds": duration,
                "script": script,
            }
            for index, (duration, script) in enumerate(zip(durations, exact_scripts), start=1)
        ],
    }


def duration_plan_digest(
    model: Dict[str, Any],
    delivery_max_seconds: int,
    request_durations: List[int],
    scripts: List[str],
) -> str:
    payload = canonical_duration_plan_payload(
        model,
        delivery_max_seconds,
        request_durations,
        scripts,
    )
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def contains_secret(text: str) -> bool:
    return bool(SECRET_PATTERN.search(text))


def redact_exact_secret(text: str, secret: str | None) -> str:
    if secret and len(secret) >= 8:
        return text.replace(secret, "***")
    return text


def require_secure_api_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return
    raise ScriptError(f"Refusing to send an API key to a non-HTTPS endpoint: {url}")


def http_json(
    method: str,
    url: str,
    api_key: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: int = 60,
    auth_scheme: str = "Bearer",
    extra_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    require_secure_api_url(url)
    body = None
    auth_value = f"{auth_scheme} {api_key}".strip() if auth_scheme else api_key
    headers = {
        "Authorization": auth_value,
        "Accept": "application/json",
        "User-Agent": "ai-creator-talking-head-video-skill/1.0",
    }
    for key, value in (extra_headers or {}).items():
        if key.lower() == "authorization":
            raise ScriptError("extra_headers cannot override Authorization")
        headers[str(key)] = str(value)
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = redact_exact_secret(response.read().decode("utf-8"), api_key)
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise ScriptError(f"Expected JSON from {url}, got: {text[:160]}") from exc
    except urllib.error.HTTPError as exc:
        text = redact_exact_secret(exc.read().decode("utf-8", errors="replace"), api_key)
        raise ScriptError(f"HTTP {exc.code} from {url}: {text[:500]}") from exc
    except urllib.error.URLError as exc:
        raise ScriptError(f"Network error calling {url}: {exc}") from exc


def download_file(url: str, output_path: Path, timeout: int = 120) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "ai-creator-talking-head-video-skill/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, output_path.open("wb") as out:
            shutil.copyfileobj(response, out)
    except urllib.error.URLError as exc:
        raise ScriptError(f"Failed to download {url}: {exc}") from exc


def run_json_command(cmd: List[str], timeout: int = 60) -> Dict[str, Any]:
    try:
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=True)
        return json.loads(proc.stdout)
    except FileNotFoundError as exc:
        raise ScriptError(f"Required command not found: {cmd[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise ScriptError(f"Command failed: {' '.join(cmd)}\n{exc.stderr[:500]}") from exc
    except json.JSONDecodeError as exc:
        raise ScriptError(f"Command did not return JSON: {' '.join(cmd)}") from exc


def ffprobe_media(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise ScriptError(f"Media file not found: {path}")
    if path.stat().st_size <= 0:
        raise ScriptError(f"Media file is empty: {path}")
    return run_json_command(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", str(path)])


def media_summary(path: Path) -> Dict[str, Any]:
    data = ffprobe_media(path)
    video = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"), None)
    fmt = data.get("format") or {}
    try:
        duration = float(fmt.get("duration", 0) or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "duration_seconds": round(duration, 3),
        "has_video": video is not None,
        "has_audio": audio is not None,
        "video": {
            "codec": video.get("codec_name"),
            "width": video.get("width"),
            "height": video.get("height"),
            "fps": video.get("r_frame_rate"),
            "pixel_format": video.get("pix_fmt"),
        } if video else None,
        "audio": {
            "codec": audio.get("codec_name"),
            "sample_rate": audio.get("sample_rate"),
            "channels": audio.get("channels"),
        } if audio else None,
    }


def verify_media_file(path: Path, require_audio: bool = False) -> Dict[str, Any]:
    summary = media_summary(path)
    if not summary["has_video"]:
        raise ScriptError(f"Downloaded file has no video stream: {path}")
    if require_audio and not summary["has_audio"]:
        raise ScriptError(f"Downloaded file has no audio stream: {path}")
    if summary["duration_seconds"] <= 0:
        raise ScriptError(f"Media duration is zero or unavailable: {path}")
    return summary


def require_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise ScriptError("ffmpeg not found. Install ffmpeg or run stitch_clips.py --dry-run.")
    return path
