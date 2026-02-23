"""冒烟测试：验证项目基本可用。新建项目后请替换为真实的关键路径测试。"""

import importlib


def test_main_module_importable() -> None:
    """src 包能被正常 import，证明项目结构和依赖没有破损。"""
    mod = importlib.import_module("src")
    assert mod is not None
