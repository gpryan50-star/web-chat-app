from flask import Flask, render_template, request, redirect
from flask_socketio import SocketIO, emit
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    current_user,
    login_required,
)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from flask_socketio import join_room

app = Flask(__name__)
app.config["SECRET_KEY"] = "supersecret"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///chat.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["DEBUG"] = True

db = SQLAlchemy(app)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    ping_timeout=60,
    ping_interval=25,
    async_mode="eventlet",
    manage_session=False
)

login_manager = LoginManager(app)
login_manager.login_view = "login"


# ===== DATABASE MODELS =====

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True)
    password_hash = db.Column(db.String(128))

    # Profile fields
    bio = db.Column(db.Text, default="Hey, I'm new here!")
    avatar = db.Column(db.String(255), default="/static/default.png")
    joined = db.Column(db.String(20), default=datetime.now().strftime("%Y-%m-%d"))


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey("chat.id"))
    user = db.Column(db.String(80))
    text = db.Column(db.Text)
    timestamp = db.Column(db.String(20))


class Chat(db.Model):
    id = db.Column(db.Integer, primary_key=True)


class ChatUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey("chat.id"))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))


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

        if user:
            if check_password_hash(user.password_hash, password):
                login_user(user)
                return redirect("/home")
            return "Incorrect password", 401

        new_user = User(username=username, password_hash=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        return redirect("/home")

    return render_template("login.html")


@app.route("/home")
@login_required
def home():
    chats = (
        db.session.query(Chat)
        .join(ChatUser)
        .filter(ChatUser.user_id == current_user.id)
        .all()
    )

    chat_data = []
    for chat in chats:
        last_msg = (
            Message.query.filter_by(chat_id=chat.id)
            .order_by(Message.id.desc())
            .first()
        )

        other = (
            db.session.query(User)
            .join(ChatUser)
            .filter(ChatUser.chat_id == chat.id, User.id != current_user.id)
            .first()
        )

        chat_data.append({
            "chat_id": chat.id,
            "other": other,
            "last_msg": last_msg.text if last_msg else "",
            "last_time": last_msg.timestamp if last_msg else ""
        })

    return render_template("home.html", chats=chat_data)



@app.route("/profile/<username>")
@login_required
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    return render_template("profile.html", user=user)


@app.route("/edit-profile", methods=["GET", "POST"])
@login_required
def edit_profile():
    if request.method == "POST":
        current_user.bio = request.form["bio"]
        current_user.avatar = request.form["avatar"]
        db.session.commit()
        return redirect(f"/profile/{current_user.username}")

    return render_template("edit_profile.html", user=current_user)


@app.route("/chat/<int:chat_id>")
@login_required
def chat(chat_id):
    messages = Message.query.filter_by(chat_id=chat_id).all()

    other = (
        db.session.query(User)
        .join(ChatUser)
        .filter(ChatUser.chat_id == chat_id, User.id != current_user.id)
        .first()
    )

    chats = (
        db.session.query(Chat)
        .join(ChatUser)
        .filter(ChatUser.user_id == current_user.id)
        .all()
    )

    return render_template(
        "chat.html",
        username=current_user.username,
        messages=messages,
        chat_id=chat_id,
        chats=chats,
        other=other
    )


@app.route("/new_chat", methods=["POST"])
@login_required
def new_chat():
    username = request.form["username"]
    other = User.query.filter_by(username=username).first()

    if not other or other.id == current_user.id:
        return redirect("/chat/1")

    # Check if chat already exists
    existing = (
        db.session.query(Chat)
        .join(ChatUser)
        .filter(ChatUser.user_id.in_([current_user.id, other.id]))
        .group_by(Chat.id)
        .having(db.func.count(Chat.id) == 2)
        .first()
    )

    if existing:
        return redirect(f"/chat/{existing.id}")

    chat = Chat()
    db.session.add(chat)
    db.session.commit()

    db.session.add_all([
        ChatUser(chat_id=chat.id, user_id=current_user.id),
        ChatUser(chat_id=chat.id, user_id=other.id)
    ])
    db.session.commit()

    return redirect(f"/chat/{chat.id}")


@app.route("/chat")
@login_required
def chat_list():
    chats = (
        db.session.query(Chat)
        .join(ChatUser)
        .filter(ChatUser.user_id == current_user.id)
        .all()
    )
    return render_template(
        "chat.html",
        username=current_user.username,
        chats=chats,
        messages=[],
        chat_id=None
    )


@socketio.on("join_chat")
def join(chat_id):
    join_room(str(chat_id))


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
        return False

    users_online[request.sid] = username
    emit("status", f"{username} joined", broadcast=True)


@socketio.on("disconnect")
def disconnect():
    username = users_online.pop(request.sid, None)
    if username:
        emit("status", f"{username} left", broadcast=True)


@socketio.on("chat_message")
def handle_message(data):
    chat_id = data["chat_id"]
    username = users_online.get(request.sid)

    if not username:
        return  # socket not authenticated

    msg = Message(
        chat_id=chat_id,
        user=username,
        text=data["text"],
        timestamp=datetime.now().strftime("%H:%M")
    )
    db.session.add(msg)
    db.session.commit()

    emit("chat_message", {
        "user": msg.user,
        "text": msg.text,
        "time": msg.timestamp
    }, room=str(chat_id))


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
