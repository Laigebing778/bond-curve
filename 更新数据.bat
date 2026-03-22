@echo off
chcp 65001 >nul
echo ========================================
echo 债券收益率曲线分析平台 - 数据更新
echo ========================================
echo.

cd /d "C:\Users\Emma\聪明的小C\bond_curve_platform"

echo 请选择更新方式:
echo 1. 更新最新交易日
echo 2. 更新指定日期
echo 3. 批量更新日期范围
echo.

set /p choice="请输入选项 (1/2/3): "

if "%choice%"=="1" (
    echo.
    echo 正在更新最新交易日数据...
    python data_preprocess.py --latest
) else if "%choice%"=="2" (
    set /p date="请输入日期 (YYYY-MM-DD): "
    echo.
    echo 正在更新 %date% 数据...
    python data_preprocess.py --date %date%
) else if "%choice%"=="3" (
    set /p start="请输入开始日期 (YYYY-MM-DD): "
    set /p end="请输入结束日期 (YYYY-MM-DD): "
    echo.
    echo 正在批量更新 %start% 至 %end% 数据...
    python data_preprocess.py --start %start% --end %end%
) else (
    echo 无效选项
)

echo.
echo ========================================
echo 更新完成
echo ========================================
pause