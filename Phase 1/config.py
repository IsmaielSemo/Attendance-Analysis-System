#config.py -> Provides connection string to SQL Server



CONNECTION_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=np:\\\\.\\pipe\\MSSQL$SQLEXPRESS\\sql\\query;"
    "DATABASE=Att_Log;"
    "Trusted_Connection=yes;"
)