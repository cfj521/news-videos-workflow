from app.store._slug import slugify, unique_slug


def test_slugify_basic():
    assert slugify("Hacker News") == "hacker_news"
    assert slugify("YouTube  Main!") == "youtube_main"
    assert slugify("  a--b  ") == "a_b"


def test_slugify_chinese_returns_empty():
    assert slugify("抖音官方") == ""


def test_unique_slug_no_collision():
    assert unique_slug("youtube", set(), "target") == "youtube"


def test_unique_slug_collision_appends_number():
    assert unique_slug("youtube", {"youtube"}, "target") == "youtube_1"
    assert unique_slug("youtube", {"youtube", "youtube_1"}, "target") == "youtube_2"


def test_unique_slug_empty_base_uses_fallback():
    assert unique_slug("", set(), "douyin") == "douyin"
    assert unique_slug("", {"douyin"}, "douyin") == "douyin_1"
