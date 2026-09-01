import pandas as pd
import pyodbc
from datetime import datetime
from config import ATTENDANCE_CONNECTION_STRING

#excel1 = "/manual template/Pearl-In"
#excel2 = "/manual template/PearlOut.xlsx"

# Fix: Changed PearlIn to Pearl-In and added .xlsx
#excel1 = r"C:\Users\Administrator\Documents\Work Phase 3\manual template\Pearl-In.xlsx"
#excel2 = r"C:\Users\Administrator\Documents\Work Phase 3\manual template\Pearl-Out.xlsx"

# Notice the space after In and before .xlsx
excel = r"C:\Users\Administrator\Documents\Work Phase 3\manual template\Pearl-In .xlsx"


# Excel has Number, Datetime, LocationID, VerifyCode, InOut, Branch
# ManualEntry has Code, Datetime, IP, CreatedAt
# What we need: Number (Code), Datetime, IP (InOut/Branch same time), CreatedAt(upload date)


def excel_to_db(excel):
    df = pd.read_excel(excel)
    records_to_insert = []
    created_at = datetime.now()

    for index, row in df.iterrows():
        # Cast pandas/numpy types to native Python types to prevent pyodbc crashes
        code = str(row["No."])
        dt = pd.to_datetime(row["Date/Time"]).to_pydatetime()
        ip = str(row["branch"])

        row_data = [code, dt, ip, created_at]
        records_to_insert.append(row_data)

    write_to_db(records_to_insert)

def write_to_db(records):
    conn = pyodbc.connect(ATTENDANCE_CONNECTION_STRING)
    cursor = conn.cursor()

    # sql_query = """
    # INSERT INTO dbo.ManualEntry  (code, Datetime, Ip, CreatedAt)
    # VALUES (?, ?, ?, ?)
    # """

    sql_query = """   
        INSERT INTO dbo.ManualEntry (
            code, Datetime, Ip, CreatedAt,
            InType, OutType, Explain,
            VerifyMode, InOutMode, MachineNumber
        ) 
        VALUES (
            ?, ?, ?, ?,
            NULL, NULL, NULL,
            '', '', ''
        )
        """

    # Execute the batch insert
    cursor.executemany(sql_query, records)
    conn.commit()

    cursor.close()
    conn.close()

def main():
    excel_to_db(excel)

if __name__ == "__main__":
    main()

