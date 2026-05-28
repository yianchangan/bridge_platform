from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.memory_store import store
from app.routers import documents, assets, index_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时: 配置持久化存储并从磁盘恢复
    store.configure(settings.db_path)

    print(f"[启动] 存储路径: {settings.storage_path}")
    print(f"[启动] 持久化文件: {settings.db_path}")
    yield

    # 关闭时: 持久化
    store._persist()


app = FastAPI(
    title="桥梁施工方案智能数据整治平台",
    description="后端 API - 文档整理、拆分、审核入库",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS - 允许所有来源 (公开 API, 无 cookie 认证)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(documents.router)
app.include_router(assets.router)
app.include_router(index_router.router)


@app.get("/", tags=["健康检查"])
async def root():
    return {
        "service": "桥梁施工方案智能数据整治平台",
        "version": "1.0.0",
        "docs": "/docs",
    }
