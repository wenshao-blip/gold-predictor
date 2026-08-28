"""
部署模块——读取最新日志和数据 → 重新生成 dashboard.html → 推送 GitHub Pages。

将 log.xlsx 和采集数据合并为 PAGE_DATA JSON，
替换 dashboard.html 中的数据块。
"""
import os
import re
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import (
    get_logger, load_workbook, get_all_records, DASHBOARD_PATH,
    beijing_datetime_str, beijing_date_str, DATA_DIR
)

log = get_logger("deploy")


def build_page_data() -> dict:
    """从 log.xlsx 和采集数据构建 PAGE_DATA。"""
    wb, ws = load_workbook()
    records = get_all_records(ws)

    # 加载采集数据
    collected_path = os.path.join(DATA_DIR, "collected.json")
    prediction_path = os.path.join(DATA_DIR, "prediction.json")
    collected = json.load(open(collected_path, encoding="utf-8")) if os.path.exists(collected_path) else {}
    prediction = json.load(open(prediction_path, encoding="utf-8")) if os.path.exists(prediction_path) else {}

    # 取最新记录
    latest = records[-1] if records else None
    if not latest:
        log.error("日志中无记录")
        return {}

    # 统计
    settled = [r for r in records if r["dir_correct"] in ("√", "×")]
    settled_count = len(settled)
    dir_correct = sum(1 for r in settled if r["dir_correct"] == "√")
    mag_correct = sum(1 for r in settled if r["mag_correct"] == "√")

    dir_rate = round(dir_correct / settled_count * 100, 1) if settled_count else None
    mag_rate = round(mag_correct / settled_count * 100, 1) if settled_count else None

    recent_30 = settled[-30:]
    recent_count = len(recent_30)
    recent_dir = sum(1 for r in recent_30 if r["dir_correct"] == "√")
    recent_mag = sum(1 for r in recent_30 if r["mag_correct"] == "√")

    # 分市况
    trend_settled = [r for r in settled if "趋势" in (r["market"] or "")]
    range_settled = [r for r in settled if "震荡" in (r["market"] or "")]
    trend_rate = round(sum(1 for r in trend_settled if r["dir_correct"] == "√") / len(trend_settled) * 100, 1) if trend_settled else None
    range_rate = round(sum(1 for r in range_settled if r["dir_correct"] == "√") / len(range_settled) * 100, 1) if range_settled else None

    # 置信度统计
    conf_recorded = [r for r in records if r["confidence"] is not None]
    conf_settled = [r for r in settled if r["confidence"] is not None]

    # 价格历史
    price_history = collected.get("price_history", [])

    # 胜率历史（累计）
    win_rate_history = []
    cumulative_dir = 0
    cumulative_mag = 0
    count = 0
    for r in settled:
        count += 1
        if r["dir_correct"] == "√":
            cumulative_dir += 1
        if r["mag_correct"] == "√":
            cumulative_mag += 1
        win_rate_history.append({
            "date": r["target_date"],
            "direction": round(cumulative_dir / count * 100, 1),
            "magnitude": round(cumulative_mag / count * 100, 1),
            "settled": count
        })

    # 构建历史记录（倒序，最新在前）
    history_list = []
    for r in reversed(records):
        history_list.append({
            "date": r["target_date"],
            "dir": r["final_dir"],
            "mag": r["final_mag"],
            "basePrice": r["base_price"],
            "actualPrice": r["actual_price"],
            "actualChange": r["actual_change"],
            "dirCorrect": r["dir_correct"],
            "magCorrect": r["mag_correct"],
            "market": r["market"],
            "drivers": r["drivers"],
            "note": r["note"],
            "confidence": r["confidence"],
            "settled": r["dir_correct"] in ("√", "×"),
        })

    # 实时金价
    gold = collected.get("gold_price", {})
    fx = collected.get("fx", {})

    page_data = {
        "meta": {
            "generatedAt": beijing_datetime_str(),
            "pipelineVersion": "1.0",
            "nextUpdate": f"{beijing_date_str()} 15:35" if True else None,
        },
        "prediction": {
            "date": latest["target_date"],
            "generatedAt": latest["gen_time"],
            "direction": latest["final_dir"],
            "magnitude": latest["final_mag"],
            "confidence": latest["confidence"] or 0,
            "basePrice": latest["base_price"],
            "summary": prediction.get("summary", ""),
            "modelRawDirection": latest["model_dir"],
            "modelRawMagnitude": latest["model_mag"],
            "humanAdjusted": latest["human_adj"] == "是",
            "marketCondition": latest["market"],
        },
        "realtime": {
            "usdPerOz": gold.get("usd_per_oz"),
            "cnyPerGram": collected.get("cny_per_gram"),
            "lastUpdate": gold.get("timestamp", ""),
            "source": gold.get("source", ""),
        },
        "marketLabel": {
            "tag": latest["market"] or "—",
            "detail": latest["market"] or "",
            "trend20d": price_history[-1]["usd"] / price_history[0]["usd"] * 100 - 100 if len(price_history) >= 2 else 0,
        },
        "record": {
            "settled": settled_count,
            "total": len(records),
            "directionCorrect": dir_correct,
            "magnitudeCorrect": mag_correct,
            "directionRate": dir_rate or 0,
            "magnitudeRate": mag_rate or 0,
            "directionRate30": round(recent_dir / recent_count * 100, 1) if recent_count else 0,
            "magnitudeRate30": round(recent_mag / recent_count * 100, 1) if recent_count else 0,
            "trendWinRate": trend_rate,
            "rangeWinRate": range_rate,
            "confidenceRecorded": len(conf_recorded),
            "confidenceSettled": len(conf_settled),
            "calibrationThreshold": 20,
        },
        "priceHistory": price_history,
        "winRateHistory": win_rate_history,
        "bullSignals": prediction.get("bull_signals", []),
        "bearSignals": prediction.get("bear_signals", []),
        "glossary": prediction.get("glossary", []),
        "professionalText": prediction.get("professional_analysis", ""),
        "history": history_list,
        "news": collected.get("news", []),
    }

    return page_data


def replace_page_data(html: str, new_data: dict) -> str:
    """替换 dashboard.html 中的 PAGE_DATA JSON 块。"""
    new_json = json.dumps(new_data, ensure_ascii=False, indent=2)
    replacement = f'const PAGE_DATA = {new_json};'
    # Use lambda to avoid re.sub() processing \n escape sequences in the replacement
    result = re.sub(r'const PAGE_DATA = \{.*?\};', lambda m: replacement, html, flags=re.DOTALL)
    if result == html:
        log.warning("PAGE_DATA 未被替换（正则未匹配），检查 HTML 模板")
    return result


def deploy():
    """生成最新的 dashboard.html。"""
    log.info("===== 开始部署 =====")

    page_data = build_page_data()
    if not page_data:
        log.error("无法构建页面数据")
        return False

    # 读取模板
    if not os.path.exists(DASHBOARD_PATH):
        log.error(f"dashboard.html 不存在: {DASHBOARD_PATH}")
        return False

    with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # 替换数据
    html = replace_page_data(html, page_data)

    # 写入
    with open(DASHBOARD_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    log.info(f"dashboard.html 已更新: {DASHBOARD_PATH}")
    log.info("===== 部署完成 =====")
    return True


if __name__ == "__main__":
    success = deploy()
    print("部署成功" if success else "部署失败")
