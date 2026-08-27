"""
自动结算模块——回填实际金价、自动打分、胜率滚动统计。

幂等设计：用 dir_correct 是否已填写做幂等键，已结算的不重复结算。
时区安全：所有日期判断显式转北京时间。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import (
    get_logger, load_workbook, find_row_by_date, save_workbook,
    yesterday_beijing_date_str, beijing_date_str, beijing_datetime_str,
    get_magnitude, get_direction, update_stats_sheet, COL, get_all_records
)
from collect import fetch_gold_price

log = get_logger("settle")


def settle_prediction(target_date: str = None) -> dict:
    """
    结算指定日期的预测（默认结算昨天）。
    幂等：如果该行已有 dir_correct（√或×），跳过。

    返回: {"settled": bool, "target_date": str, "result": dict}
    """
    if target_date is None:
        target_date = yesterday_beijing_date_str()

    log.info(f"===== 开始结算 {target_date} 的预测 =====")

    wb, ws = load_workbook()
    row = find_row_by_date(ws, target_date)

    if row == -1:
        log.warning(f"在日志中未找到 {target_date} 的预测记录，跳过结算")
        return {"settled": False, "target_date": target_date, "reason": "no_record"}

    # 幂等检查：检查 dir_correct 是否已填写
    existing_dir_correct = ws.cell(row=row, column=COL["dir_correct"]).value
    if existing_dir_correct in ("√", "×"):
        log.info(f"{target_date} 已结算（dir_correct={existing_dir_correct}），跳过")
        return {"settled": False, "target_date": target_date, "reason": "already_settled"}

    # 获取基准价
    base_price = ws.cell(row=row, column=COL["base_price"]).value
    if base_price is None:
        log.error(f"{target_date} 无基准价，无法结算")
        return {"settled": False, "target_date": target_date, "reason": "no_base_price"}

    # 获取实际金价（当前实时价作为实际价）
    gold_data = fetch_gold_price()
    actual_price = gold_data.get("usd_per_oz")

    if actual_price is None:
        log.error(f"获取实际金价失败，无法结算 {target_date}")
        return {"settled": False, "target_date": target_date, "reason": "price_fetch_failed"}

    # 计算涨跌幅
    change_pct = round((actual_price - base_price) / base_price * 100, 4)
    actual_dir = get_direction(change_pct)
    actual_mag = get_magnitude(change_pct)

    # 读取预测值
    pred_dir = ws.cell(row=row, column=COL["final_dir"]).value or ""
    pred_mag = ws.cell(row=row, column=COL["final_mag"]).value or ""

    # 判定对错
    dir_correct = "√" if pred_dir == actual_dir else "×"
    mag_correct = "√" if pred_mag == actual_mag else "×"

    # 平盘特殊情况
    if actual_dir == "平":
        dir_correct = "—"
        log.info(f"{target_date} 实际恰好持平，方向不计对错")

    # 写入日志
    ws.cell(row=row, column=COL["actual_price"], value=actual_price)
    ws.cell(row=row, column=COL["actual_change"], value=change_pct)
    ws.cell(row=row, column=COL["actual_dir"], value=actual_dir)
    ws.cell(row=row, column=COL["actual_mag"], value=actual_mag)
    ws.cell(row=row, column=COL["dir_correct"], value=dir_correct)
    ws.cell(row=row, column=COL["mag_correct"], value=mag_correct)

    existing_note = ws.cell(row=row, column=COL["note"]).value or ""
    settle_note = f"[{beijing_datetime_str()} 自动结算] 实际价=${actual_price}, 涨跌={change_pct:+.2f}%"
    if existing_note:
        ws.cell(row=row, column=COL["note"], value=f"{existing_note}；{settle_note}")
    else:
        ws.cell(row=row, column=COL["note"], value=settle_note)

    # 更新统计
    update_stats_sheet(wb)

    # 保存
    save_workbook(wb)

    result = {
        "target_date": target_date,
        "base_price": base_price,
        "actual_price": actual_price,
        "change_pct": change_pct,
        "actual_dir": actual_dir,
        "actual_mag": actual_mag,
        "pred_dir": pred_dir,
        "pred_mag": pred_mag,
        "dir_correct": dir_correct,
        "mag_correct": mag_correct,
    }

    log.info(f"结算完成: {target_date} | 预测 {pred_dir}/{pred_mag} → 实际 {actual_dir}/{actual_mag} | 方向{dir_correct} 档位{mag_correct}")
    return {"settled": True, "target_date": target_date, "result": result}


def settle_all_unsettled() -> list:
    """
    结算所有未结算的预测（dir_correct 为空的行）。
    跳过今天的预测（还未到结算时间）。
    返回结算结果列表。
    """
    log.info("===== 开始批量结算所有未结算预测 =====")

    wb, ws = load_workbook()
    records = get_all_records(ws)
    today = beijing_date_str()
    results = []

    # 获取一次实时金价用于所有结算
    gold_data = fetch_gold_price()
    actual_price = gold_data.get("usd_per_oz")

    if actual_price is None:
        log.error("获取实时金价失败，无法批量结算")
        return results

    log.info(f"当前实时金价: ${actual_price}/oz")

    for r in records:
        target_date = r["target_date"]

        # 跳过今天的预测
        if target_date == today:
            log.info(f"跳过今天的预测 {target_date}（未到结算时间）")
            continue

        # 跳过已结算的
        if r["dir_correct"] in ("√", "×"):
            log.info(f"{target_date} 已结算，跳过")
            continue

        # 跳过无基准价的
        base_price = r["base_price"]
        if base_price is None:
            log.warning(f"{target_date} 无基准价，跳过")
            continue

        row = r["row"]
        change_pct = round((actual_price - base_price) / base_price * 100, 4)
        actual_dir = get_direction(change_pct)
        actual_mag = get_magnitude(change_pct)

        pred_dir = r["final_dir"] or ""
        pred_mag = r["final_mag"] or ""

        dir_correct = "√" if pred_dir == actual_dir else "×"
        mag_correct = "√" if pred_mag == actual_mag else "×"

        if actual_dir == "平":
            dir_correct = "—"

        ws.cell(row=row, column=COL["actual_price"], value=actual_price)
        ws.cell(row=row, column=COL["actual_change"], value=change_pct)
        ws.cell(row=row, column=COL["actual_dir"], value=actual_dir)
        ws.cell(row=row, column=COL["actual_mag"], value=actual_mag)
        ws.cell(row=row, column=COL["dir_correct"], value=dir_correct)
        ws.cell(row=row, column=COL["mag_correct"], value=mag_correct)

        existing_note = r["note"] or ""
        settle_note = f"[{beijing_datetime_str()} 批量结算] 实际价=${actual_price}, 涨跌={change_pct:+.2f}%"
        if existing_note:
            ws.cell(row=row, column=COL["note"], value=f"{existing_note}；{settle_note}")
        else:
            ws.cell(row=row, column=COL["note"], value=settle_note)

        results.append({
            "target_date": target_date,
            "pred_dir": pred_dir,
            "pred_mag": pred_mag,
            "actual_dir": actual_dir,
            "actual_mag": actual_mag,
            "change_pct": change_pct,
            "dir_correct": dir_correct,
            "mag_correct": mag_correct,
        })

        log.info(f"结算 {target_date}: 预测 {pred_dir}/{pred_mag} → 实际 {actual_dir}/{actual_mag} | 方向{dir_correct} 档位{mag_correct}")

    if results:
        update_stats_sheet(wb)
        save_workbook(wb)
        log.info(f"批量结算完成: {len(results)} 条")
    else:
        log.info("无未结算的预测")

    return results


if __name__ == "__main__":
    # 先批量结算所有历史未结算的预测
    batch_results = settle_all_unsettled()
    if batch_results:
        for r in batch_results:
            print(f"\n批量结算: {r['target_date']}")
            print(f"  预测: {r['pred_dir']}/{r['pred_mag']}")
            print(f"  实际: {r['actual_dir']}/{r['actual_mag']}")
            print(f"  涨跌: {r['change_pct']:+.2f}%")
            print(f"  方向: {r['dir_correct']} | 档位: {r['mag_correct']}")

    # 再尝试结算昨天的（幂等，已结算的会跳过）
    result = settle_prediction()
    if result["settled"]:
        r = result["result"]
        print(f"\n结算结果: {r['target_date']}")
        print(f"  基准价: ${r['base_price']}")
        print(f"  实际价: ${r['actual_price']}")
        print(f"  涨跌幅: {r['change_pct']:+.2f}%")
        print(f"  方向: 预测{r['pred_dir']} → 实际{r['actual_dir']} → {r['dir_correct']}")
        print(f"  档位: 预测{r['pred_mag']} → 实际{r['actual_mag']} → {r['mag_correct']}")
    elif not batch_results:
        print(f"未结算: {result.get('reason', 'unknown')}")
