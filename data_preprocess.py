# -*- coding: utf-8 -*-
"""
债券收益率曲线分析平台 - 数据预处理模块 v2

功能：
1. 读取Excel债券池，筛选合格信用债
2. 调用Choice API获取中债估值收益率和特殊剩余期限
3. 按发行人分组拟合期限结构曲线
4. 支持增量更新（只处理缺失日期）

作者：Emma
日期：2026-03-06
"""

import sys
import os
import json
import time
import re
import logging
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.optimize import minimize

# 添加Choice API路径
CHOICE_API_PATH = r"D:\choice\EMQuantAPI_Python\EMQuantAPI_Python\python3"
if CHOICE_API_PATH not in sys.path:
    sys.path.insert(0, CHOICE_API_PATH)

# 配置日志
PROJECT_DIR = r"C:\Users\Emma\聪明的小C\bond_curve_platform"
DATA_DIR = os.path.join(PROJECT_DIR, "data")
LOG_FILE = os.path.join(PROJECT_DIR, "data_preprocess.log")

# 确保目录存在
os.makedirs(DATA_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8", mode='a')
    ]
)
logger = logging.getLogger(__name__)

# 项目路径配置
INPUT_FILE = r"C:\Users\Emma\桌面\存续信用债0322.xlsx"


# ==================== 债券筛选配置 ====================

# 需要剔除的债券类型（Wind二级分类）
EXCLUDED_BOND_TYPES = [
    "金监总局主管ABS",
    "政府支持机构债",
    "交易商协会ABN",
    "国际开发机构债",
    "可转债",
    "证监会主管ABS",
    "同业存单",
    "可交换债",
    "项目收益票据",
    "外国政府类机构债",
]

# 保留的信用债类型
CREDIT_BOND_TYPES = [
    "中期票据",
    "私募公司债",
    "公募公司债",
    "企业债",
    "定向工具",
    "超短期融资券",
    "商业银行债",
    "短期融资券",
    "证券公司短期融资券",
    "保险公司债",
    "融资租赁公司债",
    "其他金融机构债",
    "资产管理公司债",
]

# 永续债关键词（备用，优先使用Choice API的PERPETUAL指标）
PERPETUAL_KEYWORDS = ["永续", "可续期"]


# ==================== 债券筛选器 ====================

class BondFilter:
    """债券筛选器"""

    def filter_bonds(self, df: pd.DataFrame) -> pd.DataFrame:
        """筛选合格信用债"""
        original_count = len(df)
        logger.info(f"原始债券数量: {original_count}")

        # 1. 剔除指定债券类型
        df = self._exclude_bond_types(df)
        logger.info(f"剔除指定类型后: {len(df)}")

        # 2. 剔除有担保债
        df = self._exclude_guaranteed(df)
        logger.info(f"剔除有担保债后: {len(df)}")

        # 3. 保留信用债类型
        df = self._keep_credit_bonds(df)
        logger.info(f"保留信用债后: {len(df)}")

        return df

    def _exclude_bond_types(self, df: pd.DataFrame) -> pd.DataFrame:
        """剔除指定债券类型"""
        if "Wind债券二级分类(2025)" not in df.columns:
            return df
        mask = pd.Series([True] * len(df), index=df.index)
        for bond_type in EXCLUDED_BOND_TYPES:
            mask &= ~df["Wind债券二级分类(2025)"].fillna("").str.contains(
                bond_type, case=False, na=False
            )
        return df[mask]

    def _exclude_guaranteed(self, df: pd.DataFrame) -> pd.DataFrame:
        """剔除有担保债"""
        if "担保人" not in df.columns:
            return df
        return df[df["担保人"].isna()]

    def _keep_credit_bonds(self, df: pd.DataFrame) -> pd.DataFrame:
        """保留信用债类型"""
        if "Wind债券二级分类(2025)" not in df.columns:
            return df
        mask = pd.Series([False] * len(df), index=df.index)
        for bond_type in CREDIT_BOND_TYPES:
            mask |= df["Wind债券二级分类(2025)"].fillna("").str.contains(
                bond_type, case=False, na=False
            )
        return df[mask]

    @staticmethod
    def is_perpetual(bond_name: str) -> bool:
        """判断是否为永续债"""
        for keyword in PERPETUAL_KEYWORDS:
            if keyword in bond_name:
                return True
        return False


# ==================== Choice API 数据获取 ====================

