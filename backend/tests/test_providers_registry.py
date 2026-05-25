import pytest
from app.providers.base import CollectorProvider, RawArticleData
from app.providers.registry import ProviderRegistry


class FakeCollector(CollectorProvider):
    async def collect(self, source_config, time_range, max_items=30):
        return []


def test_register_and_get():
    registry = ProviderRegistry()
    registry.register("collector", "fake", FakeCollector)
    provider = registry.get("collector", "fake")
    assert isinstance(provider, FakeCollector)


def test_get_unknown_raises():
    registry = ProviderRegistry()
    with pytest.raises(KeyError):
        registry.get("collector", "nonexistent")


def test_register_duplicate_overwrites():
    registry = ProviderRegistry()
    registry.register("collector", "fake", FakeCollector)
    registry.register("collector", "fake", FakeCollector)
    provider = registry.get("collector", "fake")
    assert isinstance(provider, FakeCollector)


def test_list_providers():
    registry = ProviderRegistry()
    registry.register("collector", "rss", FakeCollector)
    registry.register("collector", "hackernews", FakeCollector)
    providers = registry.list_providers("collector")
    assert set(providers) == {"rss", "hackernews"}


def test_list_empty_category():
    registry = ProviderRegistry()
    assert registry.list_providers("nonexistent") == []
