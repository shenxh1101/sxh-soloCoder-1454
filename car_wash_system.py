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
RESERVATION_WINDOW_MINUTES = 30


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "reservations" not in data:
                data["reservations"] = []
            return data
    return {
        "members": {},
        "wash_history": [],
        "queue": [],
        "daily_stats": {},
        "next_ticket_number": 1,
        "active_bays": [None] * WASH_BAYS,
        "reservations": [],
    }


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_today_str():
    return datetime.now().strftime("%Y-%m-%d")


def now():
    return datetime.now()


def get_today_stats(data):
    today = get_today_str()
    if today not in data["daily_stats"]:
        data["daily_stats"][today] = {
            "total_washes": 0,
            "member_washes": 0,
            "cash_income": 0.0,
            "recharge_amount": 0.0,
            "plate_washes_today": {},
            "promotion_count": 0,
            "wash_credits_used": 0,
            "payment_breakdown": {},
        }
    stats = data["daily_stats"][today]
    for key in ("promotion_count", "wash_credits_used", "payment_breakdown"):
        if key not in stats:
            if key == "payment_breakdown":
                stats[key] = {}
            else:
                stats[key] = 0
    return stats


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
        "register_date": now().strftime("%Y-%m-%d %H:%M:%S"),
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


def add_reservation(data, plate_number, arrival_time_str, is_member_known=False):
    try:
        arrival_time = datetime.strptime(arrival_time_str, "%Y-%m-%d %H:%M")
    except ValueError:
        return False, "时间格式错误，请使用 YYYY-MM-DD HH:MM"
    reservation = {
        "plate_number": plate_number,
        "arrival_time": arrival_time.strftime("%Y-%m-%d %H:%M:%S"),
        "is_member": is_member_known,
        "create_time": now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "pending",
    }
    data["reservations"].append(reservation)
    save_data(data)
    return True, f"预约成功！车牌 {plate_number}，预约时间 {arrival_time.strftime('%m月%d日 %H:%M')}"


def find_valid_reservation(data, plate_number):
    current_time = now()
    for res in data["reservations"]:
        if res["plate_number"] != plate_number:
            continue
        if res["status"] != "pending":
            continue
        arrival = datetime.strptime(res["arrival_time"], "%Y-%m-%d %H:%M:%S")
        delta = (arrival - current_time).total_seconds() / 60
        if -RESERVATION_WINDOW_MINUTES <= delta <= RESERVATION_WINDOW_MINUTES:
            return res
    return None


def mark_reservation_used(data, reservation):
    reservation["status"] = "used"
    reservation["used_time"] = now().strftime("%Y-%m-%d %H:%M:%S")
    save_data(data)


def list_today_reservations(data):
    today = get_today_str()
    result = []
    for res in data["reservations"]:
        if res["arrival_time"].startswith(today):
            result.append(res)
    result.sort(key=lambda x: x["arrival_time"])
    return result


