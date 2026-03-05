import database as db

def reset_skipped_leads():
    db.init_db()
    # Move leads from 'skipped' back to 'new' so the new Manager logic 
    # (which accepts 'medium' urgency) can process them.
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE leads SET status = 'new' WHERE status = 'skipped';")
    count = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    print(f"Successfully reset {count} leads back to 'new'.")

if __name__ == "__main__":
    reset_skipped_leads()
