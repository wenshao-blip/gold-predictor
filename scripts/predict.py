"""
模型推理模块——整理采集数据 → 调用 LLM → 解析方向/幅度/置信度 → 生成报告 → 写入日志。

LLM 兼容 OpenAI API 格式（支持 OpenAI / Claude / DeepSeek / 通义 等）。
幂等设计：如果今天已有预测行，跳过。
"""
import os
import sys
import json
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import (
    get_logger, load_workbook, save_workbook, update_stats_sheet,
    beijing_date_str, beijing_datetime_str, now_beijing,
    is_weekend, find_row_by_date, find_last_data_row,
    determine_market_label, COL, LOG_PATH, DATA_DIR
)
from collect import run_collection, fetch_gold_price

log = get_logger("predict")


def build_prompt(collected: dict) -> str:
    """将采集数据整理为 LLM 推理 prompt。"""
    gold = collected.get("gold_price", {})
    vix = collected.get("vix", {})
    fx = collected.get("fx", {})
    cny_g = collected.get("cny_per_gram")
    news = collected.get("news", [])
    history = collected.get("price_history", [])

    # 价格序列摘要
    recent_5 = history[-5:] if len(history) >= 5 else history
    price_lines = "\n".join(
        f"  {p['date']}: ${p['usd']} ({p['chg']:+.2f}%)" for p in recent_5
    )

    # 新闻摘要
    news_lines = "\n".join(
        f"  [{n.get('source','')}] {n.get('title','')} ({n.get('published_date','')})"
        for n in news[:15]
    )

    # 20日趋势
    if len(history) >= 20:
        recent_20 = history[-20:]
        trend_20 = (recent_20[-1]["usd"] - recent_20[0]["usd"]) / recent_20[0]["usd"] * 100
        trend_str = f"{trend_20:+.2f}%"
    else:
        trend_str = "数据不足"

    prompt = f"""你是专业的黄金价格分析师。请基于以下数据，预测今日 XAU/USD 的走势。

===== 今日数据 =====
当前金价: ${gold.get('usd_per_oz', 'N/A')}/oz
VIX 恐慌指数: {vix.get('value', 'N/A')}
USD/CNY 汇率: {fx.get('rate', 'N/A')}
折合人民币: ¥{cny_g}/g
近20日累计涨跌: {trend_str}

近5日价格:
{price_lines}

===== 今日要闻 =====
{news_lines}

===== 预测要求 =====
预测窗口: 北京时间当日 06:00 → 次日 06:00
方向二分: 涨 或 跌
幅度三档: 小(≤0.3%) / 中(≤1.0%) / 大(>1.0%)
置信度: 你对方向判断的把握程度（50%-95%）

请按以下 JSON 格式回复（不要有其他内容）:
{{
  "direction": "涨或跌",
  "magnitude": "小或中或大",
  "confidence": 50到95的整数,
  "summary": "一段大白话预测摘要，3-5句话，说人话",
  "bull_signals": [
    {{"title": "信号标题", "desc": "一句话解释"}}
  ],
  "bear_signals": [
    {{"title": "信号标题", "desc": "一句话解释"}}
  ],
  "glossary": [
    {{"term": "术语", "def": "人话解释"}}
  ],
  "professional_analysis": "专业分析原文，包含技术面、资金面、宏观、地缘、风险提示等段落",
  "key_drivers": "关键驱动摘要，利多利空信号的综合描述"
}}"""

    return prompt


def call_llm(prompt: str) -> dict:
    """调用 LLM API（OpenAI 兼容格式）。"""
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("LLM_MODEL", "gpt-4o")

    if not api_key:
        log.error("LLM_API_KEY 未设置，无法推理")
        return None

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是专业黄金分析师，精通技术分析、宏观经济学和地缘政治。你的预测必须诚实、有据、不夸大。回复只包含 JSON，不要有 markdown 代码块标记。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 4096,
    }

    try:
        log.info(f"调用 LLM: {model} @ {base_url}")
        resp = requests.post(url, headers=headers, json=body, timeout=90)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        # 去除可能的 markdown 代码块标记
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        result = json.loads(content)
        log.info(f"LLM 推理完成: 方向={result.get('direction')}, 幅度={result.get('magnitude')}, 置信度={result.get('confidence')}%")
        return result
    except json.JSONDecodeError as e:
        log.error(f"LLM 返回 JSON 解析失败: {e}")
        log.error(f"原始返回: {content[:500]}")
        return None
    except Exception as e:
        log.error(f"LLM 调用失败: {e}")
        return None


