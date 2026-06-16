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
    defaults = {
        "members": {},
        "wash_history": [],
        "queue": [],
        "daily_stats": {},
        "next_ticket_number": 1,
        "active_bays": [None] * WASH_BAYS,
        "reservations": [],
        "skipped_tickets": [],
    }
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in defaults.items():
            if k not in data:
                data[k] = v
        for bay in data["active_bays"]:
            if isinstance(bay, dict):
                bay.setdefault("paused", False)
                bay.setdefault("pause_start_time", None)
                bay.setdefault("total_paused_seconds", 0)
                bay.setdefault("extra_duration_minutes", 0)
        return data
    return defaults.copy()


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
            "member_balance_spent": 0.0,
        }
    stats = data["daily_stats"][today]
    for key in ("promotion_count", "wash_credits_used", "payment_breakdown", "member_balance_spent"):
        if key not in stats:
            if key == "payment_breakdown":
                stats[key] = {}
            else:
                stats[key] = 0.0 if key.endswith("_spent") else 0
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


def find_valid_reservation(data, plate_number, require_checked_in=True):
    current_time = now()
    for res in data["reservations"]:
        if res["plate_number"] != plate_number:
            continue
        if res["status"] not in ("pending", "checked_in"):
            continue
        arrival = datetime.strptime(res["arrival_time"], "%Y-%m-%d %H:%M:%S")
        delta = (arrival - current_time).total_seconds() / 60
        if -RESERVATION_WINDOW_MINUTES <= delta <= RESERVATION_WINDOW_MINUTES:
            if require_checked_in and res["status"] != "checked_in":
                continue
            return res
    return None


def check_in_reservation(data, plate_number):
    res = find_valid_reservation(data, plate_number, require_checked_in=False)
    if res is None:
        return False, "未找到可签到的预约（超出签到时间窗口或状态异常）"
    if res["status"] == "checked_in":
        return False, "该预约已签到"
    res["status"] = "checked_in"
    res["check_in_time"] = now().strftime("%Y-%m-%d %H:%M:%S")
    save_data(data)
    return True, f"签到成功！车牌 {plate_number}，可前往取号享受预约优先"


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
    balance_spent = 0.0

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
            balance_spent = final_price
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
    if balance_spent > 0:
        today_stats["member_balance_spent"] = today_stats.get("member_balance_spent", 0.0) + balance_spent
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
        "balance_spent": balance_spent,
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
        "balance_spent": balance_spent,
    }


def get_queue_position(data):
    normal_queue = [item for item in data["queue"] if item["priority"] == "normal"]
    vip_queue = [item for item in data["queue"] if item["priority"] == "vip"]
    reserved_queue = [item for item in data["queue"] if item["priority"] == "reserved"]
    return len(vip_queue), len(reserved_queue), len(normal_queue)


def get_effective_elapsed_seconds(bay, current_time):
    start = datetime.strptime(bay["start_time"], "%Y-%m-%d %H:%M:%S")
    total_paused = bay.get("total_paused_seconds", 0)
    if bay.get("paused") and bay.get("pause_start_time"):
        pause_start = datetime.strptime(bay["pause_start_time"], "%Y-%m-%d %H:%M:%S")
        total_paused += (current_time - pause_start).total_seconds()
    elapsed = (current_time - start).total_seconds() - total_paused
    return max(0.0, elapsed), total_paused


