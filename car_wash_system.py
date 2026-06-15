import json
import os
import csv
from datetime import datetime, timedelta
from collections import deque

DATA_FILE = "car_wash_data.json"
WASH_BAYS = 2
WASH_DURATION_MINUTES = 15
WASH_PRICE = 20
RECHARGE_AMOUNT = 100
RECHARGE_BONUS_WASHES = 3
PROMOTION_WASH_COUNT = 3
PROMOTION_DISCOUNT = 0.5
LOW_WASHES_THRESHOLD = 3


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "members": {},
        "wash_history": [],
        "queue": [],
        "daily_stats": {},
        "next_ticket_number": 1,
        "active_bays": [None] * WASH_BAYS,
    }


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_today_str():
    return datetime.now().strftime("%Y-%m-%d")


def get_today_stats(data):
    today = get_today_str()
    if today not in data["daily_stats"]:
        data["daily_stats"][today] = {
            "total_washes": 0,
            "member_washes": 0,
            "cash_income": 0.0,
            "recharge_amount": 0.0,
            "plate_washes_today": {},
        }
    return data["daily_stats"][today]


def is_member(data, plate_number):
    return plate_number in data["members"]


def get_member(data, plate_number):
    return data["members"].get(plate_number)


def register_member(data, plate_number, phone, name="", level="普通"):
    if plate_number in data["members"]:
        return False, "该车牌已注册会员"
    data["members"][plate_number] = {
        "plate_number": plate_number,
        "phone": phone,
        "name": name,
        "level": level,
        "remaining_washes": 0,
        "balance": 0.0,
        "register_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_washes": 0,
        "total_recharge": 0.0,
    }
    save_data(data)
    return True, "会员注册成功"


def recharge_member(data, plate_number, amount=RECHARGE_AMOUNT):
    member = get_member(data, plate_number)
    if not member:
        return False, "非会员，请先注册"
    bonus_washes = RECHARGE_BONUS_WASHES if amount == RECHARGE_AMOUNT else 0
    member["remaining_washes"] += bonus_washes
    member["balance"] += amount
    member["total_recharge"] += amount
    today_stats = get_today_stats(data)
    today_stats["recharge_amount"] += amount
    save_data(data)
    return True, f"充值成功！余额：{member['balance']:.2f}元，赠送{bonus_washes}次洗车，剩余总次数：{member['remaining_washes']}次"


def calculate_promotion_discount(today_stats, plate_number):
    washes_today = today_stats["plate_washes_today"].get(plate_number, 0)
    if washes_today + 1 == PROMOTION_WASH_COUNT:
        return PROMOTION_DISCOUNT, True
    return 1.0, False


def process_wash_payment(data, plate_number):
    member = get_member(data, plate_number)
    today_stats = get_today_stats(data)
    discount, is_promotion = calculate_promotion_discount(today_stats, plate_number)
    final_price = WASH_PRICE * discount

    payment_method = "现金"
    used_washes = 0

    if member:
        if member["remaining_washes"] > 0:
            member["remaining_washes"] -= 1
            member["total_washes"] += 1
            used_washes = 1
            payment_method = "会员次数"
            final_price = 0
        elif member["balance"] >= final_price:
            member["balance"] -= final_price
            member["total_washes"] += 1
            payment_method = "会员余额"
        else:
            if final_price > 0:
                today_stats["cash_income"] += final_price
            payment_method = "现金（会员余额不足）"
            member["total_washes"] += 1
    else:
        today_stats["cash_income"] += final_price

    today_stats["total_washes"] += 1
    if member:
        today_stats["member_washes"] += 1

    today_stats["plate_washes_today"][plate_number] = today_stats["plate_washes_today"].get(plate_number, 0) + 1

    record = {
        "plate_number": plate_number,
        "wash_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "price": final_price,
        "payment_method": payment_method,
        "is_member": member is not None,
        "is_promotion": is_promotion,
        "used_washes": used_washes,
    }
    data["wash_history"].append(record)
    save_data(data)

    reminder = ""
    if member and member["remaining_washes"] < LOW_WASHES_THRESHOLD and payment_method == "会员次数":
        reminder = f"\n⚠️  套餐提醒：剩余次数不足（仅剩{member['remaining_washes']}次），建议充值！"

    promotion_msg = ""
    if is_promotion:
        promotion_msg = f"\n🎉 恭喜！今日第{PROMOTION_WASH_COUNT}次洗车，享受{PROMOTION_DISCOUNT*10:.0f}折优惠！"

    return True, {
        "price": final_price,
        "payment_method": payment_method,
        "reminder": reminder,
        "promotion_msg": promotion_msg,
        "remaining_washes": member["remaining_washes"] if member else 0,
        "balance": member["balance"] if member else 0,
    }


