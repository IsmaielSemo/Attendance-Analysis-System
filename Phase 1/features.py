# features.py -> Describes the features that will be used in ML

from collections import defaultdict
from statistics import mean, stdev

from attendance import (
    clean_records,
    group_records,
    get_first_in,
    get_last_out,
    detect_missing_pairs
)

# ==========================================================
# CONSTANTS
# ==========================================================
WORK_START = 9 * 60  # 09:00
WORK_END = 17 * 60  # 17:00
LATE_THRESHOLD = 15  # minutes
EARLY_THRESHOLD = 15  # minutes
SHORT_DAY = 4 * 60  # 4 hours
LONG_DAY = 10 * 60  # 10 hours


# ==========================================================
# UTILITIES
# ==========================================================
def to_minutes(dt):
    """Converts datetime -> minutes after midnight."""
    return dt.hour * 60 + dt.minute


def duration_minutes(start, end):
    """Returns duration in minutes if both timestamps exist."""
    if start is None or end is None:
        return None
    return int((end - start).total_seconds() / 60)


def safe_div(n, d):
    """Prevents division by zero errors."""
    return n / d if d else 0.0


def group_by_employee(records):
    employees = defaultdict(list)
    for record in records:
        employees[record.BadgeID].append(record)
    return employees


# ==========================================================
# BUILD DAILY INFORMATION
# ==========================================================
def build_daily_information(records):
    """Produces one summary per employee per day."""
    records = clean_records(records)
    grouped = group_records(records)
    daily = defaultdict(list)

    for (badge, day), rows in grouped.items():
        rows = sorted(rows, key=lambda r: r.Datetime)
        first = get_first_in(rows)
        last = get_last_out(rows)
        duration = duration_minutes(
            first.Datetime if first else None,
            last.Datetime if last else None
        )

        daily[badge].append({
            "date": day,
            "first_in": first,
            "last_out": last,
            "duration": duration,
            "punches": len(rows)
        })
    return daily


# ==========================================================
# BUILD ML FEATURES
# ==========================================================
def build_features(records):
    """Calculates statistical features for the ML model."""
    daily_info = build_daily_information(records)
    raw_alerts = detect_missing_pairs(records)

    employee_alerts = defaultdict(lambda: {
        "MissingIN": 0, "MissingOUT": 0, "DuplicateIN": 0, "DuplicateOUT": 0
    })

    for alert in raw_alerts:
        badge = alert["BadgeID"]
        problem = alert["Problem"]
        if "Expected IN" in problem:
            employee_alerts[badge]["MissingIN"] += 1
        elif "Expected OUT" in problem or "Missing OUT" in problem:
            employee_alerts[badge]["MissingOUT"] += 1

    feature_vectors = []

    for badge, days in daily_info.items():
        arrivals, departures, durations, punches = [], [], [], []
        late_days, early_leave_days, short_days, long_days, weekend_days = 0, 0, 0, 0, 0

        working_days = len(days)

        for d in days:
            punches.append(d["punches"])
            if d["date"].weekday() in [4, 5]:  # 4=Friday, 5=Saturday
                weekend_days += 1

            if d["first_in"]:
                arr_min = to_minutes(d["first_in"].Datetime)
                arrivals.append(arr_min)
                if arr_min > WORK_START + LATE_THRESHOLD:
                    late_days += 1

            if d["last_out"]:
                dep_min = to_minutes(d["last_out"].Datetime)
                departures.append(dep_min)
                if dep_min < WORK_END - EARLY_THRESHOLD:
                    early_leave_days += 1

            if d["duration"] is not None:
                durations.append(d["duration"])
                if d["duration"] < SHORT_DAY:
                    short_days += 1
                elif d["duration"] > LONG_DAY:
                    long_days += 1

        avg_arrival = round(mean(arrivals), 2) if arrivals else 0
        arr_std = round(stdev(arrivals), 2) if len(arrivals) > 1 else 0

        avg_departure = round(mean(departures), 2) if departures else 0

        avg_duration = round(mean(durations), 2) if durations else 0
        dur_std = round(stdev(durations), 2) if len(durations) > 1 else 0

        total_missing = employee_alerts[badge]["MissingIN"] + employee_alerts[badge]["MissingOUT"]

        # RATIOS AND COEFFICIENTS (Data-Driven ML Inputs)
        feature_vectors.append({
            "BadgeID": badge,
            "WorkingDays": working_days,

            # Raw Means
            "AverageArrival": avg_arrival,
            "AverageDeparture": avg_departure,
            "AverageDuration": avg_duration,

            # Relative Variance (Coefficient of Variation)
            "ArrivalCV": safe_div(arr_std, avg_arrival),
            "DurationCV": safe_div(dur_std, avg_duration),

            # Ratios (Scales dynamically regardless of days worked)
            "LateRatio": safe_div(late_days, working_days),
            "EarlyRatio": safe_div(early_leave_days, working_days),
            "ShortDayRatio": safe_div(short_days, working_days),
            "LongDayRatio": safe_div(long_days, working_days),
            "WeekendRatio": safe_div(weekend_days, working_days),
            "MissingPunchRatio": safe_div(total_missing, working_days * 2)
        })

    return feature_vectors


# ==========================================================
# FEATURE MATRIX
# ==========================================================
def feature_matrix(records):
    """Returns Employee IDs and Numerical matrix suitable for sklearn."""
    features = build_features(records)
    ids, X = [], []

    for emp in features:
        ids.append(emp["BadgeID"])
        # Only feeding the normalized ratios and continuous variables to the ML
        X.append([
            emp["AverageArrival"],
            emp["AverageDeparture"],
            emp["AverageDuration"],
            emp["ArrivalCV"],
            emp["DurationCV"],
            emp["LateRatio"],
            emp["EarlyRatio"],
            emp["ShortDayRatio"],
            emp["LongDayRatio"],
            emp["WeekendRatio"],
            emp["MissingPunchRatio"]
        ])

    return ids, X
