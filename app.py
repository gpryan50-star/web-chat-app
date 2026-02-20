from flask import Flask, render_template, request, redirect
from flask_socketio import SocketIO, emit
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

app = Flask(__name__)
app.config["SECRET_KEY"] = "supersecret"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///chat.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["DEBUG"] = True

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")
login_manager = LoginManager(app)
login_manager.login_view = "login"

# ===== DATABASE MODELS =====

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True)
    password_hash = db.Column(db.String(128))


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user = db.Column(db.String(80))
    text = db.Column(db.Text)
    timestamp = db.Column(db.String(20))


# ===== LOGIN MANAGER =====

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ===== ROUTES =====

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect("/chat")

        # Create new user
        new_user = User(username=username, password_hash=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        return redirect("/chat")

    return render_template("login.html")


@app.route("/chat")
@login_required
def chat():
    messages = Message.query.order_by(Message.id).all()
    return render_template("chat.html", username=current_user.username, messages=messages)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/")


# ===== SOCKET.IO EVENTS =====

users_online = {}

@socketio.on("connect")
def connect():
    username = request.args.get("username")
    if not username:
        return False  # reject socket connection

    users_online[request.sid] = username
    emit("status", f"{username} joined", broadcast=True)


@socketio.on("disconnect")
def disconnect():
    username = users_online.pop(request.sid, None)
    if username:
        emit("status", f"{username} left", broadcast=True)


@socketio.on("chat_message")
def handle_message(msg):
    username = users_online.get(request.sid)
    if not username:
        return

    data = {
        "user": username,
        "text": msg,
        "time": datetime.now().strftime("%H:%M")
    }

    db.session.add(
        Message(
            user=data["user"],
            text=data["text"],
            timestamp=data["time"]
        )
    )
    db.session.commit()

    emit("chat_message", data, broadcast=True)


@socketio.on("typing")
def handle_typing():
    username = users_online.get(request.sid)
    if username:
        emit("typing", username, broadcast=True, include_self=False)


# ===== RUN =====

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    socketio.run(app, host="0.0.0.0", port=10000, debug=True)
