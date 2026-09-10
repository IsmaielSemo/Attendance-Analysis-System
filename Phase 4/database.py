# database.py -> connects and retrieves information from SQL Server

import pyodbc
import re
from datetime import datetime, timedelta
from collections import namedtuple
from config import ATTENDANCE_CONNECTION_STRING, AUTH_CONNECTION_STRING

Record = namedtuple('Record', ['BadgeID', 'Datetime', 'InOut', 'Branch'])

# FULL MASTER LIST OF ALL 36 GATES
IP_MAPPING = {
    '10.1.100.1': ('IN', 'Plaza - Gate1-IN'),
    '10.1.100.2': ('OUT', 'Plaza - Gate1-OUT'),
    '10.1.100.3': ('IN', 'Plaza - Gate2-IN'),
    '10.1.100.4': ('OUT', 'Plaza - Gate2-OUT'),
    '10.1.100.5': ('IN', 'Plaza - Gate3-IN'),
    '10.1.100.6': ('OUT', 'Plaza - Gate3-OUT'),
    '10.1.100.7': ('IN', 'Plaza - Gate-DM-IN'),
    '10.1.100.8': ('OUT', 'Plaza - Gate-DM-OUT'),
    '10.1.100.9': ('IN', 'Plaza - Gate-GT-IN'),
    '10.1.100.10': ('OUT', 'Plaza - Gate-GT-OUT'),
    '10.10.10.201': ('IN', 'HQ IN Gate'),
    '10.10.10.203': ('OUT', 'HQ Out Gate'),
    '10.10.10.202': ('IN', 'HQ-Sec IN Gate'),
    '10.10.10.204': ('OUT', 'HQ-Sec Out Gate'),
    '10.100.1.199': ('IN', 'CS IN Gate'),
    '10.100.1.200': ('OUT', 'CS Out Gate'),
    '10.4.10.202': ('IN', 'DT IN Gate'),
    '10.4.10.201': ('OUT', 'DT Out Gate'),
    '10.13.1.100': ('IN', 'Pearl IN Gate'),
    '10.13.1.200': ('OUT', 'Pearl Out Gate'),
    '10.11.10.201': ('IN', 'CH IN Gate'),
    '10.11.10.202': ('OUT', 'CH Out Gate'),
    '10.12.10.201': ('IN', 'FH In Gate'),
    '10.12.10.202': ('OUT', 'FH Out Gate'),
    '10.8.10.201': ('IN', 'CH-Sales IN Gate'),
    '10.8.10.202': ('OUT', 'CH-Sales Out Gate'),
    '10.3.10.201': ('IN', 'HC IN Gate'),
    '10.3.10.202': ('OUT', 'HC Out Gate')
}


def get_connection():
    return pyodbc.connect(ATTENDANCE_CONNECTION_STRING)


def get_auth_connection():
    conn = pyodbc.connect(AUTH_CONNECTION_STRING)
    cursor = conn.cursor()
    cursor.execute("SELECT DB_NAME()")
    return conn


def get_attendance(badge_id, start_date, end_date):
    end_date_plus_one = end_date + timedelta(days=1)
    params = [start_date, end_date_plus_one]

    conn = get_connection()
    cursor = conn.cursor()

    # Querying the database for hardware logs
    hik_query = "SELECT UserID, DeviceIP, [EventTime] FROM dbo.HikAccessLog WHERE [EventTime] >= ? AND [EventTime] < ?"
    zk_query = "SELECT code, Ip, Datetime FROM dbo.ZK_log WHERE Datetime >= ? AND Datetime < ?"
    manual_query = "SELECT code, Ip, Datetime FROM dbo.ManualEntry WHERE Datetime >= ? AND Datetime < ?"

    raw_data = []
    cursor.execute(hik_query, params)
    raw_data.extend(cursor.fetchall())

    cursor.execute(zk_query, params)
    raw_data.extend(cursor.fetchall())

    cursor.execute(manual_query, params)
    raw_data.extend(cursor.fetchall())

    conn.close()

    records = []
    seen = set()

    for row in raw_data:
        b_id_raw = str(row[0]).strip() if row[0] is not None else ''
        if b_id_raw.endswith('.0'):
            b_id_raw = b_id_raw[:-2]
        b_id = re.sub(r'[^\w]', '', b_id_raw)

        ip = re.sub(r'[^\d\.]', '', str(row[1]).strip()) if row[1] is not None else ''
        dt_val = row[2]

        if not b_id or dt_val is None:
            continue

        if badge_id is not None and b_id != str(badge_id):
            continue

        # FAST NATIVE PYTHON PARSING
        if isinstance(dt_val, str):
            try:
                dt = datetime.strptime(dt_val[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
        elif isinstance(dt_val, datetime):
            dt = dt_val
        else:
            continue

        # Assign IN/OUT based on the Master IP list
        in_out, branch = IP_MAPPING.get(ip, ('UNKNOWN', 'UNKNOWN'))

        ident = (b_id, dt, in_out)
        if ident not in seen:
            seen.add(ident)
            records.append(Record(BadgeID=b_id, Datetime=dt, InOut=in_out, Branch=branch))

    records.sort(key=lambda x: (x.BadgeID, x.Datetime))
    return records


def get_unique_badges():
    with get_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT DISTINCT UserID AS BadgeID FROM dbo.HikAccessLog WHERE NULLIF(LTRIM(RTRIM(UserID)), '') IS NOT NULL
            UNION
            SELECT DISTINCT code AS BadgeID FROM dbo.ZK_log WHERE NULLIF(LTRIM(RTRIM(code)), '') IS NOT NULL
            UNION
            SELECT DISTINCT code AS BadgeID FROM dbo.ManualEntry WHERE NULLIF(LTRIM(RTRIM(code)), '') IS NOT NULL
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        badges = sorted(list(set(str(row[0]).strip() for row in rows)))
        return badges