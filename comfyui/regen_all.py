#!/usr/bin/env python3
"""串行重生成所有工作流，保留全部产物到 comfyui/samples/，并写结果日志。
单任务串行（每个 validate.py 等自己跑完才下一个），避免显存/队列争抢。"""
import subprocess, sys, os, glob, time, shutil

SAMPLES = "comfyui/samples"
os.makedirs(SAMPLES, exist_ok=True)

NEG_EN = "blurry, ugly, deformed, low quality, watermark"
NEG_ZH = "色调艳丽，过曝，静态，细节模糊不清，字幕，画面扭曲，低质量"
ANCHOR = "You are a helpful assistant. <Prompt Start> professional news anchor, Asian female reporter at a modern television news desk, formal business suit, studio lighting, photorealistic, sharp focus"

# (name, api, {placeholder overrides})
JOBS = [
    ("z_image_t2i",            "z_image_t2i.api.json",            dict(POSITIVE_PROMPT=ANCHOR, NEGATIVE_PROMPT=NEG_EN, SEED=42, WIDTH=1024, HEIGHT=1024)),
    ("z_image_t2i_hq",         "z_image_t2i_hq.api.json",         dict(POSITIVE_PROMPT=ANCHOR, NEGATIVE_PROMPT=NEG_EN, SEED=123, WIDTH=1024, HEIGHT=1024)),
    ("qwen_image_t2i",         "qwen_image_t2i.api.json",         dict(POSITIVE_PROMPT="a news anchor in a broadcast studio with breaking-news graphics on screen, photorealistic, high detail", NEGATIVE_PROMPT=NEG_ZH, SEED=42, WIDTH=1024, HEIGHT=1024)),
    ("qwen_image_t2i_cn_poster","qwen_image_t2i_cn_poster.api.json",dict(POSITIVE_PROMPT='电视新闻横版海报，红蓝配色，醒目大标题"今日要闻"，下方副标题"科技前沿"，专业排版，高清', NEGATIVE_PROMPT=NEG_ZH, SEED=88, WIDTH=1664, HEIGHT=928)),
    ("wan22_5b_t2v",           "wan22_5b_t2v.api.json",           dict(POSITIVE_PROMPT="a news reporter speaking to camera on a busy city street, gentle camera push-in, daytime, cinematic", NEGATIVE_PROMPT=NEG_ZH, SEED=42, WIDTH=704, HEIGHT=480, LENGTH=41)),
    ("wan22_5b_i2v",           "wan22_5b_i2v.api.json",           dict(POSITIVE_PROMPT="the reporter in the photo starts talking, subtle natural motion, gentle camera movement", NEGATIVE_PROMPT=NEG_ZH, SEED=42, WIDTH=704, HEIGHT=480, LENGTH=41, INPUT_IMAGE="wan_i2v_test.png")),
    ("wan22_14b_t2v",          "wan22_14b_t2v.api.json",          dict(POSITIVE_PROMPT="a news reporter speaking to camera on a busy city street, gentle camera push-in, daytime, cinematic", NEGATIVE_PROMPT=NEG_ZH, SEED=42, WIDTH=704, HEIGHT=480, LENGTH=41)),
    ("wan22_14b_t2v_lightx2v", "wan22_14b_t2v_lightx2v.api.json", dict(POSITIVE_PROMPT="a news reporter speaking to camera on a busy city street, gentle camera push-in, daytime, cinematic", NEGATIVE_PROMPT=NEG_ZH, SEED=42, WIDTH=704, HEIGHT=480, LENGTH=41)),
    ("wan22_14b_i2v",          "wan22_14b_i2v.api.json",          dict(POSITIVE_PROMPT="the reporter in the photo starts talking, subtle natural motion, gentle camera movement", NEGATIVE_PROMPT=NEG_ZH, SEED=42, WIDTH=704, HEIGHT=480, LENGTH=41, INPUT_IMAGE="wan_i2v_test.png")),
    ("wan22_14b_i2v_lightx2v", "wan22_14b_i2v_lightx2v.api.json", dict(POSITIVE_PROMPT="the reporter in the photo starts talking, subtle natural motion, gentle camera movement", NEGATIVE_PROMPT=NEG_ZH, SEED=42, WIDTH=704, HEIGHT=480, LENGTH=41, INPUT_IMAGE="wan_i2v_test.png")),
    ("ltx23_t2v",              "ltx23_t2v.api.json",              dict(POSITIVE_PROMPT="a professional news anchor presenting in a modern television studio, cinematic lighting, detailed", NEGATIVE_PROMPT=NEG_EN, SEED=42, WIDTH=704, HEIGHT=480, LENGTH=49)),
    ("ltx23_i2v",              "ltx23_i2v.api.json",              dict(POSITIVE_PROMPT="the reporter in the photo starts speaking, subtle natural motion, gentle camera movement", NEGATIVE_PROMPT=NEG_EN, SEED=42, WIDTH=704, HEIGHT=480, LENGTH=49, INPUT_IMAGE="wan_i2v_test.png")),
]

results = []
log_path = os.path.join(SAMPLES, "REGEN_RESULTS.txt")
log = open(log_path, "w", encoding="utf-8")
def emit(s):
    print(s); log.write(s + "\n"); log.flush()

emit(f"==== 重生成全部工作流 @ {time.strftime('%Y-%m-%d %H:%M:%S')} ====\n")
for name, api, params in JOBS:
    apath = f"comfyui/workflows/api/{api}"
    if not os.path.exists(apath):
        emit(f"[SKIP] {name}: 缺 api 文件 {api}"); results.append((name, "SKIP", "", 0)); continue
    cmd = [sys.executable, "comfyui/validate.py", "--api", apath, "--save", SAMPLES, "--timeout", "900"]
    for k, v in params.items():
        cmd += ["--set", f"{k}={v}"]
    before = set(glob.glob(SAMPLES + "/*"))
    emit(f"\n---- {name} ----")
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    dt = time.time() - t0
    out = (p.stdout or "") + (p.stderr or "")
    ok = p.returncode == 0 and "SUCCESS" in out
    saved = ""
    if ok:
        after = set(glob.glob(SAMPLES + "/*"))
        new = [f for f in (after - before) if not f.endswith(".txt")]
        if new:
            srcf = max(new, key=os.path.getmtime)
            ext = os.path.splitext(srcf)[1]
            dst = os.path.join(SAMPLES, f"{name}{ext}")
            shutil.move(srcf, dst); saved = dst
    tail = out.strip().splitlines()[-1] if out.strip() else ""
    emit(f"  {'SUCCESS' if ok else 'FAIL'}  {dt:.1f}s  {saved}  | {tail}")
    results.append((name, "SUCCESS" if ok else "FAIL", saved, dt))

emit("\n==== 汇总 ====")
for name, st, saved, dt in results:
    emit(f"  {st:8} {dt:6.1f}s  {name}  {os.path.basename(saved) if saved else ''}")
ok_n = sum(1 for _,s,_,_ in results if s=="SUCCESS")
emit(f"\n成功 {ok_n}/{len(results)}。产物在 {SAMPLES}/（未清理）。日志：{log_path}")
log.close()
