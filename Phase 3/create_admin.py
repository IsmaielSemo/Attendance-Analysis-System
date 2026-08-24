from werkzeug.security import generate_password_hash
import database as db

username = "admin"
password = "password123"  # Change this to your desired password
role = "Admin"

print(f"Creating account for '{username}'...")
hashed_pw = generate_password_hash(password)

try:
    conn = db.get_connection()
    cursor = conn.cursor()

    # Inserting the user
    cursor.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
        (username, hashed_pw, role)
    )
    conn.commit()
    conn.close()

    print(f"SUCCESS: Admin account '{username}' created successfully!")
except Exception as e:
    print(f"FAILED: {str(e)}")
