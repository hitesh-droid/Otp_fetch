import json
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from straiveclass import EmailAuthenticator, send_request, extract_otp, fetch_webmail_data, mark_all_as_read
from datetime import datetime
from mongo import session_collection
import time


def setup_browser():
    """Set up and return a headless Chrome WebDriver."""
    service = Service(ChromeDriverManager().install())
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--headless")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--ignore-ssl-errors")
    options.add_argument("--allow-running-insecure-content")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    return webdriver.Chrome(service=service, options=options)


def extract_session_id(logs):
    """Extract session ID from browser logs."""
    for log in logs:
        try:
            log_json = json.loads(log["message"])
            if log_json["message"]["method"] == "Network.requestWillBeSent" and "hasPostData" in log_json["message"]["params"]["request"]:
                return re.search(r'sid="([^"]+)"', log_json["message"]["params"]["request"]["postData"]).group(1)
        except Exception as e:
            print(f"Error extracting session ID: {e}")
    return None


def update_session(email, sid):
    """Update session information in the database."""
    session_collection.update_one(
        {"Email": email},
        {"$set": {"SID": sid, "Timestamp": datetime.utcnow()}},
        upsert=True
    )


def get_session_id(email, password, auth_secret):
    """Authenticate and retrieve session ID."""
    authenticator = EmailAuthenticator(email, password, auth_secret)
    auth_token = authenticator.get_auth_token()

    if not auth_token:
        print("Authentication failed.")
        return None

    url = f"https://mail.straive.co/webmail/?atoken={auth_token}&language=en&remember=0"
    driver = setup_browser()
    driver.get(url)
    time.sleep(1)

    logs = driver.get_log("performance")
    sid_match = extract_session_id(logs)
    driver.quit()

    if sid_match:
        update_session(email, sid_match)
        print("Session ID retrieved successfully.")
    else:
        print("Failed to retrieve session ID.")

    return sid_match


def fetch_otp(email, sid, toggle):
    """Fetch OTP using session ID."""
    inbox_values = send_request(sid, email)
    read_status = mark_all_as_read(toggle, sid, email)

    if not inbox_values:
        print("No emails found in the inbox.")
        return None, read_status

    uids = [item["ATTRIBUTES"]["UID"] for item in inbox_values]
    mail_data = [json.loads(fetch_webmail_data(sid, email, uid)) for uid in uids]
    otp = extract_otp(mail_data)

    if otp == "LOL":
        print("No OTP found. Kindly resend.")
        return ("No OTP", "Kindly Resend"), read_status

    print("Extracted OTP:", otp)
    return otp, read_status


# Example usage
def automate_email_login(email, password, auth_secret, toggle):
    sid = get_session_id(email, password, auth_secret)
    if sid:
        return fetch_otp(email, sid, toggle)
    return None, None