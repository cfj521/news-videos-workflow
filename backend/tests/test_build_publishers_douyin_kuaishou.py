from app.providers.publisher import build_publishers
from app.providers.publisher.douyin import DouyinPublisher
from app.providers.publisher.kuaishou import KuaishouPublisher
from app.store.targets_store import TargetData


def test_build_douyin():
    # 账号无需配置字段；登录态标识 = 账号自身的 slug
    t = TargetData(slug="dy", name="抖音", platform="douyin", enabled=True, config={})
    pubs = build_publishers([t])
    assert len(pubs) == 1
    _, adapter = pubs[0]
    assert isinstance(adapter, DouyinPublisher)
    assert adapter._account == "dy"


def test_build_kuaishou():
    t = TargetData(slug="ks", name="快手", platform="kuaishou", enabled=True, config={})
    _, adapter = build_publishers([t])[0]
    assert isinstance(adapter, KuaishouPublisher)
    assert adapter._account == "ks"
