"""
手动刷新模块——盘中触发采集最新金价 → 更新面板实时数据。

不推翻早上的预测，仅更新实时价和追踪状态。
"""
import os
import re
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import get_logger, beijing_datetime_str, DASHBOARD_PATH
from collect import fetch_gold_price, fetch_usd_cny

log = get_logger("refresh")


def refresh_realtime():
    """采集最新金价并更新 dashboard.html 的实时数据。"""
    log.info("===== 开始手动刷新 =====")

    # 采集最新数据
    gold = fetch_gold_price()
    fx = fetch_usd_cny()

    usd_per_oz = gold.get("usd_per_oz")
    fx_rate = fx.get("rate")
    cny_per_gram = round(usd_per_oz * fx_rate / 31.1035, 2) if usd_per_oz and fx_rate else None

    if usd_per_oz is None:
        log.error("获取最新金价失败")
        return False

    # 读取 dashboard.html
    with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # 更新 realtime 部分
    # 使用正则替换 PAGE_DATA 中的 realtime 和 meta.generatedAt 字段
    timestamp = beijing_datetime_str()

    # 替换 usdPerOz (JSON format: "usdPerOz": value)
    html = re.sub(
        r'("usdPerOz":\s*)[\d.]+',
        lambda m: f'{m.group(1)}{usd_per_oz}',
        html
    )
    # 替换 cnyPerGram
    if cny_per_gram:
        html = re.sub(
            r'("cnyPerGram":\s*)[\d.]+',
            lambda m: f'{m.group(1)}{cny_per_gram}',
            html
        )
    # 替换 lastUpdate
    html = re.sub(
        r'("lastUpdate":\s*)"[^"]*"',
        lambda m: f'{m.group(1)}"{timestamp}"',
        html
    )
    # 替换 generatedAt
    html = re.sub(
        r'("generatedAt":\s*)"[^"]*"',
        lambda m: f'{m.group(1)}"{timestamp}"',
        html
    )

    with open(DASHBOARD_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    log.info(f"实时金价已更新: ${usd_per_oz}/oz, ¥{cny_per_gram}/g")
    log.info("===== 刷新完成 =====")
    return True


if __name__ == "__main__":
    success = refresh_realtime()
    if success:
        print("刷新成功")
    else:
        print("刷新失败")
        sys.exit(1)
