from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MODEL_NAME = os.getenv("FINWISE_LOCAL_MODEL_NAME", "finwise-scratch:0.1")
DEFAULT_MODELS_DIR = Path(os.getenv("FINWISE_LOCAL_MODELS_DIR", Path(__file__).parent / "models"))


@dataclass(frozen=True)
class LocalModel:
    name: str
    family: str = "finwise"
    format: str = "finwise"
    engine: str = "auto"
    parameter_size: str = "rules+context"
    quantization_level: str = "none"
    system_prompt: str = "You are Finwise Copilot, a practical trading assistant."
    template: str = ""
    weight_path: str = ""
    digest: str = "finwise-owned-runtime"
    size: int = 0
    modified_at: str = ""

    def to_ollama_tag(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "model": self.name,
            "modified_at": self.modified_at or _now_iso(),
            "size": int(self.size or 0),
            "digest": self.digest,
            "details": {
                "format": self.format,
                "family": self.family,
                "engine": self.engine,
                "parameter_size": self.parameter_size,
                "quantization_level": self.quantization_level,
            },
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _model_file_name(model_name: str) -> str:
    return model_name.replace("/", "_").replace(":", "__") + ".json"


def _default_model() -> LocalModel:
    return LocalModel(name=DEFAULT_MODEL_NAME, modified_at=_now_iso())


def ensure_models_dir(models_dir: Path = DEFAULT_MODELS_DIR) -> Path:
    models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir


def model_path(model_name: str, models_dir: Path = DEFAULT_MODELS_DIR) -> Path:
    return ensure_models_dir(models_dir) / _model_file_name(model_name)


def save_model(model: LocalModel, models_dir: Path = DEFAULT_MODELS_DIR) -> Path:
    payload = asdict(model)
    if not payload.get("modified_at"):
        payload["modified_at"] = _now_iso()
    path = model_path(model.name, models_dir)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def delete_model(model_name: str, models_dir: Path = DEFAULT_MODELS_DIR) -> bool:
    path = model_path(model_name, models_dir)
    if not path.exists():
        return False
    path.unlink()
    return True


def copy_model(source_name: str, destination_name: str, models_dir: Path = DEFAULT_MODELS_DIR) -> LocalModel:
    source = load_model(source_name, models_dir)
    copied = replace(source, name=destination_name, modified_at=_now_iso())
    save_model(copied, models_dir)
    return copied


def load_model(model_name: str = DEFAULT_MODEL_NAME, models_dir: Path = DEFAULT_MODELS_DIR) -> LocalModel:
    path = model_path(model_name, models_dir)
    if not path.exists():
        default_model = _default_model() if model_name == DEFAULT_MODEL_NAME else LocalModel(name=model_name, modified_at=_now_iso())
        save_model(default_model, models_dir)
        return default_model
    payload = json.loads(path.read_text(encoding="utf-8"))
    return LocalModel(
        name=str(payload.get("name") or model_name),
        family=str(payload.get("family") or "finwise"),
        format=str(payload.get("format") or "finwise"),
        engine=str(payload.get("engine") or "auto"),
        parameter_size=str(payload.get("parameter_size") or "rules+context"),
        quantization_level=str(payload.get("quantization_level") or "none"),
        system_prompt=str(payload.get("system_prompt") or ""),
        template=str(payload.get("template") or ""),
        weight_path=str(payload.get("weight_path") or ""),
        digest=str(payload.get("digest") or "finwise-owned-runtime"),
        size=int(payload.get("size") or 0),
        modified_at=str(payload.get("modified_at") or _now_iso()),
    )


def list_models(models_dir: Path = DEFAULT_MODELS_DIR) -> list[LocalModel]:
    ensure_models_dir(models_dir)
    models: list[LocalModel] = []
    for path in sorted(models_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            name = str(payload.get("name") or "")
            if name:
                models.append(load_model(name, models_dir))
        except (OSError, ValueError, TypeError):
            continue
    if not models:
        models.append(load_model(DEFAULT_MODEL_NAME, models_dir))
    return models


def parse_modelfile(text: str, *, default_name: str = DEFAULT_MODEL_NAME) -> LocalModel:
    name = default_name
    family = "finwise"
    parameter_size = "rules+context"
    quantization = "none"
    engine = "auto"
    system_lines: list[str] = []
    template_lines: list[str] = []
    weight_path = ""
    active_block = ""

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        upper = line.upper()
        if upper.startswith("NAME "):
            name = line.split(None, 1)[1].strip()
            active_block = ""
        elif upper.startswith("FAMILY "):
            family = line.split(None, 1)[1].strip()
            active_block = ""
        elif upper.startswith("PARAMETER_SIZE "):
            parameter_size = line.split(None, 1)[1].strip()
            active_block = ""
        elif upper.startswith("ENGINE "):
            engine = line.split(None, 1)[1].strip()
            active_block = ""
        elif upper.startswith("QUANTIZATION "):
            quantization = line.split(None, 1)[1].strip()
            active_block = ""
        elif upper.startswith("WEIGHTS "):
            weight_path = line.split(None, 1)[1].strip()
            active_block = ""
        elif upper == "SYSTEM":
            active_block = "system"
        elif upper == "TEMPLATE":
            active_block = "template"
        elif active_block == "system":
            system_lines.append(raw_line)
        elif active_block == "template":
            template_lines.append(raw_line)

    return LocalModel(
        name=name,
        family=family,
        engine=engine,
        parameter_size=parameter_size,
        quantization_level=quantization,
        system_prompt="\n".join(system_lines).strip() or "You are Finwise Copilot, a practical trading assistant.",
        template="\n".join(template_lines).strip(),
        weight_path=weight_path,
        modified_at=_now_iso(),
    )