def calculate_promotion_discount(today_stats, plate_number):
    store_washes_today = today_stats["total_washes"]
    if store_washes_today + 1 == PROMOTION_WASH_COUNT:
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

    if is_promotion:
        today_stats["promotion_count"] = today_stats.get("promotion_count", 0) + 1
    if used_washes:
        today_stats["wash_credits_used"] = today_stats.get("wash_credits_used", 0) + 1
    breakdown = today_stats.setdefault("payment_breakdown", {})
    breakdown[payment_method] = breakdown.get(payment_method, 0.0) + final_price

    record = {
        "plate_number": plate_number,
        "wash_time": now().strftime("%Y-%m-%d %H:%M:%S"),
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
        promotion_msg = f"\n🎉 恭喜！您是本店今日第{PROMOTION_WASH_COUNT}台洗车，享受{PROMOTION_DISCOUNT*10:.0f}折优惠！"

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
    reserved_queue = [item for item in data["queue"] if item["priority"] == "reserved"]
    return len(vip_queue), len(reserved_queue), len(normal_queue)


def get_bay_free_times(data, current_time=None):
    if current_time is None:
        current_time = now()
    free_times = []
    for i in range(WASH_BAYS):
        bay = data["active_bays"][i]
        if bay is None:
            free_times.append((i, current_time))
        else:
            start = datetime.strptime(bay["start_time"], "%Y-%m-%d %H:%M:%S")
            free_at = start + timedelta(minutes=WASH_DURATION_MINUTES)
            free_times.append((i, free_at))
    free_times.sort(key=lambda x: x[1])
    return free_times


def get_detailed_wait_info(data, ticket_index_in_queue):
    current_time = now()
    bay_free_times = get_bay_free_times(data, current_time)
    queue_snapshot = list(data["queue"])

    simulated_free = list(bay_free_times)
    target_start_time = None
    assigned_bay = None
    cars_ahead_exclusive = 0

    for idx in range(len(queue_snapshot)):
        bay_idx, free_at = simulated_free.pop(0)
        start_time = max(free_at, current_time)

        if idx == ticket_index_in_queue:
            target_start_time = start_time
            assigned_bay = bay_idx + 1
            break
        else:
            cars_ahead_exclusive += 1

        next_free = start_time + timedelta(minutes=WASH_DURATION_MINUTES)
        simulated_free.append((bay_idx, next_free))
        simulated_free.sort(key=lambda x: x[1])

    if target_start_time is None:
        return None

    wait_minutes = int(round((target_start_time - current_time).total_seconds() / 60))
    if wait_minutes < 0:
        wait_minutes = 0

    return {
        "cars_ahead": cars_ahead_exclusive,
        "wait_minutes": wait_minutes,
        "estimated_start": target_start_time,
        "assigned_bay": assigned_bay,
    }


def get_wait_time(data):
    vip_count, reserved_count, normal_count = get_queue_position(data)
    total_waiting = vip_count + reserved_count + normal_count

    current_time = now()
    bay_free_times = get_bay_free_times(data, current_time)

    if total_waiting == 0:
        busy_count = sum(1 for _, t in bay_free_times if t > current_time)
        if busy_count == 0:
            return 0, 0
        else:
            earliest_free = min(t for _, t in bay_free_times)
            wait = int(round((earliest_free - current_time).total_seconds() / 60))
            return 0, max(0, wait)

    last_car_index = total_waiting - 1
    info = get_detailed_wait_info(data, last_car_index)
    if info is None:
        return total_waiting, 0
    return total_waiting, info["wait_minutes"]


def _insert_ticket(data, ticket, priority):
    queue = data["queue"]
    priority_order = {"vip": 0, "reserved": 1, "normal": 2}
    ticket_rank = priority_order.get(priority, 2)
    insert_pos = len(queue)
    for i, existing in enumerate(queue):
        existing_rank = priority_order.get(existing["priority"], 2)
        if ticket_rank < existing_rank:
            insert_pos = i
            break
    queue.insert(insert_pos, ticket)
    return insert_pos


def take_ticket(data, plate_number):
    member = get_member(data, plate_number)
    is_vip = member and member["level"] == "金卡"

    reservation = None
    priority = "normal"
    reservation_info = None

    if not is_vip:
        reservation = find_valid_reservation(data, plate_number)
        if reservation:
            priority = "reserved"
            reservation_info = reservation

    if is_vip:
        priority = "vip"

    ticket = {
        "ticket_number": data["next_ticket_number"],
        "plate_number": plate_number,
        "is_vip": is_vip,
        "priority": priority,
        "take_time": now().strftime("%Y-%m-%d %H:%M:%S"),
        "is_reservation": reservation is not None,
    }
    data["next_ticket_number"] += 1

    insert_pos = _insert_ticket(data, ticket, priority)

    if reservation:
        mark_reservation_used(data, reservation)
    else:
        save_data(data)

    actual_index = next(
        (i for i, q in enumerate(data["queue"]) if q["ticket_number"] == ticket["ticket_number"]),
        insert_pos,
    )
    wait_info = get_detailed_wait_info(data, actual_index)
    vip_c, res_c, norm_c = get_queue_position(data)
    total_waiting = vip_c + res_c + norm_c

    position_msg = ""
    if is_vip:
        vip_pos = actual_index + 1 if ticket["priority"] == "vip" else sum(1 for q in data["queue"][:actual_index] if q["priority"] == "vip") + 1
        position_msg = f"您是金卡会员，已优先排到第{vip_pos}位（VIP队列）"
    elif reservation:
        reserved_before = sum(1 for q in data["queue"][:actual_index] if q["priority"] == "reserved")
        position_msg = f"已匹配预约，排到预约队列第{reserved_before + 1}位"
    else:
        position_msg = f"您排在第{actual_index + 1}位"

    result = {
        "ticket_number": ticket["ticket_number"],
        "position_msg": position_msg,
        "total_waiting": total_waiting,
        "wait_minutes": wait_info["wait_minutes"] if wait_info else 0,
        "is_vip": is_vip,
        "is_reservation": reservation is not None,
        "cars_ahead": wait_info["cars_ahead"] if wait_info else 0,
        "estimated_start": wait_info["estimated_start"] if wait_info else None,
        "assigned_bay": wait_info["assigned_bay"] if wait_info else None,
    }
    return True, result


def call_next_car(data):
    if not data["queue"]:
        return False, "队列为空，没有等待的车辆"

    available_bay = None
    current_time = now()
    bay_free = get_bay_free_times(data, current_time)
    for bay_idx, free_at in bay_free:
        if free_at <= current_time + timedelta(seconds=1):
            available_bay = bay_idx
            break

    if available_bay is None:
        return False, "所有洗车位都在使用中"

    next_car = data["queue"].pop(0)
    next_car["start_time"] = now().strftime("%Y-%m-%d %H:%M:%S")
    next_car["bay_number"] = available_bay + 1
    data["active_bays"][available_bay] = next_car

    save_data(data)
    return True, {
        "ticket_number": next_car["ticket_number"],
        "plate_number": next_car["plate_number"],
        "bay_number": available_bay + 1,
        "is_vip": next_car["is_vip"],
        "is_reservation": next_car.get("is_reservation", False),
    }


def get_bay_status(data):
    current_time = now()
    result = []
    for i in range(WASH_BAYS):
        bay = data["active_bays"][i]
        info = {"bay_number": i + 1, "is_busy": False}
        if bay:
            start = datetime.strptime(bay["start_time"], "%Y-%m-%d %H:%M:%S")
            elapsed_seconds = (current_time - start).total_seconds()
            elapsed_minutes = int(elapsed_seconds // 60)
            remaining_minutes = max(0, WASH_DURATION_MINUTES - elapsed_minutes)
            progress_pct = min(100, int(elapsed_seconds / (WASH_DURATION_MINUTES * 60) * 100))
            estimated_end = start + timedelta(minutes=WASH_DURATION_MINUTES)
            info.update({
                "is_busy": True,
                "plate_number": bay["plate_number"],
                "ticket_number": bay["ticket_number"],
                "is_vip": bay["is_vip"],
                "is_reservation": bay.get("is_reservation", False),
                "start_time": bay["start_time"],
                "elapsed_minutes": elapsed_minutes,
                "remaining_minutes": remaining_minutes,
                "progress_pct": progress_pct,
                "estimated_end": estimated_end,
            })
        result.append(info)
    return result


def finish_wash(data, bay_number, auto_call_next=True):
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

    auto_called = None
    if auto_call_next and data["queue"]:
        ok, auto_res = call_next_car(data)
        if ok:
            auto_called = auto_res

    result = {
        "plate_number": plate_number,
        "bay_number": bay_number,
        **result,
    }
    if auto_called:
        result["auto_called"] = auto_called
    return True, result


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
    payment_breakdown = stats.get("payment_breakdown", {})
    return {
        "date": date_str,
        "total_washes": stats["total_washes"],
        "member_washes": stats["member_washes"],
        "cash_income": stats["cash_income"],
        "recharge_amount": stats["recharge_amount"],
        "total_income": stats["cash_income"] + stats["recharge_amount"],
        "promotion_count": stats.get("promotion_count", 0),
        "wash_credits_used": stats.get("wash_credits_used", 0),
        "payment_breakdown": payment_breakdown,
        "non_member_washes": stats["total_washes"] - stats["member_washes"],
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
    print("\n" + "=" * 55)
    print("🚗  洗车店会员管理系统  🚗")
    print("=" * 55)
    print(" 1. 会员注册")
    print(" 2. 会员充值")
    print(" 3. 预约登记")
    print(" 4. 查看今日预约")
    print(" 5. 取号排队")
    print(" 6. 叫号洗车")
    print(" 7. 完成洗车 & 结算")
    print(" 8. 查询洗车历史")
    print(" 9. 每日经营报表")
    print("10. 导出会员列表(CSV)")
    print("11. 查看排队状态")
    print("12. 查看洗车位状态")
    print(" 0. 退出系统")
    print("=" * 55)


def _fmt_time(dt):
    if isinstance(dt, datetime):
        return dt.strftime("%H:%M")
    return str(dt)


def _fmt_datetime(dt):
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M")
    return str(dt)


def main():
    data = load_data()

    while True:
        display_menu()
        choice = input("请选择操作 (0-12): ").strip()

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
            print("\n--- 预约登记 ---")
            plate = input("请输入车牌号: ").strip()
            if not plate:
                print("车牌号不能为空！")
                continue
            time_hint = now().strftime("%Y-%m-%d %H:%M")
            arrival = input(f"请输入预约到店时间 (YYYY-MM-DD HH:MM，例 {time_hint}): ").strip()
            if not arrival:
                print("预约时间不能为空！")
                continue
            known_member = input("已知是否为会员？(y/n，默认n): ").strip().lower()
            is_known = known_member == "y"
            success, msg = add_reservation(data, plate, arrival, is_known)
            print(msg)

        elif choice == "4":
            print("\n--- 今日预约列表 ---")
            reservations = list_today_reservations(data)
            if not reservations:
                print("今日暂无预约")
            else:
                print(f"共 {len(reservations)} 条预约：")
                for i, res in enumerate(reservations, 1):
                    status_map = {"pending": "待取号", "used": "已使用", "expired": "已过期"}
                    st = status_map.get(res.get("status", "pending"), res.get("status", "未知"))
                    member_mark = "【会员】" if res.get("is_member") else ""
                    print(f"  {i:2d}. {res['arrival_time'][5:16]} | {res['plate_number']} {member_mark}| {st}")

        elif choice == "5":
            print("\n--- 取号排队 ---")
            plate = input("请输入车牌号: ").strip()
            if not plate:
                print("车牌号不能为空！")
                continue
            success, result = take_ticket(data, plate)
            if success:
                labels = []
                if result["is_vip"]:
                    labels.append("金卡VIP")
                if result["is_reservation"]:
                    labels.append("预约车")
                label_str = f"【{'/'.join(labels)}】" if labels else ""
                print(f"\n🎫  取号成功！{label_str}")
                print(f"   票号: {result['ticket_number']:03d}")
                print(f"   {result['position_msg']}")
                print(f"   当前排队总人数: {result['total_waiting']} 人")
                print(f"   您前面还有: {result['cars_ahead']} 台车")
                print(f"   预计等待: 约 {result['wait_minutes']} 分钟")
                if result.get("estimated_start"):
                    print(f"   预计开洗时间: {_fmt_datetime(result['estimated_start'])}")
                if result.get("assigned_bay"):
                    print(f"   预计分配车位: {result['assigned_bay']} 号")
            else:
                print(result)

        elif choice == "6":
            print("\n--- 叫号洗车 ---")
            success, result = call_next_car(data)
            if success:
                labels = []
                if result["is_vip"]:
                    labels.append("VIP")
                if result.get("is_reservation"):
                    labels.append("预约")
                label_str = f"【{'/'.join(labels)}】" if labels else ""
                print(f"\n📢  叫号成功！{label_str}")
                print(f"   票号: {result['ticket_number']:03d}")
                print(f"   车牌: {result['plate_number']}")
                print(f"   请到 {result['bay_number']} 号洗车位")
            else:
                print(result)

        elif choice == "7":
            print("\n--- 完成洗车 & 结算 ---")
            bay_statuses = get_bay_status(data)
            print("当前洗车位状态：")
            for bs in bay_statuses:
                if bs["is_busy"]:
                    print(f"  {bs['bay_number']}号: {bs['plate_number']} (已洗{bs['elapsed_minutes']}分/剩{bs['remaining_minutes']}分)")
                else:
                    print(f"  {bs['bay_number']}号: 空闲")
            bay_input = input(f"\n请输入完成的洗车位号 (1-{WASH_BAYS}): ").strip()
            try:
                bay = int(bay_input)
            except ValueError:
                print("请输入有效的数字！")
                continue
            auto_opt = input("完成后自动叫下一台？(y/n，默认y): ").strip().lower()
            auto = auto_opt != "n"
            success, result = finish_wash(data, bay, auto_call_next=auto)
            if success:
                print(f"\n✅ 洗车完成！")
                print(f"   车牌: {result['plate_number']}")
                print(f"   洗车位: {result['bay_number']} 号")
                print(f"   支付方式: {result['payment_method']}")
                print(f"   本次费用: {result['price']:.2f} 元")
                if result["payment_method"].startswith("会员"):
                    print(f"   剩余次数: {result['remaining_washes']} 次")
                    print(f"   剩余余额: {result['balance']:.2f} 元")
                if result.get("promotion_msg"):
                    print(result["promotion_msg"])
                if result.get("reminder"):
                    print(result["reminder"])
                if result.get("auto_called"):
                    ac = result["auto_called"]
                    print(f"\n🔄 已自动叫下一台：票号{ac['ticket_number']:03d} {ac['plate_number']} → {ac['bay_number']}号车位")
            else:
                print(result)

        elif choice == "8":
            print("\n--- 查询洗车历史 ---")
            plate = input("请输入车牌号: ").strip()
            history = get_wash_history(data, plate)
            if not history:
                print("未找到该车辆的洗车记录")
                continue
            print(f"\n📋  {plate} 最近洗车记录（最近5次）:")
            print("-" * 55)
            for i, record in enumerate(history, 1):
                member_mark = "会员" if record["is_member"] else "非会员"
                promotion_mark = "【促销半价】" if record.get("is_promotion") else ""
                print(f"{i}. {record['wash_time']} | {member_mark} | {record['payment_method']} | {record['price']:.2f}元 {promotion_mark}")

        elif choice == "9":
            print("\n--- 每日经营报表 ---")
            date_input = input("请输入日期 (YYYY-MM-DD，默认今天): ").strip()
            report = get_daily_report(data, date_input if date_input else None)
            if not report:
                print("该日期没有经营数据")
                continue
            print(f"\n📊  {report['date']} 经营报表")
            print("-" * 55)
            print(f"【洗车台数】")
            print(f"  总台数: {report['total_washes']}")
            print(f"  会员洗车: {report['member_washes']}")
            print(f"  非会员洗车: {report['non_member_washes']}")
            print(f"\n【收入统计】")
            print(f"  现金收入: {report['cash_income']:.2f} 元")
            print(f"  会员充值: {report['recharge_amount']:.2f} 元")
            print(f"  当日总收入: {report['total_income']:.2f} 元")
            print(f"\n【优惠与抵扣】")
            print(f"  半价优惠次数: {report['promotion_count']} 次")
            print(f"  会员次数抵扣: {report['wash_credits_used']} 次")
            if report["payment_breakdown"]:
                print(f"\n【支付方式明细】")
                for method, amount in report["payment_breakdown"].items():
                    print(f"  {method}: {amount:.2f} 元")

        elif choice == "10":
            print("\n--- 导出会员列表 ---")
            filename = input("请输入导出文件名(默认members.csv): ").strip()
            if not filename:
                filename = "members.csv"
            if not filename.endswith(".csv"):
                filename += ".csv"
            success, msg = export_members_csv(data, filename)
            print(msg)

        elif choice == "11":
            print("\n--- 排队状态 ---")
            total_waiting, wait_minutes = get_wait_time(data)
            vip_c, res_c, norm_c = get_queue_position(data)
            print(f"当前排队总人数: {total_waiting} 人")
            print(f"  VIP排队: {vip_c} 人")
            if res_c:
                print(f"  预约排队: {res_c} 人")
            print(f"  普通排队: {norm_c} 人")
            print(f"队尾预计等待: 约 {wait_minutes} 分钟")
            if data["queue"]:
                print("\n排队列表（含每台预计开洗时间）:")
                for i, item in enumerate(data["queue"], 1):
                    labels = []
                    if item["is_vip"]:
                        labels.append("VIP")
                    if item.get("is_reservation"):
                        labels.append("预约")
                    label_str = f"【{'/'.join(labels)}】" if labels else "       "
                    info = get_detailed_wait_info(data, i - 1)
                    extra = ""
                    if info:
                        extra = f" | 约{info['wait_minutes']}分钟 → {_fmt_datetime(info['estimated_start'])} (预计{info['assigned_bay']}号)"
                    print(f"  {i:2d}. 票号{item['ticket_number']:03d} {label_str} {item['plate_number']}{extra}")

        elif choice == "12":
            print("\n--- 洗车位状态 ---")
            statuses = get_bay_status(data)
            for bs in statuses:
                if bs["is_busy"]:
                    labels = []
                    if bs["is_vip"]:
                        labels.append("VIP")
                    if bs.get("is_reservation"):
                        labels.append("预约")
                    label_str = f"【{'/'.join(labels)}】" if labels else ""
                    bar_len = 20
                    filled = int(bs["progress_pct"] / 100 * bar_len)
                    bar = "█" * filled + "░" * (bar_len - filled)
                    print(f"  {bs['bay_number']}号车位: 使用中")
                    print(f"     {bs['plate_number']} {label_str} (票号:{bs['ticket_number']:03d})")
                    print(f"     进度: {bar} {bs['progress_pct']}%")
                    print(f"     已洗: {bs['elapsed_minutes']}分钟 | 剩余: {bs['remaining_minutes']}分钟 | 预计结束: {_fmt_time(bs['estimated_end'])}")
                else:
                    print(f"  {bs['bay_number']}号车位: 空闲 ✅")

        else:
            print("无效的选择，请重新输入！")

        input("\n按回车键继续...")


if __name__ == "__main__":
    main()