class ChoiceDataFetcher:
    """Choice API数据获取器"""

    def __init__(self):
        self.choice = None
        self.logged_in = False

    def login(self) -> bool:
        """登录Choice API"""
        try:
            from EmQuantAPI import c
            self.choice = c
            result = c.start("ForceLogin=1")
            if result.ErrorCode == 0:
                self.logged_in = True
                logger.info("Choice API登录成功")
                return True
            else:
                logger.error(f"Choice API登录失败: {result.ErrorMsg}")
                return False
        except Exception as e:
            logger.error(f"Choice API登录异常: {e}")
            return False

    def logout(self):
        """退出登录"""
        if self.choice and self.logged_in:
            try:
                self.choice.stop()
                logger.info("Choice API已退出")
            except:
                pass

    def get_trading_days(self, start_date: str, end_date: str) -> List[str]:
        """获取交易日列表"""
        if not self.logged_in:
            return []
        result = self.choice.tradedates(start_date, end_date, "Market=CNSESH")
        if result.ErrorCode == 0:
            return result.Data
        else:
            logger.error(f"获取交易日失败: {result.ErrorMsg}")
            return []

    def get_bond_valuation(self, bond_codes: List[str], query_date: str) -> Dict:
        """
        批量获取债券中债估值数据

        Args:
            bond_codes: 债券代码列表
            query_date: 查询日期 (YYYY-MM-DD)

        Returns:
            {bond_code: {remain_years, ytm, is_perpetual}}
        """
        if not self.logged_in or not bond_codes:
            return {}

        results = {}
        batch_size = 500  # 每批500个
        total_batches = (len(bond_codes) + batch_size - 1) // batch_size
        request_interval = 2.0  # 每次请求间隔2秒，避免限流
        rate_limit_hits = 0  # 限流计数

        for i in range(0, len(bond_codes), batch_size):
            batch_codes = bond_codes[i:i + batch_size]
            codes_str = ",".join(batch_codes)

            batch_num = i // batch_size + 1
            logger.info(f"获取批次 {batch_num}/{total_batches}，共 {len(batch_codes)} 只债券")

            try:
                # 使用正确的Choice API指标
                indicators = "YIELDCNBD,YEARWEIGHTEPTM,PERPETUALORNOT"
                options = f"EndDate={query_date},CredType=3,TDATE={query_date}"

                result = self.choice.css(codes_str, indicators, options)

                # 检测限流
                if result.ErrorCode != 0:
                    error_msg = str(result.ErrorMsg)
                    if "login count up to limit" in error_msg or "limit" in error_msg.lower():
                        rate_limit_hits += 1
                        logger.warning(f"检测到API限流 (第{rate_limit_hits}次)，暂停60秒...")
                        time.sleep(60)
                        # 重试当前批次
                        result = self.choice.css(codes_str, indicators, f"Ispandas=0,{options}")
                        if result.ErrorCode != 0:
                            logger.warning(f"批次 {batch_num} 获取失败: {result.ErrorMsg}")
                            # 再次暂停后继续
                            time.sleep(30)
                            continue
                    else:
                        logger.warning(f"批次 {batch_num} 获取失败: {result.ErrorMsg}")
                        # 尝试不使用pandas
                        result = self.choice.css(codes_str, indicators, f"Ispandas=0,{options}")

                if result.ErrorCode == 0 and result.Data is not None:
                    # 解析数据
                    if isinstance(result.Data, dict):
                        for code, values in result.Data.items():
                            if isinstance(values, list) and len(values) >= 3:
                                ytm = values[0]
                                remain_years_raw = values[1]
                                is_perpetual_flag = values[2]
                                self._process_bond_values(code, ytm, remain_years_raw, is_perpetual_flag, results)
                            elif isinstance(values, list) and len(values) >= 2:
                                ytm = values[0]
                                remain_years_raw = values[1]
                                self._process_bond_values(code, ytm, remain_years_raw, None, results)
                            elif isinstance(values, dict):
                                self._process_bond_data(code, values, results)
                    elif isinstance(result.Data, pd.DataFrame):
                        df = result.Data
                        for _, row in df.iterrows():
                            code = row.get("CODES", "")
                            if not code:
                                continue
                            self._process_bond_data(code, row, results)
                    elif isinstance(result.Data, list):
                        for item in result.Data:
                            if isinstance(item, dict):
                                code = item.get("CODES", item.get("CODE", ""))
                                self._process_bond_data(code, item, results)

                # 避免请求过快 - 增加间隔到2秒
                time.sleep(request_interval)

            except Exception as e:
                logger.error(f"批次 {batch_num} 获取异常: {e}")
                time.sleep(5)  # 异常后暂停5秒
                continue

        logger.info(f"成功获取 {len(results)} 只债券数据")
        return results

    def _process_bond_data(self, code: str, data, results: Dict):
        """处理单只债券数据（DataFrame或dict格式）"""
        if not code:
            return

        # 获取中债估值收益率
        ytm = data.get("YIELDCNBD")
        if ytm is not None and pd.notna(ytm):
            try:
                ytm = float(ytm)
            except:
                ytm = None
        else:
            ytm = None

        # 获取特殊剩余期限
        remain_years_raw = data.get("YEARWEIGHTEPTM")
        remain_years = self._parse_remain_years(remain_years_raw)

        # 获取永续债标志（Choice返回"是"或"否"）
        is_perpetual_flag = data.get("PERPETUALORNOT")
        is_perp = False
        if is_perpetual_flag is not None and pd.notna(is_perpetual_flag):
            flag_str = str(is_perpetual_flag).strip()
            is_perp = flag_str in ["是", "Yes", "1", "True", "true"]
        # 备用：通过债券名称判断
        if not is_perp:
            is_perp = BondFilter.is_perpetual(code.split(".")[0] if "." in code else code)

        if remain_years is not None and ytm is not None:
            results[code] = {
                "remain_years": remain_years,
                "ytm": ytm,
                "is_perpetual": is_perp,
            }

    def _process_bond_values(self, code: str, ytm, remain_years_raw, is_perpetual_flag, results: Dict):
        """处理列表格式的债券数据"""
        if not code:
            return

        # 处理收益率
        if ytm is not None and pd.notna(ytm):
            try:
                ytm = float(ytm)
            except:
                ytm = None
        else:
            ytm = None

        # 处理剩余期限
        remain_years = self._parse_remain_years(remain_years_raw)

        # 判断是否为永续债（Choice返回"是"或"否"）
        is_perp = False
        if is_perpetual_flag is not None and pd.notna(is_perpetual_flag):
            flag_str = str(is_perpetual_flag).strip()
            is_perp = flag_str in ["是", "Yes", "1", "True", "true"]
        # 备用：通过债券名称判断
        if not is_perp:
            is_perp = BondFilter.is_perpetual(code.split(".")[0] if "." in code else code)

        if remain_years is not None and ytm is not None:
            results[code] = {
                "remain_years": remain_years,
                "ytm": ytm,
                "is_perpetual": is_perp,
            }

    def _parse_remain_years(self, remain_years_raw) -> Optional[float]:
        """解析特殊剩余期限"""
        if remain_years_raw is None or pd.isna(remain_years_raw):
            return None
        try:
            remain_str = str(remain_years_raw)
            # 特殊剩余期限可能是 "3+2" 格式，只取第一个"+"前的数字
            if "+" in remain_str:
                remain_str = remain_str.split("+")[0]
            return float(remain_str)
        except:
            return None


