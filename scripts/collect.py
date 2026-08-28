"""
数据采集模块——金价、VIX、汇率、新闻。

数据源：
  - gold-api.com     实时金价 + 历史序列（免费，无需 Key）
  - Yahoo Finance    VIX 恐慌指数（免费，通过 yfinance）
  - er-api.com       USD/CNY 汇率（免费，无需 Key）
  - Tavily API       新闻搜索（需 TAVILY_API_KEY）
"""
import os
import sys
import json
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import get_logger, save_data, beijing_datetime_str

log = get_logger("collect")

# ==================== 金价 ====================

GOLD_API_URL = "https://api.gold-api.com/price/XAU"
GOLD_API_HISTORY_URL = "https://api.gold-api.com/price/XAU/history"

def fetch_gold_price() -> dict:
    """
    获取实时金价（美元/盎司）。
    返回: {"usd_per_oz": float, "timestamp": str, "source": str}
    """
    try:
        resp = requests.get(GOLD_API_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        price = float(data.get("price", data.get("value", 0)))
        log.info(f"实时金价: ${price}/oz")
        return {
            "usd_per_oz": price,
            "timestamp": beijing_datetime_str(),
            "source": "gold-api.com"
        }
    except Exception as e:
        log.error(f"获取金价失败: {e}")
        # 备用源：同一 API 的备选端点
        try:
            resp2 = requests.get("https://api.gold-api.com/price/XAU/USD", timeout=10)
            resp2.raise_for_status()
            data2 = resp2.json()
            price = float(data2.get("price", 0))
            if price:
                log.info(f"实时金价(备用源): ${price}/oz")
                return {"usd_per_oz": price, "timestamp": beijing_datetime_str(), "source": "gold-api.com/alt"}
        except:
            pass
        return {"usd_per_oz": None, "timestamp": beijing_datetime_str(), "source": "error"}

# ==================== VIX ====================

def fetch_vix() -> dict:
    """
    获取 VIX 恐慌指数。
    返回: {"value": float, "timestamp": str}
    """
    try:
        import yfinance as yf
        vix = yf.Ticker("^VIX")
        info = vix.info
        value = float(info.get("regularMarketPrice", info.get("previousClose", 0)))
        log.info(f"VIX: {value}")
        return {"value": value, "timestamp": beijing_datetime_str()}
    except Exception as e:
        log.warning(f"yfinance 获取 VIX 失败，尝试备用源: {e}")
        try:
            resp = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?range=1d&interval=1d", timeout=10)
            if resp.status_code == 200:
                result = resp.json()
                value = float(result["chart"]["result"][0]["meta"]["regularMarketPrice"])
                log.info(f"VIX (备用): {value}")
                return {"value": value, "timestamp": beijing_datetime_str()}
        except Exception as e2:
            log.error(f"VIX 获取全部失败: {e2}")
        return {"value": None, "timestamp": beijing_datetime_str()}

# ==================== 汇率 ====================

def fetch_usd_cny() -> dict:
    """
    获取 USD/CNY 实时汇率。
    返回: {"rate": float, "timestamp": str}
    """
    try:
        resp = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        rate = float(data["rates"]["CNY"])
        log.info(f"USD/CNY: {rate}")
        return {"rate": rate, "timestamp": beijing_datetime_str()}
    except Exception as e:
        log.error(f"获取汇率失败: {e}")
        return {"rate": None, "timestamp": beijing_datetime_str()}

# ==================== 新闻 ====================

def fetch_news(queries: list = None) -> list:
    """
    使用 Tavily API 搜索黄金相关新闻。
    需要 TAVILY_API_KEY 环境变量。
    返回: [{source, title, url, snippet, published_date}, ...]
    """
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        log.warning("TAVILY_API_KEY 未设置，跳过新闻采集")
        return []

    if queries is None:
        queries = [
            "gold price XAU USD today",
            "Federal Reserve interest rate decision",
            "central bank gold buying 2026",
            "gold safe haven demand geopolitical",
            "China gold demand PBOC reserves",
        ]

    all_news = []
    for query in queries:
        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                headers={"Content-Type": "application/json"},
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": "basic",
                    "topic": "news",
                    "max_results": 5,
                    "include_raw_content": False,
                },
                timeout=30
            )
            if resp.status_code != 200:
                log.error(f"新闻搜索失败 '{query}': HTTP {resp.status_code} - {resp.text[:200]}")
                continue
            data = resp.json()
            for item in data.get("results", []):
                all_news.append({
                    "source": item.get("source", "unknown"),
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("content", "")[:200],
                    "published_date": item.get("published_date", ""),
                })
            log.info(f"新闻搜索 '{query}': {len(data.get('results', []))} 条结果")
        except Exception as e:
            log.error(f"新闻搜索失败 '{query}': {e}")

    # 去重
    seen = set()
    unique = []
    for n in all_news:
        if n["title"] not in seen:
            seen.add(n["title"])
            unique.append(n)

    log.info(f"新闻采集完成: {len(unique)} 条")
    return unique

