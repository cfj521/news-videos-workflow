from app.providers.publisher import build_publishers
from app.providers.publisher.douyin import DouyinPublisher
from app.providers.publisher.kuaishou import KuaishouPublisher
from app.store.targets_store import TargetData


def test_build_douyin():
    # account 为前端自动生成的 UUID，存在 config.account
    t = TargetData(slug="dy", name="抖音", platform="douyin", enabled=True,
                   config={"account": "uuid-aaa"})
    pubs = build_publishers([t])
    assert len(pubs) == 1
    _, adapter = pubs[0]
    assert isinstance(adapter, DouyinPublisher)
    assert adapter._account == "uuid-aaa"


def test_build_kuaishou():
    t = TargetData(slug="ks", name="快手", platform="kuaishou", enabled=True,
                   config={"account": "uuid-bbb"})
    _, adapter = build_publishers([t])[0]
    assert isinstance(adapter, KuaishouPublisher)
    assert adapter._account == "uuid-bbb"