# ==================== 曲线拟合模块 ====================

class NelsonSiegelFitter:
    """Nelson-Siegel模型拟合器"""

    BOUNDS = [(-20, 20), (-20, 20), (-20, 20), (0.1, 10)]

    def ns_function(self, t: np.ndarray, beta0, beta1, beta2, tau) -> np.ndarray:
        """Nelson-Siegel函数"""
        t = np.atleast_1d(t)
        t = np.where(t == 0, 1e-10, t)
        exp_term = np.exp(-t / tau)
        factor1 = (1 - exp_term) / (t / tau)
        factor2 = factor1 - exp_term
        return beta0 + beta1 * factor1 + beta2 * factor2

    def fit(self, x: np.ndarray, y: np.ndarray) -> Tuple[Dict, float]:
        """拟合NS模型"""
        sort_idx = np.argsort(x)
        x_sorted, y_sorted = x[sort_idx], y[sort_idx]
        y_mean = np.mean(y_sorted)
        initial_params = [y_mean, 0, 0, 1.0]

        def objective(params):
            y_pred = self.ns_function(x_sorted, *params)
            return np.sum((y_sorted - y_pred) ** 2)

        try:
            result = minimize(objective, initial_params, method='L-BFGS-B',
                            bounds=self.BOUNDS, options={'maxiter': 1000})
            params = {'beta0': result.x[0], 'beta1': result.x[1],
                     'beta2': result.x[2], 'tau': result.x[3]}
            y_pred = self.ns_function(x_sorted, **params)
            ss_res = np.sum((y_sorted - y_pred) ** 2)
            ss_tot = np.sum((y_sorted - np.mean(y_sorted)) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
            return params, r_squared
        except:
            return {}, 0


class HermiteFitter:
    """Hermite插值拟合器"""
    def fit(self, x: np.ndarray, y: np.ndarray) -> Tuple[Optional[callable], float]:
        sort_idx = np.argsort(x)
        x_sorted, y_sorted = x[sort_idx], y[sort_idx]
        unique_mask = np.concatenate([[True], np.diff(x_sorted) > 1e-6])
        x_unique, y_unique = x_sorted[unique_mask], y_sorted[unique_mask]

        # 需要至少2个点才能插值
        if len(x_unique) < 2:
            return None, 0.0

        interpolator = PchipInterpolator(x_unique, y_unique)
        y_pred = interpolator(x_unique)
        ss_res = np.sum((y_unique - y_pred) ** 2)
        ss_tot = np.sum((y_unique - np.mean(y_unique)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        return interpolator, r_squared


class CurveFittingService:
    """曲线拟合服务"""
    def __init__(self):
        self.ns_fitter = NelsonSiegelFitter()
        self.hermite_fitter = HermiteFitter()
        self.min_bonds_for_ns = 5

    def fit_curve(self, bonds: List[Dict]) -> Optional[Dict]:
        if len(bonds) < 2:
            return None
        valid_data = [(b["remain_years"], b["ytm"]) for b in bonds
                     if b.get("remain_years") is not None and b.get("ytm") is not None]

        # 过滤异常收益率 (0-50% 范围内)
        valid_data = [(r, y) for r, y in valid_data if 0 < y < 50]

        # 过滤异常剩余期限 (0-30年 范围内)
        valid_data = [(r, y) for r, y in valid_data if 0 < r <= 30]

        if len(valid_data) < 2:
            return None
        x, y = np.array([d[0] for d in valid_data]), np.array([d[1] for d in valid_data])

        if len(valid_data) >= self.min_bonds_for_ns:
            model_type = "Nelson-Siegel"
            params, r_squared = self.ns_fitter.fit(x, y)
            if params:
                # NS模型成功
                # 使用数据范围内的斜率（而非外推）
                x_min_data, x_max_data = float(min(x)), float(max(x))
                y_min = self.ns_fitter.ns_function(x_min_data, **params)[0]
                y_max = self.ns_fitter.ns_function(x_max_data, **params)[0]
                slope_total = (y_max - y_min) / (x_max_data - x_min_data) * 100 if x_max_data > x_min_data else 0
            else:
                # NS失败，尝试Hermite
                interpolator, r_squared = self.hermite_fitter.fit(x, y)
                if interpolator is None:
                    return None
                model_type = "Hermite"
                params = {}
                # 斜率只计算数据范围内的变化
                x_min_data, x_max_data = float(min(x)), float(max(x))
                slope_total = (float(interpolator(x_max_data)) - float(interpolator(x_min_data))) / (x_max_data - x_min_data) * 100 if x_max_data > x_min_data else 0
        else:
            model_type = "Hermite"
            interpolator, r_squared = self.hermite_fitter.fit(x, y)
            if interpolator is None:
                return None
            params = {}
            # 斜率只计算数据范围内的变化
            x_min_data, x_max_data = float(min(x)), float(max(x))
            slope_total = (float(interpolator(x_max_data)) - float(interpolator(x_min_data))) / (x_max_data - x_min_data) * 100 if x_max_data > x_min_data else 0

        # 限制斜率在合理范围内 (-1000 到 1000 bp/年)
        slope_total = max(min(slope_total, 1000), -1000)

        # 获取实际数据范围
        x_min, x_max = float(min(x)), float(max(x))

        # 定义获取收益率的函数（只在数据范围内有效）
        def get_yield_at(tenor):
            """获取指定期限的收益率，仅对数据范围内的期限有效"""
            if model_type == "Nelson-Siegel":
                return float(self.ns_fitter.ns_function(tenor, **params)[0])
            else:
                return float(interpolator(tenor))

        # 关键期限收益率 - 只在数据范围内计算，超出范围返回None
        yield_results = {}
        for tenor, key in [(1, "yield_1y"), (3, "yield_3y"), (5, "yield_5y"), (10, "yield_10y")]:
            if x_min <= tenor <= x_max:
                y = get_yield_at(tenor)
                yield_results[key] = round(min(max(y, 0), 50), 4)
            else:
                yield_results[key] = None  # 超出数据范围，外推不可靠

        return {
            "model_type": model_type,
            "bond_count": len(valid_data),
            "r_squared": round(r_squared, 4),
            "slope_total": round(slope_total, 2),
            "tenor_min": round(x_min, 2),  # 数据最小期限
            "tenor_max": round(x_max, 2),  # 数据最大期限
            **yield_results,
        }


# ==================== 数据处理器 ====================

class DataProcessor:
    """数据处理器"""

    def __init__(self):
        self.filter = BondFilter()
        self.fetcher = ChoiceDataFetcher()
        self.curve_service = CurveFittingService()
        self._load_bond_pool()

    def _load_bond_pool(self):
        """加载债券池"""
        try:
            self.bond_pool_df = pd.read_excel(INPUT_FILE, engine='calamine')
            logger.info(f"加载债券池: {len(self.bond_pool_df)} 条")
        except Exception as e:
            logger.error(f"加载债券池失败: {e}")
            self.bond_pool_df = pd.DataFrame()

    def get_existing_dates(self) -> set:
        """获取已处理的日期"""
        existing = set()
        if os.path.exists(DATA_DIR):
            for f in os.listdir(DATA_DIR):
                if f.endswith(".json") and len(f) == 15:  # YYYY-MM-DD.json
                    existing.add(f.replace(".json", ""))
        return existing

    def process_single_date(self, query_date: str, force: bool = False) -> Dict:
        """
        处理单个日期的数据

        Args:
            query_date: 查询日期 (YYYY-MM-DD)
            force: 是否强制重新处理
        """
        logger.info(f"="*50)
        logger.info(f"开始处理日期: {query_date}")

        # 检查是否已存在
        output_path = os.path.join(DATA_DIR, f"{query_date}.json")
        if os.path.exists(output_path) and not force:
            logger.info(f"日期 {query_date} 已处理，跳过")
            return {"success": True, "date": query_date, "skipped": True}

        if self.bond_pool_df.empty:
            return {"success": False, "error": "债券池为空"}

        # 1. 筛选债券
        df = self.filter.filter_bonds(self.bond_pool_df.copy())
        if df.empty:
            return {"success": False, "error": "筛选后无债券"}

        # 2. 获取估值数据
        bond_codes = df["证券代码"].tolist()
        bond_data = self.fetcher.get_bond_valuation(bond_codes, query_date)

        if not bond_data:
            logger.error("未获取到债券估值数据")
            return {"success": False, "error": "未获取到债券估值数据"}

        # 3. 合并数据
        merged_data = []
        for _, row in df.iterrows():
            code = row["证券代码"]
            if code in bond_data:
                merged_data.append({
                    "bond_code": code,
                    "bond_name": row["证券简称"],
                    "issuer_name": row["债务主体中文名称"],
                    "bond_type_class": "永续债" if bond_data[code]["is_perpetual"] else "普通债",
                    **bond_data[code]
                })

        if not merged_data:
            return {"success": False, "error": "合并后无数据"}

        merged_df = pd.DataFrame(merged_data)
        logger.info(f"合并后共 {len(merged_df)} 条有效数据")

        # 4. 按发行人拟合曲线
        results = self._fit_curves_by_issuer(merged_df)

        # 5. 保存结果
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.info(f"结果已保存: {output_path}")

        return {
            "success": True,
            "date": query_date,
            "total_bonds": len(merged_df),
            "normal_issuers": len(results.get("normal", [])),
            "perpetual_issuers": len(results.get("perpetual", [])),
        }

    def _fit_curves_by_issuer(self, df: pd.DataFrame) -> Dict:
        """按发行人分组拟合曲线"""
        results = {"normal": [], "perpetual": []}

        grouped = df.groupby(["issuer_name", "bond_type_class"])
        for (issuer_name, bond_type), group in grouped:
            bonds = group.to_dict("records")
            fitting_result = self.curve_service.fit_curve(bonds)
            if fitting_result:
                # 保存原始债券数据（用于前端展示）
                bond_details = []
                for b in bonds:
                    if b.get("remain_years") and b.get("ytm"):
                        bond_details.append({
                            "bond_code": b.get("bond_code", ""),
                            "bond_name": b.get("bond_name", ""),
                            "remain_years": round(b.get("remain_years", 0), 2),
                            "ytm": round(b.get("ytm", 0), 4)
                        })

                result = {
                    "issuer_name": issuer_name,
                    "bond_type": bond_type,
                    "bonds": bond_details,  # 原始债券数据
                    **fitting_result
                }
                if bond_type == "普通债":
                    results["normal"].append(result)
                else:
                    results["perpetual"].append(result)

        # 按斜率排序
        results["normal"].sort(key=lambda x: x.get("slope_total", 0), reverse=True)
        results["perpetual"].sort(key=lambda x: x.get("slope_total", 0), reverse=True)

        logger.info(f"拟合完成: 普通债 {len(results['normal'])} 个发行人, 永续债 {len(results['perpetual'])} 个发行人")
        return results

    def _generate_date_range(self, start_date: str, end_date: str) -> List[str]:
        """生成日期范围（仅工作日）"""
        from datetime import datetime, timedelta
        dates = []
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        current = start
        while current <= end:
            # 跳过周末
            if current.weekday() < 5:
                dates.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)
        return dates

    def process_date_range(self, start_date: str, end_date: str, incremental: bool = True) -> List[Dict]:
        """
        处理日期范围

        Args:
            start_date: 开始日期
            end_date: 结束日期
            incremental: 是否增量更新（跳过已处理的日期）
        """
        trading_days = self.fetcher.get_trading_days(start_date, end_date)
        if not trading_days:
            # 如果API获取交易日失败，直接使用用户指定的日期
            logger.warning("获取交易日失败，直接使用指定日期范围")
            trading_days = [start_date] if start_date == end_date else self._generate_date_range(start_date, end_date)
            if not trading_days:
                logger.error("日期范围处理失败")
                return []

        # 增量更新：过滤已处理的日期
        if incremental:
            existing = self.get_existing_dates()
            original_count = len(trading_days)
            trading_days = [d.replace("/", "-") for d in trading_days if d.replace("/", "-") not in existing]
            logger.info(f"增量更新: 原始 {original_count} 天, 已处理 {original_count - len(trading_days)} 天, 待处理 {len(trading_days)} 天")

        if not trading_days:
            logger.info("无新日期需要处理")
            return []

        results = []
        for i, trading_day in enumerate(trading_days):
            date_str = trading_day.replace("/", "-")
            logger.info(f"处理第 {i+1}/{len(trading_days)} 天: {date_str}")

            result = self.process_single_date(date_str)
            results.append(result)

            # 每5天休息更长时间（避免API限流）
            if (i + 1) % 5 == 0:
                logger.info("已处理5天，休息30秒...")
                time.sleep(30)

            # 每20天大休息
            if (i + 1) % 20 == 0:
                logger.info("已处理20天，休息2分钟...")
                time.sleep(120)

        return results


# ==================== 主函数 ====================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="债券收益率曲线数据预处理")
    parser.add_argument("--date", type=str, help="处理单个日期 (YYYY-MM-DD)")
    parser.add_argument("--start", type=str, help="开始日期")
    parser.add_argument("--end", type=str, help="结束日期")
    parser.add_argument("--latest", action="store_true", help="处理最新交易日")
    parser.add_argument("--force", action="store_true", help="强制重新处理")
    args = parser.parse_args()

    processor = DataProcessor()

    if not processor.fetcher.login():
        logger.error("Choice API登录失败，退出")
        return

    try:
        if args.date:
            result = processor.process_single_date(args.date, force=args.force)
            print(json.dumps(result, ensure_ascii=False, indent=2))

        elif args.start and args.end:
            results = processor.process_date_range(args.start, args.end, incremental=not args.force)
            print(json.dumps(results, ensure_ascii=False, indent=2))

        elif args.latest:
            today = datetime.now().strftime("%Y-%m-%d")
            result = processor.process_single_date(today, force=args.force)
            print(json.dumps(result, ensure_ascii=False, indent=2))

        else:
            parser.print_help()

    finally:
        processor.fetcher.logout()


if __name__ == "__main__":
    main()