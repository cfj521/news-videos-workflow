from app.services.compliance import ComplianceService


def test_keyword_filter_catches_sensitive():
    service = ComplianceService(sensitive_keywords=["暴力", "赌博"])
    result = service.check("这篇文章包含暴力内容", "普通标题")
    assert result.status == "blocked"
    assert "暴力" in result.matched_keywords


def test_keyword_filter_passes_clean():
    service = ComplianceService(sensitive_keywords=["暴力", "赌博"])
    result = service.check("这是一篇关于人工智能的文章", "AI 新突破")
    assert result.status == "passed"
    assert result.matched_keywords == []


def test_empty_keywords_passes_all():
    service = ComplianceService(sensitive_keywords=[])
    result = service.check("任何内容", "任何标题")
    assert result.status == "passed"


def test_title_also_checked():
    service = ComplianceService(sensitive_keywords=["赌博"])
    result = service.check("正文内容安全", "赌博网站推荐")
    assert result.status == "blocked"
