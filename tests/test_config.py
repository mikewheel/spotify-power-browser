import application.config as config


def test_env_bool_truthy_values(monkeypatch):
    for v in ("true", "TRUE", "1", "yes", "on"):
        monkeypatch.setenv("SPB_TEST_FLAG", v)
        assert config._env_bool("SPB_TEST_FLAG", False) is True


def test_env_bool_falsy_and_garbage_values(monkeypatch):
    for v in ("false", "0", "no", "off", "nonsense"):
        monkeypatch.setenv("SPB_TEST_FLAG", v)
        assert config._env_bool("SPB_TEST_FLAG", True) is False


def test_env_bool_unset_returns_default(monkeypatch):
    monkeypatch.delenv("SPB_TEST_FLAG", raising=False)
    assert config._env_bool("SPB_TEST_FLAG", True) is True
    assert config._env_bool("SPB_TEST_FLAG", False) is False


def test_shipped_flag_defaults():
    # Dedup on, batch off, no reset -- the safe shipped defaults.
    assert config.CRAWLED_URL_DEDUP is True
    assert config.USE_BATCH_ENDPOINTS is False
    assert config.RESET_CRAWL is False
