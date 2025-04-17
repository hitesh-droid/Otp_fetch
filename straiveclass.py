import random
import re
import time
import requests
import pyotp
import urllib3
from Crypto.PublicKey import RSA
from datetime import datetime, timezone, timedelta
from Crypto.Cipher import PKCS1_v1_5
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class EmailAuthenticator:
    BASE_URL = "https://mail.straive.co/icewarpapi/"
    HEADERS = {
        "Content-Type": "text/xml",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Host": "mail.straive.co",
        "Origin": "https://mail.straive.co",
        "Referer": "https://mail.straive.co/webmail/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
    }

    def __init__(self, email, password, auth_key):
        self.email = email
        self.password = password
        self.auth_key = auth_key
        self.session_id = None
        self.cookie = None

    def send_request0(self, xml_payload):
        headers = self.HEADERS.copy()
        if self.session_id:
            headers["Cookie"] = f"session={self.session_id}"

        response = requests.post(self.BASE_URL, data=xml_payload, headers=headers, verify=False)
        return response.text

    def get_auth_challenge(self):
        payload = """<iq uid="1" format="text/xml">
            <query xmlns="admin:iq:rpc">
                <commandname>getauthchallenge</commandname>
                <commandparams>
                    <authtype>1</authtype>
                </commandparams>
            </query>
        </iq>"""

        response = self.send_request0(payload)
        hashid = re.search(r"<hashid>(.*?)</hashid>", response)
        timestamp = re.search(r"<timestamp>(.*?)</timestamp>", response)

        if hashid and timestamp:
            return hashid.group(1).strip(), timestamp.group(1).strip()
        return None, None

    def construct_rsa_key(self, modulus_hex):
        try:
            modulus_int = int(modulus_hex, 16)
            exponent_int = 65537
            return RSA.construct((modulus_int, exponent_int))
        except ValueError as e:
            return None

    def encrypt_password(self, hashid, timestamp):
        rsa_key = self.construct_rsa_key(hashid)
        if rsa_key is None:
            return None
        try:
            cipher = PKCS1_v1_5.new(rsa_key)
            data = f"p={self.password}&t={timestamp}".encode()
            return cipher.encrypt(data).hex()
        except Exception:
            return None

    def generate_otp(self):
        return pyotp.TOTP(self.auth_key).now()

    def get_auth_token(self):
        hashid, timestamp = self.get_auth_challenge()
        if not hashid or not timestamp:
            return None

        encrypted_password = self.encrypt_password(hashid, timestamp)
        if not encrypted_password:
            return None

        otp = self.generate_otp()
        payload = f"""<iq uid="3" format="text/xml">
            <query xmlns="admin:iq:rpc">
                <commandname>getauthtoken</commandname>
                <commandparams>
                    <email>{self.email}</email>
                    <authtype>1</authtype>
                    <persistentlogin>0</persistentlogin>
                    <digest>{encrypted_password}</digest>
                    <totpcode>{otp}</totpcode>
                </commandparams>
            </query>
        </iq>"""

        response = self.send_request0(payload)
        token_match = re.search(r"<authtoken>(.*?)</authtoken>", response)
        return token_match.group(1).strip() if token_match else None

    @staticmethod
    def generate_uid():
        return f"{random.randint(10 ** 15, 9 * 10 ** 15)}{int(time.time() * 1000)}"

def convert_to_ist(timestamp):
    """
    Convert a Unix timestamp to IST (Indian Standard Time, UTC+5:30).

    Args:
    timestamp (int): Unix timestamp (seconds since Jan 1, 1970)

    Returns:
    str: Formatted IST date-time string
    """
    # Convert to UTC datetime
    utc_time = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)


    # Convert to IST (UTC+5:30)
    ist_time = utc_time + timedelta(hours=5, minutes=30)
    # Return formatted IST time
    return ist_time.strftime('%Y-%m-%d %H:%M:%S')

