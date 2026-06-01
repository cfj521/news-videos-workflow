import copy
import json
from pathlib import Path


def _repo_root() -> Path:
    # workflow.py 在 backend/app/providers/comfyui/ ；parents[4] = 仓库根
    return Path(__file__).resolve().parents[4]


def load_api_workflow(name: str, workflows_dir: str) -> dict:
    base = Path(workflows_dir)
    if not base.is_absolute():
        base = _repo_root() / base
    return json.loads((base / f"{name}.api.json").read_text(encoding="utf-8"))


def fill_placeholders(graph: dict, values: dict) -> dict:
    def walk(x):
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, str) and x.startswith("__") and x.endswith("__") and x[2:-2] in values:
            return values[x[2:-2]]
        return x
    out = walk(copy.deepcopy(graph))
    leftover = sorted({p for p in json.dumps(out).split('"') if p.startswith("__") and p.endswith("__")})
    if leftover:
        raise ValueError(f"unfilled placeholders: {leftover}")
    return out
