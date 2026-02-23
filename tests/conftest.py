# conftest.py
# 配置 pytest 失败时输出详细上下文：默认 --tb=short

def pytest_configure(config):
    if config.option.tbstyle == "auto":
        config.option.tbstyle = "short"
