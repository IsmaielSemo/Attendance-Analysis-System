# attendance.py -> Logic of the project

from collections import defaultdict
from statistics import mean
from datetime import datetime


def safe_date_str(dt_val):
    if not dt_val: return None
    return dt_val.strftime('%Y-%m-%d') if isinstance(dt_val, datetime) else str(dt_val).split(' ')[0]


def safe_time_sort(dt_val):
    return dt_val if isinstance(dt_val, datetime) else datetime.min


def clean_records(records):
    grouped = defaultdict(list)
    for record in records:
        day_str = safe_date_str(record.Datetime)
        if day_str:
            key = (record.BadgeID, day_str)
            grouped[key].append(record)

    cleaned = []
    for key in grouped:
        day_records = sorted(grouped[key], key=lambda x: safe_time_sort(x.Datetime))
        if not day_records:
            continue

        cleaned.append(day_records[0])
        previous_record = day_records[0]

        for current_record in day_records[1:]:
            status = str(current_record.InOut).strip().upper()
            prev_status = str(previous_record.InOut).strip().upper()

            if status != prev_status:
                cleaned.append(current_record)
                previous_record = current_record
            else:
                # INSTANT NATIVE MATH (No Pandas)
                diff = (current_record.Datetime - previous_record.Datetime).total_seconds()
                if diff > 300:
                    cleaned.append(current_record)
                    previous_record = current_record

    cleaned.sort(key=lambda x: (x.BadgeID, safe_time_sort(x.Datetime)))
    return cleaned


def group_records(records):
    grouped = defaultdict(list)
    for record in records:
        day_str = safe_date_str(record.Datetime)
        if day_str:
            key = (record.BadgeID, day_str)
            grouped[key].append(record)
    return grouped


def get_first_in(records):
    if not records: return None
    in_punches = [r for r in records if 'IN' in str(r.InOut).upper()]
    if not in_punches: return None
    return min(in_punches, key=lambda x: safe_time_sort(x.Datetime))


def get_last_out(records):
    if not records: return None
    out_punches = [r for r in records if 'OUT' in str(r.InOut).upper()]
    if not out_punches: return None
    return max(out_punches, key=lambda x: safe_time_sort(x.Datetime))


def format_records(records):
    output = []
    for record in records:
        output.append({
            "BadgeID": record.BadgeID,
            "Datetime": record.Datetime,
            "Status": str(record.InOut).strip(),
            "Branch": str(record.Branch).strip() if record.Branch else ""
        })
    return output


