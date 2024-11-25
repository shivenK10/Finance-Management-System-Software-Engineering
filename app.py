from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import mysql.connector
import yfinance as yf
from yahooquery import search
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import pandas as pd
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
import schedule
import threading
import time
import phonenumbers
import re
from forex_python.converter import CurrencyRates, RatesNotAvailableError
import requests

app = Flask(__name__)
app.secret_key = 'FMS123'

# Twilio configuration
TWILIO_ACCOUNT_SID = 'ACb3638a2dfad29871e6523cebbdc25ba6'
TWILIO_AUTH_TOKEN = 'eb0b22562f597a15dd08b1d4b0b82349'
TWILIO_WHATSAPP_NUMBER = 'whatsapp:+14155238886'
client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Database connection
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="ShivenKhare1206",
    database="finance_management"
)

# Helper function to format phone numbers
def format_phone_number(phone):
    try:
        parsed_number = phonenumbers.parse(phone, "IN")
        if phonenumbers.is_valid_number(parsed_number):
            return phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)
        else:
            raise ValueError("Invalid phone number")
    except phonenumbers.NumberParseException:
        print("Error formatting phone number:", phone)
        return None

# Routes
@app.route('/')
def home():
    return render_template('index.html', logged_in=('user_id' in session))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error_message = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()
        cursor.close()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            return redirect(url_for('expenditure'))
        else:
            error_message = "Invalid Username or Password!"
            return render_template('login.html', error_message=error_message, logged_in=False)
    return render_template('login.html', logged_in=('user_id' in session))


def validate_password(password):
    """
    Validates that the password meets the following criteria:
    - At least 8 characters long
    - Contains at least one uppercase letter
    - Contains at least one lowercase letter
    - Contains at least one digit
    - Contains at least one special character
    """
    regex = r'^(?=.*[A-Z])(?=.*[a-z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$'
    return re.match(regex, password) is not None

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        username = request.form['username']
        raw_phone = request.form['phone']
        phone = format_phone_number(raw_phone)
        
        if not phone:
            return render_template('signup.html', error_message="Invalid phone number format. Please include the country code.",
                                   name=name, username=username, phone=raw_phone)

        password = request.form['password']

        # Password validation
        if not validate_password(password):
            error_message = ("Password must be at least 8 characters long, include at least one uppercase letter, "
                             "one lowercase letter, one number, and one special character.")
            return render_template('signup.html', error_message=error_message,
                                   name=name, username=username, phone=raw_phone)

        hashed_password = generate_password_hash(password)
        session['temp_user_data'] = {
            'name': name,
            'username': username,
            'phone': phone,
            'password': hashed_password
        }

        return redirect(url_for('whatsapp_instructions'))

    return render_template('signup.html', logged_in=('user_id' in session))


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('home'))

@app.route('/whatsapp_opt_in')
def whatsapp_opt_in():
    user_data = session.get('temp_user_data')
    if not user_data:
        return redirect(url_for('signup'))
    return render_template('whatsapp_opt_in.html', phone=user_data['phone'])

@app.route('/confirm_whatsapp_opt_in', methods=['POST'])
def confirm_whatsapp_opt_in():
    user_data = session.get('temp_user_data')
    if not user_data:
        return redirect(url_for('signup'))

    if request.form['opt_in'] == 'yes':
        session['whatsapp_opt_in'] = True
        return redirect(url_for('whatsapp_instructions'))
    else:
        return complete_signup()

@app.route('/whatsapp_instructions')
def whatsapp_instructions():
    return render_template('whatsapp_instructions.html', twilio_number=TWILIO_WHATSAPP_NUMBER)

@app.route('/verify_whatsapp', methods=['POST'])
def verify_whatsapp():
    user_data = session.get('temp_user_data')
    if not user_data:
        return redirect(url_for('signup'))

    if verify_whatsapp_message(user_data['phone']):
        return complete_signup()
    else:
        return "Please send 'join copper-stage' to the WhatsApp number provided and try again."

def verify_whatsapp_message(phone):
    return True

