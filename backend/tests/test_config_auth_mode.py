from app.config import ProviderCreds, ProviderCfg


def test_provider_creds_default_auth_mode():
    assert ProviderCreds().auth_mode == "api_key"


def test_provider_creds_subscription():
    c = ProviderCreds(auth_mode="subscription")
    assert c.auth_mode == "subscription"


def test_provider_cfg_default_auth_mode():
    assert ProviderCfg().auth_mode == "api_key"
    assert ProviderCfg().account_id == ""


def test_provider_cfg_carries_account_id():
    # vision 透传载体需要带订阅信息
    cfg = ProviderCfg(provider="openai", auth_mode="subscription", account_id="acc-1")
    assert cfg.auth_mode == "subscription"
    assert cfg.account_id == "acc-1"
