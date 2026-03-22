# -*- coding: utf-8 -*-
"""
债券收益率曲线分析平台 - FastAPI后端
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
import json
import os
import logging
from datetime import datetime

# 配置
PROJECT_DIR = r"C:\Users\Emma\聪明的小C\bond_curve_platform"
DATA_DIR = os.path.join(PROJECT_DIR, "data")
FRONTEND_DIR = os.path.join(PROJECT_DIR, "frontend")

# 日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 创建FastAPI应用
app = FastAPI(
    title="债券收益率曲线分析平台",
    version="1.0.0",
    description="债券收益率期限结构分析工具"
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 数据模型 ====================

class IssuerCurveResult(BaseModel):
    """发行人曲线结果"""
    issuer_name: str
    bond_type: str
    bond_count: int
    model_type: str
    r_squared: Optional[float] = None
    slope_total: Optional[float] = None
    tenor_min: Optional[float] = None  # 数据最小期限
    tenor_max: Optional[float] = None  # 数据最大期限
    yield_1y: Optional[float] = None
    yield_3y: Optional[float] = None
    yield_5y: Optional[float] = None
    yield_10y: Optional[float] = None
    bonds: Optional[List[dict]] = None  # 原始债券数据


class DateAnalysisResult(BaseModel):
    """日期分析结果"""
    date: str
    normal: List[IssuerCurveResult] = []
    perpetual: List[IssuerCurveResult] = []


class UpdateRequest(BaseModel):
    """更新请求"""
    date: Optional[str] = None


class UpdateResponse(BaseModel):
    """更新响应"""
    success: bool
    message: str
    date: Optional[str] = None
    total_bonds: Optional[int] = None
    total_issuers: Optional[int] = None


# ==================== API路由 ====================

@app.get("/")
async def root():
    """API根路径"""
    return {
        "name": "债券收益率曲线分析平台",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/api/dates")
async def get_available_dates():
    """获取已有数据的日期列表"""
    try:
        dates = []
        if os.path.exists(DATA_DIR):
            for filename in os.listdir(DATA_DIR):
                if filename.endswith(".json"):
                    date_str = filename.replace(".json", "")
                    dates.append(date_str)
        dates.sort(reverse=True)
        return {"dates": dates, "count": len(dates)}
    except Exception as e:
        logger.error(f"获取日期列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analysis/{date}", response_model=DateAnalysisResult)
async def get_analysis(date: str):
    """获取指定日期的分析结果"""
    try:
        file_path = os.path.join(DATA_DIR, f"{date}.json")
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"未找到 {date} 的数据")

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        normal_list = [IssuerCurveResult(**item) for item in data.get("normal", [])]
        perpetual_list = [IssuerCurveResult(**item) for item in data.get("perpetual", [])]

        return DateAnalysisResult(date=date, normal=normal_list, perpetual=perpetual_list)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取分析结果失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/update", response_model=UpdateResponse)
async def update_data(request: UpdateRequest):
    """触发数据更新"""
    try:
        import subprocess

        if request.date:
            cmd = ["python", os.path.join(PROJECT_DIR, "data_preprocess.py"), "--date", request.date]
        else:
            cmd = ["python", os.path.join(PROJECT_DIR, "data_preprocess.py"), "--latest"]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=600)

        if result.returncode == 0:
            output = result.stdout
            try:
                data = json.loads(output)
                return UpdateResponse(
                    success=data.get("success", False),
                    message="更新成功" if data.get("success") else data.get("error", "未知错误"),
                    date=data.get("date"),
                    total_bonds=data.get("total_bonds"),
                    total_issuers=data.get("total_issuers")
                )
            except:
                return UpdateResponse(success=True, message="更新完成")
        else:
            return UpdateResponse(success=False, message=f"更新失败: {result.stderr}")

    except subprocess.TimeoutExpired:
        return UpdateResponse(success=False, message="更新超时")
    except Exception as e:
        return UpdateResponse(success=False, message=str(e))


@app.get("/api/export/{date}")
async def export_excel(date: str):
    """导出Excel"""
    try:
        import pandas as pd

        file_path = os.path.join(DATA_DIR, f"{date}.json")
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"未找到 {date} 的数据")

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        output_path = os.path.join(DATA_DIR, f"收益率曲线分析_{date}.xlsx")

        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            if data.get("normal"):
                normal_df = pd.DataFrame(data["normal"])
                normal_df = normal_df.sort_values("slope_total", ascending=False)
                normal_df.to_excel(writer, sheet_name="普通债", index=False)

            if data.get("perpetual"):
                perpetual_df = pd.DataFrame(data["perpetual"])
                perpetual_df = perpetual_df.sort_values("slope_total", ascending=False)
                perpetual_df.to_excel(writer, sheet_name="永续债", index=False)

        return FileResponse(
            path=output_path,
            filename=f"收益率曲线分析_{date}.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/curve", response_class=HTMLResponse)
async def serve_curve_viewer():
    """服务期限结构曲线查询页面"""
    frontend_path = os.path.join(FRONTEND_DIR, "curve_viewer.html")
    if os.path.exists(frontend_path):
        with open(frontend_path, "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse(content="<h1>前端文件未找到</h1>", status_code=404)


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """服务前端页面"""
    frontend_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(frontend_path):
        with open(frontend_path, "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse(content="<h1>前端文件未找到</h1>", status_code=404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)