def complete_signup():
    user_data = session.pop('temp_user_data', None)
    if not user_data:
        return redirect(url_for('signup'))

    cursor = db.cursor()
    cursor.execute("INSERT INTO users (name, username, phone, password) VALUES (%s, %s, %s, %s)", 
                   (user_data['name'], user_data['username'], user_data['phone'], user_data['password']))
    db.commit()
    cursor.close()

    # Check if Twilio WhatsApp message is triggered
    try:
        client.messages.create(
            body="Welcome to the Finance Management System! You will receive daily reminders to log your expenses. You can enter your expenses here to keep the record. Please enter as '<Amount> <Category>' (e.g., '1000 Groceries'). Also, to get your expense summary, send: 'Send me my expense summary for <month>'.",
            from_=TWILIO_WHATSAPP_NUMBER,
            to=f"whatsapp:{user_data['phone']}"
        )
    except Exception as e:
        print(f"Error sending message: {e}")

    return redirect(url_for('login'))


@app.route('/expenditure', methods=['GET', 'POST'])
def expenditure():
    if 'user_id' in session:
        user_id = session['user_id']

        # Handle adding a new expenditure
        if request.method == 'POST':
            amount = request.form['amount']
            category = request.form['category']

            # Insert the expense into the database
            cursor = db.cursor()
            cursor.execute("INSERT INTO expenses (user_id, amount, category, date) VALUES (%s, %s, %s, %s)", 
                           (user_id, amount, category, datetime.datetime.now()))
            db.commit()
            cursor.close()

            # Redirect to the same page to avoid duplicate POST submission
            return redirect(url_for('expenditure'))

        # Handle the GET request for displaying expenses
        selected_month = request.args.get('month', 'all')
        cursor = db.cursor(dictionary=True)

        # Filter data by month if selected
        if selected_month == 'all':
            cursor.execute("SELECT * FROM expenses WHERE user_id=%s ORDER BY date DESC", (user_id,))
        else:
            cursor.execute("""
                SELECT * FROM expenses 
                WHERE user_id=%s AND MONTH(date)=%s 
                ORDER BY date DESC
            """, (user_id, selected_month))

        expenses = cursor.fetchall()

        # Get category totals for pie chart
        cursor.execute("""
            SELECT category, SUM(amount) AS total_amount 
            FROM expenses 
            WHERE user_id=%s
        """ + ("" if selected_month == 'all' else " AND MONTH(date)=%s") + " GROUP BY category",
            (user_id,) if selected_month == 'all' else (user_id, selected_month))
        
        category_totals = cursor.fetchall()
        cursor.close()

        return render_template(
            'expenditure.html', 
            expenses=expenses, 
            category_totals=category_totals, 
            selected_month=selected_month,
            logged_in=True
        )
    return redirect(url_for('login'))

