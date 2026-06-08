from app.store.oauth_models import OAuthData


def test_oauthdata_defaults_empty():
    d = OAuthData()
    assert d.access_token == "" and d.refresh_token == ""
    assert d.expires_at == "" and d.account_id == ""


def test_oauthdata_roundtrip_dict():
    d = OAuthData(access_token="a", refresh_token="r", expires_at="2026-06-07T00:00:00+00:00",
                  account_id="acc", plan_type="plus", account_email="x@y.z",
                  id_token="idt", last_refresh="2026-06-07T00:00:00+00:00")
    out = d.model_dump()
    assert OAuthData(**out) == d
