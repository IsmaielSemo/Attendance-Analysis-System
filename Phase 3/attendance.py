# #attendance.py -> Logic of the project

from collections import defaultdict
from statistics import mean



def clean_records(records):
    """
    Remove consecutive identical IN/OUT punches
    within the same employee and calendar day.

    Records from different days are never treated
    as duplicates of one another.
    """

    grouped = defaultdict(list)

    for record in records:
        key = (
            record.BadgeID,
            record.Datetime.date()
        )
        grouped[key].append(record)

    cleaned = []

    for key in grouped:

        day_records = sorted(
            grouped[key],
            key=lambda x: x.Datetime
        )

        previous = None

        for record in day_records:

            status = record.InOut.strip().upper()

            if status != previous:
                cleaned.append(record)
                previous = status

    cleaned.sort(
        key=lambda x: (x.BadgeID, x.Datetime)
    )

    return cleaned



def group_records(records): #Group the records

    grouped = defaultdict(list)

    for record in records:

        key = (
            record.BadgeID,
            record.Datetime.date()
        )

        grouped[key].append(record)

    return grouped




def get_first_in(records): #Get first in

    for record in records:

        if record.InOut.strip().upper() == "IN":
            return record

    return None



def get_last_out(records): #Get last out

    for record in reversed(records):

        if record.InOut.strip().upper() == "OUT":
            return record

    return None




def format_records(records): #Format the records

    output = []

    for record in records:

        output.append({

            "BadgeID": record.BadgeID,

            "Datetime": record.Datetime,

            "Status": record.InOut.strip(),

            "Branch": record.Branch.strip()
            if record.Branch else ""

        })

    return output


def create_daily_summary(records): #Create daily summary (one row per employee per day)

    records = clean_records(records)

    grouped = group_records(records)

    summary = []

    for (badge, day) in sorted(grouped.keys()):

        day_records = sorted(
            grouped[(badge, day)],
            key=lambda x: x.Datetime
        )

        first_in = get_first_in(day_records)
        last_out = get_last_out(day_records)

        summary.append({

            "BadgeID": badge,

            "Date": day,

            "FirstIn":
                first_in.Datetime if first_in else None,

            "LastOut":
                last_out.Datetime if last_out else None,

            "Punches":
                len(day_records)

        })

    return summary


def create_overall_summary(records): #Create the overall summary (one row per employee but works for multiple employees)

    records = clean_records(records)

    employees = defaultdict(list)

    for record in records:
        employees[record.BadgeID].append(record)

    summary = []

    for badge in sorted(employees.keys()):

        employee = employees[badge]

        first_in = get_first_in(employee)
        last_out = get_last_out(employee)

        working_days = len({

            r.Datetime.date()

            for r in employee

        })

        summary.append({

            "BadgeID": badge,

            "WorkingDays": working_days,

            "TotalPunches": len(employee),

            "FirstEntry":
                first_in.Datetime if first_in else None,

            "LastExit":
                last_out.Datetime if last_out else None

        })

    return summary






def detect_missing_pairs(records): #Detects any duplicates/missing IN/OUT pairs

    grouped = defaultdict(list)

    # Group by employee and day
    for record in records:
        key = (
            record.BadgeID,
            record.Datetime.date()
        )
        grouped[key].append(record)

    warnings = []

    for (badge, day), day_records in sorted(grouped.items()):

        day_records.sort(key=lambda r: r.Datetime)

        if not day_records:
            continue

        # -----------------------------
        # Missing IN
        # -----------------------------
        first = day_records[0]

        if first.InOut.strip().upper() == "OUT":

            warnings.append({

                "BadgeID": badge,

                "Date": day,

                "Datetime": first.Datetime,

                "Problem": "Missing IN"

            })

        # -----------------------------
        # Missing OUT
        # -----------------------------
        last = day_records[-1]

        if last.InOut.strip().upper() == "IN":

            warnings.append({

                "BadgeID": badge,

                "Date": day,

                "Datetime": last.Datetime,

                "Problem": "Missing OUT"

            })

        # -----------------------------
        # Duplicate punches
        # -----------------------------
        previous = None

        for record in day_records:

            status = record.InOut.strip().upper()

            if previous == status:

                warnings.append({

                    "BadgeID": badge,

                    "Date": day,

                    "Datetime": record.Datetime,

                    "Problem": f"Duplicate {status}"

                })

            previous = status

    return warnings





def employee_statistics(records): #Get some statistics about employee behaviors

    records = clean_records(records)

    if not records:

        return {

            "Employees": 0,
            "WorkingDays": 0,
            "TotalPunches": 0,
            "AveragePunchesPerDay": 0,
            "AverageArrival": None,
            "AverageDeparture": None

        }

    grouped = group_records(records)

    first_arrivals = []
    last_departures = []

    for key in grouped:

        day = sorted(
            grouped[key],
            key=lambda x: x.Datetime
        )

        first = get_first_in(day)
        last = get_last_out(day)

        if first:

            first_arrivals.append(

                first.Datetime.hour * 60 +
                first.Datetime.minute

            )

        if last:

            last_departures.append(

                last.Datetime.hour * 60 +
                last.Datetime.minute

            )

    def minutes_to_time(value): #Converts the minutes to time for calculations

        if value is None:
            return None

        h = value // 60
        m = value % 60

        return f"{h:02}:{m:02}"

    employees = {

        r.BadgeID

        for r in records

    }

    employee_days = defaultdict(set)

    for record in records:
        employee_days[record.BadgeID].add(record.Datetime.date())

    total_employee_days = sum(
        len(days)
        for days in employee_days.values()
    )

    unique_dates = {
        r.Datetime.date()
        for r in records
    }

    return {

        "Employees":
            len(employees),

        "WorkingDays":
            len(unique_dates),

        "TotalPunches":
            len(records),

        "AveragePunchesPerDay":

            round(

                len(records) / total_employee_days,

                2

            ) if total_employee_days else 0,

        "AverageArrival":

            minutes_to_time(

                round(mean(first_arrivals))

            ) if first_arrivals else None,

        "AverageDeparture":

            minutes_to_time(

                round(mean(last_departures))

            ) if last_departures else None

    }



def get_employee_list(records): #Returns employee list

    return sorted({

        r.BadgeID

        for r in records

    })