# ==================== 价格历史 ====================

def fetch_price_history(days: int = 60) -> list:
    """
    获取近 N 日金价历史序列。
    返回: [{"date": "YYYY-MM-DD", "usd": float, "chg": float}, ...]
    """
    try:
        import yfinance as yf
        gold = yf.Ticker("GC=F")
        hist = gold.history(period=f"{days + 10}d")
        result = []
        prev_close = None
        for idx, row in hist.iterrows():
            date_str = idx.strftime("%Y-%m-%d")
            close = round(float(row["Close"]), 2)
            chg = round((close - prev_close) / prev_close * 100, 2) if prev_close else 0
            result.append({"date": date_str, "usd": close, "chg": chg})
            prev_close = close
        result = result[-days:]
        log.info(f"价格历史: {len(result)} 天")
        return result
    except Exception as e:
        log.error(f"获取价格历史失败: {e}")
        return []

# ==================== 主函数 ====================

def run_collection():
    """执行完整数据采集流程，结果保存到 data/ 目录。"""
    log.info("===== 开始数据采集 =====")

    # 每个采集独立 try-except，确保部分失败不影响整体
    try:
        gold = fetch_gold_price()
    except Exception as e:
        log.error(f"金价采集异常: {e}")
        gold = {"usd_per_oz": None, "timestamp": beijing_datetime_str(), "source": "error"}

    try:
        vix = fetch_vix()
    except Exception as e:
        log.error(f"VIX 采集异常: {e}")
        vix = {"value": None, "timestamp": beijing_datetime_str()}

    try:
        fx = fetch_usd_cny()
    except Exception as e:
        log.error(f"汇率采集异常: {e}")
        fx = {"rate": None, "timestamp": beijing_datetime_str()}

    try:
        news = fetch_news()
    except Exception as e:
        log.error(f"新闻采集异常: {e}")
        news = []

    try:
        history = fetch_price_history(60)
    except Exception as e:
        log.error(f"价格历史采集异常: {e}")
        history = []

    # 计算 ¥/g
    cny_per_gram = None
    if gold.get("usd_per_oz") and fx.get("rate"):
        cny_per_gram = round(gold["usd_per_oz"] * fx["rate"] / 31.1035, 2)

    collected = {
        "timestamp": beijing_datetime_str(),
        "gold_price": gold,
        "vix": vix,
        "fx": fx,
        "cny_per_gram": cny_per_gram,
        "news": news,
        "price_history": history,
    }

    save_data("collected.json", collected)
    log.info(f"采集完成: 金价={gold.get('usd_per_oz')}, VIX={vix.get('value')}, 新闻={len(news)}条, 历史={len(history)}天")
    log.info("===== 数据采集完成 =====")
    return collected

if __name__ == "__main__":
    run_collection()
