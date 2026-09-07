# features.py -> Describes the features that will be used in ML

from collections import defaultdict
from statistics import mean, stdev
from datetime import datetime

# ==========================================================
# CONSTANTS
# ==========================================================

WORK_START = 9 * 60  # 09:00
WORK_END = 17 * 60  # 17:00

SHORT_DAY = 4 * 60  # 4 hours
LONG_DAY = 10 * 60  # 10 hours


# ==========================================================
# TIME UTILITIES
# ==========================================================

def to_datetime(value):
    """
    Converts a datetime value to a datetime object.

    Supports:
        - datetime objects
        - strings in YYYY-MM-DD HH:MM:SS format
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
    """
    Converts datetime -> minutes after midnight.
    """

    dt = to_datetime(value)

    if dt is None:
        return 0

    return dt.hour * 60 + dt.minute


def safe_div(numerator, denominator):
    """
    Safe division.

    Returns 0.0 if denominator is zero.
    """

    if denominator is None or denominator == 0:
        return 0.0

    return numerator / denominator


# ==========================================================
# BUILD DAILY INFORMATION
# ==========================================================

def build_daily_information(records):
    """
    Build one attendance record per employee/day.

    Important:
    We deliberately use the FIRST IN and LAST OUT of the day.
    This keeps the ML features focused on overall attendance
    behavior rather than individual punch noise.
    """

    daily_info = defaultdict(lambda: defaultdict(list))

    for record in records:

        badge = record.BadgeID

        dt = to_datetime(record.Datetime)

        if dt is None:
            continue

        daily_info[badge][dt.date()].append(record)

    processed_info = defaultdict(list)

    for badge, days in daily_info.items():

        for date_key, day_records in days.items():

            day_records.sort(
                key=lambda x: to_datetime(x.Datetime)
            )

            in_records = [
                r for r in day_records
                if str(r.InOut).upper().strip() == "IN"
            ]

            out_records = [
                r for r in day_records
                if str(r.InOut).upper().strip() == "OUT"
            ]

            first_in = in_records[0] if in_records else None
            last_out = out_records[-1] if out_records else None

            duration = None

            if first_in is not None and last_out is not None:

                first_dt = to_datetime(first_in.Datetime)
                last_dt = to_datetime(last_out.Datetime)

                if first_dt is not None and last_dt is not None:

                    duration = (
                                       last_dt - first_dt
                               ).total_seconds() / 60.0

                    # Prevent invalid negative durations from entering ML.
                    if duration < 0:
                        duration = None

            processed_info[badge].append({
                "date": date_key,
                "first_in": first_in,
                "last_out": last_out,
                "duration": duration,
                "punches": len(day_records),
            })

    return processed_info


# ==========================================================
# FEATURE GENERATION
# ==========================================================

def build_features(records, missing_pairs_alerts=None):
    if missing_pairs_alerts is None:
        missing_pairs_alerts = []

    daily_info = build_daily_information(records)

    # --------------------------------------------------------
    # Missing-punch information
    # --------------------------------------------------------

    employee_alerts = defaultdict(
        lambda: {
            "MissingIN": 0,
            "MissingOUT": 0,
        }
    )

    for alert in missing_pairs_alerts:

        badge = alert.get("BadgeID")
        problem = str(alert.get("Problem", ""))

        if "Missing IN" in problem:
            employee_alerts[badge]["MissingIN"] += 1

        elif "Missing OUT" in problem:
            employee_alerts[badge]["MissingOUT"] += 1

    # --------------------------------------------------------
    # Build employee vectors
    # --------------------------------------------------------

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

        for day in days:

            punches.append(day["punches"])

            # Egypt workweek context:
            # Friday = 4
            # Saturday = 5
            if day["date"].weekday() in (4, 5):
                weekend_days += 1

            # First arrival
            if day["first_in"] is not None:
                arrival = to_minutes(
                    day["first_in"].Datetime
                )

                arrivals.append(arrival)

            # Last departure
            if day["last_out"] is not None:
                departure = to_minutes(
                    day["last_out"].Datetime
                )

                departures.append(departure)

            # Working duration
            if day["duration"] is not None:

                durations.append(day["duration"])

                if day["duration"] < SHORT_DAY:
                    short_days += 1

                elif day["duration"] > LONG_DAY:
                    long_days += 1

        # ----------------------------------------------------
        # Basic statistics
        # ----------------------------------------------------

        avg_arrival = (
            round(mean(arrivals), 2)
            if arrivals else 0.0
        )

        avg_departure = (
            round(mean(departures), 2)
            if departures else 0.0
        )

        avg_duration = (
            round(mean(durations), 2)
            if durations else 0.0
        )

        arrival_std = (
            round(stdev(arrivals), 2)
            if len(arrivals) > 1
            else 0.0
        )

        departure_std = (
            round(stdev(departures), 2)
            if len(departures) > 1
            else 0.0
        )

        duration_std = (
            round(stdev(durations), 2)
            if len(durations) > 1
            else 0.0
        )

        # ----------------------------------------------------
        # Missing punches
        # ----------------------------------------------------

        missing_in = employee_alerts[badge]["MissingIN"]
        missing_out = employee_alerts[badge]["MissingOUT"]

        total_missing = missing_in + missing_out

        # ----------------------------------------------------
        # Feature vector
        # ----------------------------------------------------

        feature_vectors.append({

            "BadgeID": badge,

            # Exposure
            "WorkingDays": working_days,

            # Attendance timing
            "AverageArrival": avg_arrival,
            "AverageDeparture": avg_departure,
            "AverageDuration": avg_duration,

            # Distance from standard daytime schedule
            "AvgArrivalDeviation":
                avg_arrival - WORK_START,

            "AvgDepartureDeviation":
                avg_departure - WORK_END,

            # Timing consistency
            "ArrivalCV":
                safe_div(arrival_std, avg_arrival),

            "DepartureCV":
                safe_div(departure_std, avg_departure),

            "DurationCV":
                safe_div(duration_std, avg_duration),

            # Working-day behavior
            "ShortDayRatio":
                safe_div(short_days, working_days),

            "LongDayRatio":
                safe_div(long_days, working_days),

            # Attendance reliability
            "MissingPunchRatio":
                safe_div(
                    total_missing,
                    working_days * 2
                ),

            # Weekend behavior
            "WeekendRatio":
                safe_div(
                    weekend_days,
                    working_days
                ),

            # Punch behavior
            "AvgPunchesPerDay":
                safe_div(
                    sum(punches),
                    working_days
                ),

            # Raw counts useful for explanations
            "MissingIN":
                missing_in,

            "MissingOUT":
                missing_out,

            "TotalMissingPunches":
                total_missing,

            "WeekendDays":
                weekend_days,

            "ShortDays":
                short_days,

            "LongDays":
                long_days,
        })

    return feature_vectors


# ==========================================================
# ML MATRIX
# ==========================================================

def feature_matrix(records, missing_pairs_alerts=None):
    features = build_features(
        records,
        missing_pairs_alerts
    )

    ids = []
    X = []

    for employee in features:
        ids.append(employee["BadgeID"])

        X.append([
            employee["AverageArrival"],
            employee["AverageDeparture"],
            employee["AverageDuration"],
            employee["AvgArrivalDeviation"],
            employee["AvgDepartureDeviation"],
            employee["ArrivalCV"],
            employee["DepartureCV"],
            employee["DurationCV"],
            employee["ShortDayRatio"],
            employee["LongDayRatio"],
            employee["WeekendRatio"],

            # ----------------------------------------------------
            # EXCLUDED FROM ML INPUT:
            # employee["MissingPunchRatio"],
            # employee["AvgPunchesPerDay"],
            # ----------------------------------------------------
        ])

    return ids, X