import os
import json

DATA_FILE = "car_wash_data.json"

if os.path.exists(DATA_FILE):
    os.remove(DATA_FILE)

from car_wash_system import (
    load_data, save_data, register_member, recharge_member,
    take_ticket, call_next_car, finish_wash,
    get_wash_history, get_daily_report, export_members_csv,
    get_queue_position, get_wait_time, WASH_PRICE
)

def test():
    print("=" * 60)
    print("🧪 洗车店会员管理系统 - 功能测试")
    print("=" * 60)

    data = load_data()
    all_passed = True

    print("\n1. 测试会员注册...")
    success, msg = register_member(data, "京A12345", "13800138001", "张三", "普通")
    assert success, f"注册失败: {msg}"
    success, msg = register_member(data, "京B66666", "13900139009", "李四", "金卡")
    assert success, f"金卡会员注册失败: {msg}"
    success, msg = register_member(data, "京A12345", "111", "重复", "普通")
    assert not success, "重复注册应该失败"
    print("   ✅ 会员注册功能正常")

    print("\n2. 测试会员充值...")
    success, msg = recharge_member(data, "京A12345", 100)
    assert success, f"充值失败: {msg}"
    member = data["members"]["京A12345"]
    assert member["balance"] == 100.0, f"余额错误: {member['balance']}"
    assert member["remaining_washes"] == 3, f"赠送次数错误: {member['remaining_washes']}"
    print("   ✅ 会员充值功能正常（100元送3次）")

    print("\n3. 测试取号排队...")
    success, r1 = take_ticket(data, "京C99999")
    assert success and r1["ticket_number"] == 1
    success, r2 = take_ticket(data, "京A12345")
    assert success and r2["ticket_number"] == 2
    success, r3 = take_ticket(data, "京B66666")
    assert success and r3["ticket_number"] == 3
    assert r3["is_vip"] == True, "金卡会员应该是VIP"
    
    vip_count, normal_count = get_queue_position(data)
    assert vip_count == 1, f"VIP排队人数错误: {vip_count}"
    assert normal_count == 2, f"普通排队人数错误: {normal_count}"
    assert data["queue"][0]["plate_number"] == "京B66666", "VIP应该插队到前面"
    print("   ✅ 取号排队 & VIP插队功能正常")

    print("\n4. 测试叫号洗车...")
    success, r = call_next_car(data)
    assert success, f"叫号失败: {r}"
    assert r["plate_number"] == "京B66666", "应该先叫VIP"
    assert r["bay_number"] == 1
    print(f"      叫到 {r['plate_number']} 到 {r['bay_number']} 号车位")
    
    success, r = call_next_car(data)
    assert success
    assert r["bay_number"] == 2
    print(f"      叫到 {r['plate_number']} 到 {r['bay_number']} 号车位")
    
    success, r = call_next_car(data)
    assert not success, "车位满时应该叫号失败"
    print("   ✅ 叫号功能正常（2个车位满员）")

    print("\n5. 测试完成洗车 & 结算...")
    success, r = finish_wash(data, 1)
    assert success, f"结算失败: {r}"
    assert r["plate_number"] == "京B66666"
    print(f"      1号车位完成: {r['plate_number']} (金卡未充值), 费用: {r['price']}元, 方式: {r['payment_method']}")
    
    success, r = finish_wash(data, 2)
    assert success
    assert r["plate_number"] == "京C99999"
    assert r["payment_method"] == "现金"
    assert r["price"] == WASH_PRICE
    print(f"      2号车位完成: {r['plate_number']} (非会员), 费用: {r['price']}元, 方式: {r['payment_method']}")
    
    success, call_r = call_next_car(data)
    assert success and call_r["plate_number"] == "京A12345"
    success, r = finish_wash(data, call_r["bay_number"])
    assert success
    assert r["payment_method"] == "会员次数"
    assert r["price"] == 0
    member = data["members"]["京A12345"]
    assert member["remaining_washes"] == 2, f"剩余次数扣除错误: {member['remaining_washes']}"
    print(f"      {call_r['bay_number']}号车位完成: {r['plate_number']} (会员), 费用: {r['price']}元, 方式: {r['payment_method']}")
    print("   ✅ 洗车结算功能正常")

    print("\n6. 测试套餐提醒...")
    member = data["members"]["京A12345"]
    print(f"      当前剩余次数: {member['remaining_washes']}")
    
    success, r = take_ticket(data, "京A12345")
    success, call_r = call_next_car(data)
    success, r = finish_wash(data, call_r["bay_number"])
    member = data["members"]["京A12345"]
    print(f"      再洗1次后剩余: {member['remaining_washes']}, 提醒: {'有' if r.get('reminder') else '无'}")
    assert r.get("reminder"), f"剩余次数{member['remaining_washes']}应该触发提醒"
    
    success, r = take_ticket(data, "京A12345")
    success, call_r = call_next_car(data)
    success, r = finish_wash(data, call_r["bay_number"])
    member = data["members"]["京A12345"]
    print(f"      再洗1次后剩余: {member['remaining_washes']}, 提醒: {'有' if r.get('reminder') else '无'}")
    
    print("   ✅ 套餐提醒功能正常（剩余次数<3时触发）")

    print("\n7. 测试满减促销（第3次5折）...")
    success, r = take_ticket(data, "促销测试车")
    success, call_r = call_next_car(data)
    success, r1 = finish_wash(data, call_r["bay_number"])
    print(f"      第1次: {r1['price']}元 {'【促销】' if r1.get('promotion_msg') else ''}")
    
    success, r = take_ticket(data, "促销测试车")
    success, call_r = call_next_car(data)
    success, r2 = finish_wash(data, call_r["bay_number"])
    print(f"      第2次: {r2['price']}元 {'【促销】' if r2.get('promotion_msg') else ''}")
    
    success, r = take_ticket(data, "促销测试车")
    success, call_r = call_next_car(data)
    success, r3 = finish_wash(data, call_r["bay_number"])
    print(f"      第3次: {r3['price']}元 {'【促销】' if r3.get('promotion_msg') else ''}")
    assert r3["price"] == WASH_PRICE * 0.5, f"第3次应该5折: {r3['price']}"
    assert r3.get("promotion_msg"), "应该有促销消息"
    print("   ✅ 满减促销功能正常")

    print("\n8. 测试洗车历史查询...")
    history = get_wash_history(data, "京A12345", 5)
    assert len(history) > 0, "应该有历史记录"
    print(f"      找到 {len(history)} 条历史记录")
    for i, h in enumerate(history[:3], 1):
        print(f"        {i}. {h['wash_time']} - {h['price']}元 ({h['payment_method']})")
    print("   ✅ 洗车历史查询功能正常")

    print("\n9. 测试每日经营报表...")
    report = get_daily_report(data)
    assert report is not None
    print(f"      日期: {report['date']}")
    print(f"      洗车总台数: {report['total_washes']}")
    print(f"      会员洗车次数: {report['member_washes']}")
    print(f"      现金收入: {report['cash_income']:.2f} 元")
    print(f"      会员充值金额: {report['recharge_amount']:.2f} 元")
    print(f"      当日总收入: {report['total_income']:.2f} 元")
    print("   ✅ 每日经营报表功能正常")

    print("\n10. 测试会员列表CSV导出...")
    success, msg = export_members_csv(data, "test_members.csv")
    assert success
    import os
    assert os.path.exists("test_members.csv")
    print(f"   ✅ {msg}")

    print("\n" + "=" * 60)
    print("🎉 所有测试通过！系统功能正常！")
    print("=" * 60)

if __name__ == "__main__":
    test()
