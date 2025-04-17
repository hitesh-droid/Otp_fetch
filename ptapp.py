from flask import Flask, render_template, request, jsonify
import imaplib
import certifi
import email
from email.header import decode_header
import re
from pymongo.mongo_client import MongoClient
import pytz
from email.utils import parsedate_to_datetime
import os
import threading
import json
from concurrent.futures import ThreadPoolExecutor
from pymongo.errors import ServerSelectionTimeoutError, OperationFailure, ConfigurationError

# MongoDB connection
MONGO_URI = "mongodb+srv://dobriyalhitesh1:L6D9qLy5H4l196cw@cluster0.6sx9pme.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
mongo_client = MongoClient(MONGO_URI, tls=True, tlsCAFile=certifi.where())
db = mongo_client['Ils']
pt_ids_collection = db["web_mail"]
app = Flask(__name__)

# Error Logs
error_logs = []

def get_mongo_connection():
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)  # Timeout for quicker failure
        db = client['Credentials']
        collection = db['web_mail']
        return collection
    except ServerSelectionTimeoutError as e:
        print("Error: Unable to connect to MongoDB. Server selection timed out.")
        return None
    except OperationFailure as e:
        print(f"Error: MongoDB operation failed - {e}")
        return None
    except ConfigurationError as e:
        print(f"Error: MongoDB configuration error - {e}")
        return None
    except Exception as e:
        print(f"Error: An unexpected error occurred - {e}")
        return None

# Function to log errors
def log_error(error_message):
    error_logs.append(error_message)
    # Optionally log to a file as well:
    # with open('error_log.txt', 'a') as file:
    #     file.write(f"{error_message}\n")

# Route to display logs
@app.route('/logs', methods=['GET'])
def logs():
    return render_template('logs.html', logs=error_logs)


# Thread-local storage for connections
thread_local = threading.local()

# Function to get password from MongoDB with error handling
def get_password_from_mongo(email_id):
    try:
        # Attempt to get the MongoDB collection connection
        collection = pt_ids_collection

        # Check if the collection is valid
        if collection is None:
            log_error(f"Failed to connect to MongoDB.")
            return None

        # Log successful connection
        print("Successfully connected to MongoDB!")

        # Query for the user document with the given email_id
        user = collection.find_one({"email_id": email_id})

        # If user exists, return the password
        if user:
            return user.get("password")
        else:
            # If the user is not found in the database, log the error
            log_error(f"Email ID {email_id} not found in the database.")
            return None

    except Exception as e:
        # Log any exceptions during the function execution
        log_error(f"Error fetching password for {email_id}: {str(e)}")
        return None

# Store the connection in thread-local storage for thread safety
def get_imap_connections(email_id, password, imap_server):
    if not hasattr(thread_local, 'imap_connection'):
        try:
            # Create a new IMAP connection for each request
            imap = imaplib.IMAP4_SSL(imap_server)
            imap.login(email_id, password)
            thread_local.imap_connection = imap
        except Exception as e:
            log_error(f"Error connecting to IMAP for {email_id}: {str(e)}")
            return None
    return thread_local.imap_connection

# Function to extract OTP from email
def extract_otp_from_email(email_id, password, imap_server):
    try:
        mail = get_imap_connections(email_id, password, imap_server)
        if not mail:
            return json.dumps({"error": "IMAP connection failed."})

        mail.select("inbox")
        status, messages = mail.search(None, '(BODY "OTP" FROM "Chegg")')

        if status != "OK" or not messages[0]:
            return json.dumps({"error": "No OTP emails found."})

        email_ids = messages[0].split()
        latest_email_id = email_ids[-1]

        status, msg_data = mail.fetch(latest_email_id, "(RFC822)")
        if status != "OK":
            return json.dumps({"error": "Error fetching the latest OTP email."})

        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                subject, encoding = decode_header(msg["Subject"])[0]
                if isinstance(subject, bytes):
                    subject = subject.decode(encoding if encoding else "utf-8")

                email_date = msg["Date"]
                email_time_str = "Unknown time"
                if email_date:
                    email_time = parsedate_to_datetime(email_date)
                    india_timezone = pytz.timezone('Asia/Kolkata')
                    email_time = email_time.astimezone(india_timezone)
                    email_time_str = email_time.strftime("%Y-%m-%d %H:%M:%S")

                otp = None
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode(errors="ignore")
                            otp_match = re.search(r'\d{6}', body)
                            if otp_match:
                                otp = otp_match.group(0)
                                break
                else:
                    body = msg.get_payload(decode=True).decode(errors="ignore")
                    otp_match = re.search(r'\d{6}', body)
                    if otp_match:
                        otp = otp_match.group(0)

                if otp:
                    result = {
                        "otp": otp,
                        "date": email_time_str.split(" ")[0],
                        "time": email_time_str.split(" ")[1]
                    }
                    return result
                return json.dumps({"error": "No OTP found in the latest email."})

    except Exception as e:
        log_error(f"Error extracting OTP: {str(e)}")
        return json.dumps({"error": str(e)})

# Route to get OTPs for multiple email IDs
@app.route('/pt_otps', methods=['POST'])
def get_otps():
    try:
        email_ids = request.json.get("email_ids", [])
        otps = {}

        # Use ThreadPoolExecutor to fetch OTPs concurrently
        with ThreadPoolExecutor() as executor:
            futures = {email_id: executor.submit(fetch_otp_for_email, email_id) for email_id in email_ids}
            for email_id, future in futures.items():
                try:
                    otp = future.result()
                    otps[email_id] = otp
                except Exception as e:
                    otps[email_id] = {"error": str(e)}

        print("OTPs Retrieved:", otps)  # Debug log for OTPs
        return jsonify({"otps": otps})
    except Exception as e:
        log_error(f"Error fetching OTPs: {str(e)}")
        return jsonify({"error": str(e)}), 500

def fetch_otp_for_email(email_id):
    password = get_password_from_mongo(email_id)
    if password:
        otp = extract_otp_from_email(email_id, password, 'mail.triviumservice.com')
        return otp
    else:
        return {"error": "Email ID not found in the credentials database."}



# Route to add email and password
@app.route('/add_email', methods=['GET', 'POST'])
def add_email():
    message = None
    if request.method == 'POST':
        email_id = request.form['email_id']
        password = request.form['password']
        entered_passcode = request.form['passcode']

        # Verify the passcode
        if entered_passcode != SECURE_PASSCODE:
            message = "Invalid passcode. You are not authorized to add credentials."
        else:
            collection = get_mongo_connection()
            if collection is None:
                message = "Failed to connect to the database."
            else:
                # Check if the email_id already exists in the database
                existing_user = collection.find_one({"email_id": email_id})
                if existing_user:
                    # Update the existing user's password
                    collection.update_one({"email_id": email_id}, {"$set": {"password": password}})
                    message = "Password updated successfully!"
                else:
                    # Add new email credentials to the database
                    collection.insert_one({"email_id": email_id, "password": password})
                    message = "Email ID and password added successfully!"

    return render_template('add_email.html', message=message)



if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5006)