def write_prediction_to_log(prediction: dict, collected: dict):
    """将预测结果写入 log.xlsx。"""
    wb, ws = load_workbook()

    today = beijing_date_str()
    existing_row = find_row_by_date(ws, today)
    if existing_row != -1:
        log.info(f"今日已有预测行（行 {existing_row}），更新而非新增")
        row = existing_row
    else:
        row = find_last_data_row(ws) + 1

    base_price = collected.get("gold_price", {}).get("usd_per_oz")
    history = collected.get("price_history", [])
    market_label = determine_market_label(history) if history else "震荡"

    ws.cell(row=row, column=COL["target_date"], value=today)
    ws.cell(row=row, column=COL["gen_time"], value=beijing_datetime_str())
    ws.cell(row=row, column=COL["base_price"], value=base_price)
    ws.cell(row=row, column=COL["final_dir"], value=prediction["direction"])
    ws.cell(row=row, column=COL["final_mag"], value=prediction["magnitude"])
    ws.cell(row=row, column=COL["model_dir"], value=prediction["direction"])
    ws.cell(row=row, column=COL["model_mag"], value=prediction["magnitude"])
    ws.cell(row=row, column=COL["human_adj"], value="否")
    ws.cell(row=row, column=COL["market"], value=market_label)
    ws.cell(row=row, column=COL["drivers"], value=prediction.get("key_drivers", ""))
    ws.cell(row=row, column=COL["note"], value=f"[{beijing_datetime_str()} 自动生成]")
    ws.cell(row=row, column=COL["confidence"], value=prediction.get("confidence"))

    update_stats_sheet(wb)
    save_workbook(wb)
    log.info(f"预测已写入 log.xlsx 行 {row}")

    # 保存完整预测数据（供 deploy.py 使用）
    from utils import save_data
    save_data("prediction.json", prediction)

    return row


def run_prediction():
    """执行完整推理流程：采集 → 推理 → 写入日志。"""
    log.info("===== 开始模型推理 =====")

    # 周末守卫
    if is_weekend():
        log.info("今天是周末（北京时间），休市不预测")
        return {"predicted": False, "reason": "weekend"}

    # 幂等检查
    today = beijing_date_str()
    wb, ws = load_workbook()
    existing = find_row_by_date(ws, today)
    if existing != -1:
        existing_conf = ws.cell(row=existing, column=COL["confidence"]).value
        if existing_conf is not None:
            log.info(f"今日已生成预测（行 {existing}），跳过")
            wb.close()
            return {"predicted": False, "reason": "already_predicted"}

    # 采集数据
    collected = run_collection()

    # 构建 prompt 并调用 LLM
    prompt = build_prompt(collected)
    prediction = call_llm(prompt)

    if prediction is None:
        log.error("LLM 推理失败，无法生成预测")
        return {"predicted": False, "reason": "llm_failed"}

    # 写入日志
    row = write_prediction_to_log(prediction, collected)

    log.info("===== 模型推理完成 =====")
    return {"predicted": True, "row": row, "prediction": prediction}


if __name__ == "__main__":
    result = run_prediction()
    if result["predicted"]:
        p = result["prediction"]
        print(f"\n预测完成:")
        print(f"  方向: {p['direction']}")
        print(f"  幅度: {p['magnitude']}")
        print(f"  置信度: {p['confidence']}%")
        print(f"  摘要: {p['summary']}")
    else:
        print(f"未生成预测: {result.get('reason', 'unknown')}")