def get_queue_position(data):
    normal_queue = [item for item in data["queue"] if item["priority"] == "normal"]
    vip_queue = [item for item in data["queue"] if item["priority"] == "vip"]
    return len(vip_queue), len(normal_queue)


def get_wait_time(data):
    vip_count, normal_count = get_queue_position(data)
    total_waiting = vip_count + normal_count
    active_count = sum(1 for bay in data["active_bays"] if bay is not None)
    total = total_waiting + max(0, active_count - WASH_BAYS)
    wait_minutes = (total // WASH_BAYS) * WASH_DURATION_MINUTES
    return total_waiting, wait_minutes


def take_ticket(data, plate_number):
    member = get_member(data, plate_number)
    is_vip = member and member["level"] == "金卡"

    ticket = {
        "ticket_number": data["next_ticket_number"],
        "plate_number": plate_number,
        "is_vip": is_vip,
        "priority": "vip" if is_vip else "normal",
        "take_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    data["next_ticket_number"] += 1

    if is_vip:
        insert_pos = 0
        for i, item in enumerate(data["queue"]):
            if item["priority"] == "normal":
                insert_pos = i
                break
        else:
            insert_pos = len(data["queue"])
        data["queue"].insert(insert_pos, ticket)
    else:
        data["queue"].append(ticket)

    save_data(data)

    total_waiting, wait_minutes = get_wait_time(data)
    vip_count, normal_count = get_queue_position(data)

    position_msg = ""
    if is_vip:
        position_msg = f"您是金卡会员，已优先排到第{vip_count}位（VIP队列）"
    else:
        position_msg = f"您排在第{vip_count + normal_count}位"

    return True, {
        "ticket_number": ticket["ticket_number"],
        "position_msg": position_msg,
        "total_waiting": total_waiting,
        "wait_minutes": wait_minutes,
        "is_vip": is_vip,
    }


def call_next_car(data):
    if not data["queue"]:
        return False, "队列为空，没有等待的车辆"

    available_bay = None
    for i in range(WASH_BAYS):
        if data["active_bays"][i] is None:
            available_bay = i
            break

    if available_bay is None:
        return False, "所有洗车位都在使用中"

    next_car = data["queue"].pop(0)
    next_car["start_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    next_car["bay_number"] = available_bay + 1
    data["active_bays"][available_bay] = next_car

    save_data(data)
    return True, {
        "ticket_number": next_car["ticket_number"],
        "plate_number": next_car["plate_number"],
        "bay_number": available_bay + 1,
        "is_vip": next_car["is_vip"],
    }


def finish_wash(data, bay_number):
    bay_index = bay_number - 1
    if bay_index < 0 or bay_index >= WASH_BAYS:
        return False, "无效的洗车位号"

    if data["active_bays"][bay_index] is None:
        return False, "该洗车位当前没有车辆"

    car = data["active_bays"][bay_index]
    plate_number = car["plate_number"]
    data["active_bays"][bay_index] = None

    success, result = process_wash_payment(data, plate_number)
    if not success:
        return False, result

    return True, {
        "plate_number": plate_number,
        "bay_number": bay_number,
        **result,
    }


def get_wash_history(data, plate_number, limit=5):
    history = [
        record for record in data["wash_history"]
        if record["plate_number"] == plate_number
    ]
    history.sort(key=lambda x: x["wash_time"], reverse=True)
    return history[:limit]


def get_daily_report(data, date_str=None):
    if date_str is None:
        date_str = get_today_str()
    stats = data["daily_stats"].get(date_str)
    if not stats:
        return None
    return {
        "date": date_str,
        "total_washes": stats["total_washes"],
        "member_washes": stats["member_washes"],
        "cash_income": stats["cash_income"],
        "recharge_amount": stats["recharge_amount"],
        "total_income": stats["cash_income"] + stats["recharge_amount"],
    }


def export_members_csv(data, filename="members.csv"):
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["车牌号", "姓名", "手机号", "会员等级", "剩余洗车次数", "余额", "注册日期", "累计洗车次数", "累计充值"])
        for plate, member in data["members"].items():
            writer.writerow([
                member["plate_number"],
                member["name"],
                member["phone"],
                member["level"],
                member["remaining_washes"],
                f"{member['balance']:.2f}",
                member["register_date"],
                member["total_washes"],
                f"{member['total_recharge']:.2f}",
            ])
    return True, f"会员列表已导出到 {filename}"


def display_menu():
    print("\n" + "=" * 50)
    print("🚗  洗车店会员管理系统  🚗")
    print("=" * 50)
    print("1. 会员注册")
    print("2. 会员充值")
    print("3. 取号排队")
    print("4. 叫号洗车")
    print("5. 完成洗车 & 结算")
    print("6. 查询洗车历史")
    print("7. 每日经营报表")
    print("8. 导出会员列表(CSV)")
    print("9. 查看排队状态")
    print("10. 查看洗车位状态")
    print("0. 退出系统")
    print("=" * 50)


def main():
    data = load_data()

    while True:
        display_menu()
        choice = input("请选择操作 (0-10): ").strip()

        if choice == "0":
            print("感谢使用，再见！")
            break

        elif choice == "1":
            print("\n--- 会员注册 ---")
            plate = input("请输入车牌号: ").strip()
            if not plate:
                print("车牌号不能为空！")
                continue
            phone = input("请输入手机号: ").strip()
            name = input("请输入车主姓名(可选): ").strip()
            level_input = input("会员等级 (1-普通, 2-金卡，默认普通): ").strip()
            level = "金卡" if level_input == "2" else "普通"
            success, msg = register_member(data, plate, phone, name, level)
            print(msg)

        elif choice == "2":
            print("\n--- 会员充值 ---")
            plate = input("请输入车牌号: ").strip()
            amount_input = input(f"充值金额(默认{RECHARGE_AMOUNT}元送{RECHARGE_BONUS_WASHES}次): ").strip()
            amount = float(amount_input) if amount_input else RECHARGE_AMOUNT
            success, msg = recharge_member(data, plate, amount)
            print(msg)

        elif choice == "3":
            print("\n--- 取号排队 ---")
            plate = input("请输入车牌号: ").strip()
            if not plate:
                print("车牌号不能为空！")
                continue
            success, result = take_ticket(data, plate)
            if success:
                vip_label = "【金卡VIP】" if result["is_vip"] else ""
                print(f"\n🎫  取号成功！{vip_label}")
                print(f"   票号: {result['ticket_number']:03d}")
                print(f"   {result['position_msg']}")
                print(f"   当前排队人数: {result['total_waiting']} 人")
                print(f"   预计等待时间: 约 {result['wait_minutes']} 分钟")
            else:
                print(result)

        elif choice == "4":
            print("\n--- 叫号洗车 ---")
            success, result = call_next_car(data)
            if success:
                vip_label = "【金卡VIP】" if result["is_vip"] else ""
                print(f"\n📢  叫号成功！")
                print(f"   票号: {result['ticket_number']:03d}")
                print(f"   车牌: {result['plate_number']} {vip_label}")
                print(f"   请到 {result['bay_number']} 号洗车位")
            else:
                print(result)

        elif choice == "5":
            print("\n--- 完成洗车 & 结算 ---")
            bay_input = input(f"请输入洗车位号 (1-{WASH_BAYS}): ").strip()
            try:
                bay = int(bay_input)
            except ValueError:
                print("请输入有效的数字！")
                continue
            success, result = finish_wash(data, bay)
            if success:
                print(f"\n✅ 洗车完成！")
                print(f"   车牌: {result['plate_number']}")
                print(f"   洗车位: {result['bay_number']} 号")
                print(f"   支付方式: {result['payment_method']}")
                print(f"   本次费用: {result['price']:.2f} 元")
                if result["payment_method"].startswith("会员"):
                    print(f"   剩余次数: {result['remaining_washes']} 次")
                    print(f"   剩余余额: {result['balance']:.2f} 元")
                if result["promotion_msg"]:
                    print(result["promotion_msg"])
                if result["reminder"]:
                    print(result["reminder"])
            else:
                print(result)

        elif choice == "6":
            print("\n--- 查询洗车历史 ---")
            plate = input("请输入车牌号: ").strip()
            history = get_wash_history(data, plate)
            if not history:
                print("未找到该车辆的洗车记录")
                continue
            print(f"\n📋  {plate} 最近洗车记录（最近5次）:")
            print("-" * 40)
            for i, record in enumerate(history, 1):
                member_mark = "会员" if record["is_member"] else "非会员"
                promotion_mark = "【促销】" if record.get("is_promotion") else ""
                print(f"{i}. {record['wash_time']} | {member_mark} | {record['payment_method']} | {record['price']:.2f}元 {promotion_mark}")

        elif choice == "7":
            print("\n--- 每日经营报表 ---")
            date_input = input("请输入日期 (YYYY-MM-DD，默认今天): ").strip()
            report = get_daily_report(data, date_input if date_input else None)
            if not report:
                print("该日期没有经营数据")
                continue
            print(f"\n📊  {report['date']} 经营报表")
            print("-" * 40)
            print(f"洗车总台数: {report['total_washes']}")
            print(f"会员洗车次数: {report['member_washes']}")
            print(f"现金收入: {report['cash_income']:.2f} 元")
            print(f"会员充值金额: {report['recharge_amount']:.2f} 元")
            print(f"当日总收入: {report['total_income']:.2f} 元")

        elif choice == "8":
            print("\n--- 导出会员列表 ---")
            filename = input("请输入导出文件名(默认members.csv): ").strip()
            if not filename:
                filename = "members.csv"
            if not filename.endswith(".csv"):
                filename += ".csv"
            success, msg = export_members_csv(data, filename)
            print(msg)

        elif choice == "9":
            print("\n--- 排队状态 ---")
            total_waiting, wait_minutes = get_wait_time(data)
            vip_count, normal_count = get_queue_position(data)
            print(f"当前排队总人数: {total_waiting} 人")
            print(f"  VIP排队: {vip_count} 人")
            print(f"  普通排队: {normal_count} 人")
            print(f"预计等待时间: 约 {wait_minutes} 分钟")
            if data["queue"]:
                print("\n排队列表:")
                for i, item in enumerate(data["queue"], 1):
                    vip_label = "【VIP】" if item["is_vip"] else "     "
                    print(f"  {i:2d}. 票号{item['ticket_number']:03d} {vip_label} {item['plate_number']}")

        elif choice == "10":
            print("\n--- 洗车位状态 ---")
            for i in range(WASH_BAYS):
                bay = data["active_bays"][i]
                if bay:
                    vip_label = "【VIP】" if bay["is_vip"] else ""
                    print(f"  {i+1} 号车位: 使用中 - {bay['plate_number']} {vip_label} (票号:{bay['ticket_number']:03d})")
                else:
                    print(f"  {i+1} 号车位: 空闲")

        else:
            print("无效的选择，请重新输入！")

        input("\n按回车键继续...")


if __name__ == "__main__":
    main()
