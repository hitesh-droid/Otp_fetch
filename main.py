import json
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, redirect, url_for, render_template, session, jsonify
from pymongo import MongoClient
from flask_session import Session
from datetime import timedelta, timezone, datetime
from werkzeug.security import generate_password_hash, check_password_hash
import os
import certifi
from functools import wraps
from mainapp import automate_email_login, fetch_otp
from ptapp import log_error, fetch_otp_for_email
from straiveclass import mark_all_as_read
from zoneinfo import ZoneInfo

# Constants
SESSION_TIMEOUT = timedelta(minutes=30)

# Flask App Init
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)

# MongoDB Config
MONGO_URI = "mongodb+srv://dobriyalhitesh1:L6D9qLy5H4l196cw@cluster0.6sx9pme.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
mongo_client = MongoClient(MONGO_URI, tls=True, tlsCAFile=certifi.where())
db = mongo_client['Ils']
st_ids_collection = db['UserAuthData']
pt_ids_collection = db["web_mail"]
session_collection = db['SessionData']
api_call_logs_collection = db['TestApiCallLogs']
toggle_collection = db['toggle']

# Flask-Session Setup
app.config['SESSION_TYPE'] = 'mongodb'
app.config['SESSION_MONGODB'] = mongo_client
app.config['SESSION_MONGODB_DB'] = 'session_db'
app.config['SESSION_MONGODB_COLLECT'] = 'sessions'
Session(app)

# Decorators
def admin_or_poc_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        user = db.users.find_one({"email": session['user']})
        if not user or user.get('role') not in ['Admin', 'POC']:
            return "Access Denied: Admin or POC only", 403
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        user = db.users.find_one({"email": session['user']})
        if not user or user.get('role') != 'Admin':
            return "Access Denied: Admins only", 403
        return f(*args, **kwargs)
    return decorated_function

# Session Validator
def get_valid_sid(email):
    sess = session_collection.find_one({"Email": email})
    if sess and "SID" in sess and "Timestamp" in sess:
        if datetime.now(timezone.utc) - sess["Timestamp"].replace(tzinfo=timezone.utc) < SESSION_TIMEOUT:
            return sess["SID"]
    return None

