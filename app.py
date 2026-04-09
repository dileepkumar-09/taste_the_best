from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
import boto3
from datetime import datetime
import json, uuid

app = Flask(__name__)
app.secret_key = 'homemade_secret_key'

dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
users_table = dynamodb.Table('Users')
orders_table = dynamodb.Table('Orders')

products = {
    'non_veg_pickles': [
        {'id': 1, 'name': 'Chicken Pickle', 'weights': {'250': 600, '500': 1200, '1000': 1800}},
        {'id': 2, 'name': 'Fish Pickle', 'weights': {'250': 200, '500': 400, '1000': 800}},
        {'id': 3, 'name': 'Gongura Mutton', 'weights': {'250': 400, '500': 800, '1000': 1600}},
        {'id': 4, 'name': 'Mutton Pickle', 'weights': {'250': 400, '500': 800, '1000': 1600}},
        {'id': 5, 'name': 'Gongura Prawns', 'weights': {'250': 600, '500': 1200, '1000': 1800}},
        {'id': 6, 'name': 'Chicken Pickle (Gongura)', 'weights': {'250': 600, '500': 1200, '1000': 1800}}
    ],
    'veg_pickles': [
        {'id': 7, 'name': 'Traditional Mango Pickle', 'weights': {'250': 150, '500': 280, '1000': 500}},
        {'id': 8, 'name': 'Zesty Lemon Pickle', 'weights': {'250': 120, '500': 220, '1000': 400}},
        {'id': 9, 'name': 'Tomato Pickle', 'weights': {'250': 130, '500': 240, '1000': 450}},
        {'id': 10, 'name': 'Kakarakaya Pickle', 'weights': {'250': 130, '500': 240, '1000': 450}},
        {'id': 11, 'name': 'Chintakaya Pickle', 'weights': {'250': 130, '500': 240, '1000': 450}},
        {'id': 12, 'name': 'Spicy Pandu Mirchi', 'weights': {'250': 130, '500': 240, '1000': 450}}
    ],
    'snacks': [
        {'id': 13, 'name': 'Banana Chips', 'weights': {'250': 300, '500': 600, '1000': 800}},
        {'id': 14, 'name': 'Crispy Aam-Papad', 'weights': {'250': 150, '500': 300, '1000': 600}},
        {'id': 15, 'name': 'Crispy Chekka Pakodi', 'weights': {'250': 100, '500': 200, '1000': 400}},
        {'id': 16, 'name': 'Boondhi Acchu', 'weights': {'250': 300, '500': 600, '1000': 900}},
        {'id': 17, 'name': 'Ragi Laddu', 'weights': {'250': 350, '500': 700, '1000': 1000}},
        {'id': 18, 'name': 'Dry Fruit Laddu', 'weights': {'250': 500, '500': 1000, '1000': 1500}}
    ]
}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip()
        password = request.form['password']
        hashed_password = generate_password_hash(password)
        users_table.put_item(Item={'username': username, 'email': email, 'password': hashed_password})
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        response = users_table.get_item(Key={'username': username})
        if 'Item' in response:
            user = response['Item']
            if check_password_hash(user['password'], password):
                session['logged_in'] = True
                session['username'] = username
                return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/home')
def home():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('home.html')

@app.route('/veg_pickles')
def veg_pickles():
    return render_template('veg_pickles.html', products=products['veg_pickles'])

@app.route('/non_veg_pickles')
def non_veg_pickles():
    return render_template('non_veg_pickles.html', products=products['non_veg_pickles'])

@app.route('/snacks')
def snacks():
    return render_template('snacks.html', products=products['snacks'])

@app.route('/cart')
def cart():
    return render_template('cart.html')

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if request.method == 'POST':
        orders_table.put_item(Item={
            'order_id': str(uuid.uuid4()),
            'username': session.get('username', 'Guest'),
            'name': request.form.get('name'),
            'address': request.form.get('address'),
            'phone': request.form.get('phone'),
            'items': json.loads(request.form.get('cart_data', '[]')),
            'total_amount': float(request.form.get('total_amount', 0)),
            'timestamp': datetime.now().isoformat()
        })
        return redirect(url_for('success'))
    return render_template('checkout.html')

@app.route('/success')
def success():
    return render_template('success.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact us')
def contact_us():
    return render_template('contact us.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':

    app.run(host='0.0.0.0', port=5000, debug=True)
