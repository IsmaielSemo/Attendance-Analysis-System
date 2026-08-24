# config.py -> Provides connection strings to SQL Server

ATTENDANCE_CONNECTION_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=np:\\\\.\\pipe\\MSSQL$SQLEXPRESS\\sql\\query;"
    "DATABASE=Att_Log;"
    "Trusted_Connection=yes;"
)

AUTH_CONNECTION_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=np:\\\\.\\pipe\\MSSQL$SQLEXPRESS\\sql\\query;"
    "DATABASE=SUD_Auth;"
    "Trusted_Connection=yes;"
)