# Auth Routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form['email'].lower()
        password = request.form['password']
        user = db.users.find_one({"email": email})
        if user and check_password_hash(user['password'], password):
            session['user'] = email
            return redirect(url_for('dashboard'))
        return redirect(url_for('login', error='Invalid credentials'))

    return render_template("login_page.html")

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/')
def home():
    return redirect(url_for('dashboard') if 'user' in session else url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user' in session:
        email = session['user']
        user = db.users.find_one({"email": email}, {"_id": 0, "password": 0})
        name = user.get('name', 'User')
        return render_template("dashboard.html", name=name)
    return redirect(url_for('login'))

# Admin-only: Manage Users
@app.route('/manage_users')
@admin_required
def manage_users():
    st_emails = list(st_ids_collection.distinct("ID")) or []
    pt_emails = list(pt_ids_collection.distinct("email_id")) or []
    users = list(db.users.find({}, {"_id": 0, "password": 0}))
    return render_template("manage_users.html", users=users, st_emails=st_emails, pt_emails=pt_emails)

@app.route('/get_user/<email>')
def get_user(email):
    user = db.users.find_one({"email": email}, {"_id": 0, "password": 0})
    user['st_ids'] = user.get('st_ids', [])
    return jsonify(user)

@app.route('/update_user', methods=['POST'])
def update_user():
    data = request.json
    email = data['email'].lower()
    update_fields = {key: data[key] for key in ['name', 'role', 'st_ids', 'pt_ids'] if key in data}
    db.users.update_one({"email": email}, {"$set": update_fields})
    return jsonify({"status": "success"})

@app.route('/update_password', methods=['POST'])
def update_password():
    data = request.json
    email = data['email'].lower()
    new_password = generate_password_hash(data['new_password'])
    db.users.update_one({"email": email}, {"$set": {"password": new_password}})
    return jsonify({"status": "success"})

@app.route('/get_all_emails')
def get_all_emails():
    st_emails = list(st_ids_collection.distinct("ID")) or []
    pt_emails = list(pt_ids_collection.distinct("email_id")) or []
    return jsonify({"st_emails": st_emails, "pt_emails": pt_emails})

@app.route('/delete_user/<email>', methods=['DELETE'])
def delete_user(email):
    db.users.delete_one({"email": email})
    return jsonify({"status": "success"})

@app.route('/add_user', methods=['POST'])
def add_user():
    data = request.json
    email = data['email'].lower()
    if db.users.find_one({"email": email}):
        return jsonify({"status": "error", "message": "User already exists"})
    user_data = {
        "email": email,
        "password": generate_password_hash(data['password']),
        "name": data['name'],
        "role": data['role'],
        "st_ids": data.get('st_ids', []),
        "pt_ids": data.get('pt_ids', [])
    }
    db.users.insert_one(user_data)
    return jsonify({"status": "success"})

# ST OTP Route
@app.route('/dashboard/st')
def st():
    if 'user' in session:
        email = session['user']
        user = db.users.find_one({"email": email})
        role = user.get('role', '')
        st_emails = user.get('st_ids', []) if role == 'User' else list(st_ids_collection.distinct("ID"))
        return render_template("st_otp_page.html", st_emails=st_emails, user_id=email)
    return redirect(url_for('login'))

@app.route("/dashboard/st/fetch_otp", methods=["POST"])
def fetch_st_otp():
    try:
        data = request.json
        portal_id, user_id = data.get("email"), data.get("user_id")
        user = db.users.find_one({"email": user_id})
        if user.get('role') not in ["Admin", "POC"] and portal_id not in user.get('st_ids', ''):
            return jsonify({"otp": "User", "date": "don't have", "time": "access"})

        user_data = st_ids_collection.find_one({"ID": portal_id})
        sid_match = get_valid_sid(user_data["Email"])
        toggle = toggle_collection.find_one({"name": "toggle_check"})

        read = mark_all_as_read(toggle["toggle"], sid_match, user_data["Email"])

        if sid_match:
            otp, read_status = fetch_otp(user_data["Email"], sid_match, toggle)
            return jsonify({"otp": otp[0][0], "date": otp[0][1].split(" ", 1)[0], "time": otp[0][1].split(" ", 1)[1], "read": read})

        otp, read = automate_email_login(user_data["Email"], user_data["Password"], user_data["OTP_Secret"], toggle["toggle"])
        date, time = otp[0][1].split(" ", 1)
        api_call_logs_collection.insert_one({
            "user_id": user_id, "email_id": portal_id,
            "timestamp": datetime.now(timezone.utc), "type": "st"
        })
        return jsonify({"otp": otp[0][0], "date": date, "time": time, "read": read})

    except Exception as e:
        log_error(f"Error fetching ST OTP: {str(e)}")
        return jsonify({"error": str(e)}), 500

# PT OTP Routes
@app.route('/dashboard/pt')
def pt():
    if 'user' in session:
        email = session['user']
        user = db.users.find_one({"email": email})
        role = user.get('role', '')
        pt_emails = user.get('pt_ids', []) if role == 'User' else list(pt_ids_collection.distinct("email_id"))
        return render_template("pt_otp_page.html", pt_emails=pt_emails)
    return redirect(url_for('login'))

@app.route('/dashboard/pt/fetch_otps', methods=['POST'])
def get_pt_otps():
    try:
        email_ids = request.json.get("email_ids", [])
        user_id = session.get('user')
        otps = {}
        with ThreadPoolExecutor() as executor:
            futures = {eid: executor.submit(fetch_otp_for_email, eid) for eid in email_ids}
            for eid, future in futures.items():
                try:
                    otps[eid] = future.result()
                except Exception as e:
                    otps[eid] = {"error": str(e)}

            api_call_logs_collection.insert_one({
                "user_id": user_id,
                "email_ids": email_ids,
                "timestamp": datetime.now(timezone.utc),
                "type": "pt"
            })
            return jsonify({"otps": otps})
    except Exception as e:
        log_error(f"Error fetching PT OTPs: {str(e)}")
        return jsonify({"error": str(e)}), 500


# Admin-only Logs View
@app.route('/view_logs')
@admin_required
def view_logs():
    return render_template('view_logs.html')


@app.route('/get_all_users')
@admin_required
def get_all_users():
    user_ids = api_call_logs_collection.distinct("user_id")
    return jsonify({"user_ids": user_ids})


@app.route('/get_logs', methods=['POST'])
@admin_required
def get_logs():
    data = request.json
    filter_type = data.get('filter', 'today')
    user_filter = data.get('user_id')
    page = data.get('page', 1)
    logs_per_page = 10

    now = datetime.now(timezone.utc)
    query = {}

    if filter_type == 'today':
        start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
        query['timestamp'] = {'$gte': start_time}
    elif filter_type == 'week':
        start_time = now - timedelta(days=now.weekday())
        start_time = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
        query['timestamp'] = {'$gte': start_time}
    elif filter_type == 'month':
        start_time = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        query['timestamp'] = {'$gte': start_time}

    if user_filter:
        query['user_id'] = user_filter

    total_logs = api_call_logs_collection.count_documents(query)
    logs = list(api_call_logs_collection.find(query).sort('timestamp', -1).skip((page - 1) * logs_per_page).limit(
        logs_per_page))

    for log in logs:
        log['_id'] = str(log['_id'])
        log['timestamp'] = log['timestamp'].astimezone(ZoneInfo("Asia/Kolkata")).strftime('%Y-%m-%d %H:%M:%S')

    return jsonify({'logs': logs, 'total': total_logs})


@app.route('/delete_all_logs', methods=['DELETE'])
@admin_required
def delete_all_logs():
    try:
        result = api_call_logs_collection.delete_many({})
        return jsonify({"status": "success", "deleted_count": result.deleted_count})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/add_creds', methods=['GET', 'POST'])
@admin_or_poc_required
def add_id():
    if request.method == 'POST':
        client = request.form.get('client')
        email = request.form.get('email')
        password = request.form.get('password')
        secret = request.form.get('secret', '')

        data = {
            "Email": email,
            "Password": password
        }

        if client == 'st':
            data["OTP_Secret"] = secret
            st_ids_collection.insert_one(data)
        elif client == 'pt':
            pt_ids_collection.insert_one({"email_id": email, "password": password})

        return redirect(url_for('manage_users'))

    return render_template("add_credentials.html")


@app.route('/toggle')
@admin_required
def toggle_change():
    toggle = toggle_collection.find_one({"name": "toggle_check"})
    new_toggle_value = "True" if toggle["toggle"] == "False" else "False"
    toggle_collection.update_one(
        {'name': 'toggle_check'},
        {'$set': {'toggle': new_toggle_value}},
        upsert=True
    )
    return redirect(url_for('dashboard'))


if __name__ == '__main__':
    app.run(debug=True, port=5001)