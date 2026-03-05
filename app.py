from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os

app = Flask(__name__)
app.config["SECRET_KEY"] = "ize-hostel-secret-2026"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:////tmp/ize_hostel.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# ── Models ───────────────────────────────────────────────────────────────────

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="manager")

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw, method="pbkdf2:sha256")

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)


class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    block = db.Column(db.String(1), nullable=False)
    room_number = db.Column(db.String(10), nullable=False)
    room_type = db.Column(db.String(30), nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    beds = db.relationship("Bed", backref="room", lazy=True, cascade="all, delete-orphan")

    @property
    def occupied_beds(self):
        return sum(1 for b in self.beds if b.is_occupied)

    @property
    def available_beds(self):
        return self.capacity - self.occupied_beds


class Bed(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), nullable=False)
    bed_label = db.Column(db.String(10), nullable=False)
    is_occupied = db.Column(db.Boolean, default=False)
    student = db.relationship("Student", backref="bed", uselist=False)


class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    matric_number = db.Column(db.String(30), unique=True, nullable=False)
    university = db.Column(db.String(10), nullable=False)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    bed_id = db.Column(db.Integer, db.ForeignKey("bed.id"), nullable=True)
    meal_plan = db.Column(db.Boolean, default=False)
    payment_type = db.Column(db.String(20))
    semester_paid = db.Column(db.String(30))
    amount_paid = db.Column(db.Float, default=0.0)
    check_in_date = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)


# ── Pricing ──────────────────────────────────────────────────────────────────

PRICES = {
    "Nile": {
        "room_1": 2_800_000,
        "room_2": 2_200_000,
        "room_2_exclusive": 2_300_000,
        "room_3": 2_000_000,
    },
    "Baze": {
        "room_1": 3_200_000,
        "room_2": 2_725_000,
        "room_2_exclusive": 2_875_000,
        "room_3": 2_500_000,
    },
}

MEAL_PLAN_PRICE = 300_000

SEMESTER_SCHEDULE = {
    "Nile": "Double (2 semesters/session)",
    "Baze": "Tri (3 semesters/session)"
}

ROOM_TYPE_LABELS = {
    "room_1": "Room of 1",
    "room_2": "Room of 2",
    "room_2_exclusive": "Room of 2 Exclusive",
    "room_3": "Room of 3",
}


def get_price(university, room_type, payment_type, meal_plan=False):
    full_price = PRICES.get(university, {}).get(room_type, 0)
    if payment_type == "Semester":
        divisor = 2 if university == "Nile" else 3
        amount = full_price / divisor
    else:
        amount = full_price
    if meal_plan:
        amount += MEAL_PLAN_PRICE
    return amount


