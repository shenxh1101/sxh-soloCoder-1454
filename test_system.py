import os
import json
from datetime import datetime, timedelta

DATA_FILE = "car_wash_data.json"

if os.path.exists(DATA_FILE):
    os.remove(DATA_FILE)

from car_wash_system import (
    load_data, save_data, register_member, recharge_member,
    take_ticket, call_next_car, finish_wash,
    get_wash_history, get_daily_report, export_members_csv,
    get_queue_position, get_wait_time, WASH_PRICE,
    WASH_DURATION_MINUTES, WASH_BAYS,
    add_reservation, check_in_reservation, find_valid_reservation,
    list_today_reservations,
    get_detailed_wait_info, get_bay_free_times, get_bay_status,
    get_today_stats, skip_called_car, restore_skipped_car,
    pause_bay, resume_bay, extend_bay_service, get_range_report,
    get_effective_elapsed_seconds, get_total_duration_minutes,
)


def _set_bay_start_time(data, bay_index, minutes_ago):
    bay = data["active_bays"][bay_index]
    if bay is None:
        return
    new_start = datetime.now() - timedelta(minutes=minutes_ago)
    bay["start_time"] = new_start.strftime("%Y-%m-%d %H:%M:%S")
    bay["paused"] = False
    bay["pause_start_time"] = None
    bay["total_paused_seconds"] = 0
    bay["extra_duration_minutes"] = 0
    save_data(data)


