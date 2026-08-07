import sys
import os
import asyncio
import json
import uuid
from datetime import datetime

# Prevent socket reuse crashes in multi-threaded Windows environments
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from flask import Flask, Response, render_template, request, redirect, url_for, session, jsonify, stream_with_context
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient

# ── Add the local Zaby SDK to the path ──
SDK_PATH = os.path.join(os.path.dirname(__file__), '..', 'zaby-sdk-python', 'src')
sys.path.insert(0, os.path.abspath(SDK_PATH))

from zaby import Zaby, ZabyRuntime, ZabyGlobalConfig, configure_zaby, ZabyApiError

# ── Load .env if python-dotenv is available ──
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

app = Flask(__name__)
app.secret_key = 'homemade_secret_key'

# ── MongoDB ──
client = MongoClient('mongodb://localhost:27017/')
db = client['taste_the_best_db']
users_table = db['Users']
orders_table = db['Orders']

# ── Zaby SDK Configuration ──
ZABY_API_KEY = os.environ.get('ZABY_API_KEY', '')
ZABY_ACCESS_TOKEN = os.environ.get('ZABY_ACCESS_TOKEN', '')
ZABY_EXTERNAL_APP_ID = os.environ.get('ZABY_EXTERNAL_APP_ID', '')
ZABY_DEPLOYMENT_ID = os.environ.get('ZABY_DEPLOYMENT_ID', '')

configure_zaby(ZabyGlobalConfig(
    environment=os.environ.get('ZABY_ENVIRONMENT', 'production'),
    api_origin=os.environ.get('ZABY_API_ORIGIN', None),
    timeout_ms=120_000
))

def get_zaby_client():
    if ZABY_API_KEY:
        return Zaby(
            api_key=ZABY_API_KEY,
            access_token=ZABY_ACCESS_TOKEN or None,
        )
    return None