# ── Auth ─────────────────────────────────────────────────────────────────────

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(username=request.form["username"]).first()
        if user and user.check_password(request.form["password"]):
            login_user(user)
            return redirect(url_for("dashboard"))
        flash("Invalid credentials", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def dashboard():
    rooms = Room.query.all()
    total_beds = sum(r.capacity for r in rooms)
    occupied = sum(r.occupied_beds for r in rooms)
    available = total_beds - occupied
    blocks = {}
    for r in rooms:
        blocks.setdefault(r.block, []).append(r)
    students = Student.query.filter_by(is_active=True).all()
    return render_template("dashboard.html",
        rooms=rooms, total_beds=total_beds, occupied=occupied,
        available=available, blocks=blocks, students=students,
        room_type_labels=ROOM_TYPE_LABELS)


# ── Real-time API ─────────────────────────────────────────────────────────────

@app.route("/api/availability")
@login_required
def api_availability():
    rooms = Room.query.all()
    data = []
    for r in rooms:
        data.append({
            "room": r.room_number,
            "block": r.block,
            "type": ROOM_TYPE_LABELS.get(r.room_type, r.room_type),
            "capacity": r.capacity,
            "occupied": r.occupied_beds,
            "available": r.available_beds,
        })
    return jsonify(data)


# ── Rooms ─────────────────────────────────────────────────────────────────────

@app.route("/rooms")
@login_required
def rooms():
    all_rooms = Room.query.order_by(Room.block, Room.room_number).all()
    return render_template("rooms.html", rooms=all_rooms, room_type_labels=ROOM_TYPE_LABELS)


@app.route("/rooms/add", methods=["GET", "POST"])
@login_required
def add_room():
    if current_user.role != "admin":
        flash("Admin only", "danger")
        return redirect(url_for("rooms"))
    if request.method == "POST":
        rt = request.form["room_type"]
        cap_map = {"room_1": 1, "room_2": 2, "room_2_exclusive": 2, "room_3": 3}
        cap = cap_map.get(rt, 1)
        room = Room(
            block=request.form["block"].upper(),
            room_number=request.form["room_number"].upper(),
            room_type=rt,
            capacity=cap,
        )
        db.session.add(room)
        db.session.flush()
        for i in range(1, cap + 1):
            db.session.add(Bed(room_id=room.id, bed_label=f"{room.room_number}-B{i}"))
        db.session.commit()
        flash(f"Room {room.room_number} added.", "success")
        return redirect(url_for("rooms"))
    return render_template("add_room.html")


@app.route("/rooms/delete/<int:room_id>", methods=["POST"])
@login_required
def delete_room(room_id):
    if current_user.role != "admin":
        flash("Admin only", "danger")
        return redirect(url_for("rooms"))
    room = Room.query.get_or_404(room_id)
    db.session.delete(room)
    db.session.commit()
    flash("Room deleted.", "warning")
    return redirect(url_for("rooms"))


# ── Students ──────────────────────────────────────────────────────────────────

@app.route("/students")
@login_required
def students():
    all_students = Student.query.order_by(Student.full_name).all()
    return render_template("students.html", students=all_students,
        room_type_labels=ROOM_TYPE_LABELS)


@app.route("/students/add", methods=["GET", "POST"])
@login_required
def add_student():
    available_beds = (
        Bed.query.filter_by(is_occupied=False)
        .join(Room)
        .order_by(Room.block, Room.room_number)
        .all()
    )
    if request.method == "POST":
        bed_id = int(request.form["bed_id"])
        bed = Bed.query.get_or_404(bed_id)
        univ = request.form["university"]
        ptype = request.form["payment_type"]
        has_meal = "meal_plan" in request.form
        price = get_price(univ, bed.room.room_type, ptype, meal_plan=has_meal)
        student = Student(
            full_name=request.form["full_name"],
            matric_number=request.form["matric_number"],
            university=univ,
            phone=request.form.get("phone"),
            email=request.form.get("email"),
            bed_id=bed_id,
            meal_plan=has_meal,
            payment_type=ptype,
            semester_paid=request.form["semester_paid"],
            amount_paid=price,
        )
        bed.is_occupied = True
        db.session.add(student)
        db.session.commit()
        flash(f"Student {student.full_name} checked in. Amount: ₦{price:,.0f}", "success")
        return redirect(url_for("students"))
    return render_template("add_student.html", beds=available_beds,
        prices=PRICES, meal_plan_price=MEAL_PLAN_PRICE,
        semester_schedule=SEMESTER_SCHEDULE,
        room_type_labels=ROOM_TYPE_LABELS)


@app.route("/students/checkout/<int:student_id>", methods=["POST"])
@login_required
def checkout_student(student_id):
    student = Student.query.get_or_404(student_id)
    if student.bed:
        student.bed.is_occupied = False
    student.is_active = False
    db.session.commit()
    flash(f"{student.full_name} checked out.", "warning")
    return redirect(url_for("students"))


@app.route("/students/<int:student_id>")
@login_required
def student_detail(student_id):
    student = Student.query.get_or_404(student_id)
    return render_template("student_detail.html", student=student,
        room_type_labels=ROOM_TYPE_LABELS, semester_schedule=SEMESTER_SCHEDULE)


# ── Users (admin only) ────────────────────────────────────────────────────────

@app.route("/users")
@login_required
def users():
    if current_user.role != "admin":
        flash("Admin only", "danger")
        return redirect(url_for("dashboard"))
    all_users = User.query.all()
    return render_template("users.html", users=all_users)


@app.route("/users/add", methods=["GET", "POST"])
@login_required
def add_user():
    if current_user.role != "admin":
        flash("Admin only", "danger")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        u = User(username=request.form["username"], role=request.form["role"])
        u.set_password(request.form["password"])
        db.session.add(u)
        db.session.commit()
        flash("User created.", "success")
        return redirect(url_for("users"))
    return render_template("add_user.html")


# ── Seed & Run ────────────────────────────────────────────────────────────────

def seed():
    db.create_all()
    if not User.query.filter_by(username="admin").first():
        admin = User(username="admin", role="admin")
        admin.set_password("admin123")
        db.session.add(admin)

    if not User.query.filter_by(username="manager").first():
        mgr = User(username="manager", role="manager")
        mgr.set_password("manager123")
        db.session.add(mgr)

    db.session.commit()

    if Room.query.count() == 0:
        room_defs = [
            ("C", "C1", "room_1", 1),
            ("C", "C2", "room_2", 2),
            ("C", "C3", "room_2", 2),
            ("C", "C4", "room_2", 2),
            ("C", "C5", "room_3", 3),
            ("D", "D1", "room_1", 1),
            ("D", "D2", "room_2", 2),
            ("D", "D3", "room_2", 2),
            ("D", "D4", "room_2", 2),
            ("D", "D5", "room_3", 3),
            ("B", "B1", "room_2", 2),
            ("B", "B2", "room_3", 3),
            ("B", "B3", "room_2", 2),
            ("B", "B4", "room_3", 3),
            ("B", "B5", "room_2", 2),
            ("B", "B6", "room_3", 3),
            ("A", "A1", "room_3", 3),
            ("A", "A2", "room_2", 2),
            ("A", "A3", "room_3", 3),
            ("A", "A4", "room_2", 2),
            ("A", "A5", "room_1", 1),
            ("A", "A6", "room_2", 2),
            ("A", "A7", "room_2", 2),
        ]
        for block, rnum, rtype, cap in room_defs:
            room = Room(block=block, room_number=rnum, room_type=rtype, capacity=cap)
            db.session.add(room)
            db.session.flush()
            for i in range(1, cap + 1):
                db.session.add(Bed(room_id=room.id, bed_label=f"{rnum}-B{i}"))
        db.session.commit()


if __name__ == "__main__":
    with app.app_context():
        seed()
    app.run(debug=True)