def calculate_time_inside(records):
    records = clean_records(records)
    grouped = group_records(records)
    time_summary = []

    for (badge, day) in sorted(grouped.keys()):
        day_records = sorted(grouped[(badge, day)], key=lambda x: safe_time_sort(x.Datetime))

        total_seconds = 0
        current_in_time = None  # This is our "lock"

        for record in day_records:
            status = str(record.InOut).upper().strip()

            if status == "IN":
                # Only set the IN time if we aren't already waiting for an OUT
                if current_in_time is None:
                    current_in_time = record.Datetime
                # If current_in_time is already set, it ignores this extra IN entirely!

            elif status == "OUT":
                # Only do the math if we have a locked IN time
                if current_in_time is not None:
                    diff = (record.Datetime - current_in_time).total_seconds()
                    total_seconds += diff
                    current_in_time = None  # Reset the lock for the next pair (e.g., after lunch)

        hours, remainder = divmod(int(total_seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        formatted_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        time_summary.append({
            "BadgeID": badge,
            "Date": day,
            "TotalTimeInside": formatted_time,
            "TotalSeconds": int(total_seconds)
        })

    return time_summary


def create_daily_summary(records):
    raw_grouped = group_records(records)
    cleaned = clean_records(records)
    clean_grouped = group_records(cleaned)

    # 1. Pull the time inside data mapping using your robust function
    time_inside_data = calculate_time_inside(records)

    # 2. Convert it to a fast dictionary lookup mapping (Badge, Date) -> HH:MM:SS
    time_map = {(item['BadgeID'], item['Date']): item['TotalTimeInside'] for item in time_inside_data}

    summary = []
    for (badge, day) in sorted(raw_grouped.keys()):
        raw_day_records = raw_grouped[(badge, day)]
        first_in = get_first_in(raw_day_records)
        last_out = get_last_out(raw_day_records)
        clean_day_records = clean_grouped.get((badge, day), [])

        # 3. Safely pull the calculated time, defaulting to 0 if they missed a punch
        total_time = time_map.get((badge, day), "00:00:00")

        summary.append({
            "BadgeID": badge,
            "Date": day,
            "FirstIn": first_in.Datetime if first_in else None,
            "LastOut": last_out.Datetime if last_out else None,
            "TotalTime": total_time,
            "Punches": len(clean_day_records)
        })

    return summary


def create_overall_summary(records):
    raw_employees = defaultdict(list)
    for record in records:
        raw_employees[record.BadgeID].append(record)

    cleaned = clean_records(records)
    clean_employees = defaultdict(list)
    for record in cleaned:
        clean_employees[record.BadgeID].append(record)

    summary = []
    for badge in sorted(raw_employees.keys()):
        raw_employee_records = raw_employees[badge]
        first_in = get_first_in(raw_employee_records)
        last_out = get_last_out(raw_employee_records)
        clean_employee_records = clean_employees.get(badge, [])
        working_days = len({safe_date_str(r.Datetime) for r in clean_employee_records if safe_date_str(r.Datetime)})

        summary.append({
            "BadgeID": badge,
            "WorkingDays": working_days,
            "TotalPunches": len(clean_employee_records),
            "FirstEntry": first_in.Datetime if first_in else None,
            "LastExit": last_out.Datetime if last_out else None
        })

    return summary


def detect_missing_pairs(records):
    records = clean_records(records)
    grouped = group_records(records)

    warnings = []
    for (badge, day), day_records in sorted(grouped.items()):
        day_records.sort(key=lambda r: safe_time_sort(r.Datetime))
        if not day_records:
            continue

        first = day_records[0]
        if "OUT" in str(first.InOut).upper():
            warnings.append({"BadgeID": badge, "Date": day, "Datetime": first.Datetime, "Problem": "Missing IN"})

        last = day_records[-1]
        if "IN" in str(last.InOut).upper():
            warnings.append({"BadgeID": badge, "Date": day, "Datetime": last.Datetime, "Problem": "Missing OUT"})

        previous = None
        for record in day_records:
            status = str(record.InOut).strip().upper()
            if previous == status:
                warnings.append(
                    {"BadgeID": badge, "Date": day, "Datetime": record.Datetime, "Problem": f"Duplicate {status}"})
            previous = status

    return warnings


def employee_statistics(records):
    if not records:
        return {
            "Employees": 0, "WorkingDays": 0, "TotalPunches": 0,
            "AveragePunchesPerDay": 0, "AverageArrival": None, "AverageDeparture": None
        }

    raw_grouped = group_records(records)
    cleaned = clean_records(records)
    first_arrivals = []
    last_departures = []

    for key, day_records in raw_grouped.items():
        first = get_first_in(day_records)
        last = get_last_out(day_records)

        if first and first.Datetime:
            first_arrivals.append(first.Datetime.hour * 60 + first.Datetime.minute)
        if last and last.Datetime:
            last_departures.append(last.Datetime.hour * 60 + last.Datetime.minute)

    def minutes_to_time(val):
        if val is None:
            return None
        return f"{int(val) // 60:02d}:{int(val) % 60:02d}"

    employees = {r.BadgeID for r in cleaned}
    unique_dates = {safe_date_str(r.Datetime) for r in cleaned if safe_date_str(r.Datetime)}
    total_employee_days = len({(r.BadgeID, safe_date_str(r.Datetime)) for r in cleaned if safe_date_str(r.Datetime)})

    return {
        "Employees": len(employees),
        "WorkingDays": len(unique_dates),
        "TotalPunches": len(cleaned),
        "AveragePunchesPerDay": round(len(cleaned) / total_employee_days, 2) if total_employee_days else 0,
        "AverageArrival": minutes_to_time(mean(first_arrivals)) if first_arrivals else None,
        "AverageDeparture": minutes_to_time(mean(last_departures)) if last_departures else None
    }


def get_employee_list(records):
    return sorted({r.BadgeID for r in records})