#!/usr/bin/env python3
"""向运行中的 ComfyUI (127.0.0.1:8188) 提交一个 API 格式工作流并验证能否成功生成。

用法：
  python comfyui/validate.py --api comfyui/workflows/api/z_image_t2i.api.json \
      --set POSITIVE_PROMPT="a news anchor in a studio, cinematic" \
      --set NEGATIVE_PROMPT="blurry, ugly" --set SEED=42 --set WIDTH=768 --set HEIGHT=768 \
      --save comfyui/samples/

把 api 文件里的 __KEY__ 占位符替换为 --set KEY=值（数字自动转 int/float）。
成功打印 SUCCESS + 输出文件名；失败打印 ERROR + 节点报错。退出码 0=成功 1=失败。
"""
import argparse, copy, json, sys, time, uuid, urllib.request, urllib.error, os

HOST = "http://127.0.0.1:8188"


def _coerce(v: str):
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return v


def _fill(obj, repl: dict):
    if isinstance(obj, dict):
        return {k: _fill(v, repl) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fill(v, repl) for v in obj]
    if isinstance(obj, str) and obj.startswith("__") and obj.endswith("__"):
        key = obj[2:-2]
        return repl.get(key, obj)
    return obj


def _post(path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(HOST + path, data=data,
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def _get(path):
    return json.loads(urllib.request.urlopen(HOST + path, timeout=30).read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True, help="API 格式工作流 json")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VAL",
                    help="替换 __KEY__ 占位符；可多次")
    ap.add_argument("--save", default="", help="把首个输出文件下载到该目录")
    ap.add_argument("--timeout", type=int, default=600, help="等待生成秒数上限")
    args = ap.parse_args()

    repl = {}
    for kv in args.set:
        k, _, v = kv.partition("=")
        repl[k] = _coerce(v)

    prompt = _fill(copy.deepcopy(json.load(open(args.api, encoding="utf-8"))), repl)

    # 残留未替换的占位符 → 直接报错（避免发出非法类型）
    leftover = sorted({x for x in json.dumps(prompt).split('"') if x.startswith("__") and x.endswith("__")})
    if leftover:
        print(f"ERROR: 未替换的占位符: {leftover}", file=sys.stderr)
        return 1

    cid = uuid.uuid4().hex
    try:
        res = _post("/prompt", {"prompt": prompt, "client_id": cid})
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(f"ERROR: /prompt 被拒 ({e.code}):\n{body[:2000]}", file=sys.stderr)
        return 1
    pid = res.get("prompt_id")
    if not pid:
        print(f"ERROR: 无 prompt_id，返回={res}", file=sys.stderr)
        return 1
    print(f"queued prompt_id={pid}")

    t0 = time.time()
    while time.time() - t0 < args.timeout:
        hist = _get(f"/history/{pid}")
        if pid in hist:
            entry = hist[pid]
            status = entry.get("status", {})
            if status.get("status_str") == "error" or not status.get("completed", True) and status.get("status_str") == "error":
                msgs = status.get("messages", [])
                print(f"ERROR: 执行失败 status={status.get('status_str')}\n{json.dumps(msgs, ensure_ascii=False)[:2000]}", file=sys.stderr)
                return 1
            outputs = entry.get("outputs", {})
            files = []
            for node_id, out in outputs.items():
                for kind in ("images", "gifs", "videos", "audio"):
                    for f in out.get(kind, []):
                        files.append((kind, f.get("filename"), f.get("subfolder", ""), f.get("type", "output")))
            if not files:
                # completed but no media (e.g. only SaveWEBM disabled) — still a success signal if no error
                if status.get("status_str") == "success" or status.get("completed"):
                    print(f"SUCCESS (无媒体输出，status={status.get('status_str')})，用时 {time.time()-t0:.1f}s")
                    return 0
            else:
                print(f"SUCCESS: {len(files)} 个输出，用时 {time.time()-t0:.1f}s")
                for kind, fn, sub, typ in files:
                    print(f"   [{kind}] {sub+'/' if sub else ''}{fn}")
                if args.save and files:
                    os.makedirs(args.save, exist_ok=True)
                    kind, fn, sub, typ = files[0]
                    url = f"{HOST}/view?filename={urllib.parse.quote(fn)}&subfolder={urllib.parse.quote(sub)}&type={typ}"
                    dst = os.path.join(args.save, fn)
                    urllib.request.urlretrieve(url, dst)
                    print(f"   saved -> {dst}")
                return 0
        time.sleep(2)

    print(f"ERROR: 超时 {args.timeout}s 未完成 (prompt_id={pid})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    import urllib.parse  # noqa: needed for --save
    sys.exit(main())
