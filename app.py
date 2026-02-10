from flask import Flask, render_template, request, redirect, session
from flask_socketio import SocketIO, emit
from datetime import datetime

app = Flask(__name__)
app.config["SECRET_KEY"] = "supersecret"
socketio = SocketIO(app, cors_allowed_origins="*")

users = {}  # sid -> username
messages = []  # chat history


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        session["username"] = request.form["username"]
        return redirect("/chat")
    return render_template("login.html")


@app.route("/chat")
def chat():
    if "username" not in session:
        return redirect("/")
    return render_template("chat.html", username=session["username"], messages=messages)


@socketio.on("connect")
def connect():
    if "username" in session:
        users[request.sid] = session["username"]
        emit("status", f"{session['username']} joined", broadcast=True)


@socketio.on("disconnect")
def disconnect():
    username = users.pop(request.sid, None)
    if username:
        emit("status", f"{username} left", broadcast=True)


@socketio.on("message")
def handle_message(msg):
    data = {
        "user": users[request.sid],
        "text": msg,
        "time": datetime.now().strftime("%H:%M")
    }
    messages.append(data)
    emit("message", data, broadcast=True)


@socketio.on("typing")
def typing():
    emit("typing", users[request.sid], broadcast=True, include_self=False)


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=10000)
