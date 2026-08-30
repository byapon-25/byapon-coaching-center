from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from pathlib import Path
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date

BASE_DIR = Path(__file__).resolve().parent
DB = BASE_DIR / "coaching.db"

app = Flask(__name__)
app.secret_key = "CHANGE_ME_TO_A_LONG_RANDOM_SECRET"

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con

def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS students(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      student_id TEXT UNIQUE NOT NULL,
      name TEXT NOT NULL,
      phone TEXT, guardian TEXT, guardian_phone TEXT,
      class_name TEXT, batch TEXT, address TEXT,
      admission_date TEXT, monthly_fee REAL DEFAULT 0,
      active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS attendance(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      student_id INTEGER NOT NULL,
      attendance_date TEXT NOT NULL,
      status TEXT NOT NULL,
      UNIQUE(student_id,attendance_date),
      FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS exams(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL, exam_date TEXT NOT NULL,
      subject TEXT NOT NULL, full_marks REAL DEFAULT 100,
      pass_marks REAL DEFAULT 33
    );
    CREATE TABLE IF NOT EXISTS marks(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      exam_id INTEGER NOT NULL, student_id INTEGER NOT NULL,
      marks REAL DEFAULT 0,
      UNIQUE(exam_id,student_id),
      FOREIGN KEY(exam_id) REFERENCES exams(id) ON DELETE CASCADE,
      FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS transactions(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      tx_date TEXT NOT NULL, tx_type TEXT NOT NULL,
      category TEXT NOT NULL, amount REAL NOT NULL, note TEXT
    );
    CREATE TABLE IF NOT EXISTS coaching_days(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      day_date TEXT UNIQUE NOT NULL, status TEXT NOT NULL, note TEXT
    );
    CREATE TABLE IF NOT EXISTS teachers(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL, phone TEXT, subject TEXT,
      salary REAL DEFAULT 0, active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS routines(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      day_name TEXT NOT NULL, batch TEXT, subject TEXT,
      teacher TEXT, start_time TEXT, end_time TEXT
    );
    """)
    if not con.execute("SELECT 1 FROM users WHERE username='admin'").fetchone():
        con.execute("INSERT INTO users(username,password_hash) VALUES(?,?)",
                    ("admin", generate_password_hash("admin123")))
    con.commit()
    con.close()

def login_required(f):
    @wraps(f)
    def w(*a,**k):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*a,**k)
    return w

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        con=db()
        u=con.execute("SELECT * FROM users WHERE username=?",(request.form["username"],)).fetchone()
        con.close()
        if u and check_password_hash(u["password_hash"],request.form["password"]):
            session["user_id"]=u["id"]; session["username"]=u["username"]
            return redirect(url_for("dashboard"))
        flash("Login information is incorrect.","danger")
    return render_template("login.html")

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.get("/")
@login_required
def dashboard():
    con=db()
    students=con.execute("SELECT COUNT(*) c FROM students WHERE active=1").fetchone()["c"]
    present=con.execute("SELECT COUNT(*) c FROM attendance WHERE attendance_date=? AND status='Present'",
                        (date.today().isoformat(),)).fetchone()["c"]
    income=con.execute("SELECT COALESCE(SUM(amount),0) s FROM transactions WHERE tx_type='Income'").fetchone()["s"]
    expense=con.execute("SELECT COALESCE(SUM(amount),0) s FROM transactions WHERE tx_type='Expense'").fetchone()["s"]
    exams=con.execute("SELECT * FROM exams ORDER BY exam_date LIMIT 6").fetchall()
    teachers=con.execute("SELECT COUNT(*) c FROM teachers WHERE active=1").fetchone()["c"]
    con.close()
    return render_template("dashboard.html",students=students,present=present,income=income,
                           expense=expense,exams=exams,teachers=teachers)

@app.route("/students",methods=["GET","POST"])
@login_required
def students():
    con=db()
    if request.method=="POST":
        try:
            con.execute("""INSERT INTO students
            (student_id,name,phone,guardian,guardian_phone,class_name,batch,address,admission_date,monthly_fee)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (request.form["student_id"],request.form["name"],request.form.get("phone"),
             request.form.get("guardian"),request.form.get("guardian_phone"),
             request.form.get("class_name"),request.form.get("batch"),request.form.get("address"),
             request.form.get("admission_date"),float(request.form.get("monthly_fee") or 0)))
            con.commit(); flash("Student added.","success")
        except sqlite3.IntegrityError:
            flash("This Student ID already exists.","danger")
        return redirect(url_for("students"))
    rows=con.execute("SELECT * FROM students ORDER BY id DESC").fetchall()
    con.close()
    return render_template("students.html",students=rows)

@app.post("/students/<int:sid>/toggle")
@login_required
def toggle_student(sid):
    con=db(); con.execute("UPDATE students SET active=1-active WHERE id=?",(sid,))
    con.commit(); con.close(); return redirect(url_for("students"))

@app.post("/students/<int:sid>/delete")
@login_required
def delete_student(sid):
    con=db(); con.execute("DELETE FROM students WHERE id=?",(sid,))
    con.commit(); con.close(); flash("Student deleted.","success")
    return redirect(url_for("students"))

@app.route("/attendance",methods=["GET","POST"])
@login_required
def attendance():
    d=request.values.get("date") or date.today().isoformat()
    con=db()
    if request.method=="POST":
        for k,v in request.form.items():
            if k.startswith("status_"):
                sid=int(k.split("_")[1])
                con.execute("""INSERT INTO attendance(student_id,attendance_date,status)
                VALUES(?,?,?) ON CONFLICT(student_id,attendance_date)
                DO UPDATE SET status=excluded.status""",(sid,d,v))
        con.commit(); flash("Attendance saved.","success")
    rows=con.execute("""SELECT s.*,COALESCE(a.status,'Absent') status
      FROM students s LEFT JOIN attendance a
      ON a.student_id=s.id AND a.attendance_date=?
      WHERE s.active=1 ORDER BY s.class_name,s.batch,s.name""",(d,)).fetchall()
    con.close()
    return render_template("attendance.html",students=rows,selected_date=d)

@app.route("/exams",methods=["GET","POST"])
@login_required
def exams():
    con=db()
    if request.method=="POST":
        con.execute("INSERT INTO exams(title,exam_date,subject,full_marks,pass_marks) VALUES(?,?,?,?,?)",
                    (request.form["title"],request.form["exam_date"],request.form["subject"],
                     float(request.form.get("full_marks") or 100),float(request.form.get("pass_marks") or 33)))
        con.commit(); flash("Exam created.","success")
        return redirect(url_for("exams"))
    rows=con.execute("SELECT * FROM exams ORDER BY exam_date DESC").fetchall()
    con.close(); return render_template("exams.html",exams=rows)

@app.route("/exams/<int:eid>/marks",methods=["GET","POST"])
@login_required
def marks(eid):
    con=db(); exam=con.execute("SELECT * FROM exams WHERE id=?",(eid,)).fetchone()
    if not exam: con.close(); return "Exam not found",404
    if request.method=="POST":
        for k,v in request.form.items():
            if k.startswith("mark_"):
                sid=int(k.split("_")[1])
                con.execute("""INSERT INTO marks(exam_id,student_id,marks) VALUES(?,?,?)
                ON CONFLICT(exam_id,student_id) DO UPDATE SET marks=excluded.marks""",
                (eid,sid,float(v or 0)))
        con.commit(); flash("Marks saved.","success")
    rows=con.execute("""SELECT s.id,s.student_id,s.name,COALESCE(m.marks,0) marks
      FROM students s LEFT JOIN marks m ON m.student_id=s.id AND m.exam_id=?
      WHERE s.active=1 ORDER BY s.name""",(eid,)).fetchall()
    con.close(); return render_template("marks.html",exam=exam,students=rows)

@app.get("/marksheet/<int:sid>")
@login_required
def marksheet(sid):
    con=db()
    student=con.execute("SELECT * FROM students WHERE id=?",(sid,)).fetchone()
    results=con.execute("""SELECT e.*,COALESCE(m.marks,0) marks
      FROM exams e LEFT JOIN marks m ON m.exam_id=e.id AND m.student_id=?
      ORDER BY e.exam_date DESC""",(sid,)).fetchall()
    con.close()
    return render_template("marksheet.html",student=student,results=results)

@app.route("/finance",methods=["GET","POST"])
@login_required
def finance():
    con=db()
    if request.method=="POST":
        con.execute("INSERT INTO transactions(tx_date,tx_type,category,amount,note) VALUES(?,?,?,?,?)",
                    (request.form["tx_date"],request.form["tx_type"],request.form["category"],
                     float(request.form["amount"]),request.form.get("note")))
        con.commit(); flash("Transaction saved.","success")
        return redirect(url_for("finance"))
    rows=con.execute("SELECT * FROM transactions ORDER BY tx_date DESC,id DESC").fetchall()
    income=con.execute("SELECT COALESCE(SUM(amount),0) s FROM transactions WHERE tx_type='Income'").fetchone()["s"]
    expense=con.execute("SELECT COALESCE(SUM(amount),0) s FROM transactions WHERE tx_type='Expense'").fetchone()["s"]
    con.close(); return render_template("finance.html",transactions=rows,income=income,expense=expense)

@app.route("/calendar",methods=["GET","POST"])
@login_required
def calendar():
    con=db()
    if request.method=="POST":
        con.execute("""INSERT INTO coaching_days(day_date,status,note) VALUES(?,?,?)
        ON CONFLICT(day_date) DO UPDATE SET status=excluded.status,note=excluded.note""",
        (request.form["day_date"],request.form["status"],request.form.get("note")))
        con.commit(); flash("Coaching day saved.","success")
    rows=con.execute("SELECT * FROM coaching_days ORDER BY day_date DESC").fetchall()
    con.close(); return render_template("calendar.html",days=rows)

@app.route("/teachers",methods=["GET","POST"])
@login_required
def teachers():
    con=db()
    if request.method=="POST":
        con.execute("INSERT INTO teachers(name,phone,subject,salary) VALUES(?,?,?,?)",
                    (request.form["name"],request.form.get("phone"),request.form.get("subject"),
                     float(request.form.get("salary") or 0)))
        con.commit(); flash("Teacher added.","success"); return redirect(url_for("teachers"))
    rows=con.execute("SELECT * FROM teachers ORDER BY id DESC").fetchall()
    con.close(); return render_template("teachers.html",teachers=rows)

@app.route("/routine",methods=["GET","POST"])
@login_required
def routine():
    con=db()
    if request.method=="POST":
        con.execute("""INSERT INTO routines(day_name,batch,subject,teacher,start_time,end_time)
        VALUES(?,?,?,?,?,?)""",(request.form["day_name"],request.form.get("batch"),
        request.form.get("subject"),request.form.get("teacher"),request.form.get("start_time"),
        request.form.get("end_time")))
        con.commit(); flash("Routine added.","success"); return redirect(url_for("routine"))
    rows=con.execute("SELECT * FROM routines ORDER BY id DESC").fetchall()
    con.close(); return render_template("routine.html",routines=rows)

if __name__=="__main__":
    init_db()
    app.run(debug=True)