@app.route('/delete_expenditure/<int:id>', methods=['POST'])
def delete_expenditure(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    cursor = db.cursor()
    cursor.execute("DELETE FROM expenses WHERE id = %s AND user_id = %s", (id, session['user_id']))
    db.commit()
    cursor.close()
    
    return redirect(url_for('expenditure'))

@app.route('/stock')
def stock():
    if 'user_id' in session:
        nifty = yf.Ticker("^NSEI").history(period="5d")['Close'].tolist()
        sensex = yf.Ticker("^BSESN").history(period="5d")['Close'].tolist()
        usd_inr = yf.Ticker("USDINR=X").history(period="5d")['Close'].tolist()
        banknifty = yf.Ticker("^NSEBANK").history(period="5d")['Close'].tolist()
        midcpnifty = yf.Ticker("^NSEMDCP50").history(period="5d")['Close'].tolist()
        niftyit = yf.Ticker("^CNXIT").history(period="5d")['Close'].tolist()

        return render_template(
            'stock.html',
            nifty=nifty,
            sensex=sensex,
            usd_inr=usd_inr,
            banknifty=banknifty,
            midcpnifty=midcpnifty,
            niftyit=niftyit,
            logged_in=True
        )
    return redirect(url_for('login'))

@app.route('/live_stock_data')
def live_stock_data():
    try:
        nifty = yf.Ticker("^NSEI").history(period="1d")['Close'].tolist()
        sensex = yf.Ticker("^BSESN").history(period="1d")['Close'].tolist()
        usd_inr = yf.Ticker("USDINR=X").history(period="1d")['Close'].tolist()
        banknifty = yf.Ticker("^NSEBANK").history(period="1d")['Close'].tolist()
        midcpnifty = yf.Ticker("^NSEMDCP50").history(period="1d")['Close'].tolist()
        niftyit = yf.Ticker("^CNXIT").history(period="1d")['Close'].tolist()

        return jsonify({
            "nifty": nifty[-5:],
            "sensex": sensex[-5:],
            "usd_inr": usd_inr[-5:],
            "banknifty": banknifty[-5:],
            "midcpnifty": midcpnifty[-5:],
            "niftyit": niftyit[-5:]
        })
    except Exception as e:
        return jsonify({"error": str(e)})

def get_exchange_rate(base_currency, target_currency):
    try:
        url = f"https://v6.exchangerate-api.com/v6/2c933e61d5b2c53a6c2fe70a/latest/{base_currency}"
        response = requests.get(url)
        data = response.json()
        if response.status_code != 200 or "error" in data:
            raise Exception(data.get("error-type", "Unknown error"))
        return data["conversion_rates"][target_currency]
    except Exception as e:
        print(f"Error fetching exchange rate: {e}")
        return None
    
@app.route('/search_stock', methods=['POST'])
def search_stock():
    company_name = request.form['symbol']
    duration = request.form['duration']
    period_map = {'6mo': '6mo', '1y': '1y', '2y': '2y', '5y': '5y'}
    period = period_map.get(duration, '6mo')

    try:
        # Search for the stock using YahooQuery
        results = search(company_name)
        quotes = results.get('quotes', [])
        if not quotes:
            return jsonify({"error": f"No companies found for '{company_name}'"})

        symbol = quotes[0]['symbol']
        stock_name = quotes[0]['shortname']
        stock = yf.Ticker(symbol)
        history = stock.history(period=period)

        if history.empty:
            return jsonify({"error": f"No data available for {stock_name} ({symbol}) over the selected period."})

        currency = stock.info.get('currency', 'N/A')
        dates = history.index.strftime('%Y-%m-%d').tolist()
        prices = history['Close'].tolist()
        current_price = prices[-1] if prices else None

        # Convert the current price to INR if the currency is not INR
        if currency != 'INR' and current_price is not None:
            conversion_rate = get_exchange_rate(currency, 'INR')
            if conversion_rate is not None:
                current_price_in_inr = round(current_price * conversion_rate, 2)
            else:
                return jsonify({"error": "Failed to fetch exchange rate."})
        else:
            current_price_in_inr = current_price

        return jsonify({
            "symbol": symbol.upper(),
            "stock_name": stock_name,
            "currency": currency,
            "current_price": round(current_price_in_inr, 2),
            "original_price": current_price,
            "original_currency": currency,
            "dates": dates,
            "prices": prices
        })
    except Exception as e:
        return jsonify({"error": str(e)})
    
def send_daily_reminders():
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT phone FROM users")
    users = cursor.fetchall()
    cursor.close()

    for user in users:
        try:
            client.messages.create(
                body="Reminder: Please log your daily expenses in the format '<Amount> <Category>' (e.g., '1000 Groceries')",
                from_=TWILIO_WHATSAPP_NUMBER,
                to=f"whatsapp:{user['phone']}"
            )
        except Exception as e:
            print(f"Failed to send message to {user['phone']}: {e}")

def schedule_daily_reminders():
    schedule.every().day.at("22:00").do(send_daily_reminders)
    while True:
        schedule.run_pending()
        time.sleep(60)

threading.Thread(target=schedule_daily_reminders).start()

@app.route('/whatsapp', methods=['POST'])
def whatsapp_reply():
    incoming_msg = request.values.get('Body', '').strip()
    from_number = request.values.get('From', '').replace('whatsapp:', '')

    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT id, reset_pending FROM users WHERE phone = %s", (from_number,))
    user = cursor.fetchone()
    cursor.close()

    response = MessagingResponse()

    if not user:
        response.message("User not found. Please ensure your number is registered.")
        return str(response)

    user_id = user['id']

    # Handle password reset flow
    if user['reset_pending']:
        if not validate_password(incoming_msg):  # Check password complexity
            error_message = (
                "Invalid password format. Password must be at least 8 characters long, include at least one uppercase letter, "
                "one lowercase letter, one number, and one special character."
            )
            response.message(error_message)
        else:
            # Update the password in the database
            hashed_password = generate_password_hash(incoming_msg)
            cursor = db.cursor()
            cursor.execute("UPDATE users SET password = %s, reset_pending = FALSE WHERE id = %s", (hashed_password, user_id))
            db.commit()
            cursor.close()
            response.message("Password reset successfully. You can now log in.")
        return str(response)

    # Handle expense summary
    if incoming_msg.lower().startswith("send me my expense summary for"):
        try:
            # Extract the month from the message
            month_name = incoming_msg.split("for")[-1].strip().lower()
            month_number = datetime.datetime.strptime(month_name, "%B").month

            # Query the database for the category-wise summary
            cursor = db.cursor(dictionary=True)
            cursor.execute("""
                SELECT category, SUM(amount) AS total_amount 
                FROM expenses 
                WHERE user_id = %s AND MONTH(date) = %s
                GROUP BY category
            """, (user_id, month_number))
            summary = cursor.fetchall()
            cursor.close()

            # Prepare the response
            if summary:
                summary_text = f"Expense summary for {month_name.capitalize()}:\n"
                for item in summary:
                    summary_text += f"• {item['category']}: ₹{item['total_amount']:.2f}\n"
                response.message(summary_text)
            else:
                response.message(f"No expenses found for {month_name.capitalize()}.")
        except ValueError:
            response.message("Invalid month name. Please use the full month name (e.g., 'January').")
        except Exception as e:
            response.message(f"An error occurred: {str(e)}")
        return str(response)

    # Handle expense logging
    expenses = []
    for line in incoming_msg.splitlines():
        try:
            amount, category = line.split(" ", 1)
            expenses.append((float(amount), category.strip()))
        except ValueError:
            response.message("Invalid format. Please enter as '<Amount> <Category>' (e.g., '1000 Groceries').")
            return str(response)

    for amount, category in expenses:
        try:
            cursor = db.cursor()
            cursor.execute("INSERT INTO expenses (user_id, amount, category, date) VALUES (%s, %s, %s, %s)", 
                           (user_id, amount, category, datetime.datetime.now()))
            db.commit()
            cursor.close()
        except Exception as e:
            response.message(f"Error logging expense: {str(e)}")
            return str(response)

    response.message("Expenses logged successfully.")
    return str(response)


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        phone = request.form['phone']
        formatted_phone = format_phone_number(phone)
        
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE phone = %s", (formatted_phone,))
        user = cursor.fetchone()
        cursor.close()
        
        if user:
            session['reset_phone'] = formatted_phone
            cursor = db.cursor()
            cursor.execute("UPDATE users SET reset_pending = TRUE WHERE phone = %s", (formatted_phone,))
            db.commit()
            cursor.close()

            client.messages.create(
                body="Request for reset password: Please enter your new password.",
                from_=TWILIO_WHATSAPP_NUMBER,
                to=f"whatsapp:{formatted_phone}"
            )
            return render_template("verify_password_reset.html")
        else:
            # Pass an error message to the template if the phone number is unregistered
            error_message = "Invalid or Unregistered Phone Number"
            return render_template('forgot_password.html', error_message=error_message)

    return render_template('forgot_password.html')


@app.route('/verify_password_reset', methods=['GET', 'POST'])
def verify_password_reset():
    if 'reset_phone' not in session:
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        new_password = request.form.get('password', '').strip()
        phone = session.pop('reset_phone', None)

        # Password validation
        if not validate_password(new_password):
            error_message = ("Password must be at least 8 characters long, include at least one uppercase letter, "
                             "one lowercase letter, one number, and one special character.")
            return render_template('verify_password_reset.html', error_message=error_message)

        hashed_password = generate_password_hash(new_password)
        cursor = db.cursor()
        cursor.execute("UPDATE users SET password = %s WHERE phone = %s", (hashed_password, phone))
        db.commit()
        cursor.close()

        return "Your password has been successfully reset. <a href='/login'>Login here</a>."
    return render_template('verify_password_reset.html')

@app.route('/educational')
def educational():
    return render_template('educational.html', logged_in=('user_id' in session))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