def test():
    print("=" * 60)
    print("🧪 洗车店会员管理系统 v3 - 功能测试")
    print("=" * 60)

    # =================== 1. 签到 + 预约优先级 ===================
    print("\n1. 预约签到 + 预约车必须先签到才享受优先...")
    if os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)
    data = load_data()

    arrival = (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M")
    add_reservation(data, "预约未签到车", arrival, False)

    ok, r = take_ticket(data, "预约未签到车")
    assert ok
    assert not r["is_reservation"], "没签到不应该识别为预约"
    assert r["cars_ahead"] == 0
    print("      没签到时取号，按普通车处理 ✅")

    arrival2 = (datetime.now()).strftime("%Y-%m-%d %H:%M")
    add_reservation(data, "预约已签到车", arrival2, False)
    check_in_reservation(data, "预约已签到车")

    # 重置队列
    data["queue"] = []
    data["next_ticket_number"] = 1
    save_data(data)

    take_ticket(data, "普通车A")
    ok, r2 = take_ticket(data, "预约已签到车")
    assert ok
    assert r2["is_reservation"], "已签到应该识别为预约"
    assert data["queue"][0]["plate_number"] == "预约已签到车", "预约车应该排到普通车前面"
    print(f"      签到后取号，识别为预约车并插队到普通车前: {[q['plate_number'] for q in data['queue']]} ✅")
    print("   ✅ 预约签到功能正常")

    # =================== 2. 过号 & 恢复 ===================
    print("\n2. 过号处理 & 恢复到合适位置...")
    if os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)
    data = load_data()
    register_member(data, "金卡A", "13800000001", "金卡A", "金卡")
    recharge_member(data, "金卡A", 100)

    take_ticket(data, "普通1")
    take_ticket(data, "普通2")
    ok, r_vip = take_ticket(data, "金卡A")   # VIP应该排第一
    take_ticket(data, "普通3")

    assert data["queue"][0]["plate_number"] == "金卡A"
    assert data["queue"][3]["plate_number"] == "普通3"
    print(f"      队列: {[q['plate_number'] for q in data['queue']]}")

    ok, msg = skip_called_car(data, "普通2")
    assert ok, f"过号失败: {msg}"
    assert len(data["skipped_tickets"]) == 1
    assert data["skipped_tickets"][0]["plate_number"] == "普通2"
    assert len(data["queue"]) == 3, f"队列应该剩3台，实际{len(data['queue'])}"
    print(f"      普通2过号，队列剩余: {[q['plate_number'] for q in data['queue']]} ✅")

    ok, res = restore_skipped_car(data, "普通2")
    assert ok, f"恢复失败: {res}"
    assert len(data["skipped_tickets"]) == 0
    assert res["priority"] == "normal"
    print(f"      恢复成功: 普通2现在队列第{res['new_position']}位，前面{res['cars_ahead']}台")
    print(f"      恢复后队列: {[q['plate_number'] for q in data['queue']]}")
    assert data["queue"][-1]["plate_number"] == "普通2", "恢复普通车应该排到同优先级队尾"
    print("   ✅ 过号 & 恢复按优先级插入正确")

    # =================== 3. 叫号衔接严格化 ===================
    print("\n3. 叫号衔接更严：车位未明确完成时不能被下一台占用...")
    if os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)
    data = load_data()

    take_ticket(data, "车A")
    take_ticket(data, "车B")
    take_ticket(data, "车C")

    ok, r1 = call_next_car(data)  # 1号车A
    assert ok and r1["bay_number"] == 1
    ok, r2 = call_next_car(data)  # 2号车B
    assert ok and r2["bay_number"] == 2

    # 2个车位都忙，再叫号应该失败，给出具体车位信息
    ok, msg3 = call_next_car(data)
    assert not ok
    assert "1号" in msg3 and "2号" in msg3
    print(f"      2个车位忙时叫号失败: {msg3} ✅")

    # 先手动改1号车位的 start_time 为 100 分钟前，模拟早就洗完了，但系统还没"完成结算"
    _set_bay_start_time(data, 0, 100)
    # 再叫号应该仍然失败——因为 active_bays[0] 不是 None（没有明确完成）
    ok, msg4 = call_next_car(data)
    assert not ok, "即使时间早就到了，只要没显式完成，车位应仍被占用"
    print(f"      即使预计结束时间已过，未显式完成时叫号仍失败: {msg4} ✅")

    # 显式完成1号
    ok, res = finish_wash(data, 1, auto_call_next=True)
    assert ok
    assert data["active_bays"][0]["plate_number"] == "车C", "完成后应该自动叫车C"
    print(f"      完成1号，自动叫车C到1号 ✅")
    print("   ✅ 叫号衔接严格化（只有显式完成才能进下一台）")

    # =================== 4. 暂停 / 继续 / 延长时长 ===================
    print("\n4. 车位暂停 / 继续 / 延长时长 & 排队时间同步...")
    if os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)
    data = load_data()

    take_ticket(data, "车位车1")
    take_ticket(data, "车位车2")
    take_ticket(data, "排队车1")
    ok, r = call_next_car(data)
    assert ok and r["plate_number"] == "车位车1"
    ok, r = call_next_car(data)
    assert ok and r["plate_number"] == "车位车2"

    # 已洗10分钟：start_time 设为15分钟前，后面模拟暂停了5分钟
    _set_bay_start_time(data, 0, 15)
    _set_bay_start_time(data, 1, 15)

    # 正常情况（还没暂停）：2个车位已洗15分钟？不对，_set_bay_start_time(15)表示15分钟前开始，所以已洗15分，剩0分
    # 重新调整为：start_time 设为20分钟前，已洗15分，剩0分（模拟马上要洗完，但我们要"已洗10分钟"，所以start_time = 25分钟前，已洗15分？不对...
    # 简单点：先让已洗10分钟，剩5分钟，不暂停
    _set_bay_start_time(data, 0, 10)
    _set_bay_start_time(data, 1, 10)

    # 正常情况：2个车位都已洗10分钟，各剩5分钟，排队车1约等5分钟
    status = get_bay_status(data)[0]
    assert status["elapsed_minutes"] >= 9, f"已洗约10分，实际{status['elapsed_minutes']}"
    assert status["remaining_minutes"] <= 6, f"剩约5分，实际{status['remaining_minutes']}"

    _, baseline_wait = get_wait_time(data)
    print(f"      暂停前：1号已洗{status['elapsed_minutes']}分，剩{status['remaining_minutes']}分，队尾约等{baseline_wait}分钟")
    assert baseline_wait >= 4, f"基线应该约5分，实际{baseline_wait}"

    # 暂停1号
    ok, msg = pause_bay(data, 1)
    assert ok
    assert data["active_bays"][0]["paused"] is True
    print(f"      暂停1号: {msg}")

    # 模拟：洗车是10分钟前开始的（start_time），暂停发生在5分钟前
    # 即 start_time = now - 15分钟，pause_start_time = now - 5分钟
    # 这样总经过15分钟，其中暂停了5分钟，有效已洗10分钟
    new_start = (datetime.now() - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
    data["active_bays"][0]["start_time"] = new_start
    ps = datetime.strptime(data["active_bays"][0]["pause_start_time"], "%Y-%m-%d %H:%M:%S")
    data["active_bays"][0]["pause_start_time"] = (ps - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    save_data(data)

    # 暂停状态下读状态：有效已洗时间应该是10分钟，暂停累计5分钟
    status2 = get_bay_status(data)[0]
    assert status2["paused"] is True
    assert 9 <= status2["elapsed_minutes"] <= 11, f"暂停中有效已洗时间应该约10分，实际{status2['elapsed_minutes']}"
    assert status2["total_paused_minutes"] >= 4, f"累计暂停应该约5分，实际{status2['total_paused_minutes']}"
    print(f"      暂停5分钟后读状态：1号已洗{status2['elapsed_minutes']}分（冻结），暂停累计{status2['total_paused_minutes']}分 ✅")

    # 继续1号
    ok, msg = resume_bay(data, 1)
    assert ok
    assert data["active_bays"][0]["paused"] is False

    status3 = get_bay_status(data)[0]
    assert status3["total_paused_minutes"] >= 4
    # 继续后：总时长15分，有效已洗10分，剩余应该约5分（但还要加暂停的5分到预计结束）
    # 暂停累计5分钟，所以预计结束 = start + 15分 + 5分暂停 = 现在 + 5分
    assert status3["remaining_minutes"] >= 3, f"1号继续后应该剩约5分，实际{status3['remaining_minutes']}"
    print(f"      继续1号后：剩{status3['remaining_minutes']}分，累计暂停{status3['total_paused_minutes']}分 ✅")

    # 再延长1号10分钟（加内饰打蜡）
    ok, msg = extend_bay_service(data, 1, 10)
    assert ok
    status4 = get_bay_status(data)[0]
    assert status4["extra_duration_minutes"] == 10
    # 剩余应该约5分+10分=15分
    assert status4["remaining_minutes"] >= 13, f"1号延长后应该剩约15分，实际{status4['remaining_minutes']}"
    print(f"      延长1号10分后：剩{status4['remaining_minutes']}分，总时长{get_total_duration_minutes(data['active_bays'][0])}分 ✅")

    # 同样处理2号：start_time=15分钟前，暂停5分钟，延长5分钟
    new_start2 = (datetime.now() - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
    data["active_bays"][1]["start_time"] = new_start2
    pause_bay(data, 2)
    ps2 = datetime.strptime(data["active_bays"][1]["pause_start_time"], "%Y-%m-%d %H:%M:%S")
    data["active_bays"][1]["pause_start_time"] = (ps2 - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    save_data(data)
    resume_bay(data, 2)
    extend_bay_service(data, 2, 5)

    # 排队时间同步：队尾等待时间应该显著大于基线（约多10-20分钟）
    _, wait_after = get_wait_time(data)
    print(f"      队尾等待：2个车位都延迟后约等{wait_after}分钟（基线{baseline_wait}分钟）")
    assert wait_after >= baseline_wait + 5, f"延迟后等待时间应该更长，实际{wait_after} vs 基线{baseline_wait}"
    print("   ✅ 暂停/继续/延长 & 排队时间同步全部正常")

    # =================== 5. 时间段经营报表 ===================
    print("\n5. 时间段经营报表（跨日汇总、会员余额消费、各项明细）...")
    if os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)
    data = load_data()
    register_member(data, "京A", "13800000001", "A", "普通")
    recharge_member(data, "京A", 100)      # 充值100

    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # 手动往 daily_stats 里塞一些昨天的数据（模拟跨日）
    data["daily_stats"][yesterday] = {
        "total_washes": 4,
        "member_washes": 2,
        "cash_income": 40.0,
        "recharge_amount": 100.0,
        "promotion_count": 1,
        "wash_credits_used": 1,
        "member_balance_spent": 20.0,
        "payment_breakdown": {"现金": 40.0, "会员余额": 20.0, "会员次数": 0.0},
        "plate_washes_today": {},
    }

    # 今天再实际跑几台，让今天也有数据
    plates_flow = ["非A", "非B", "京A"]
    for p in plates_flow:
        take_ticket(data, p)
        ok, c = call_next_car(data)
        while not ok:
            for i in range(1, WASH_BAYS + 1):
                if data["active_bays"][i - 1] is not None:
                    finish_wash(data, i, auto_call_next=False)
                    break
            ok, c = call_next_car(data)
    for i in range(1, WASH_BAYS + 1):
        if data["active_bays"][i - 1] is not None:
            finish_wash(data, i, auto_call_next=False)

    ok, rep = get_range_report(data, yesterday, today)
    assert ok, f"时间段报表失败: {rep}"
    print(f"      周期: {rep['start_date']} ~ {rep['end_date']}")
    print(f"      天数: {rep['days_total']}天，有数据{rep['days_covered']}天")
    print(f"      总洗台数: {rep['total_washes']} (昨天4 + 今天{rep['total_washes'] - 4})")
    print(f"      现金收入: {rep['cash_income']:.2f}")
    print(f"      会员充值: {rep['recharge_amount']:.2f}")
    print(f"      会员余额消费: {rep['member_balance_spent']:.2f}")
    print(f"      半价优惠: {rep['promotion_count']} 次")
    print(f"      会员次数抵扣: {rep['wash_credits_used']} 次")
    print(f"      支付方式明细: {rep['payment_breakdown']}")
    print(f"      每日明细: {rep['daily_details']}")

    assert rep["days_covered"] == 2
    assert rep["total_washes"] >= 7, f"至少4+3=7台"
    assert rep["recharge_amount"] >= 200.0, f"昨天100+今天100=200充值，实际{rep['recharge_amount']}"
    assert rep["member_balance_spent"] >= 20.0, f"昨天消费20"
    assert rep["promotion_count"] >= 1
    assert rep["wash_credits_used"] >= 1
    assert isinstance(rep["payment_breakdown"], dict) and len(rep["payment_breakdown"]) >= 1
    assert len(rep["daily_details"]) == 2

    # 非法日期
    ok, err = get_range_report(data, "2025-13-40", "2025-01-01")
    assert not ok
    ok, err2 = get_range_report(data, "2025-12-31", "2025-01-01")
    assert not ok
    print("   ✅ 时间段报表跨日汇总、日期校验正常")

    print("\n" + "=" * 60)
    print("🎉 所有v3测试通过！新功能验证完毕！")
    print("=" * 60)


if __name__ == "__main__":
    test()
