# Plan 1 — 存储基座 + model_providers.yaml 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭起 YAML 存储基座（原子 IO + per-file 锁），把供应商凭证与 OpenAI OAuth 订阅 token 从 `config.yaml`/DB 迁到 `model_providers.yaml`，并瘦身 `config.yaml`（删废弃 claude 块）。

**Architecture:** 新增 `backend/app/store/` 包：`_io.py`（原子 yaml 读写 + 每文件 `threading.Lock`）、`providers_store.py`（读写 `model_providers.yaml`，含 providers 凭证与 oauth 两部分）。`config.py` 的 `get_settings()/save_settings()` 把 `providers` 字段透明路由到 `providers_store`，因此 `provider_creds()`/`resolve()` 与前端 Settings 页全部无需改动。`oauth/openai_oauth.py` 改为读写 store、去掉 `db` 参数（`OAuthLoginSession` 仍走 DB）。启动时一次性把 config.yaml 的 providers + DB 的 oauth_credentials 迁入 `model_providers.yaml`。

**Tech Stack:** Python 3.12 / FastAPI / pydantic / PyYAML / pytest；前端本计划不改。

**整体规则:** 仓库根 `model_providers.yaml`（与 config.yaml 同级）。后端命令在 `backend/` 下跑（`cd backend`）。本计划完成后 `pytest` 全绿、`ruff check .` 干净。

---

## 文件结构

- **新增** `backend/app/store/__init__.py` — 空包标记。
- **新增** `backend/app/store/_io.py` — `load_yaml(path)` / `save_yaml(path, data)`（原子写）+ `file_lock(path)`（每文件 `threading.Lock`）。
- **新增** `backend/app/store/providers_store.py` — `MODEL_PROVIDERS_PATH`、`load_providers()`、`save_providers(creds_by_name)`、`load_oauth(provider)`、`save_oauth(provider, oauth)`、`clear_oauth(provider)`。
- **新增** `backend/app/store/oauth_models.py` — `OAuthData` pydantic 模型（oauth 子结构）。
- **修改** `backend/app/config.py` — `Settings.providers` 改由 store 注入/持久化；删 `_migrate_legacy` 的 providers 迁移路径不再从 config.yaml 读 providers（保留对极旧配置兼容由迁移脚本兜底）。
- **修改** `backend/app/oauth/openai_oauth.py` — 全函数去 `db`，改读写 `providers_store`。
- **修改** `backend/app/api/openai_oauth.py` — `status()`/`logout()` 去 db 传参；import 收敛。
- **修改** `backend/app/main.py` — lifespan 加一次性迁移 `_migrate_providers_to_yaml()`。
- **修改** 仓库根 `config.yaml` — 删 `providers`（迁出）、删废弃 `claude`。
- **修改** `config.yaml.example` — 同步删 providers/claude，加注释指向 `model_providers.yaml.example`。
- **新增** `model_providers.yaml.example` — 模板。
- **测试** `backend/tests/test_store_io.py`、`test_providers_store.py`、`test_openai_oauth.py`（改写）、`test_config_providers.py`、`test_migrate_providers.py`。

---

## Task 1: 原子 YAML IO 基座

**Files:**
- Create: `backend/app/store/__init__.py`
- Create: `backend/app/store/_io.py`
- Test: `backend/tests/test_store_io.py`

- [ ] **Step 1: 建空包**

Create `backend/app/store/__init__.py` 内容为空（仅作包标记）。

- [ ] **Step 2: 写失败测试**

Create `backend/tests/test_store_io.py`:

```python
import threading
from pathlib import Path

from app.store import _io


def test_save_then_load_roundtrip(tmp_path: Path):
    p = tmp_path / "x.yaml"
    _io.save_yaml(p, {"a": 1, "b": ["x", "y"]})
    assert _io.load_yaml(p) == {"a": 1, "b": ["x", "y"]}


def test_load_missing_returns_empty(tmp_path: Path):
    assert _io.load_yaml(tmp_path / "nope.yaml") == {}


def test_load_corrupt_raises(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("a: [unclosed\n", encoding="utf-8")
    try:
        _io.load_yaml(p)
        raise AssertionError("应抛出错误")
    except Exception as e:  # noqa: BLE001
        assert str(p) in str(e)


def test_save_is_atomic_no_partial_temp_left(tmp_path: Path):
    p = tmp_path / "y.yaml"
    _io.save_yaml(p, {"k": "v"})
    # 写完目录里不应残留临时文件
    leftovers = [f.name for f in tmp_path.iterdir() if f.name != "y.yaml"]
    assert leftovers == []


def test_file_lock_serializes_writers(tmp_path: Path):
    p = tmp_path / "z.yaml"
    order: list[str] = []

    def worker(tag: str):
        with _io.file_lock(p):
            order.append(f"{tag}-start")
            order.append(f"{tag}-end")

    t1 = threading.Thread(target=worker, args=("a",))
    t2 = threading.Thread(target=worker, args=("b",))
    t1.start(); t1.join(); t2.start(); t2.join()
    # 每个 start 紧跟自己的 end（未交错）
    assert order in (
        ["a-start", "a-end", "b-start", "b-end"],
        ["b-start", "b-end", "a-start", "a-end"],
    )
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && pytest tests/test_store_io.py -v`
Expected: FAIL（`ModuleNotFoundError: app.store._io` 或属性缺失）

