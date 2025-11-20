"""主程序入口"""
import asyncio
from api import app

if __name__ == "__main__":
    print("启动AI聚合代理服务...")
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8003,
        log_level="info"
    )