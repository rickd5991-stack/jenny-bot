from flask import Flask, request
from dotenv import load_dotenv
import os
import requests
from datetime import datetime
import re
from dateutil import parser as date_parser

load_dotenv()

app = Flask(__name__)

# In-memory storage (fine for low traffic ~5 bookings/day; resets on redeploy/sleep)
STATE = {}
BOOKINGS = []

# Config from .env
AT_API_KEY = os.getenv('AFRICAS_TALKING_API_KEY')
AT_USERNAME = os.getenv('AT_USERNAME', 'sandbox')  # 'sandbox' for testing

# Helper: Send confirmation SMS via Africa's Talking
def send_sms(to, message):
    cleaned_to = re.sub(r'\D', '', to)
    if not to.startswith('+'):
        cleaned_to = '254' + cleaned_to.lstrip('0')
    to = '+' + cleaned_to

    url = 'https://api.sandbox.africastalking.com/version1/messaging' if AT_USERNAME == 'sandbox' else 'https://api.africastalking.com/version1/messaging'
    
    payload = {
        'username': AT_USERNAME,
        'to': to,
        'message': message,
        'from': 'JENNY'  # Alphanumeric sender ID (works in sandbox)
    }
    headers = {'apiKey': AT_API_KEY, 'Content-Type': 'application/x-www-form-urlencoded'}
    
    try:
        requests.post(url, data=payload, headers=headers, timeout=10)
    except:
        pass  # Fail silently (check logs in production)

# Validation helpers
def is_name(text):
    return len(text) >= 2 and any(c.isalpha() for c in text) and not text.isdigit()

def is_contact(text):
    email_re = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    phone_re = r'^\+?[\d\s-]{10,15}$'
    cleaned = re.sub(r'\D', '', text)
    return bool(re.match(email_re, text)) or (len(cleaned) >= 9 and text.replace(' ', '').lstrip('+').isdigit())

def is_datetime(text):
    keywords = ['today', 'tomorrow', 'leo', 'kesho', 'monday', 'tuesday', 'am', 'pm', 'saa', 'at', ':']
    if any(k in text.lower() for k in keywords):
        return True
    try:
        date_parser.parse(text, fuzzy=True)
        return True
    except:
        return False

def check_availability(dt_str):
    dt_lower = dt_str.lower()
    return not any(b['datetime_str'].lower() == dt_lower for b in BOOKINGS)

def book_appointment(data, dt_str, phone_number):
    booking = {
        'name': data['name'],
        'contact': data['contact'],
        'datetime_str': dt_str,
        'phone': phone_number,
        'booked_at': datetime.now().isoformat()
    }
    BOOKINGS.append(booking)

# Repeat prompts for timeouts/no input
REPEAT_PROMPTS = {
    'name': "Pole, sielewi. Sema jina lako kamili tena.",
    'contact': "Pole, toa namba au email sahihi tena.",
    'datetime': "Pole, eleza wakati vizuri tena. Kama tomorrow at 3 PM."
}

@app.route('/callback', methods=['POST'])
def callback():
    global STATE, BOOKINGS

    session_id = request.form.get('sessionId')
    phone_number = request.form.get('phoneNumber')
    text = request.form.get('text', '').strip()
    is_voice = 'duration' in request.form or request.form.get('isActive') == '1'

    # Init session
    if session_id not in STATE:
        STATE[session_id] = {'stage': 'start', 'phone': phone_number}

    data = STATE[session_id]
    stage = data['stage']

    # Handle no input / timeout (repeat question)
    if text == '' and stage != 'start':
        response = REPEAT_PROMPTS.get(stage, "Pole, sema tena.")
    else:
        response = ""

        if stage == 'start':
            if text == '':
                response = "Jambo! Habari yako? This is Jenny, your poa beauty parlor reservation assistant. \nKaribu sana! Sema 'book' au 1 kuweka slot."
            elif 'book' in text.lower() or '1' in text or 'slot' in text.lower():
                data['stage'] = 'name'
                response = "Poa! Sema jina lako kamili."
            else:
                response = "Sorry, sielewi. Sema 'book' kuendelea."

        elif stage == 'name':
            if is_name(text):
                data['name'] = text.title()
                data['stage'] = 'contact'
                response = f"Sawa {data['name']}! Ni namba yako au email for confirmation?"
            else:
                response = REPEAT_PROMPTS['name']

        elif stage == 'contact':
            if is_contact(text):
                data['contact'] = text
                data['stage'] = 'datetime'
                response = "Poa! Sasa, slot gani unataka? Kama tomorrow at 3 PM au kesho saa tisa."
            else:
                response = REPEAT_PROMPTS['contact']

        elif stage == 'datetime':
            if is_datetime(text):
                dt_str = text
                if check_availability(dt_str):
                    book_appointment(data, dt_str, phone_number)
                    send_sms(phone_number, f"Asante {data['name']}! Slot yako {dt_str} imebooked. Karibu! ~Jenny")
                    response = f"END Asante {data['name']}! Slot yako {dt_str} imebooked. Confirmation imekufikia kwa SMS. Kwaheri!"
                    del STATE[session_id]
                else:
                    response = "END Pole sana, slot hiyo imejaa. Jaribu nyingine. Piga tena!"
                    del STATE[session_id]
            else:
                response = REPEAT_PROMPTS['datetime']

    # Return format
    if not is_voice:
        prefix = "END " if 'END ' in response else "CON "
        return prefix + response.replace('END ', '').replace('CON ', '')

    # Voice: Return AML XML with speech recognition + woman voice
    clean_response = response.replace('END ', '').replace('CON ', '')
    xml = '<?xml version="1.0" encoding="UTF-8"?>'
    xml += '<Response>'
    xml += f'<Say voice="woman">{clean_response}</Say>'
    
    if 'END ' not in response:
        xml += '<GetSpeech timeout="60" />'  # 60s to speak
    xml += '</Response>'
    
    return xml, 200, {'Content-Type': 'application/xml'}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=os.getenv('PORT', 5000))