- [ ] **Step 4: 实现 `_io.py`**

Create `backend/app/store/_io.py`:

```python
"""YAML 文件存储基座：原子写 + 每文件线程锁。

后端当前单进程（uvicorn + 单 worker 串行执行器 + OAuth 回调线程），用
threading.Lock 防同文件并发写交错即可，无需跨进程锁。
"""
from __future__ import annotations

import contextlib
import os
import tempfile
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

# 每个文件路径一把锁（按绝对路径字符串归一）
_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _locks_guard:
        return _locks[key]


@contextlib.contextmanager
def file_lock(path: Path):
    lock = _lock_for(path)
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def load_yaml(path: Path) -> dict[str, Any]:
    """读 YAML；文件不存在返回 {}；解析失败抛带路径的错误。"""
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise RuntimeError(f"YAML 解析失败：{path}：{e}") from e


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    """原子写：先写同目录临时文件再 os.replace，避免半截文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            with contextlib.suppress(OSError):
                os.remove(tmp)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && pytest tests/test_store_io.py -v`
Expected: PASS（5 passed）

- [ ] **Step 6: 提交**

```bash
git add backend/app/store/__init__.py backend/app/store/_io.py backend/tests/test_store_io.py
git commit -m "feat(store): 原子 YAML IO 基座 + per-file 锁"
```

---

## Task 2: oauth 子模型

**Files:**
- Create: `backend/app/store/oauth_models.py`
- Test: `backend/tests/test_providers_store.py`（本任务先建文件，含 OAuthData 用例）

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_providers_store.py`:

```python
from app.store.oauth_models import OAuthData


def test_oauthdata_defaults_empty():
    d = OAuthData()
    assert d.access_token == "" and d.refresh_token == ""
    assert d.expires_at == "" and d.account_id == ""


def test_oauthdata_roundtrip_dict():
    d = OAuthData(access_token="a", refresh_token="r", expires_at="2026-06-07T00:00:00+00:00",
                  account_id="acc", plan_type="plus", account_email="x@y.z",
                  id_token="idt", last_refresh="2026-06-07T00:00:00+00:00")
    out = d.model_dump()
    assert OAuthData(**out) == d
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_providers_store.py -v`
Expected: FAIL（`ModuleNotFoundError: app.store.oauth_models`）

- [ ] **Step 3: 实现 `oauth_models.py`**

Create `backend/app/store/oauth_models.py`:

```python
from __future__ import annotations

from pydantic import BaseModel


class OAuthData(BaseModel):
    """供应商订阅 OAuth 凭证（当前仅 openai）。datetime 以 ISO8601 字符串存。"""
    access_token: str = ""
    refresh_token: str = ""
    id_token: str = ""
    account_id: str = ""
    expires_at: str = ""        # ISO8601；空串表示未登录
    plan_type: str = ""
    account_email: str = ""
    last_refresh: str = ""
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_providers_store.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/store/oauth_models.py backend/tests/test_providers_store.py
git commit -m "feat(store): OAuthData 子模型"
```

---

## Task 3: providers_store（读写 model_providers.yaml）

**Files:**
- Create: `backend/app/store/providers_store.py`
- Test: `backend/tests/test_providers_store.py`（追加用例）

`ProviderCreds` 复用 `app.config` 中已有的 pydantic 模型，避免重复定义。

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/test_providers_store.py` 末尾追加：

```python
from pathlib import Path

import app.store.providers_store as ps
from app.config import ProviderCreds
from app.store.oauth_models import OAuthData


def _point_to_tmp(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ps, "MODEL_PROVIDERS_PATH", tmp_path / "model_providers.yaml")


def test_load_providers_empty(tmp_path, monkeypatch):
    _point_to_tmp(tmp_path, monkeypatch)
    assert ps.load_providers() == {}


def test_save_then_load_providers(tmp_path, monkeypatch):
    _point_to_tmp(tmp_path, monkeypatch)
    creds = {"openai": ProviderCreds(base_url="https://api.openai.com/v1", api_key="sk-x")}
    ps.save_providers(creds)
    got = ps.load_providers()
    assert got["openai"].api_key == "sk-x"
    assert got["openai"].base_url == "https://api.openai.com/v1"


def test_save_providers_preserves_oauth(tmp_path, monkeypatch):
    _point_to_tmp(tmp_path, monkeypatch)
    ps.save_oauth("openai", OAuthData(access_token="tok", refresh_token="r"))
    ps.save_providers({"openai": ProviderCreds(api_key="sk-new")})
    # 保存 creds 不能清掉已有 oauth
    assert ps.load_oauth("openai").access_token == "tok"


def test_oauth_roundtrip_and_clear(tmp_path, monkeypatch):
    _point_to_tmp(tmp_path, monkeypatch)
    assert ps.load_oauth("openai") == OAuthData()
    ps.save_oauth("openai", OAuthData(access_token="a", refresh_token="r"))
    assert ps.load_oauth("openai").access_token == "a"
    ps.clear_oauth("openai")
    assert ps.load_oauth("openai") == OAuthData()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_providers_store.py -v`
Expected: FAIL（`AttributeError: module ... has no attribute 'MODEL_PROVIDERS_PATH'`）

