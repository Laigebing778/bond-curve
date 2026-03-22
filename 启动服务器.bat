@echo off
chcp 65001 >nul
echo ========================================
echo 债券收益率曲线分析平台 - 启动服务器
echo ========================================
echo.

cd /d "C:\Users\Emma\聪明的小C\bond_curve_platform"

echo 启动后端服务...
echo.
echo 服务地址: http://localhost:8000
echo 局域网访问: http://你的IP:8000
echo.
echo 按 Ctrl+C 停止服务
echo ========================================

python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

pause