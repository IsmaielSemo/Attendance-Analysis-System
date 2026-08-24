# features.py -> Describes the features that will be used in ML

from collections import defaultdict
from statistics import mean, stdev
from datetime import datetime

# ==========================================================
# CONSTANTS
# Default schedule used to compute deviation.
# These are not hard cutoffs — employees are compared to
# their cluster peers, not to these absolute values.
# ==========================================================

WORK_START = 9 * 60   # 09:00 in minutes
WORK_END   = 17 * 60  # 17:00 in minutes
SHORT_DAY  = 4 * 60   # 4 hours in minutes
LONG_DAY   = 10 * 60  # 10 hours in minutes


# ==========================================================
# TIME UTILITIES
# ==========================================================

def to_datetime(value):
    """
    Converts a value to a datetime object.
    Supports datetime objects and common string formats.
    """
    if isinstance(value, datetime):
        return value

    if isinstance(value, str):
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%m/%d/%Y %H:%M:%S",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue

    return None


def to_minutes(value):
    """Converts a datetime to minutes after midnight."""
    dt = to_datetime(value)
    if dt is None:
        return 0
    return dt.hour * 60 + dt.minute


def safe_div(numerator, denominator):
    """Safe division — returns 0.0 if denominator is zero."""
    if denominator is None or denominator == 0:
        return 0.0
    return numerator / denominator


# ==========================================================
# BUILD DAILY INFORMATION
# One summary record per employee per day.
# Uses FIRST IN and LAST OUT to capture overall attendance
# behavior rather than individual punch noise.
# ==========================================================

def build_daily_information(records):
    daily_info = defaultdict(lambda: defaultdict(list))

    for record in records:
        badge = record.BadgeID
        dt    = to_datetime(record.Datetime)
        if dt is None:
            continue
        daily_info[badge][dt.date()].append(record)

    processed_info = defaultdict(list)

    for badge, days in daily_info.items():
        for date_key, day_records in days.items():
            day_records.sort(key=lambda x: to_datetime(x.Datetime))

            in_records  = [r for r in day_records if str(r.InOut).upper().strip() == "IN"]
            out_records = [r for r in day_records if str(r.InOut).upper().strip() == "OUT"]

            first_in = in_records[0]   if in_records  else None
            last_out = out_records[-1] if out_records else None

            duration = None
            if first_in is not None and last_out is not None:
                first_dt = to_datetime(first_in.Datetime)
                last_dt  = to_datetime(last_out.Datetime)
                if first_dt is not None and last_dt is not None:
                    duration = (last_dt - first_dt).total_seconds() / 60.0
                    if duration < 0:
                        duration = None  # drop invalid negative durations

            processed_info[badge].append({
                "date"    : date_key,
                "first_in": first_in,
                "last_out": last_out,
                "duration": duration,
                "punches" : len(day_records),
            })

    return processed_info


# ==========================================================
# FEATURE GENERATION
# One feature vector per employee.
#
# Design decisions:
# - ArrivalStd / DepartureStd instead of CV
#   CV = std/mean only works for ratio data where 0 means nothing.
#   Time of day is interval data — midnight is arbitrary.
#   Dividing by avg_arrival inflates CV for night shift workers
#   who arrive near midnight. Raw std is mathematically correct.
#
# - DurationCV kept (not DurationStd)
#   Duration 0 genuinely means zero minutes worked —
#   ratio data where CV is valid.
#
# - MissingPunchRatio and AvgPunchesPerDay excluded from ML matrix
#   They dominate StandardScaler when most employees have 0
#   missing punches and a few have many — turning the SVM into
#   a missing-punch detector instead of a behavior detector.
#   Both are kept in build_features for explanation purposes only.
# ==========================================================

