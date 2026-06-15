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
    add_reservation, find_valid_reservation, list_today_reservations,
    get_detailed_wait_info, get_bay_free_times, get_bay_status,
    get_today_stats,
)


def _set_bay_start_time(data, bay_index, minutes_ago):
    """辅助函数：手动设置车位的开始时间，模拟已洗N分钟"""
    bay = data["active_bays"][bay_index]
    if bay is None:
        return
    new_start = datetime.now() - timedelta(minutes=minutes_ago)
    bay["start_time"] = new_start.strftime("%Y-%m-%d %H:%M:%S")
    save_data(data)


def test():
    print("=" * 60)
    print("🧪 洗车店会员管理系统 v2 - 功能测试")
    print("=" * 60)

    data = load_data()

    # =================== 基础功能回归 ===================
    print("\n1. 会员注册 & 充值...")
    register_member(data, "京A普通", "13800000001", "张普通", "普通")
    register_member(data, "京B金卡", "13900000002", "李金卡", "金卡")
    recharge_member(data, "京A普通", 100)
    member = data["members"]["京A普通"]
    assert member["remaining_washes"] == 3 and member["balance"] == 100
    print("   ✅ OK")

    # =================== 预约功能 ===================
    print("\n2. 预约登记 & 取号...")
    arrival = (datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M")
    ok, msg = add_reservation(data, "京C预约", arrival, False)
    assert ok
    ok, msg = add_reservation(data, "京D未来预约", (datetime.now() + timedelta(hours=5)).strftime("%Y-%m-%d %H:%M"), True)
    assert ok

    today_res = list_today_reservations(data)
    assert len(today_res) == 2, f"今日预约应为2条: {len(today_res)}"
    print(f"      今日预约 {len(today_res)} 条")

    # 预约在窗口内，能匹配到
    res = find_valid_reservation(data, "京C预约")
    assert res is not None, "预约窗口内应该能匹配"
    # 预约在5小时后，匹配不到
    res2 = find_valid_reservation(data, "京D未来预约")
    assert res2 is None, "预约太早应该匹配不到"
    print("   ✅ 预约窗口内匹配正常")

    # 预约车取号，优先级应该在普通之前、VIP之后
    take_ticket(data, "普通1号")
    take_ticket(data, "京C预约")     # 应该是 reserved 优先级
    take_ticket(data, "京B金卡")     # vip

    # 队列顺序：VIP 先 → 预约 → 普通
    assert data["queue"][0]["plate_number"] == "京B金卡", f"第一个应该是VIP，实际 {data['queue'][0]}"
    assert data["queue"][1]["plate_number"] == "京C预约", f"第二个应该是预约，实际 {data['queue'][1]}"
    assert data["queue"][2]["plate_number"] == "普通1号", f"第三个应该是普通，实际 {data['queue'][2]}"
    print(f"      队列顺序: {[q['plate_number'] for q in data['queue']]}")
    print("   ✅ 预约优先级(VIP>预约>普通)正常")

    # =================== 个人等待时间 & 预计开洗时间 ===================
    print("\n3. 细化等待时间计算（每台车独立算）...")
    if os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)
    data = load_data()
    register_member(data, "京A普通", "13800000001", "张普通", "普通")
    register_member(data, "京B金卡", "13900000002", "李金卡", "金卡")
    recharge_member(data, "京A普通", 100)

    # 场景：2个车位都忙（1号已洗10分钟剩5，2号已洗0分钟剩15），队里3台车
    take_ticket(data, "车S1")
    take_ticket(data, "车S2")
    call_next_car(data)   # 1号车位车S1
    call_next_car(data)   # 2号车位车S2
    _set_bay_start_time(data, 0, 10)  # 1号已洗10分
    _set_bay_start_time(data, 1, 0)   # 2号刚开洗

    # 取号：车Q1(普通)、车Q2(预约)、车Q3(VIP)
    arrival = (datetime.now()).strftime("%Y-%m-%d %H:%M")
    add_reservation(data, "车Q2", arrival, False)

    ok, r1 = take_ticket(data, "车Q1")     # 普通
    ok, r2 = take_ticket(data, "车Q2")     # 预约 (插队到普通前)
    ok, r3 = take_ticket(data, "京B金卡")  # VIP (插队最前)

    print(f"      取号顺序: Q1({r1['ticket_number']}), Q2({r2['ticket_number']}), VIP({r3['ticket_number']})")
    print(f"      队列顺序: {[q['plate_number'] for q in data['queue']]}")

    # 重新获取每台车的实时等待信息（因为后来者插队会改变位置）
    def _live_info(ticket_num):
        idx = next(i for i, q in enumerate(data["queue"]) if q["ticket_number"] == ticket_num)
        return idx, get_detailed_wait_info(data, idx)

    idx_r3, info_r3 = _live_info(r3["ticket_number"])
    idx_r2, info_r2 = _live_info(r2["ticket_number"])
    idx_r1, info_r1 = _live_info(r1["ticket_number"])

    # VIP应该在队首，前面0台车
    assert idx_r3 == 0, f"VIP应该第0个，实际{idx_r3}"
    assert info_r3["cars_ahead"] == 0, f"VIP前面应该0台车，实际{info_r3['cars_ahead']}"
    # VIP 预计使用1号车位（5分钟后空），所以等待约5分钟
    print(f"      VIP(Q3) 前面 {info_r3['cars_ahead']} 台，等待 {info_r3['wait_minutes']} 分钟，预计开洗 {info_r3['estimated_start']}，预计车位 {info_r3['assigned_bay']}号")
    assert info_r3["assigned_bay"] == 1, f"VIP应该分配1号车位（先空闲），实际{info_r3['assigned_bay']}"
    assert info_r3["wait_minutes"] >= 4, f"VIP等待时间应该约5分钟，实际{info_r3['wait_minutes']}"

    # 预约车Q2，应该排第2（0号VIP，1号Q2，2号Q1）
    print(f"      预约(Q2) 前面 {info_r2['cars_ahead']} 台，等待 {info_r2['wait_minutes']} 分钟，预计车位 {info_r2['assigned_bay']}号")
    assert idx_r2 == 1, f"Q2应该第1个，实际{idx_r2}"
    assert info_r2["cars_ahead"] == 1, f"预约车前面应该1台(VIP)，实际{info_r2['cars_ahead']}"

    # 普通车Q1，应该最后
    print(f"      普通(Q1) 前面 {info_r1['cars_ahead']} 台，等待 {info_r1['wait_minutes']} 分钟，预计车位 {info_r1['assigned_bay']}号")
    assert idx_r1 == 2, f"Q1应该第2个，实际{idx_r1}"
    assert info_r1["cars_ahead"] == 2, f"普通车前面应该2台(VIP+预约)，实际{info_r1['cars_ahead']}"

    print("   ✅ 个人等待时间（前面几台、预计开洗、预计车位）计算正常")

    # =================== 洗车位状态（已洗时长/剩余时间/进度） ===================
    print("\n4. 洗车位状态细化...")
    statuses = get_bay_status(data)
    for s in statuses:
        if s["is_busy"]:
            print(f"      {s['bay_number']}号: {s['plate_number']}, 已洗{s['elapsed_minutes']}分, 剩{s['remaining_minutes']}分, 进度{s['progress_pct']}%")
            if s["bay_number"] == 1:
                assert s["elapsed_minutes"] >= 9, f"1号车位已洗时间应该约10分，实际{s['elapsed_minutes']}"
                assert s["remaining_minutes"] <= 6, f"1号车位剩余应该约5分，实际{s['remaining_minutes']}"
                assert 60 <= s["progress_pct"] <= 80, f"1号进度应该~67%，实际{s['progress_pct']}%"
    print("   ✅ 洗车位状态（已洗/剩余/进度）正常")

    # =================== 完成后自动叫下一台 ===================
    print("\n5. 完成洗车 & 自动叫号...")
    # 完全重置数据，避免前面测试残留
    if os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)
    data = load_data()
    # 场景：3台车在队里，2个车位叫2台
    take_ticket(data, "车X1")
    take_ticket(data, "车X2")
    take_ticket(data, "车X3")
    call_next_car(data)  # 1号：车X1
    call_next_car(data)  # 2号：车X2

    assert len(data["queue"]) == 1, f"队列应该剩1台，实际{len(data['queue'])}"

    # 完成1号车位，应该自动把车X3叫进去
    ok, result = finish_wash(data, 1, auto_call_next=True)
    assert ok
    print(f"      车X1完成，自动叫号结果: {result.get('auto_called')}")
    assert result.get("auto_called"), "应该自动叫下一台"
    assert result["auto_called"]["plate_number"] == "车X3"
    assert data["active_bays"][0] is not None, "1号车位应该已经有新车"

    queue_after = len(data["queue"])
    print(f"      队列剩余 {queue_after} 台")
    assert queue_after == 0, f"自动叫完队列应该空，实际{queue_after}"

    # 再完成2号，队列空，不应该auto_called
    ok, result2 = finish_wash(data, 2, auto_call_next=True)
    assert ok and "auto_called" not in result2
    print("   ✅ 完成后自动叫下一台（有排队时）正常，无排队时不报错")

    # =================== 日报表细化 ===================
    print("\n6. 日报表细化（半价次数、抵扣次数、支付明细）...")
    # 构造5台车场景（第3台半价）
    if os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)
    data = load_data()
    register_member(data, "京A普通", "13800000001", "张普通", "普通")
    register_member(data, "京B金卡", "13900000002", "李金卡", "金卡")
    recharge_member(data, "京A普通", 100)   # 充值100

    plates = ["非会员A", "非会员B", "京A普通", "非会员C", "京B金卡"]
    for p in plates:
        take_ticket(data, p)
        ok, c = call_next_car(data)
        while not ok:
            # 车位忙，先释放一个
            for i in range(1, WASH_BAYS + 1):
                if data["active_bays"][i - 1] is not None:
                    ok_f, _ = finish_wash(data, i, auto_call_next=False)
                    if ok_f:
                        break
            ok, c = call_next_car(data)
    # 完成剩余占用
    for i in range(1, WASH_BAYS + 1):
        if data["active_bays"][i - 1] is not None:
            finish_wash(data, i, auto_call_next=False)

    report = get_daily_report(data)
    assert report
    print(f"      总洗台数: {report['total_washes']}")
    print(f"      半价优惠次数: {report['promotion_count']}")
    print(f"      会员次数抵扣: {report['wash_credits_used']}")
    print(f"      会员/非会员: {report['member_washes']}/{report['non_member_washes']}")
    print(f"      支付方式明细: {report['payment_breakdown']}")

    assert report["total_washes"] == 5, f"应该5台（手动5台），实际{report['total_washes']}"
    assert report["promotion_count"] == 1, f"半价优惠应该正好1次（第3台），实际{report['promotion_count']}"
    assert report["wash_credits_used"] == 1, f"次数抵扣应该正好1次（京A普通），实际{report['wash_credits_used']}"
    assert isinstance(report["payment_breakdown"], dict) and len(report["payment_breakdown"]) > 0
    print("   ✅ 日报表（半价次数/抵扣次数/支付明细）齐全")

    # =================== 综合场景 ===================
    print("\n7. 综合场景：VIP/预约/普通混合取号+等待计算...")
    if os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)
    data = load_data()
    register_member(data, "京B金卡", "13900000002", "李金卡", "金卡")

    # 2个车位都刚开洗（满）
    take_ticket(data, "占位A")
    take_ticket(data, "占位B")
    call_next_car(data)
    call_next_car(data)

    # 取号顺序：普通A → 预约A → VIP → 普通B → 预约B
    arrival = (datetime.now()).strftime("%Y-%m-%d %H:%M")
    add_reservation(data, "预约甲", arrival)
    add_reservation(data, "预约乙", arrival)

    take_ticket(data, "普通A")
    take_ticket(data, "预约甲")
    take_ticket(data, "京B金卡")
    take_ticket(data, "普通B")
    take_ticket(data, "预约乙")

    # 最终队列应该是：京B金卡 → 预约甲 → 预约乙 → 普通A → 普通B
    expected = ["京B金卡", "预约甲", "预约乙", "普通A", "普通B"]
    actual = [q["plate_number"] for q in data["queue"]]
    print(f"      期望顺序: {expected}")
    print(f"      实际顺序: {actual}")
    assert actual == expected, f"队列顺序不对: {actual}"

    # 每个人的前面几台数
    for i, plate in enumerate(expected):
        info = get_detailed_wait_info(data, i)
        assert info["cars_ahead"] == i, f"{plate}前面应该{i}台，实际{info['cars_ahead']}"
        # 2车位都刚开洗=15分钟后空
        # i=0,1: 15分钟后开 (分配1号和2号)
        # i=2,3: 30分钟后 (1号2号下一轮)
        # i=4:   45分钟 (再下一轮第一个)
        expected_wait = ((i // WASH_BAYS) + 1) * WASH_DURATION_MINUTES
        assert abs(info["wait_minutes"] - expected_wait) <= 2, f"{plate}等待约{expected_wait}分，实际{info['wait_minutes']}分"
        print(f"      {plate}: 前面{info['cars_ahead']}台, 等{info['wait_minutes']}分, 预计{info['assigned_bay']}号")

    print("   ✅ 综合混合队列优先级和等待时间都正确")

    print("\n" + "=" * 60)
    print("🎉 所有v2测试通过！新功能验证完毕！")
    print("=" * 60)


if __name__ == "__main__":
    test()
