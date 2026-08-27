"""
置信度校准模块——验证模型声称的置信度 vs 实际命中率。

攒够 20 个已结算样本后运行：
  - 按置信度分档统计
  - 对比"声称把握"与"实际命中率"
  - 生成校准报告
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import get_logger, load_workbook, get_all_records, save_data, DATA_DIR
from collect import fetch_gold_price

log = get_logger("calibration")

CALIBRATION_THRESHOLD = 20


def run_calibration():
    """执行置信度校准分析。"""
    log.info("===== 开始置信度校准 =====")

    wb, ws = load_workbook()
    records = get_all_records(ws)

    # 筛选有置信度且已结算的记录
    settled = [
        r for r in records
        if r["dir_correct"] in ("√", "×") and r["confidence"] is not None
    ]

    if len(settled) < CALIBRATION_THRESHOLD:
        log.info(f"已结算样本不足: {len(settled)}/{CALIBRATION_THRESHOLD}，暂不校准")
        return {"calibrated": False, "reason": "insufficient_samples", "count": len(settled)}

    # 按置信度分档
    bins = {
        "50-59%": {"claimed": [], "actual": []},
        "60-69%": {"claimed": [], "actual": []},
        "70-79%": {"claimed": [], "actual": []},
        "80-89%": {"claimed": [], "actual": []},
        "90-95%": {"claimed": [], "actual": []},
    }

    for r in settled:
        conf = r["confidence"]
        correct = r["dir_correct"] == "√"
        if 50 <= conf < 60:
            key = "50-59%"
        elif 60 <= conf < 70:
            key = "60-69%"
        elif 70 <= conf < 80:
            key = "70-79%"
        elif 80 <= conf < 90:
            key = "80-89%"
        else:
            key = "90-95%"
        bins[key]["claimed"].append(conf)
        bins[key]["actual"].append(1 if correct else 0)

    # 计算各档校准结果
    report_lines = [
        "=" * 60,
        "黄金预测系统 · 置信度校准报告",
        f"样本数: {len(settled)} | 生成时间: {__import__('utils').beijing_datetime_str()}",
        "=" * 60,
        "",
        f"{'置信度档':<12} {'声称把握':>10} {'实际命中率':>12} {'偏差':>8} {'样本数':>8}",
        "-" * 60,
    ]

    calibration_data = []
    for bin_name, data in bins.items():
        if not data["claimed"]:
            continue
        avg_claimed = sum(data["claimed"]) / len(data["claimed"])
        actual_rate = sum(data["actual"]) / len(data["actual"]) * 100
        deviation = actual_rate - avg_claimed
        sample_count = len(data["claimed"])

        report_lines.append(
            f"{bin_name:<12} {avg_claimed:>9.1f}% {actual_rate:>11.1f}% {deviation:>+7.1f}% {sample_count:>8}"
        )
        calibration_data.append({
            "bin": bin_name,
            "avg_claimed": round(avg_claimed, 1),
            "actual_rate": round(actual_rate, 1),
            "deviation": round(deviation, 1),
            "sample_count": sample_count,
        })

    # 总体校准评估
    total_claimed = sum(r["confidence"] for r in settled) / len(settled)
    total_actual = sum(1 for r in settled if r["dir_correct"] == "√") / len(settled) * 100
    total_dev = total_actual - total_claimed

    report_lines.extend([
        "-" * 60,
        f"{'总体':<12} {total_claimed:>9.1f}% {total_actual:>11.1f}% {total_dev:>+7.1f}% {len(settled):>8}",
        "",
    ])

    if abs(total_dev) < 5:
        assessment = "校准良好（偏差 < 5%）：模型声称的置信度基本可信。"
    elif total_dev > 0:
        assessment = f"低估自信（偏差 +{total_dev:.1f}%）：实际表现优于声称，模型偏保守。"
    else:
        assessment = f"高估自信（偏差 {total_dev:.1f}%）：实际表现低于声称，模型偏乐观，需谨慎。"

    report_lines.append(f"评估: {assessment}")
    report_lines.append("")
    report_lines.append("注: 各置信度档的声称把握 vs 实际命中率越接近，说明模型越诚实。")
    report_lines.append("     偏差 > 10% 的档位需要重点关注。")

    report_text = "\n".join(report_lines)
    print(report_text)

    # 保存
    report = {
        "calibrated": True,
        "sample_count": len(settled),
        "overall": {
            "avg_claimed": round(total_claimed, 1),
            "actual_rate": round(total_actual, 1),
            "deviation": round(total_dev, 1),
        },
        "assessment": assessment,
        "bins": calibration_data,
        "report_text": report_text,
    }
    save_data("calibration_report.json", report)

    # 写入 log.xlsx 的统计 Sheet 备注
    ws_stats = wb["统计"]
    # 找到校准报告门槛行并更新
    for row in range(1, ws_stats.max_row + 1):
        cell_val = ws_stats.cell(row=row, column=1).value
        if cell_val and "校准报告门槛" in str(cell_val):
            ws_stats.cell(row=row, column=2, value=f"已校准（{len(settled)} 样本，偏差 {total_dev:+.1f}%）")
            break
    wb.save(__import__('utils').LOG_PATH)

    log.info("===== 校准完成 =====")
    return report


if __name__ == "__main__":
    result = run_calibration()
    if not result.get("calibrated"):
        print(f"\n未校准: {result.get('reason')} (样本: {result.get('count', 0)}/{CALIBRATION_THRESHOLD})")
