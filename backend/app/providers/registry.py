from typing import Any


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, dict[str, type]] = {}
        self._instances: dict[str, dict[str, Any]] = {}

    def register(self, category: str, name: str, provider_class: type) -> None:
        self._providers.setdefault(category, {})[name] = provider_class
        self._instances.setdefault(category, {}).pop(name, None)

    def get(self, category: str, name: str, **kwargs: Any) -> Any:
        if name in self._instances.get(category, {}):
            return self._instances[category][name]
        providers = self._providers.get(category, {})
        if name not in providers:
            available = list(providers.keys())
            raise KeyError(
                f"Provider '{name}' not found in category '{category}'. "
                f"Available: {available}"
            )
        instance = providers[name](**kwargs)
        self._instances.setdefault(category, {})[name] = instance
        return instance

    def list_providers(self, category: str) -> list[str]:
        return list(self._providers.get(category, {}).keys())