- [ ] **Step 3: 实现 `providers_store.py`**

Create `backend/app/store/providers_store.py`:

```python
"""model_providers.yaml 读写：providers 凭证（被 config.Settings 注入）+ oauth 订阅凭证。

文件结构：
    providers:
      openai:
        base_url, api_key, auth_mode, max_output_tokens
        models: {text: [], image: [], vision: [], tts: []}
        oauth: {access_token, refresh_token, ...}   # 仅订阅模式有意义
"""
from __future__ import annotations

from pathlib import Path

from app.config import ProviderCreds
from app.store import _io
from app.store.oauth_models import OAuthData

MODEL_PROVIDERS_PATH = Path(__file__).resolve().parents[3] / "model_providers.yaml"


def _read() -> dict:
    return _io.load_yaml(MODEL_PROVIDERS_PATH)


def _write(data: dict) -> None:
    _io.save_yaml(MODEL_PROVIDERS_PATH, data)


def load_providers() -> dict[str, ProviderCreds]:
    """返回 {name: ProviderCreds}（不含 oauth 子键）。"""
    raw = _read().get("providers", {}) or {}
    out: dict[str, ProviderCreds] = {}
    for name, slot in raw.items():
        slot = dict(slot or {})
        slot.pop("oauth", None)  # oauth 单独取
        out[name] = ProviderCreds(**slot)
    return out


def save_providers(creds_by_name: dict[str, ProviderCreds]) -> None:
    """整体替换 providers 的凭证部分；保留每个 provider 已有的 oauth 子键。"""
    with _io.file_lock(MODEL_PROVIDERS_PATH):
        data = _read()
        old = data.get("providers", {}) or {}
        new: dict[str, dict] = {}
        for name, creds in creds_by_name.items():
            slot = creds.model_dump()
            existing_oauth = (old.get(name) or {}).get("oauth")
            if existing_oauth:
                slot["oauth"] = existing_oauth
            new[name] = slot
        data["providers"] = new
        _write(data)


def load_oauth(provider: str) -> OAuthData:
    slot = (_read().get("providers", {}) or {}).get(provider, {}) or {}
    return OAuthData(**(slot.get("oauth") or {}))


def save_oauth(provider: str, oauth: OAuthData) -> None:
    with _io.file_lock(MODEL_PROVIDERS_PATH):
        data = _read()
        providers = data.setdefault("providers", {})
        slot = providers.setdefault(provider, {})
        slot["oauth"] = oauth.model_dump()
        _write(data)


def clear_oauth(provider: str) -> None:
    with _io.file_lock(MODEL_PROVIDERS_PATH):
        data = _read()
        slot = (data.get("providers", {}) or {}).get(provider)
        if slot and "oauth" in slot:
            del slot["oauth"]
            _write(data)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_providers_store.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/store/providers_store.py backend/tests/test_providers_store.py
git commit -m "feat(store): providers_store 读写 model_providers.yaml（含 oauth 保留）"
```

---

## Task 4: config.py 把 providers 路由到 store

现状（`backend/app/config.py`）：`Settings.providers` 是字段，从 config.yaml 加载；`get_settings()` 在 379 行 `Settings(**raw)`；`save_settings()` 在 387 行 `_save_yaml(CONFIG_PATH, settings.model_dump())`。
改为：providers 不再进出 config.yaml，而是 `get_settings()` 从 `providers_store` 注入、`save_settings()` 写回 `providers_store`，config.yaml 的 dump 排除 providers。`provider_creds()` / `resolve()` 不变。

**Files:**
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_config_providers.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_config_providers.py`:

```python
from pathlib import Path

import app.config as cfgmod
import app.store.providers_store as ps
from app.config import ProviderCreds, Settings


