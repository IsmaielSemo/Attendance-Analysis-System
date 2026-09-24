# features.py -> Describes the features that will be used in ML
#
# Design decisions:
# 1. Utilizes exact `calculate_time_inside` logic from attendance.py to model
#    actual time worked inside the facility, ignoring off-site lunch/breaks.
# 2. Continuous deviation instead of binary flags.
# 3. Coefficient of Variation (CV) for consistency relative to the employee's own mean.
# 4. Compares data against cluster peers rather than hardcoded global shift definitions.

from collections import defaultdict
from statistics import mean, stdev
from datetime import datetime

# Adjusted based on standard 9-hour workday + 1hr offshoot
SHORT_DAY = 6.5 * 60  # Less than 6.5 hours inside is a short day
LONG_DAY = 10.5 * 60  # More than 10.5 hours inside is a long day

from attendance import calculate_time_inside


def to_minutes(dt_obj):
    if isinstance(dt_obj, str):
        formats = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S"]
        for fmt in formats:
            try:
                dt_obj = datetime.strptime(dt_obj, fmt)
                break
            except ValueError:
                continue
        else:
            return 0
    return dt_obj.hour * 60 + dt_obj.minute


def safe_div(n, d):
    return n / d if d and d != 0 else 0.0


def _to_datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        formats = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S"]
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


def build_daily_information(records):
    daily_info = defaultdict(lambda: defaultdict(list))

    for r in records:
        badge = r.BadgeID
        dt = _to_datetime(r.Datetime)
        if dt is None:
            continue
        date_key = dt.date()
        daily_info[badge][date_key].append(r)

    processed_info = defaultdict(list)

    for badge, days in daily_info.items():
        for date_key, day_records in days.items():
            day_records.sort(key=lambda x: _to_datetime(x.Datetime) or datetime.min)

            in_records = [r for r in day_records if str(r.InOut).upper().strip() == "IN"]
            out_records = [r for r in day_records if str(r.InOut).upper().strip() == "OUT"]

            first_in = in_records[0] if in_records else None
            last_out = out_records[-1] if out_records else None

            processed_info[badge].append({
                "date": date_key,
                "first_in": first_in,
                "last_out": last_out,
                "punches": len(day_records),
            })

    return processed_info


def build_features(records, missing_pairs_alerts=None):
    if missing_pairs_alerts is None:
        missing_pairs_alerts = []

    daily_info = build_daily_information(records)

    # Extract exact time inside logic from attendance.py
    time_inside_data = calculate_time_inside(records)
    time_map = {(str(t["BadgeID"]), str(t["Date"])): (t["TotalSeconds"] / 60.0) for t in time_inside_data}

    employee_alerts = defaultdict(lambda: {"MissingIN": 0, "MissingOUT": 0})
    for alert in missing_pairs_alerts:
        badge = str(alert.get("BadgeID"))
        problem = alert.get("Problem", "")
        if "Missing IN" in problem:
            employee_alerts[badge]["MissingIN"] += 1
        elif "Missing OUT" in problem:
            employee_alerts[badge]["MissingOUT"] += 1

    feature_vectors = []

    for badge, days in daily_info.items():
        arrivals = []
        departures = []
        durations = []
        punches = []
        weekend_days = 0
        short_days = 0
        long_days = 0

        working_days = len(days)
        badge_str = str(badge)

        for d in days:
            punches.append(d["punches"])
            date_str = d["date"].strftime('%Y-%m-%d')

            if d["date"].weekday() in (4, 5):
                weekend_days += 1

            if d["first_in"]:
                arr_min = to_minutes(d["first_in"].Datetime)
                arrivals.append(arr_min)

            if d["last_out"]:
                dep_min = to_minutes(d["last_out"].Datetime)
                departures.append(dep_min)

            # Map the exact calculated seconds inside the building to this shift
            exact_duration = time_map.get((badge_str, date_str))
            if exact_duration is not None and exact_duration > 0:
                durations.append(exact_duration)
                if exact_duration < SHORT_DAY:
                    short_days += 1
                elif exact_duration > LONG_DAY:
                    long_days += 1

        avg_arrival = round(mean(arrivals), 2) if arrivals else 0.0
        avg_departure = round(mean(departures), 2) if departures else 0.0
        avg_duration = round(mean(durations), 2) if durations else 0.0

        arr_std = round(stdev(arrivals), 2) if len(arrivals) > 1 else 0.0
        dep_std = round(stdev(departures), 2) if len(departures) > 1 else 0.0
        dur_std = round(stdev(durations), 2) if len(durations) > 1 else 0.0

        arrival_cv = safe_div(arr_std, avg_arrival)
        departure_cv = safe_div(dep_std, avg_departure)
        duration_cv = safe_div(dur_std, avg_duration)

        total_missing = employee_alerts[badge_str]["MissingIN"] + employee_alerts[badge_str]["MissingOUT"]

        missing_ratio = safe_div(total_missing, working_days * 2)
        short_day_ratio = safe_div(short_days, working_days)
        long_day_ratio = safe_div(long_days, working_days)
        weekend_ratio = safe_div(weekend_days, working_days)
        avg_punches_day = safe_div(sum(punches), working_days)

        feature_vectors.append({
            "BadgeID": badge,
            "WorkingDays": working_days,
            "AverageArrival": avg_arrival,
            "AverageDeparture": avg_departure,
            "AverageDuration": avg_duration,
            "ArrivalCV": arrival_cv,
            "DepartureCV": departure_cv,
            "DurationCV": duration_cv,
            "ShortDayRatio": short_day_ratio,
            "LongDayRatio": long_day_ratio,
            "WeekendRatio": weekend_ratio,
            "AvgPunchesPerDay": avg_punches_day,
            "MissingPunchRatio": missing_ratio,
        })

    return feature_vectors


def feature_matrix(records, missing_pairs_alerts=None):
    features = build_features(records, missing_pairs_alerts)

    ids = []
    X = []

    for emp in features:
        ids.append(emp["BadgeID"])
        X.append([
            emp["AverageArrival"],
            emp["AverageDeparture"],
            emp["AverageDuration"],
            emp["ArrivalCV"],
            emp["DepartureCV"],
            emp["DurationCV"],
            emp["ShortDayRatio"],
            emp["LongDayRatio"],
            emp["WeekendRatio"],
        ])

    return ids, X