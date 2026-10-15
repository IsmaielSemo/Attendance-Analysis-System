import pandas as pd
import pyodbc
from datetime import datetime
from config import ATTENDANCE_CONNECTION_STRING


def excel_to_db(excel):
    df = pd.read_excel(excel)
    records_to_insert = []
    created_at = datetime.now()

    for index, row in df.iterrows():
        # Cast pandas/numpy types to native Python types and strip whitespace
        code = str(row["No."]).strip()
        dt = pd.to_datetime(row["Date/Time"]).to_pydatetime()
        ip = str(row["branch"]).strip()

        # We pass the data twice: once for the INSERT, once for the NOT EXISTS check
        row_data = (code, dt, ip, created_at, code, dt, ip)
        records_to_insert.append(row_data)

    return write_to_db(records_to_insert)


def write_to_db(records):
    conn = pyodbc.connect(ATTENDANCE_CONNECTION_STRING)
    cursor = conn.cursor()

    # The SELECT ... WHERE NOT EXISTS structure prevents duplicate entries
    sql_query = """   
        INSERT INTO dbo.ManualEntry (
            code, Datetime, Ip, CreatedAt,
            InType, OutType, Explain,
            VerifyMode, InOutMode, MachineNumber
        ) 
        SELECT ?, ?, ?, ?, NULL, NULL, NULL, '', '', ''
        WHERE NOT EXISTS (
            SELECT 1 FROM dbo.ManualEntry
            WHERE code = ? AND Datetime = ? AND Ip = ?
        )
    """

    records_added = 0

    # Execute row-by-row to safely ignore duplicates and count actual inserts
    for record in records:
        try:
            cursor.execute(sql_query, record)
            # rowcount will be 1 if inserted, 0 if it already existed and was skipped
            if cursor.rowcount > 0:
                records_added += 1
        except Exception as e:
            # If a row fails (e.g., severe data formatting error), skip it and continue
            print(f"Database error on row {record[0]} at {record[1]}: {str(e)}")
            continue

    conn.commit()
    cursor.close()
    conn.close()

    return records_added