def _isolate(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(ps, "MODEL_PROVIDERS_PATH", tmp_path / "model_providers.yaml")
    cfgmod._settings = None  # 清缓存


def test_save_settings_writes_providers_to_store_not_config(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    s = Settings()
    s.providers = {"openai": ProviderCreds(api_key="sk-z")}
    cfgmod.save_settings(s)
    # providers 落到 model_providers.yaml，不在 config.yaml
    import yaml
    raw_cfg = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8")) or {}
    assert "providers" not in raw_cfg
    assert ps.load_providers()["openai"].api_key == "sk-z"


def test_get_settings_injects_providers_from_store(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    ps.save_providers({"openai": ProviderCreds(api_key="sk-from-store")})
    cfgmod._settings = None
    s = cfgmod.get_settings()
    assert s.provider_creds("openai").api_key == "sk-from-store"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_config_providers.py -v`
Expected: FAIL（providers 仍写进 config.yaml）

- [ ] **Step 3: 改 `get_settings()`**

在 `backend/app/config.py` 的 `get_settings()`（约 375-384 行）里，`Settings(**raw)` 之后、返回之前，注入 store 的 providers：

```python
def get_settings() -> Settings:
    global _settings
    if _settings is None:
        raw = _migrate_legacy(_load_yaml(CONFIG_PATH))
        raw.pop("providers", None)  # providers 不再从 config.yaml 取
        _settings = Settings(**raw)
        from app.store import providers_store
        stored = providers_store.load_providers()
        if stored:
            _settings.providers = stored
        _ensure_default_models(_settings)
        _migrate_comfyui_keys(_settings)
        import logging
        logging.getLogger("nv.config").info("Loaded config from %s", CONFIG_PATH)
    return _settings
```

- [ ] **Step 4: 改 `save_settings()`**

把 `backend/app/config.py` 的 `save_settings()`（约 387-392 行）改为：

```python
def save_settings(settings: Settings) -> None:
    global _settings
    _settings = settings
    from app.store import providers_store
    providers_store.save_providers(settings.providers)
    data = settings.model_dump()
    data.pop("providers", None)  # providers 走 providers_store，不写 config.yaml
    _save_yaml(CONFIG_PATH, data)
    import logging
    logging.getLogger("nv.config").info("Saved config to %s", CONFIG_PATH)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && pytest tests/test_config_providers.py -v`
Expected: PASS（2 passed）

- [ ] **Step 6: 回归确认其它配置测试未坏**

Run: `cd backend && pytest tests/ -k "config or settings" -v`
Expected: PASS（无新失败）

- [ ] **Step 7: 提交**

```bash
git add backend/app/config.py backend/tests/test_config_providers.py
git commit -m "feat(config): providers 透明路由到 providers_store"
```

---

## Task 5: OAuth 文件版（openai_oauth.py 去 db）

现状见 `backend/app/oauth/openai_oauth.py`：`_apply_tokens(row, tok)` 写 SQLAlchemy row；`store_tokens(db,…)`、`get_valid_access_token(db)`、`get_status(db)`、`logout(db)`、`handle_callback(db, query)` 都用 `OAuthCredential`。改为全部基于 `providers_store.load_oauth("openai")/save_oauth/clear_oauth` 操作 `OAuthData`，去掉 `db` 参数。`OAuthLoginSession` 相关仍走 DB（`handle_callback` 里读写 session 保留 db）。

**Files:**
- Modify: `backend/app/oauth/openai_oauth.py`
- Modify: `backend/app/api/openai_oauth.py`
- Test: `backend/tests/test_openai_oauth.py`（改写为 store 版）

- [ ] **Step 1: 改写测试**

把 `backend/tests/test_openai_oauth.py` 整体替换为（store 版，无 db）：

```python
from datetime import datetime, timedelta, timezone

import pytest

import app.store.providers_store as ps
from app.oauth import openai_oauth as oo
from app.store.oauth_models import OAuthData


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "MODEL_PROVIDERS_PATH", tmp_path / "model_providers.yaml")


def _fake_tok(exp_delta_s: int) -> dict:
    # 用真实 base64url JWT payload，含 exp 与 auth/profile 声明
    import base64
    import json

    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")

    exp = int((datetime.now(timezone.utc) + timedelta(seconds=exp_delta_s)).timestamp())
    payload = {
        "exp": exp,
        "https://api.openai.com/auth": {"chatgpt_account_id": "acc1", "chatgpt_plan_type": "plus"},
        "https://api.openai.com/profile": {"email": "u@e.com"},
    }
    jwt = f"h.{b64(payload)}.s"
    return {"access_token": jwt, "refresh_token": "refresh1", "id_token": "id1"}


def test_store_tokens_writes_to_yaml():
    oo.store_tokens(_fake_tok(3600))
    d = ps.load_oauth("openai")
    assert d.refresh_token == "refresh1"
    assert d.account_id == "acc1" and d.plan_type == "plus" and d.account_email == "u@e.com"
    assert d.expires_at  # ISO 字符串


def test_get_status_logged_out():
    assert oo.get_status() == {"logged_in": False}


def test_get_status_logged_in():
    oo.store_tokens(_fake_tok(3600))
    st = oo.get_status()
    assert st["logged_in"] is True and st["email"] == "u@e.com" and st["plan"] == "plus"


def test_logout_clears():
    oo.store_tokens(_fake_tok(3600))
    oo.logout()
    assert oo.get_status() == {"logged_in": False}


def test_get_valid_access_token_not_logged_in():
    with pytest.raises(oo.NotLoggedInError):
        oo.get_valid_access_token()


def test_get_valid_access_token_returns_when_fresh():
    tok = _fake_tok(3600)
    oo.store_tokens(tok)
    access, account_id = oo.get_valid_access_token()
    assert access == tok["access_token"] and account_id == "acc1"


def test_get_valid_access_token_refreshes_when_expiring(monkeypatch):
    oo.store_tokens(_fake_tok(60))  # 60s < 300s margin → 触发刷新
    new = _fake_tok(3600)
    monkeypatch.setattr(oo, "refresh_tokens", lambda rt: new)
    access, _ = oo.get_valid_access_token()
    assert access == new["access_token"]
    assert ps.load_oauth("openai").access_token == new["access_token"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_openai_oauth.py -v`
Expected: FAIL（函数仍要 db 参数 / 仍依赖 OAuthCredential）

- [ ] **Step 3: 改 `_apply_tokens` 为操作 OAuthData**

把 `backend/app/oauth/openai_oauth.py` 的 `_apply_tokens`（112-127 行）替换为：

```python
def _apply_tokens(data: "OAuthData", tok: dict) -> None:
    """把 token dict 写入 OAuthData（解析 access_token 声明）。"""
    access = tok["access_token"]
    claims = parse_claims(access)
    data.access_token = access
    if tok.get("refresh_token"):
        data.refresh_token = tok["refresh_token"]
    if tok.get("id_token"):
        data.id_token = tok["id_token"]
    data.account_id = claims["account_id"] or data.account_id
    data.plan_type = claims["plan_type"] or data.plan_type
    data.account_email = claims["email"] or data.account_email
    if claims["exp"] is None:
        raise ValueError("access_token 缺少 exp 声明")
    data.expires_at = datetime.fromtimestamp(claims["exp"], tz=timezone.utc).isoformat()
    data.last_refresh = datetime.now(timezone.utc).isoformat()
```

并在文件顶部 import 区加：

```python
from app.store import providers_store
from app.store.oauth_models import OAuthData
```

- [ ] **Step 4: 改 store_tokens / get_valid_access_token / get_status / logout**

把 `backend/app/oauth/openai_oauth.py` 的 130-195 行（`store_tokens` 到 `logout`）整段替换为：

```python
_PROVIDER = "openai"


def store_tokens(tok: dict) -> OAuthData:
    data = providers_store.load_oauth(_PROVIDER)
    _apply_tokens(data, tok)
    providers_store.save_oauth(_PROVIDER, data)
    return data


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def get_valid_access_token() -> tuple[str, str]:
    """返回 (access_token, account_id)；临期自动刷新。未登录抛 NotLoggedInError。"""
    data = providers_store.load_oauth(_PROVIDER)
    if not data.access_token:
        raise NotLoggedInError("未登录 OpenAI（订阅模式）")
    now = datetime.now(timezone.utc)
    expires_at = _parse_iso(data.expires_at)
    remaining = (expires_at - now).total_seconds() if expires_at else -1
    if remaining < _REFRESH_MARGIN:
        with _refresh_lock:
            data = providers_store.load_oauth(_PROVIDER)  # 锁内重读，避免重复刷新
            expires_at2 = _parse_iso(data.expires_at)
            if not expires_at2 or (expires_at2 - datetime.now(timezone.utc)).total_seconds() < _REFRESH_MARGIN:
                tok = refresh_tokens(data.refresh_token)
                _apply_tokens(data, tok)
                providers_store.save_oauth(_PROVIDER, data)
    return data.access_token, data.account_id


def get_status() -> dict:
    data = providers_store.load_oauth(_PROVIDER)
    if not data.access_token:
        return {"logged_in": False}
    expires_at = _parse_iso(data.expires_at)
    return {
        "logged_in": True,
        "email": data.account_email,
        "plan": data.plan_type,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


def logout() -> None:
    providers_store.clear_oauth(_PROVIDER)
```

- [ ] **Step 5: 改 handle_callback（保留 db 仅用于 OAuthLoginSession）**

把 `backend/app/oauth/openai_oauth.py` 的 `handle_callback`（209-228 行）里 `store_tokens(db, tok)` 改为 `store_tokens(tok)`：

```python
def handle_callback(db, query: dict) -> bool:
    """处理回调 query。db 仅用于读写 OAuthLoginSession；token 走 providers_store。"""
    from app.models.oauth_credential import OAuthLoginSession
    state = query.get("state", "")
    code = query.get("code", "")
    sess = db.query(OAuthLoginSession).filter_by(state=state, status="pending").first()
    if sess is None or not code:
        return False
    try:
        tok = exchange_code(code, sess.code_verifier)
        store_tokens(tok)
        sess.status = "success"
        db.commit()
        return True
    except Exception as e:  # noqa: BLE001
        log.exception("OAuth 回调处理失败")
        sess.status = "error"
        sess.error = str(e)
        db.commit()
        return False
```

- [ ] **Step 6: 改 subscription_creds 不再开 db**

把 `backend/app/oauth/openai_oauth.py` 的 `subscription_creds`（309-316 行）替换为：

```python
def subscription_creds() -> tuple[str, str, str]:
    """供 provider 工厂用：返回 (CODEX_BASE, access_token, account_id)。"""
    token, account_id = get_valid_access_token()
    return CODEX_BASE, token, account_id
```

- [ ] **Step 7: 改 api/openai_oauth.py 去 db 传参**

把 `backend/app/api/openai_oauth.py` 的 37-45 行替换为：

```python
@router.get("/status")
async def status():
    return oo.get_status()


@router.post("/logout")
async def logout():
    oo.logout()
    return {"status": "ok"}
```

并把第 10 行 import 改为只留 session 模型：

```python
from app.models.oauth_credential import OAuthLoginSession  # noqa: F401
```

（删除 `OAuthCredential`，保留 `OAuthLoginSession`；`status`/`logout` 路由签名删掉 `db: Session = Depends(get_db)`。`login_start`/`login_status` 仍需 `db`，保持不变。）

- [ ] **Step 8: 跑 OAuth 测试确认通过**

Run: `cd backend && pytest tests/test_openai_oauth.py -v`
Expected: PASS（8 passed）

- [ ] **Step 9: 全量回归**

Run: `cd backend && pytest -q`
Expected: PASS（无新失败；若 `test_oauth_credential_model.py` 因模型仍在而通过则保留，Task 7 再处理）

- [ ] **Step 10: 提交**

```bash
git add backend/app/oauth/openai_oauth.py backend/app/api/openai_oauth.py backend/tests/test_openai_oauth.py
git commit -m "feat(oauth): token 改存 model_providers.yaml，全函数去 db"
```

---

## Task 6: 启动时一次性迁移 providers + oauth → model_providers.yaml

把现有 config.yaml 的 `providers` 块与 DB `oauth_credentials` 表的 openai 行，导出到 `model_providers.yaml`（仅当文件不存在时）。用原生 `sqlite3` 读 oauth（不依赖 ORM）。providers 这时仍可能在 config.yaml 里（旧文件），直接读原始 yaml。

**Files:**
- Create: `backend/app/store/migrate.py`
- Modify: `backend/app/main.py`（lifespan 调用）
- Test: `backend/tests/test_migrate_providers.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_migrate_providers.py`:

```python
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import yaml

import app.store.providers_store as ps
from app.store.migrate import migrate_providers_to_yaml


def _make_sqlite_with_oauth(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE oauth_credentials (provider TEXT, access_token TEXT, refresh_token TEXT,"
        " id_token TEXT, account_id TEXT, expires_at TEXT, plan_type TEXT, account_email TEXT, last_refresh TEXT)"
    )
    conn.execute(
        "INSERT INTO oauth_credentials VALUES (?,?,?,?,?,?,?,?,?)",
        ("openai", "acc-tok", "ref-tok", "idt", "acc1",
         datetime(2026, 6, 7, tzinfo=timezone.utc).isoformat(), "plus", "u@e.com", ""),
    )
    conn.commit()
    conn.close()


def test_migrate_seeds_providers_and_oauth(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({
        "providers": {"openai": {"base_url": "https://api.openai.com/v1", "api_key": "sk-old"}},
    }), encoding="utf-8")
    db = tmp_path / "app.db"
    _make_sqlite_with_oauth(db)
    monkeypatch.setattr(ps, "MODEL_PROVIDERS_PATH", tmp_path / "model_providers.yaml")

    migrate_providers_to_yaml(config_path=cfg, sqlite_path=db)

    assert ps.load_providers()["openai"].api_key == "sk-old"
    assert ps.load_oauth("openai").access_token == "acc-tok"


def test_migrate_idempotent_skips_when_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "MODEL_PROVIDERS_PATH", tmp_path / "model_providers.yaml")
    ps.save_providers({})  # 文件已存在
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"providers": {"openai": {"api_key": "sk-should-not-load"}}}), encoding="utf-8")
    migrate_providers_to_yaml(config_path=cfg, sqlite_path=tmp_path / "missing.db")
    assert "openai" not in ps.load_providers()


def test_migrate_no_db_no_providers_writes_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "MODEL_PROVIDERS_PATH", tmp_path / "model_providers.yaml")
    cfg = tmp_path / "config.yaml"
    cfg.write_text("pipeline: {}\n", encoding="utf-8")
    migrate_providers_to_yaml(config_path=cfg, sqlite_path=tmp_path / "missing.db")
    assert ps.load_providers() == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_migrate_providers.py -v`
Expected: FAIL（`ModuleNotFoundError: app.store.migrate`）

- [ ] **Step 3: 实现 `migrate.py`**

Create `backend/app/store/migrate.py`:

```python
"""一次性迁移：把 config.yaml 的 providers 与 DB 的 oauth_credentials 导入 model_providers.yaml。

幂等：model_providers.yaml 已存在则整体跳过。用原生 sqlite3 读 oauth，不依赖 ORM
（OAuthCredential 模型将被删除）。
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import yaml

from app.config import ProviderCreds
from app.store import providers_store as ps
from app.store.oauth_models import OAuthData

log = logging.getLogger("nv.migrate")

_OAUTH_COLS = ("access_token", "refresh_token", "id_token", "account_id",
               "expires_at", "plan_type", "account_email", "last_refresh")


def _read_oauth_from_sqlite(sqlite_path: Path) -> OAuthData | None:
    if not sqlite_path.exists():
        return None
    try:
        conn = sqlite3.connect(sqlite_path)
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM oauth_credentials WHERE provider = 'openai' LIMIT 1")
        row = cur.fetchone()
        conn.close()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    keys = row.keys()
    return OAuthData(**{c: (row[c] or "") for c in _OAUTH_COLS if c in keys})


def migrate_providers_to_yaml(*, config_path: Path, sqlite_path: Path) -> None:
    if ps.MODEL_PROVIDERS_PATH.exists():
        return  # 幂等：已迁移
    raw_cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    raw_providers = (raw_cfg or {}).get("providers", {}) or {}
    creds = {name: ProviderCreds(**{k: v for k, v in (slot or {}).items() if k != "oauth"})
             for name, slot in raw_providers.items()}
    ps.save_providers(creds)
    oauth = _read_oauth_from_sqlite(sqlite_path)
    if oauth and oauth.access_token:
        ps.save_oauth("openai", oauth)
    log.info("Migrated %d providers + oauth=%s → %s",
             len(creds), bool(oauth and oauth.access_token), ps.MODEL_PROVIDERS_PATH)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_migrate_providers.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 在 lifespan 调用迁移**

在 `backend/app/main.py` 的 `lifespan`（39-47 行）里，`Base.metadata.create_all` **之前**插入迁移（迁移要读旧 oauth 表，须在建表/可能改表前；但 create_all 不会删旧表，顺序上放 create_all 前后均可，放前更稳妥）。改为：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_global_logger()
    get_settings().ensure_data_dirs()
    factory = get_session_factory()
    _run_storage_migrations()
    Base.metadata.create_all(bind=factory.kw["bind"])
    _ensure_pipeline_run_columns(factory.kw["bind"])
    seed_default_admin(factory)
    yield
```

并在 `main.py` 顶部 `_ensure_pipeline_run_columns` 函数上方新增：

```python
def _sqlite_path_from_url(url: str) -> Path:
    """从 sqlite URL 解析出文件路径（仅 sqlite 支持文件迁移）。"""
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return Path("")
    raw = url[len(prefix):]
    p = Path(raw)
    return p if p.is_absolute() else (Path(__file__).resolve().parents[1] / raw).resolve()


def _run_storage_migrations() -> None:
    from app.config import CONFIG_PATH, get_settings, reload_settings
    from app.store.migrate import migrate_providers_to_yaml
    migrate_providers_to_yaml(
        config_path=CONFIG_PATH,
        sqlite_path=_sqlite_path_from_url(get_settings().infra.database_url),
    )
    reload_settings()  # 迁移可能新建 model_providers.yaml，清缓存让 providers 重新从 store 注入
```

> 注 1：`infra.database_url` 缺省 `sqlite:///../data/news_videos.db`，相对 `backend/` 解析。`parents[1]` = `backend/`。
> 注 2：lifespan 在 `_run_storage_migrations()` 之前已 `get_settings()`（缓存了 store 为空时的默认 providers），故迁移末尾必须 `reload_settings()` 清缓存，否则迁移写入的 key 不会被本次进程读到。

- [ ] **Step 6: 全量回归**

Run: `cd backend && pytest -q`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add backend/app/store/migrate.py backend/app/main.py backend/tests/test_migrate_providers.py
git commit -m "feat(migrate): 启动时 providers+oauth 一次性迁入 model_providers.yaml"
```

---

## Task 7: 删除 OAuthCredential 模型（保留 OAuthLoginSession）

迁移已不再依赖 ORM 的 `OAuthCredential`。删除该模型及其测试，保留 `OAuthLoginSession`。**删模型 + 删 import 同一提交**，避免启动 ImportError。

**Files:**
- Modify: `backend/app/models/oauth_credential.py`（删 `OAuthCredential` 类）
- Modify: `backend/app/models/__init__.py`（删 import）
- Modify: `backend/app/api/openai_oauth.py`（确认 import 已收敛，Task 5 已改）
- Delete/Modify: `backend/tests/test_oauth_credential_model.py`

- [ ] **Step 1: 查 OAuthCredential 残余引用**

Run: `cd backend && grep -rn "OAuthCredential" app/ tests/`
Expected: 仅 `models/oauth_credential.py` 定义、`models/__init__.py` import、`tests/test_oauth_credential_model.py`（Task 5 已清 oauth 源码与 api 引用）

- [ ] **Step 2: 删模型类**

把 `backend/app/models/oauth_credential.py` 的 `OAuthCredential` 类（9-22 行）整段删除，保留文件顶部 import 与 `OAuthLoginSession` 类。删后确认 `from sqlalchemy import DateTime` 等 import 仍被 `OAuthLoginSession` 用到；未用到的 import（如 `DateTime`）一并删除。

- [ ] **Step 3: 删 models/__init__.py 的 import**

在 `backend/app/models/__init__.py` 删除 `OAuthCredential` 的 import 与 `__all__` 条目（若有），保留 `OAuthLoginSession`。

Run 验证：`cd backend && grep -n "OAuth" app/models/__init__.py`
Expected: 只剩 `OAuthLoginSession`

- [ ] **Step 4: 删/改模型测试**

删除 `backend/tests/test_oauth_credential_model.py`（它测的是已删模型）：

```bash
git rm backend/tests/test_oauth_credential_model.py
```

- [ ] **Step 5: 启动 + 全量回归**

Run: `cd backend && python -c "import app.main" && pytest -q`
Expected: import 无错；pytest PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/models/oauth_credential.py backend/app/models/__init__.py
git commit -m "refactor(models): 删除 OAuthCredential（token 已迁文件），保留 OAuthLoginSession"
```

---

## Task 8: 瘦身 config.yaml + 模板

把仓库根 `config.yaml` 的 `providers` 块整段删除（已迁 model_providers.yaml），并删除废弃的 `claude` provider（Anthropic 早已移除）。同步 `config.yaml.example` 并新增 `model_providers.yaml.example`。

> ⚠️ `config.yaml` 含真实密钥，**编辑时只删 providers/claude 结构，不要把任何 key 写进示例或提交日志**。

**Files:**
- Modify: 仓库根 `config.yaml`
- Modify: 仓库根 `config.yaml.example`
- Create: 仓库根 `model_providers.yaml.example`

- [ ] **Step 1: 删 config.yaml 的 providers 块**

编辑仓库根 `config.yaml`：删除从 `providers:`（第 7 行）到 `collectors:`（第 74 行）之前的整段 `providers` 子树（含其中废弃的 `claude`、以及 openai/dashscope/edge-tts）。保留 `infra`/`storage`/`collectors`/`youtube`/`pipeline`/`video`/`comfyui`/`prompts`。

- [ ] **Step 2: 启动验证迁移生成 model_providers.yaml**

> 用户自管后端，不在此重启。改为离线验证迁移函数对当前真实文件可跑通（dry 检查路径解析），不写真文件：

Run: `cd backend && python -c "from app.store.migrate import _read_oauth_from_sqlite; from app.config import CONFIG_PATH; print('config exists:', CONFIG_PATH.exists())"`
Expected: 打印 `config exists: True`，无异常

> 实际 `model_providers.yaml` 会在用户下次启动后端时由 lifespan 迁移自动生成。

- [ ] **Step 3: 同步 config.yaml.example**

编辑仓库根 `config.yaml.example`：删除其 `providers` 块与 `claude`；在文件顶部加注释：

```yaml
# 供应商凭证（providers）已迁至 model_providers.yaml（见 model_providers.yaml.example）
```

- [ ] **Step 4: 新建 model_providers.yaml.example**

Create 仓库根 `model_providers.yaml.example`:

```yaml
# 模型供应商凭证（从 config.yaml 迁出）。首次启动后端会自动从旧 config.yaml + DB 生成 model_providers.yaml。
# 手动配置时复制本文件为 model_providers.yaml 并填入 api_key。
providers:
  openai:
    base_url: https://api.openai.com/v1
    api_key: ''
    auth_mode: api_key            # api_key | subscription（subscription 走 OAuth 订阅登录）
    max_output_tokens: 65535
    models:
      text: [gpt-5.5, gpt-5.5-pro, gpt-5]
      image: [gpt-image-2, gpt-image-1.5, gpt-image-1]
      vision: [gpt-5.5, gpt-5, gpt-4o]
      tts: [gpt-4o-mini-tts, tts-1-hd, tts-1]
    # 订阅模式登录后自动写入：
    # oauth: {access_token: '', refresh_token: '', expires_at: '', account_id: '', plan_type: '', account_email: ''}
  dashscope:
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    api_key: ''
    auth_mode: api_key
    max_output_tokens: 65535
    models:
      text: [qwen3.7-max, qwen3.6-plus, qwen3.6-flash]
      image: [qwen-image-2.0, qwen-image-2.0-pro, wan2.7-image, wan2.7-image-pro]
      vision: [qwen3.6-plus, qwen3.6-flash]
      tts: [qwen3-tts-flash, cosyvoice-v3-flash]
  edge-tts:
    base_url: ''
    api_key: ''
    auth_mode: api_key
    max_output_tokens: 65535
    models: {text: [], image: [], vision: [], tts: []}
```

- [ ] **Step 5: 确认 model_providers.yaml 被 gitignore**

Run: `git check-ignore model_providers.yaml || echo "NOT IGNORED"`
Expected: 打印 `model_providers.yaml`（已忽略）。若打印 `NOT IGNORED`，在 `.gitignore` 追加一行 `model_providers.yaml` 并 `git add .gitignore`。

- [ ] **Step 6: 提交（仅模板与示例，不含真实 config.yaml/密钥）**

```bash
git add config.yaml.example model_providers.yaml.example .gitignore
git commit -m "chore(config): config.yaml 瘦身（providers 迁出 + 删废弃 claude）+ 模板"
```

> 注：仓库根真实 `config.yaml` 通常已被 gitignore（含密钥），其 providers 块删除属本地改动、不进版本库。若 `config.yaml` 已被跟踪，需先 `git rm --cached config.yaml` 并加入 .gitignore（本步骤前与用户确认）。

---

## Self-Review（写完计划的自检结果）

- **Spec 覆盖**：本 Plan 1 覆盖 spec 的「存储层 `_io`/`providers_store`」「OAuth 文件版（全函数去 db + 回调线程 store_tokens）」「model_providers.yaml 结构（providers + 内嵌 oauth）」「config.yaml 瘦身删 claude」「一次性迁移（原生 sqlite3 读 oauth）」「删 OAuthCredential 保留 OAuthLoginSession」。collectors/youtube 迁移与 sources/targets/前端 slug 属 Plan 2/3，本计划不触及（已在 spec 标注分阶段）。
- **设置页 B2**：通过 `get_settings()/save_settings()` 路由 providers 到 store 实现「设置页零改动仍可用」，比 spec 的「新增 /api/providers + 改 Settings.tsx」更省、风险更低；满足同一需求（providers 编辑保存可用）。此为实现层优化，已在计划 Architecture 注明。
- **并发**：三条写 model_providers.yaml 路径（save_settings 写 providers / 回调线程 store_tokens / 刷新 save_oauth）均经 `_io.file_lock` 串行；`save_providers` 合并保留 oauth 不互相覆盖（test_save_providers_preserves_oauth 覆盖）。
- **类型一致**：`OAuthData`、`ProviderCreds`、`MODEL_PROVIDERS_PATH`、各 store 函数名在 Task 1-6 间一致；`get_valid_access_token()`/`subscription_creds()`/`get_status()`/`logout()` 去 db 后调用方（providers、api）签名同步（Task 5 Step 6-7）。
- **占位符扫描**：无 TBD/TODO；每个代码步骤含完整代码。
```
