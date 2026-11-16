# database.py -> connects and retrieves information from SQL Server

import pyodbc
import re
from datetime import datetime, timedelta
from collections import namedtuple
from config import ATTENDANCE_CONNECTION_STRING, AUTH_CONNECTION_STRING

Record = namedtuple('Record', ['BadgeID', 'Datetime', 'InOut', 'Branch', 'VerifyMode'])


def get_connection():
    return pyodbc.connect(ATTENDANCE_CONNECTION_STRING)


def get_auth_connection():
    conn = pyodbc.connect(AUTH_CONNECTION_STRING)
    cursor = conn.cursor()
    cursor.execute("SELECT DB_NAME()")
    return conn


def get_dynamic_ip_mapping():
    """
    Dynamically queries dbo.Machine to build the IP mapping dictionary.
    Handles all 11 columns: ID, IP, port, Name, modelid, ModelName, Direction, Location, Active, Username, Password.
    """
    mapping = {}
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                [IP], 
                [Name], 
                [Direction], 
                [port], 
                [modelid], 
                [ModelName], 
                [Location], 
                [Active], 
                [Username], 
                [Password]
            FROM dbo.Machine
        """)
        rows = cursor.fetchall()

        for row in rows:
            ip_val = re.sub(r'[^\d\.]', '', str(row[0])).strip() if row[0] is not None else ''
            branch_name = str(row[1]).strip() if row[1] is not None else ''
            direction_flag = str(row[2]).strip() if row[2] is not None else ''

            username = str(row[8]).strip() if len(row) > 8 and row[8] is not None else ''
            password = str(row[9]).strip() if len(row) > 9 and row[9] is not None else ''

            if direction_flag == '1':
                in_out = 'IN'
            elif direction_flag == '2':
                in_out = 'OUT'
            else:
                in_out = 'UNKNOWN'

            if ip_val:
                mapping[ip_val] = {
                    'in_out': in_out,
                    'branch': branch_name,
                    'username': username,
                    'password': password
                }

        conn.close()
    except Exception as e:
        print(f"Error loading dynamic IP mapping from dbo.Machine: {e}")

    return mapping


def clean_badge_id(value):
    if value is None:
        return None

    badge = str(value).strip()

    if badge.endswith(".0"):
        badge = badge[:-2]

    badge = re.sub(r"[^\w]", "", badge)

    if badge.lower() in {"", "nan", "none", "null", "nat"}:
        return None

    return badge



def get_attendance(badge_id, start_date, end_date):
    end_date_plus_one = end_date + timedelta(days=1)
    params = [start_date, end_date_plus_one]

    conn = get_connection()
    cursor = conn.cursor()

    ip_mapping = get_dynamic_ip_mapping()

    hik_query = """
        SELECT UserID, DeviceIP, [EventTime], [Minor]
        FROM dbo.HikAccessLog
        WHERE [EventTime] >= ? AND [EventTime] < ?
    """

    zk_query = """
        SELECT code, Ip, Datetime
        FROM dbo.ZK_log
        WHERE Datetime >= ? AND Datetime < ?
    """

    manual_query = """
        SELECT code, Ip, Datetime
        FROM dbo.ManualEntry
        WHERE Datetime >= ? AND Datetime < ?
    """

    raw_data = []

    try:
        cursor.execute(hik_query, params)
        raw_data.extend([('HIK', row) for row in cursor.fetchall()])

        cursor.execute(zk_query, params)
        raw_data.extend([('ZK', row) for row in cursor.fetchall()])

        cursor.execute(manual_query, params)
        raw_data.extend([('MANUAL', row) for row in cursor.fetchall()])

    finally:
        cursor.close()
        conn.close()

    records = []
    seen = set()

    for source_type, row in raw_data:

        b_id = clean_badge_id(row[0])

        ip = (
            re.sub(r'[^\d\.]', '', str(row[1]).strip())
            if row[1] is not None else ''
        )

        dt_val = row[2]

        # Default verification method
        verify_mode = 'N/A'

        # Determine verification method only for Hikvision
        if source_type == 'HIK':

            minor_val = row[3]

            try:
                minor_int = int(minor_val) if minor_val is not None else None
            except (ValueError, TypeError):
                minor_int = None

            if minor_int == 1:
                verify_mode = 'Card'

            elif minor_int == 38:
                verify_mode = 'Fingerprint'

            elif minor_int == 75:
                verify_mode = 'Face'

            # Unknown codes remain N/A.
            # NEVER discard a valid attendance punch.

        if b_id is None or dt_val is None:
            continue

        if badge_id is not None and str(badge_id) != 'All':
            if b_id != str(badge_id):
                continue

        if isinstance(dt_val, str):
            try:
                dt = datetime.strptime(
                    dt_val[:19],
                    "%Y-%m-%d %H:%M:%S"
                )
            except ValueError:
                continue

        elif isinstance(dt_val, datetime):
            dt = dt_val

        else:
            continue

        device_info = ip_mapping.get(
            ip,
            {
                'in_out': 'UNKNOWN',
                'branch': 'UNKNOWN'
            }
        )

        in_out = device_info['in_out']
        branch = device_info['branch']

        # Include verification method in the identity.
        ident = (source_type, b_id, dt, in_out, verify_mode)

        if ident in seen:
            continue

        seen.add(ident)

        records.append(
            Record(
                BadgeID=b_id,
                Datetime=dt,
                InOut=in_out,
                Branch=branch,
                VerifyMode=verify_mode
            )
        )

    records.sort(key=lambda x: (x.BadgeID, x.Datetime))

    return records


def get_unique_badges():
    query = """
        SELECT CAST(UserID AS VARCHAR(50)) AS BadgeID FROM HikAccessLog
        UNION
        SELECT CAST(code AS VARCHAR(50)) AS BadgeID FROM ZK_log
        UNION
        SELECT CAST(code AS VARCHAR(50)) AS BadgeID FROM ManualEntry
    """

    try:
        conn = pyodbc.connect(ATTENDANCE_CONNECTION_STRING)
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()

        cleaned_badges = set()
        for row in rows:
            b_id = clean_badge_id(row[0])
            if b_id is not None:
                cleaned_badges.add(b_id)

        return sorted(cleaned_badges)

    except pyodbc.Error as e:
        print(f"Database error while retrieving unique badges: {e}")
        return []

    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()