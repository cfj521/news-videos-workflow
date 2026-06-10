from app.providers.publisher import sau_runner as r


def test_classify_cookie_expired():
    msg = r.classify_upload_error("Douyin cookie is missing or expired: /x. Run `sau douyin login`...")
    assert "登录态失效" in msg


def test_classify_generic_passes_stderr_tail():
    msg = r.classify_upload_error("line1\nline2\nboom: selector not found")
    assert "boom: selector not found" in msg


def test_classify_empty_fallback():
    assert r.classify_upload_error("") == "发布失败"
