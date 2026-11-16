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
    """
    Removes exact duplicate transactions only.
    Does not remove punches based on time intervals or IN/OUT status.
    """

    seen = set()
    cleaned = []

    for record in records:

        ident = (
            record.BadgeID,
            record.Datetime,
            record.InOut,
            record.Branch,
            getattr(record, 'VerifyMode', 'N/A')
        )

        if ident in seen:
            continue

        seen.add(ident)
        cleaned.append(record)

    cleaned.sort(
        key=lambda x: (x.BadgeID, safe_time_sort(x.Datetime))
    )

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


def format_records(raw_records):
    """
    Formats raw database records into a clean list of dictionaries for the template.
    """
    formatted = []
    for r in raw_records:
        # Check if VerifyMode is present on the record namedtuple/object
        verify_mode = getattr(r, 'VerifyMode', 'N/A')
        if not verify_mode or verify_mode.strip() == '':
            verify_mode = 'N/A'

        formatted.append({
            'BadgeID': r.BadgeID,
            'Datetime': r.Datetime.strftime("%Y-%m-%d %H:%M:%S") if hasattr(r.Datetime, 'strftime') else str(r.Datetime),
            'InOut': r.InOut,
            'Branch': r.Branch,
            'VerifyMode': verify_mode
        })
    return formatted


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



def create_daily_summary(raw_records):
    """
    Creates daily summaries with first IN, last OUT,
    their verification methods, and total punch count.
    """

    daily_data = {}

    for r in raw_records:

        badge_id = r.BadgeID
        dt = r.Datetime
        in_out = str(r.InOut).upper().strip()

        verify_mode = getattr(r, 'VerifyMode', 'N/A')

        if not verify_mode:
            verify_mode = 'N/A'

        day_str = (
            dt.strftime("%Y-%m-%d")
            if hasattr(dt, 'strftime')
            else str(dt).split()[0]
        )

        time_str = (
            dt.strftime("%H:%M:%S")
            if hasattr(dt, 'strftime')
            else str(dt)
        )

        key = (badge_id, day_str)

        if key not in daily_data:

            daily_data[key] = {
                'BadgeID': badge_id,
                'Date': day_str,
                'FirstIn': '-',
                'FirstInMethod': 'N/A',
                'LastOut': '-',
                'LastOutMethod': 'N/A',
                'Punches': 0
            }

        daily_data[key]['Punches'] += 1

        if in_out == 'IN':

            if (
                daily_data[key]['FirstIn'] == '-'
                or time_str < daily_data[key]['FirstIn']
            ):

                daily_data[key]['FirstIn'] = time_str
                daily_data[key]['FirstInMethod'] = verify_mode

        elif in_out == 'OUT':

            if (
                daily_data[key]['LastOut'] == '-'
                or time_str > daily_data[key]['LastOut']
            ):

                daily_data[key]['LastOut'] = time_str
                daily_data[key]['LastOutMethod'] = verify_mode

    return list(daily_data.values())


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