def send_request(sid,email):
    generatedUID = EmailAuthenticator.generate_uid()
    headers = {
        "Content-Type": "text/xml",
        "Accept": "*/*",
        "Connection": "keep-alive",
        "Origin": "https://mail.straive.co",
        "Referer": "https://mail.straive.co/webmail/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
    }

    body = f"""
    <iq sid="{sid}" uid="{generatedUID}" type="get" format="json">
        <query xmlns="webmail:iq:items">
            <account uid="{email}">
                <folder uid="INBOX">
                    <item>
                        <values>
                            <subject/>
                            <sms/>
                            <from/>
                            <date/>
                            <ctz>330</ctz>
                        </values>
                        <filter>
                            <limit>1</limit>
                            <offset>0</offset>
                            <sort>
                                <date>desc</date>
                            </sort>
                            <search></search>
                        </filter>
                    </item>
                </folder>
            </account>
        </query>
    </iq>"""

    response = requests.post("https://mail.straive.co/webmail/server/webmail.php", headers=headers, data=body, verify=False)
    print(response.text)
    if response.status_code == 200:
        try:
            return response.json()["IQ"][0]["QUERY"][0]["ACCOUNT"][0]["FOLDER"][0]["ITEM"]
        except (ValueError, KeyError):
            return None


def extract_otp(data_list):
    extracted_otps = []
    try:
        data = data_list[0]["IQ"][0]["QUERY"][0]["ACCOUNT"][0]["FOLDER"][0]["ITEM"][0]["VALUES"][0]
        if data["SUBJECT"][0]["VALUE"]!="Your authentication code":
            return "LOL"

        html = data["HTML"][0]["VALUE"]
        date = convert_to_ist(data["DATE"][0]["VALUE"])

        otp_match = re.search(r'Your OTP.*?:\s*<strong.*?>(\d+)</strong>', html)

        if otp_match:
            extracted_otps.append((otp_match.group(1),date))
        else:
            return "LOL"
    except Exception:
            pass

    return extracted_otps


def fetch_webmail_data(sid, email, item_uid):
    url = "https://mail.straive.co/webmail/server/webmail.php"
    headers = {
        "Content-Type": "text/xml",
        "Accept": "*/*",
        "Connection": "keep-alive",
        "Origin": "https://mail.straive.co",
        "Referer": "https://mail.straive.co/webmail/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
    }

    body = f'''
    <iq sid="{sid}" type="get" format="json">
        <query xmlns="webmail:iq:items">
            <account uid="{email}">
                <folder uid="INBOX">
                    <item uid="{item_uid}">
                        <values>
                            <html/>
                            <sms/>
                            <subject/>
                            <date/>
                            <ctz>330</ctz>
                        </values>
                    </item>
                </folder>
            </account>
        </query>
    </iq>
    '''

    response = requests.post(url, headers=headers, data=body, verify=False)

    if response.status_code == 200:
        return response.text
    else:
        return {"error": f"Request failed with status code {response.status_code}"}


def mark_all_as_read(toggle, sid, email):
    """
    Marks all emails in the INBOX as read for the given email using session ID.

    Args:
        sid (str): Session ID.
        email (str): Email address of the user.

    Returns:
        str: Response text from the server.
    """
    print(toggle)
    if toggle == "True":

        url = "https://mail.straive.co/webmail/server/webmail.php"
        headers = {
            "Content-Type": "text/xml",
            "Accept": "*/*",
            "Connection": "keep-alive",
            "Origin": "https://mail.straive.co",
            "Referer": "https://mail.straive.co/webmail/",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
        }

        body = f'''
        <iq sid="{sid}" uid="{email}" type="set">
            <query xmlns="webmail:iq:folders">
                <account uid="{email}">
                    <folder uid="INBOX" action="markasread"/>
                </account>
            </query>
        </iq>'''

        response = requests.post(url, headers=headers, data=body, verify=False)
        print(response.text)

        return response.text if response.status_code == 200 else f"Failed with status {response.text}"
    else:
        return "toggle is off"