# ── Helper: run async from sync Flask ──
def run_async(coro):
    """Run an async coroutine from synchronous Flask context."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

# ── Products ──
products = {
    'non_veg_pickles': [
        {'id': 1, 'name': 'Chicken Pickle', 'weights': {'250': 600, '500': 1200, '1000': 1800}, 'energy_index': {'calories': '320 kcal', 'protein': '24g', 'carbs': '5g', 'fat': '22g'}},
        {'id': 2, 'name': 'Fish Pickle', 'weights': {'250': 200, '500': 400, '1000': 800}, 'energy_index': {'calories': '290 kcal', 'protein': '22g', 'carbs': '4g', 'fat': '20g'}},
        {'id': 3, 'name': 'Gongura Mutton', 'weights': {'250': 400, '500': 800, '1000': 1600}, 'energy_index': {'calories': '350 kcal', 'protein': '20g', 'carbs': '6g', 'fat': '26g'}},
        {'id': 4, 'name': 'Mutton Pickle', 'weights': {'250': 400, '500': 800, '1000': 1600}, 'energy_index': {'calories': '340 kcal', 'protein': '21g', 'carbs': '5g', 'fat': '25g'}},
        {'id': 5, 'name': 'Gongura Prawns', 'weights': {'250': 600, '500': 1200, '1000': 1800}, 'energy_index': {'calories': '280 kcal', 'protein': '19g', 'carbs': '6g', 'fat': '18g'}},
        {'id': 6, 'name': 'Chicken Pickle (Gongura)', 'weights': {'250': 600, '500': 1200, '1000': 1800}, 'energy_index': {'calories': '330 kcal', 'protein': '23g', 'carbs': '6g', 'fat': '23g'}},
        {'id': 19, 'name': 'Spicy Crab Pickle', 'weights': {'250': 700, '500': 1400, '1000': 2100}, 'energy_index': {'calories': '270 kcal', 'protein': '18g', 'carbs': '5g', 'fat': '19g'}},
        {'id': 20, 'name': 'Tangy Prawn Pickle', 'weights': {'250': 550, '500': 1100, '1000': 1700}, 'energy_index': {'calories': '260 kcal', 'protein': '17g', 'carbs': '4g', 'fat': '16g'}},
        {'id': 21, 'name': 'Boneless Keema Pickle', 'weights': {'250': 500, '500': 950, '1000': 1800}, 'energy_index': {'calories': '360 kcal', 'protein': '22g', 'carbs': '4g', 'fat': '28g'}},
        {'id': 22, 'name': 'Andhra Duck Pickle', 'weights': {'250': 650, '500': 1300, '1000': 1900}, 'energy_index': {'calories': '380 kcal', 'protein': '20g', 'carbs': '3g', 'fat': '31g'}}
    ],
    'veg_pickles': [
        {'id': 7, 'name': 'Traditional Mango Pickle', 'weights': {'250': 150, '500': 280, '1000': 500}, 'energy_index': {'calories': '210 kcal', 'protein': '2g', 'carbs': '12g', 'fat': '18g'}},
        {'id': 8, 'name': 'Zesty Lemon Pickle', 'weights': {'250': 120, '500': 220, '1000': 400}, 'energy_index': {'calories': '90 kcal', 'protein': '1g', 'carbs': '18g', 'fat': '0g'}},
        {'id': 9, 'name': 'Tomato Pickle', 'weights': {'250': 130, '500': 240, '1000': 450}, 'energy_index': {'calories': '180 kcal', 'protein': '3g', 'carbs': '10g', 'fat': '15g'}},
        {'id': 10, 'name': 'Kakarakaya Pickle', 'weights': {'250': 130, '500': 240, '1000': 450}, 'energy_index': {'calories': '220 kcal', 'protein': '4g', 'carbs': '14g', 'fat': '17g'}},
        {'id': 11, 'name': 'Chintakaya Pickle', 'weights': {'250': 130, '500': 240, '1000': 450}, 'energy_index': {'calories': '160 kcal', 'protein': '2g', 'carbs': '24g', 'fat': '8g'}},
        {'id': 12, 'name': 'Spicy Pandu Mirchi', 'weights': {'250': 130, '500': 240, '1000': 450}, 'energy_index': {'calories': '150 kcal', 'protein': '2g', 'carbs': '12g', 'fat': '10g'}},
        {'id': 23, 'name': 'Garlic Pickle', 'weights': {'250': 140, '500': 260, '1000': 480}, 'energy_index': {'calories': '190 kcal', 'protein': '3g', 'carbs': '22g', 'fat': '11g'}},
        {'id': 24, 'name': 'Avakaya Ginger Pickle', 'weights': {'250': 160, '500': 300, '1000': 550}, 'energy_index': {'calories': '215 kcal', 'protein': '2g', 'carbs': '14g', 'fat': '17g'}},
        {'id': 25, 'name': 'Amla Pickle', 'weights': {'250': 130, '500': 240, '1000': 450}, 'energy_index': {'calories': '140 kcal', 'protein': '1g', 'carbs': '28g', 'fat': '6g'}},
        {'id': 26, 'name': 'Green Chili Pickle', 'weights': {'250': 120, '500': 220, '1000': 400}, 'energy_index': {'calories': '130 kcal', 'protein': '2g', 'carbs': '10g', 'fat': '9g'}}
    ],
    'snacks': [
        {'id': 13, 'name': 'Banana Chips', 'weights': {'250': 300, '500': 600, '1000': 800}, 'energy_index': {'calories': '530 kcal', 'protein': '4g', 'carbs': '58g', 'fat': '32g'}},
        {'id': 14, 'name': 'Crispy Aam-Papad', 'weights': {'250': 150, '500': 300, '1000': 600}, 'energy_index': {'calories': '320 kcal', 'protein': '1g', 'carbs': '78g', 'fat': '0g'}},
        {'id': 15, 'name': 'Crispy Chekka Pakodi', 'weights': {'250': 100, '500': 200, '1000': 400}, 'energy_index': {'calories': '480 kcal', 'protein': '8g', 'carbs': '62g', 'fat': '22g'}},
        {'id': 16, 'name': 'Boondhi Acchu', 'weights': {'250': 300, '500': 600, '1000': 900}, 'energy_index': {'calories': '450 kcal', 'protein': '6g', 'carbs': '65g', 'fat': '18g'}},
        {'id': 17, 'name': 'Ragi Laddu', 'weights': {'250': 350, '500': 700, '1000': 1000}, 'energy_index': {'calories': '410 kcal', 'protein': '7g', 'carbs': '68g', 'fat': '14g'}},
        {'id': 18, 'name': 'Dry Fruit Laddu', 'weights': {'250': 500, '500': 1000, '1000': 1500}, 'energy_index': {'calories': '460 kcal', 'protein': '10g', 'carbs': '54g', 'fat': '22g'}},
        {'id': 27, 'name': 'Spicy Murukku', 'weights': {'250': 120, '500': 240, '1000': 450}, 'energy_index': {'calories': '470 kcal', 'protein': '7g', 'carbs': '60g', 'fat': '20g'}},
        {'id': 28, 'name': 'Sweet Jaggery Gavvalu', 'weights': {'250': 180, '500': 350, '1000': 650}, 'energy_index': {'calories': '430 kcal', 'protein': '5g', 'carbs': '72g', 'fat': '12g'}},
        {'id': 29, 'name': 'Sesame Chikki', 'weights': {'250': 150, '500': 300, '1000': 600}, 'energy_index': {'calories': '490 kcal', 'protein': '12g', 'carbs': '48g', 'fat': '28g'}},
        {'id': 30, 'name': 'Crispy Kumpolu', 'weights': {'250': 110, '500': 220, '1000': 400}, 'energy_index': {'calories': '460 kcal', 'protein': '6g', 'carbs': '64g', 'fat': '16g'}}
    ]
}

@app.route('/api/product/<product_id>')
def get_product_details(product_id):
    import re
    # Try integer match first
    try:
        pid = int(product_id)
        for category, item_list in products.items():
            for item in item_list:
                if item['id'] == pid:
                    return jsonify(_format_product_response(item))
    except ValueError:
        pass

    # Normalize string input (remove spaces, punctuation, lowercase)
    norm_input = re.sub(r'[^a-zA-Z0-9]', '', product_id).lower()

    # Hardcoded placeholder fallbacks to prevent empty cards when the agent copies examples from prompts
    if 'pickle' in norm_input:
        for category, item_list in products.items():
            for item in item_list:
                if item['id'] == 7: # Default to Traditional Mango Pickle
                    return jsonify(_format_product_response(item))
    if 'snack' in norm_input or 'sweet' in norm_input:
        for category, item_list in products.items():
            for item in item_list:
                if item['id'] == 13: # Default to Banana Chips
                    return jsonify(_format_product_response(item))
    
    # Check for exact normalized match
    for category, item_list in products.items():
        for item in item_list:
            norm_name = re.sub(r'[^a-zA-Z0-9]', '', item['name']).lower()
            if norm_name == norm_input:
                return jsonify(_format_product_response(item))

    # Fallback to keyword matching
    # Split input by camelCase, underscores, or hyphens
    keywords = re.findall(r'[A-Z]?[a-z]+|[0-9]+', product_id)
    keywords = [k.lower() for k in keywords if len(k) > 1]
    
    if not keywords:
        keywords = [norm_input]

    best_match = None
    max_matches = 0
    
    for category, item_list in products.items():
        for item in item_list:
            name_words = re.findall(r'[a-zA-Z0-9]+', item['name'].lower())
            matches = sum(1 for kw in keywords if kw in name_words or any(kw in word or word in kw for word in name_words))
            if matches > max_matches:
                max_matches = matches
                best_match = item

    if best_match and max_matches > 0:
        return jsonify(_format_product_response(best_match))

    return jsonify({'error': 'Product not found'}), 404

def _format_product_response(item):
    img_name = item['name'].replace(' ', '_').lower() + '.jpg'
    energy = item.get('energy_index', {})
    calories = energy.get('calories', 'N/A')
    protein = energy.get('protein', 'N/A')
    carbs = energy.get('carbs', 'N/A')
    fat = energy.get('fat', 'N/A')
    
    name_lower = item['name'].lower()
    is_sweet = any(kw in name_lower for kw in ['laddu', 'papad', 'acchu', 'gavvalu', 'chikki'])
    price = item['weights'].get('250', 200)
    
    return {
        'id': item['id'],
        'name': item['name'],
        'image': url_for('static', filename=f'images/{img_name}'),
        'price': price,
        'weights': item['weights'],
        'calories': calories,
        'protein': protein,
        'carbs': carbs,
        'fat': fat,
        'spice': 'Sweet' if is_sweet else 'Medium',
        'sweetness': 'Medium' if is_sweet else 'N/A',
        'pairing': 'Sweets/Dessert' if is_sweet else 'Rice/Rotis/Snacks'
    }


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    error = None
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip()
        password = request.form['password']
        existing_user = users_table.find_one({'Username': username})
        if existing_user:
            error = "Username already exists"
        else:
            hashed_password = generate_password_hash(password)
            users_table.insert_one({'Username': username, 'email': email, 'password': hashed_password})
            return redirect(url_for('login'))
    return render_template('signup.html', error=error)

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        user = users_table.find_one({'Username': username})
        if user and check_password_hash(user['password'], password):
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('home'))
        else:
            error = "Invalid username or password"
    return render_template('login.html', error=error)

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
        orders_table.insert_one({
            'Order_id': str(uuid.uuid4()),
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


@app.route('/api/checkout', methods=['POST'])
def api_checkout():
    """Submit checkout details and items from the chatbox widget."""
    if not session.get('logged_in'):
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        data = request.get_json(silent=True) or {}
        name = data.get('name', '').strip()
        address = data.get('address', '').strip()
        phone = data.get('phone', '').strip()
        cart_data = data.get('cart_data', [])
        total_amount = float(data.get('total_amount', 0))

        if not name or not address or not phone:
            return jsonify({'error': 'All fields (Name, Address, Phone) are required.'}), 400

        if not cart_data:
            return jsonify({'error': 'Your cart is empty.'}), 400

        order_id = str(uuid.uuid4())
        orders_table.insert_one({
            'Order_id': order_id,
            'username': session.get('username', 'Guest'),
            'name': name,
            'address': address,
            'phone': phone,
            'items': cart_data,
            'total_amount': total_amount,
            'timestamp': datetime.now().isoformat()
        })

        # Save profile details on checkout for future autofill
        username = session.get('username')
        if username:
            users_table.update_one(
                {'Username': username},
                {'$set': {
                    'profile_name': name,
                    'phone': phone,
                    'address': address
                }}
            )

        return jsonify({
            'success': True,
            'order_id': order_id
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/profile', methods=['GET'])
def api_profile():
    """Retrieve stored profile details for checkout autofill."""
    if not session.get('logged_in'):
        return jsonify({'error': 'Not authenticated'}), 401

    username = session.get('username')
    if not username:
        return jsonify({}), 200

    user = users_table.find_one({'Username': username})
    if not user:
        return jsonify({}), 200

    return jsonify({
        'name': user.get('profile_name', ''),
        'phone': user.get('phone', ''),
        'address': user.get('address', '')
    })


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

# ═══════════════════════════════════════════════
#  Zaby SDK API Endpoints
# ═══════════════════════════════════════════════

async def get_or_create_default_policy(client):
    try:
        policies = await client.runtime_token_policies.list()
        if policies and policies.get('items'):
            return policies['items'][0]['id']
    except Exception:
        pass

    try:
        new_policy = await client.runtime_token_policies.create({
            "name": "App Default Limit",
            "windowDurationMs": 3600000,
            "maxTokens": 100000
        })
        return new_policy['id']
    except Exception:
        return None


# Cache dynamically resolved deployment IDs to minimize Zaby API overhead
resolved_deployment_cache = {
    'id': None,
    'timestamp': 0
}

async def get_active_deployment_id(client):
    """Retrieve the current active production deployment ID, and automatically bind it if not bound."""
    global resolved_deployment_cache
    import time
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), '.env'), override=True)
    except Exception:
        pass
    
    # Cache for 60 seconds
    now = time.time()
    if resolved_deployment_cache['id'] and (now - resolved_deployment_cache['timestamp'] < 60):
        return resolved_deployment_cache['id']
        
    agent_id = os.environ.get('ZABY_AGENT_ID', '19f78744-57e8-49ef-8dbd-edf1bdf60b59')
    if not agent_id:
        return os.environ.get('ZABY_DEPLOYMENT_ID', '')

    try:
        # 1. Fetch agent active deployments using core client requests
        path = f"/api/v1/provisioning/agentic-os/agents/{agent_id}"
        agent_data = await client.agents._core.request("GET", path)
        active_deps = agent_data.get('activeDeployments', [])
        
        active_dep_id = None
        for dep in active_deps:
            if dep.get('status') == 'ACTIVE' and dep.get('environment') == 'PRODUCTION':
                active_dep_id = dep.get('id')
                break
                
        if not active_dep_id:
            # Fallback to .env hardcoded ID if no active production deployment is found
            return os.environ.get('ZABY_DEPLOYMENT_ID', '')
            
        # 2. Check and auto-bind if not already bound
        app_id = ZABY_EXTERNAL_APP_ID
        if app_id:
            try:
                app_details = await client.external_apps.get(app_id)
                bindings = app_details.get('bindings', [])
                bound_ids = [b.get('deploymentId') for b in bindings if b]
                if active_dep_id not in bound_ids:
                    print(f"Auto-binding fresh active deployment {active_dep_id} to app {app_id}...")
                    await client.external_apps.bind_deployment(app_id, {
                        'deploymentId': active_dep_id,
                        'allowBrowserRuntime': True
                    })
                    print(f"Active deployment cached successfully: {active_dep_id}")
            except Exception as bind_err:
                print(f"Warning: Could not auto-bind deployment (will retry next request): {bind_err}")
                # Don't return early — still cache and use the deployment ID

        resolved_deployment_cache['id'] = active_dep_id
        resolved_deployment_cache['timestamp'] = now
        return active_dep_id
    except Exception as e:
        print("Failed to dynamically resolve and bind deployment:", e)
        return os.environ.get('ZABY_DEPLOYMENT_ID', '')


async def mint_token_workflow(client, username):
    policy_id = await get_or_create_default_policy(client)
    active_dep_id = await get_active_deployment_id(client)
    params = {
        "externalAppId": ZABY_EXTERNAL_APP_ID,
        "deploymentId": active_dep_id,
        "externalUserId": username
    }
    if policy_id:
        params["quotaPolicyId"] = policy_id
    return await client.runtime_tokens.create(params)


@app.route('/api/zaby/token', methods=['POST'])
def zaby_token():
    """Mint a disposable runtime token for the logged-in user."""
    if not session.get('logged_in'):
        return jsonify({'error': 'Not authenticated'}), 401

    client = get_zaby_client()
    if not client or not ZABY_EXTERNAL_APP_ID:
        return jsonify({'error': 'Zaby SDK not configured. Set ZABY_API_KEY and ZABY_EXTERNAL_APP_ID environment variables.'}), 503

    try:
        username = session.get('username', 'Guest')
        result = run_async(mint_token_workflow(client, username))
        if not result:
            return jsonify({'error': 'Zaby API returned an empty response when minting token. Check that the deployment is bound to the external app.'}), 502
        token = result.get('token', result.get('access_token', ''))
        if not token:
            return jsonify({'error': f'Token field missing in response: {result}'}), 502
        session['zaby_runtime_token'] = token
        return jsonify({'token': token})
    except ZabyApiError as e:
        return jsonify({'error': f'Zaby API error: {e}'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/zaby/run', methods=['POST'])
def zaby_run():
    """Start an agent run with the user's message."""
    if not session.get('logged_in'):
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json(silent=True) or {}
    message = data.get('message', '').strip()
    token = data.get('token', '') or session.get('zaby_runtime_token', '')

    if not message:
        return jsonify({'error': 'Message is required'}), 400
    if not token:
        return jsonify({'error': 'Runtime token is required'}), 400

    try:
        runtime = ZabyRuntime(token=token)
        result = run_async(runtime.runs.start({'input': message}))
        run_id = result.get('runId') or result.get('id') or result.get('run_id', '')
        return jsonify({'run_id': str(run_id)})
    except ZabyApiError as e:
        return jsonify({'error': f'Zaby API error: {e}'}), 502
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/zaby/stream/<run_id>')
def zaby_stream(run_id):
    """Proxy SSE stream from Zaby agent to the browser."""
    if not session.get('logged_in'):
        return jsonify({'error': 'Not authenticated'}), 401

    token = request.args.get('token', '') or session.get('zaby_runtime_token', '')

    def _normalize_sse_item(item):
        """Convert a raw Zaby SseEvent or dict into a simple payload the frontend expects.

        Zaby streams events like:
          {type: "TextMessageContent", delta: "Hello", ...}
          {type: "RunFinished", result: "full text", ...}
        The frontend expects:
          {text: "Hello"}              — for incremental text chunks
          {type: "done", result: ...}  — for completion
        """
        if isinstance(item, Exception):
            return {'error': str(item)}

        # Get the data dict from either a raw dict or an SseEvent object
        if isinstance(item, dict):
            data = item
        elif hasattr(item, 'data') and isinstance(item.data, dict):
            data = item.data
        elif hasattr(item, 'data'):
            # Non-dict SseEvent data (plain string)
            return {'text': str(item.data)}
        else:
            return {'text': str(item)}

        event_type = data.get('type', '')

        # Incremental text token from the agent
        if event_type == 'TextMessageContent':
            delta = data.get('delta', '')
            if delta:
                return {'text': delta}
            return None  # Empty delta, skip

        # Agent finished producing text for this message
        if event_type == 'TextMessageEnd':
            return None  # No visible payload needed

        # The entire run completed — carry the final result
        if event_type == 'RunFinished':
            return {'type': 'done', 'result': data.get('result', '')}

        # Step/turn lifecycle events — not visible to the user
        if event_type in ('StepStarted', 'StepFinished', 'TextMessageStart', 'StateSnapshot'):
            return None

        # Fallback: forward any other event that has recognizable text fields
        for key in ('text', 'content', 'message', 'delta'):
            if data.get(key):
                return {'text': data[key]}

        # Truly unknown event with no text — skip silently
        return None

    def generate():
        import queue
        import threading
        q = queue.Queue()

        def run_stream():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            async def collect_events():
                try:
                    runtime = ZabyRuntime(token=token) if token else None
                    if runtime:
                        async for event in runtime.runs.stream(run_id):
                            q.put(event)
                    else:
                        client = get_zaby_client()
                        if client:
                            result = await client.agents.list_run_events(run_id)
                            items = result if isinstance(result, list) else result.get('items', [result]) if isinstance(result, dict) else [result]
                            for item in items:
                                q.put(item)
                        else:
                            q.put(Exception('No runtime token or client configured'))
                except Exception as e:
                    q.put(e)
                finally:
                    q.put(None)

            loop.run_until_complete(collect_events())
            loop.close()

        thread = threading.Thread(target=run_stream)
        thread.start()

        while True:
            item = q.get()
            if item is None:
                break
            payload = _normalize_sse_item(item)
            if payload is not None:
                yield f"data: {json.dumps(payload)}\n\n"

        yield "event: done\ndata: {}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        }
    )


if __name__ == '__main__':
    # Warm up active deployment ID cache on startup (only in the child reloader process if debug is on)
    if os.environ.get('WERKZEUG_RUN_MAIN') or not app.debug:
        client = get_zaby_client()
        if client:
            print("Pre-fetching active deployment...")
            try:
                run_async(get_active_deployment_id(client))
                print("Active deployment cached successfully:", resolved_deployment_cache['id'])
            except Exception as e:
                print("Startup pre-fetch failed:", e)

    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True, use_reloader=False)