def get_total_duration_minutes(bay):
    base = WASH_DURATION_MINUTES
    extra = bay.get("extra_duration_minutes", 0)
    return base + extra


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
            total_dur = get_total_duration_minutes(bay)
            extra_paused = 0
            if bay.get("paused") and bay.get("pause_start_time"):
                pause_start = datetime.strptime(bay["pause_start_time"], "%Y-%m-%d %H:%M:%S")
                extra_paused = (current_time - pause_start).total_seconds()
            total_paused_sec = bay.get("total_paused_seconds", 0) + extra_paused
            free_at = start + timedelta(minutes=total_dur) + timedelta(seconds=total_paused_sec)
            if bay.get("paused"):
                free_at = free_at
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

    if not is_vip:
        reservation = find_valid_reservation(data, plate_number, require_checked_in=True)
        if reservation:
            priority = "reserved"

    if is_vip:
        priority = "vip"

    ticket = {
        "ticket_number": data["next_ticket_number"],
        "plate_number": plate_number,
        "is_vip": is_vip,
        "priority": priority,
        "take_time": now().strftime("%Y-%m-%d %H:%M:%S"),
        "is_reservation": reservation is not None,
        "is_skipped": False,
        "original_priority": priority,
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
        vip_pos = sum(1 for q in data["queue"][:actual_index] if q["priority"] == "vip") + 1
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


def skip_called_car(data, ticket_number_or_plate):
    for i, q in enumerate(data["queue"]):
        match = False
        try:
            tn = int(ticket_number_or_plate)
            if q["ticket_number"] == tn:
                match = True
        except (ValueError, TypeError):
            pass
        if q["plate_number"] == ticket_number_or_plate:
            match = True
        if match:
            skipped = data["queue"].pop(i)
            skipped["is_skipped"] = True
            skipped["skip_time"] = now().strftime("%Y-%m-%d %H:%M:%S")
            skipped["skip_count"] = skipped.get("skip_count", 0) + 1
            data["skipped_tickets"].append(skipped)
            save_data(data)
            return True, f"票号{skipped['ticket_number']:03d}({skipped['plate_number']}) 已过号，稍后可凭票号恢复"
    return False, "队列为空或未找到对应车辆"


def restore_skipped_car(data, ticket_number_or_plate):
    found_idx = None
    for i, t in enumerate(data["skipped_tickets"]):
        match = False
        try:
            tn = int(ticket_number_or_plate)
            if t["ticket_number"] == tn:
                match = True
        except (ValueError, TypeError):
            pass
        if t["plate_number"] == ticket_number_or_plate:
            match = True
        if match:
            found_idx = i
            break
    if found_idx is None:
        return False, "未找到过号记录"

    ticket = data["skipped_tickets"].pop(found_idx)
    ticket["is_skipped"] = False
    ticket["restore_time"] = now().strftime("%Y-%m-%d %H:%M:%S")
    priority = ticket.get("original_priority", ticket.get("priority", "normal"))
    ticket["priority"] = priority

    priority_order = {"vip": 0, "reserved": 1, "normal": 2}
    ticket_rank = priority_order.get(priority, 2)
    same_rank_list = [i for i, q in enumerate(data["queue"]) if priority_order.get(q["priority"], 2) == ticket_rank]
    if same_rank_list:
        insert_pos = same_rank_list[-1] + 1
    else:
        insert_pos = len(data["queue"])
        for i, existing in enumerate(data["queue"]):
            existing_rank = priority_order.get(existing["priority"], 2)
            if ticket_rank < existing_rank:
                insert_pos = i
                break

    data["queue"].insert(insert_pos, ticket)
    save_data(data)

    actual_index = next(
        (i for i, q in enumerate(data["queue"]) if q["ticket_number"] == ticket["ticket_number"]),
        insert_pos,
    )
    wait_info = get_detailed_wait_info(data, actual_index)

    return True, {
        "ticket_number": ticket["ticket_number"],
        "plate_number": ticket["plate_number"],
        "new_position": actual_index + 1,
        "priority": priority,
        "wait_minutes": wait_info["wait_minutes"] if wait_info else 0,
        "cars_ahead": wait_info["cars_ahead"] if wait_info else 0,
    }


def pause_bay(data, bay_number):
    bay_index = bay_number - 1
    bay = data["active_bays"][bay_index]
    if bay is None:
        return False, "该车位当前空闲，无法暂停"
    if bay.get("paused"):
        return False, "该车位已处于暂停状态"
    bay["paused"] = True
    bay["pause_start_time"] = now().strftime("%Y-%m-%d %H:%M:%S")
    save_data(data)
    return True, f"{bay_number}号车位已暂停，计时已冻结"


def resume_bay(data, bay_number):
    bay_index = bay_number - 1
    bay = data["active_bays"][bay_index]
    if bay is None:
        return False, "该车位当前空闲"
    if not bay.get("paused"):
        return False, "该车位未暂停"
    pause_start = datetime.strptime(bay["pause_start_time"], "%Y-%m-%d %H:%M:%S")
    paused_seconds = (now() - pause_start).total_seconds()
    bay["total_paused_seconds"] = bay.get("total_paused_seconds", 0) + paused_seconds
    bay["paused"] = False
    bay["pause_start_time"] = None
    save_data(data)
    paused_min = int(round(paused_seconds / 60))
    return True, f"{bay_number}号车位已恢复，本次暂停 {paused_min} 分钟"


def extend_bay_service(data, bay_number, extra_minutes):
    bay_index = bay_number - 1
    bay = data["active_bays"][bay_index]
    if bay is None:
        return False, "该车位当前空闲"
    if extra_minutes <= 0:
        return False, "延长时长必须为正数"
    bay["extra_duration_minutes"] = bay.get("extra_duration_minutes", 0) + extra_minutes
    save_data(data)
    total_extra = bay["extra_duration_minutes"]
    return True, f"{bay_number}号车位已延长服务 {extra_minutes} 分钟，累计延长 {total_extra} 分钟"


def call_next_car(data):
    if not data["queue"]:
        return False, "队列为空，没有等待的车辆"

    available_bay = None
    for i in range(WASH_BAYS):
        if data["active_bays"][i] is None:
            available_bay = i
            break

    if available_bay is None:
        busy_list = []
        for i in range(WASH_BAYS):
            bay = data["active_bays"][i]
            if bay:
                tag = "暂停中" if bay.get("paused") else "洗车中"
                busy_list.append(f"{i+1}号({bay['plate_number']} {tag})")
        return False, f"所有洗车位都在使用中: {', '.join(busy_list)}"

    next_car = data["queue"].pop(0)
    next_car["start_time"] = now().strftime("%Y-%m-%d %H:%M:%S")
    next_car["bay_number"] = available_bay + 1
    next_car["paused"] = False
    next_car["pause_start_time"] = None
    next_car["total_paused_seconds"] = 0
    next_car["extra_duration_minutes"] = 0
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
            elapsed_sec, _ = get_effective_elapsed_seconds(bay, current_time)
            total_dur = get_total_duration_minutes(bay)
            elapsed_minutes = int(elapsed_sec // 60)
            remaining_seconds = total_dur * 60 - elapsed_sec
            remaining_minutes = max(0, int(round(remaining_seconds / 60)))
            progress_pct = min(100, int(elapsed_sec / (total_dur * 60) * 100)) if total_dur > 0 else 100
            start = datetime.strptime(bay["start_time"], "%Y-%m-%d %H:%M:%S")
            extra_paused_sec = 0
            if bay.get("paused") and bay.get("pause_start_time"):
                ps = datetime.strptime(bay["pause_start_time"], "%Y-%m-%d %H:%M:%S")
                extra_paused_sec = (current_time - ps).total_seconds()
            total_paused_min = int(round((bay.get("total_paused_seconds", 0) + extra_paused_sec) / 60))
            estimated_end = start + timedelta(minutes=total_dur) + timedelta(seconds=bay.get("total_paused_seconds", 0) + extra_paused_sec)
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
                "paused": bay.get("paused", False),
                "total_paused_minutes": total_paused_min,
                "extra_duration_minutes": bay.get("extra_duration_minutes", 0),
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
    save_data(data)

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
        "member_balance_spent": stats.get("member_balance_spent", 0.0),
        "payment_breakdown": payment_breakdown,
        "non_member_washes": stats["total_washes"] - stats["member_washes"],
        "days_covered": 1,
    }


def get_range_report(data, start_date_str, end_date_str):
    try:
        start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date_str, "%Y-%m-%d")
    except ValueError:
        return False, "日期格式错误，请使用 YYYY-MM-DD"
    if start_dt > end_dt:
        return False, "开始日期不能晚于结束日期"

    merged = {
        "start_date": start_date_str,
        "end_date": end_date_str,
        "total_washes": 0,
        "member_washes": 0,
        "non_member_washes": 0,
        "cash_income": 0.0,
        "recharge_amount": 0.0,
        "member_balance_spent": 0.0,
        "total_income": 0.0,
        "promotion_count": 0,
        "wash_credits_used": 0,
        "payment_breakdown": {},
        "days_covered": 0,
        "daily_details": [],
    }

    days = (end_dt - start_dt).days + 1
    for d in range(days):
        date = (start_dt + timedelta(days=d)).strftime("%Y-%m-%d")
        report = get_daily_report(data, date)
        if report:
            merged["days_covered"] += 1
            merged["total_washes"] += report["total_washes"]
            merged["member_washes"] += report["member_washes"]
            merged["non_member_washes"] += report["non_member_washes"]
            merged["cash_income"] += report["cash_income"]
            merged["recharge_amount"] += report["recharge_amount"]
            merged["member_balance_spent"] += report["member_balance_spent"]
            merged["promotion_count"] += report["promotion_count"]
            merged["wash_credits_used"] += report["wash_credits_used"]
            for method, amount in report["payment_breakdown"].items():
                merged["payment_breakdown"][method] = merged["payment_breakdown"].get(method, 0.0) + amount
            merged["daily_details"].append({
                "date": date,
                "total_washes": report["total_washes"],
                "cash_income": report["cash_income"],
                "recharge_amount": report["recharge_amount"],
            })

    merged["total_income"] = merged["cash_income"] + merged["recharge_amount"]
    merged["days_total"] = days
    return True, merged


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
    print("\n" + "=" * 60)
    print("🚗  洗车店会员管理系统  🚗")
    print("=" * 60)
    print(" 1. 会员注册")
    print(" 2. 会员充值")
    print(" 3. 预约登记")
    print(" 4. 查看今日预约")
    print(" 5. 预约签到")
    print(" 6. 取号排队")
    print(" 7. 叫号洗车")
    print(" 8. 过号处理 / 恢复过号")
    print(" 9. 洗车位操作(暂停/继续/延长)")
    print("10. 完成洗车 & 结算")
    print("11. 查询洗车历史")
    print("12. 每日经营报表")
    print("13. 时间段经营报表")
    print("14. 导出会员列表(CSV)")
    print("15. 查看排队状态")
    print("16. 查看洗车位状态")
    print(" 0. 退出系统")
    print("=" * 60)


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
        choice = input("请选择操作 (0-16): ").strip()

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
                    status_map = {"pending": "待签到", "checked_in": "已签到待取号", "used": "已使用", "no_show": "已过期"}
                    st = status_map.get(res.get("status", "pending"), res.get("status", "未知"))
                    member_mark = "【会员】" if res.get("is_member") else ""
                    check_in_time = f" (签到:{res['check_in_time'][11:16]})" if res.get("check_in_time") else ""
                    print(f"  {i:2d}. {res['arrival_time'][5:16]} | {res['plate_number']} {member_mark}| {st}{check_in_time}")

        elif choice == "5":
            print("\n--- 预约签到 ---")
            plate = input("请输入预约车牌号签到: ").strip()
            if not plate:
                print("车牌号不能为空！")
                continue
            success, msg = check_in_reservation(data, plate)
            print(msg)

        elif choice == "6":
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

        elif choice == "7":
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

        elif choice == "8":
            print("\n--- 过号处理 / 恢复过号 ---")
            sub = input("   s=过号处理，r=恢复过号: ").strip().lower()
            if sub == "s":
                key = input("   请输入票号或车牌号标记过号: ").strip()
                ok, msg = skip_called_car(data, key)
                print(msg)
                if data["skipped_tickets"]:
                    print(f"   当前过号列表共 {len(data['skipped_tickets'])} 张：")
                    for t in data["skipped_tickets"]:
                        print(f"     票号{t['ticket_number']:03d} {t['plate_number']} (跳过{t.get('skip_count',1)}次)")
            elif sub == "r":
                key = input("   请输入票号或车牌号恢复: ").strip()
                ok, res = restore_skipped_car(data, key)
                if ok:
                    priority_cn = {"vip": "VIP", "reserved": "预约", "normal": "普通"}
                    print(f"✅ 恢复成功！票号{res['ticket_number']:03d} {res['plate_number']}")
                    print(f"   当前队列第{res['new_position']}位（{priority_cn.get(res['priority'],'普通')}优先级）")
                    print(f"   前面{res['cars_ahead']}台车，约等{res['wait_minutes']}分钟")
                else:
                    print(res)
            else:
                print("   未选择操作")

        elif choice == "9":
            print("\n--- 洗车位操作 ---")
            statuses = get_bay_status(data)
            for bs in statuses:
                if bs["is_busy"]:
                    state = "⏸暂停" if bs["paused"] else "▶进行中"
                    extra = f" 已延长+{bs['extra_duration_minutes']}分" if bs["extra_duration_minutes"] else ""
                    paused = f" 累计暂停{bs['total_paused_minutes']}分" if bs["total_paused_minutes"] else ""
                    print(f"  {bs['bay_number']}号: {state} | {bs['plate_number']} | 已洗{bs['elapsed_minutes']}分/剩{bs['remaining_minutes']}分{extra}{paused}")
                else:
                    print(f"  {bs['bay_number']}号: 空闲 ✅")
            bay_in = input(f"\n请输入车位号 (1-{WASH_BAYS}): ").strip()
            try:
                bay = int(bay_in)
            except ValueError:
                print("车位号无效")
                continue
            op = input("操作: p=暂停，r=继续，e=延长时长: ").strip().lower()
            if op == "p":
                ok, msg = pause_bay(data, bay)
                print(msg)
            elif op == "r":
                ok, msg = resume_bay(data, bay)
                print(msg)
            elif op == "e":
                mins_in = input("请输入延长分钟数: ").strip()
                try:
                    mins = int(mins_in)
                except ValueError:
                    print("请输入整数分钟数")
                    continue
                ok, msg = extend_bay_service(data, bay, mins)
                print(msg)
            else:
                print("未选择有效操作")

        elif choice == "10":
            print("\n--- 完成洗车 & 结算 ---")
            bay_statuses = get_bay_status(data)
            print("当前洗车位状态：")
            for bs in bay_statuses:
                if bs["is_busy"]:
                    state = "⏸暂停" if bs["paused"] else "▶进行中"
                    extra = f" 已延长+{bs['extra_duration_minutes']}分" if bs["extra_duration_minutes"] else ""
                    print(f"  {bs['bay_number']}号: {bs['plate_number']} {state} (已洗{bs['elapsed_minutes']}分/剩{bs['remaining_minutes']}分){extra}")
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

        elif choice == "11":
            print("\n--- 查询洗车历史 ---")
            plate = input("请输入车牌号: ").strip()
            history = get_wash_history(data, plate)
            if not history:
                print("未找到该车辆的洗车记录")
                continue
            print(f"\n📋  {plate} 最近洗车记录（最近5次）:")
            print("-" * 60)
            for i, record in enumerate(history, 1):
                member_mark = "会员" if record["is_member"] else "非会员"
                promotion_mark = "【促销半价】" if record.get("is_promotion") else ""
                print(f"{i}. {record['wash_time']} | {member_mark} | {record['payment_method']} | {record['price']:.2f}元 {promotion_mark}")

        elif choice == "12":
            print("\n--- 每日经营报表 ---")
            date_input = input("请输入日期 (YYYY-MM-DD，默认今天): ").strip()
            report = get_daily_report(data, date_input if date_input else None)
            if not report:
                print("该日期没有经营数据")
                continue
            print(f"\n📊  {report['date']} 经营报表")
            print("-" * 60)
            print(f"【洗车台数】")
            print(f"  总台数: {report['total_washes']}")
            print(f"  会员洗车: {report['member_washes']}")
            print(f"  非会员洗车: {report['non_member_washes']}")
            print(f"\n【收入统计】")
            print(f"  现金收入: {report['cash_income']:.2f} 元")
            print(f"  会员充值: {report['recharge_amount']:.2f} 元")
            print(f"  会员余额消费: {report['member_balance_spent']:.2f} 元")
            print(f"  当日总收入(现金+充值): {report['total_income']:.2f} 元")
            print(f"\n【优惠与抵扣】")
            print(f"  半价优惠次数: {report['promotion_count']} 次")
            print(f"  会员次数抵扣: {report['wash_credits_used']} 次")
            if report["payment_breakdown"]:
                print(f"\n【支付方式明细】")
                for method, amount in report["payment_breakdown"].items():
                    print(f"  {method}: {amount:.2f} 元")

        elif choice == "13":
            print("\n--- 时间段经营报表 ---")
            today = get_today_str()
            default_start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            s = input(f"开始日期 (YYYY-MM-DD，默认近7天 {default_start}): ").strip() or default_start
            e = input(f"结束日期 (YYYY-MM-DD，默认今天 {today}): ").strip() or today
            ok, report = get_range_report(data, s, e)
            if not ok:
                print(report)
                continue
            print(f"\n📊  {report['start_date']} 至 {report['end_date']} 经营汇总")
            print(f"    共计 {report['days_total']} 天，其中 {report['days_covered']} 天有数据")
            print("-" * 60)
            print(f"【洗车台数】")
            print(f"  总台数: {report['total_washes']}")
            print(f"  会员洗车: {report['member_washes']}")
            print(f"  非会员洗车: {report['non_member_washes']}")
            print(f"\n【收入统计】")
            print(f"  现金收入: {report['cash_income']:.2f} 元")
            print(f"  会员充值: {report['recharge_amount']:.2f} 元")
            print(f"  会员余额消费: {report['member_balance_spent']:.2f} 元")
            print(f"  总收入(现金+充值): {report['total_income']:.2f} 元")
            print(f"\n【优惠与抵扣】")
            print(f"  半价优惠次数: {report['promotion_count']} 次")
            print(f"  会员次数抵扣: {report['wash_credits_used']} 次")
            if report["payment_breakdown"]:
                print(f"\n【支付方式明细(全周期)】")
                for method, amount in report["payment_breakdown"].items():
                    print(f"  {method}: {amount:.2f} 元")
            if report.get("daily_details"):
                print(f"\n【每日明细】")
                print(f"  {'日期':12s} {'台数':>5s} {'现金':>10s} {'充值':>10s}")
                for d in report["daily_details"]:
                    print(f"  {d['date']:12s} {d['total_washes']:>5d} {d['cash_income']:>10.2f} {d['recharge_amount']:>10.2f}")

        elif choice == "14":
            print("\n--- 导出会员列表 ---")
            filename = input("请输入导出文件名(默认members.csv): ").strip()
            if not filename:
                filename = "members.csv"
            if not filename.endswith(".csv"):
                filename += ".csv"
            success, msg = export_members_csv(data, filename)
            print(msg)

        elif choice == "15":
            print("\n--- 排队状态 ---")
            total_waiting, wait_minutes = get_wait_time(data)
            vip_c, res_c, norm_c = get_queue_position(data)
            print(f"当前排队总人数: {total_waiting} 人")
            print(f"  VIP排队: {vip_c} 人")
            if res_c:
                print(f"  预约排队: {res_c} 人")
            print(f"  普通排队: {norm_c} 人")
            print(f"队尾预计等待: 约 {wait_minutes} 分钟")
            if data["skipped_tickets"]:
                print(f"过号未恢复: {len(data['skipped_tickets'])} 张")
                for t in data["skipped_tickets"]:
                    print(f"  票号{t['ticket_number']:03d} {t['plate_number']} (跳过{t.get('skip_count',1)}次)")
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

        elif choice == "16":
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
                    state_str = "⏸ 暂停中" if bs["paused"] else "▶ 洗车中"
                    extra_info = []
                    if bs["extra_duration_minutes"]:
                        extra_info.append(f"已延长+{bs['extra_duration_minutes']}分")
                    if bs["total_paused_minutes"]:
                        extra_info.append(f"累计暂停{bs['total_paused_minutes']}分")
                    extra_str = f" ({', '.join(extra_info)})" if extra_info else ""
                    bar_len = 20
                    filled = int(bs["progress_pct"] / 100 * bar_len)
                    bar = "█" * filled + "░" * (bar_len - filled)
                    print(f"  {bs['bay_number']}号车位: {state_str}{extra_str}")
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
