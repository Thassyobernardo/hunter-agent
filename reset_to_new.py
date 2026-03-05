import database as db
with db.get_conn() as conn:
    cur = conn.cursor()
    cur.execute("UPDATE leads SET status='new' WHERE id IN (575, 531)")
    print("Updated 575 and 531 to new")