def build_features(records, missing_pairs_alerts=None):
    if missing_pairs_alerts is None:
        missing_pairs_alerts = []

    daily_info = build_daily_information(records)

    # Count missing punches per employee
    employee_alerts = defaultdict(lambda: {"MissingIN": 0, "MissingOUT": 0})
    for alert in missing_pairs_alerts:
        badge   = alert.get("BadgeID")
        problem = str(alert.get("Problem", ""))
        if "Missing IN"  in problem:
            employee_alerts[badge]["MissingIN"]  += 1
        elif "Missing OUT" in problem:
            employee_alerts[badge]["MissingOUT"] += 1

    feature_vectors = []

    for badge, days in daily_info.items():
        arrivals    = []
        departures  = []
        durations   = []
        punches     = []
        weekend_days = 0
        short_days   = 0
        long_days    = 0
        working_days = len(days)

        for day in days:
            punches.append(day["punches"])

            # Egypt workweek: Friday=4, Saturday=5
            if day["date"].weekday() in (4, 5):
                weekend_days += 1

            if day["first_in"] is not None:
                arrivals.append(to_minutes(day["first_in"].Datetime))

            if day["last_out"] is not None:
                departures.append(to_minutes(day["last_out"].Datetime))

            if day["duration"] is not None:
                durations.append(day["duration"])
                if day["duration"] < SHORT_DAY:
                    short_days += 1
                elif day["duration"] > LONG_DAY:
                    long_days  += 1

        # Core averages
        avg_arrival   = round(mean(arrivals),   2) if arrivals   else 0.0
        avg_departure = round(mean(departures), 2) if departures else 0.0
        avg_duration  = round(mean(durations),  2) if durations  else 0.0

        # Raw standard deviation (mathematically correct for time of day)
        arrival_std   = round(stdev(arrivals),   2) if len(arrivals)   > 1 else 0.0
        departure_std = round(stdev(departures), 2) if len(departures) > 1 else 0.0
        duration_std  = round(stdev(durations),  2) if len(durations)  > 1 else 0.0

        # DurationCV valid since duration 0 = zero minutes worked
        duration_cv = safe_div(duration_std, avg_duration)

        # Deviation from default schedule (continuous, preserves magnitude)
        avg_arrival_deviation   = avg_arrival   - WORK_START
        avg_departure_deviation = avg_departure - WORK_END

        # Reliability
        missing_in    = employee_alerts[badge]["MissingIN"]
        missing_out   = employee_alerts[badge]["MissingOUT"]
        total_missing = missing_in + missing_out

        feature_vectors.append({
            "BadgeID"              : badge,
            "WorkingDays"          : working_days,

            # Absolute averages
            "AverageArrival"       : avg_arrival,
            "AverageDeparture"     : avg_departure,
            "AverageDuration"      : avg_duration,

            # Deviation from default 9-17 schedule
            "AvgArrivalDeviation"  : avg_arrival_deviation,
            "AvgDepartureDeviation": avg_departure_deviation,

            # Consistency — raw std (not CV) for time features
            "ArrivalStd"           : arrival_std,
            "DepartureStd"         : departure_std,

            # Consistency — CV valid for duration
            "DurationCV"           : duration_cv,

            # Shift length flags
            "ShortDayRatio"        : safe_div(short_days,   working_days),
            "LongDayRatio"         : safe_div(long_days,    working_days),

            # Presence
            "WeekendRatio"         : safe_div(weekend_days, working_days),

            # Excluded from ML matrix — kept for explanation use only
            "AvgPunchesPerDay"     : safe_div(sum(punches), working_days),
            "MissingPunchRatio"    : safe_div(total_missing, working_days * 2),
            "MissingIN"            : missing_in,
            "MissingOUT"           : missing_out,
            "TotalMissingPunches"  : total_missing,
            "WeekendDays"          : weekend_days,
            "ShortDays"            : short_days,
            "LongDays"             : long_days,
        })

    return feature_vectors


# ==========================================================
# FEATURE MATRIX (from raw records)
# Kept for backward compatibility.
# Internally calls build_features then feature_matrix_from_features.
# ==========================================================

def feature_matrix(records, missing_pairs_alerts=None):
    features = build_features(records, missing_pairs_alerts)
    return feature_matrix_from_features(features)


# ==========================================================
# FEATURE MATRIX FROM PRE-BUILT FEATURES
# Use this in detect_anomalies to avoid calling build_features
# twice (which caused the quality gate to be bypassed).
#
# The bug: detect_anomalies called build_features() once to
# get features for the quality gate, then called feature_matrix()
# which internally called build_features() again — producing a
# fresh unfiltered list that was used for X. The quality gate
# filtered features but not X, causing employees like 3209
# (only IN records, no valid duration) to slip through.
# ==========================================================

def feature_matrix_from_features(features):
    """
    Builds the sklearn-compatible numerical matrix directly
    from an already-computed feature list.

    Excluded from matrix (data quality signals, not behavior):
    - MissingPunchRatio
    - AvgPunchesPerDay
    """
    ids = []
    X   = []

    for employee in features:
        ids.append(employee["BadgeID"])
        X.append([
            employee["AverageArrival"],
            employee["AverageDeparture"],
            employee["AverageDuration"],
            employee["AvgArrivalDeviation"],
            employee["AvgDepartureDeviation"],
            employee["ArrivalStd"],       # raw std, not CV
            employee["DepartureStd"],     # raw std, not CV
            employee["DurationCV"],       # CV valid for duration
            employee["ShortDayRatio"],
            employee["LongDayRatio"],
            employee["WeekendRatio"],
        ])

    return ids, X
