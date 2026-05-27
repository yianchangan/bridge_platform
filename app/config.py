from __future__ import annotations

import os


class Settings:
    """应用配置"""

    # 项目根目录
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 存储路径
    storage_path: str = os.path.join(BASE_DIR, "storage", "doc_assets")

    # 持久化数据文件
    db_path: str = os.path.join(BASE_DIR, "storage", "store.json")

    # API 前缀
    api_prefix: str = "/api"

    # 主机与端口
    host: str = "0.0.0.0"
    port: int = 8000

    # 调试模式
    debug: bool = True

    def __init__(self):
        os.makedirs(self.storage_path, exist_ok=True)


settings = Settings()
