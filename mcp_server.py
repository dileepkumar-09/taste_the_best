import sys
import os
import re
import uuid
import json
from datetime import datetime

# Prevent socket reuse crashes in multi-threaded Windows environments
if sys.platform == 'win32':
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Add directory of this script to sys.path to allow importing app.py
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    from app import products, users_table, orders_table
except ImportError as e:
    print(f"Error importing from app.py: {e}", file=sys.stderr)
    sys.exit(1)

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pymongo.errors import PyMongoError

# Initialize FastMCP Server
mcp = FastMCP(
    "Taste the Best Storefront",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)
)

def find_product_by_id_or_name(query: str):
    """Normalize and find product by integer ID or string name comparison."""
    # Try integer match first
    try:
        pid = int(query)
        for category, item_list in products.items():
            for item in item_list:
                if item['id'] == pid:
                    return item
    except ValueError:
        pass

    # Normalize string input (remove spaces, punctuation, lowercase)
    norm_input = re.sub(r'[^a-zA-Z0-9]', '', query).lower()

    # Check for exact normalized match
    for category, item_list in products.items():
        for item in item_list:
            norm_name = re.sub(r'[^a-zA-Z0-9]', '', item['name']).lower()
            if norm_name == norm_input:
                return item

    # Fallback to keyword matching
    keywords = re.findall(r'[A-Z]?[a-z]+|[0-9]+', query)
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
        return best_match
    return None


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False, "idempotentHint": True})
def list_products(category: str = None):
    """
    List products in the storefront catalog.
    
    Args:
        category (str, optional): Category to filter by. Can be 'veg_pickles', 'non_veg_pickles', or 'snacks'. If None, returns all products.
    """
    if category:
        if category not in products:
            return f"Invalid category '{category}'. Valid options are: {', '.join(products.keys())}"
        items = products[category]
        result = f"Category: {category}\n" + "-" * 50 + "\n"
        for item in items:
            result += f"- {item['name']} (ID: {item['id']}) - Weights: {', '.join([f'{w}g: Rs.{p}' for w, p in item['weights'].items()])}\n"
        return result
    
    result = "Taste the Best Storefront Catalog:\n"
    for cat, items in products.items():
        result += f"\nCategory: {cat}\n" + "-" * 50 + "\n"
        for item in items:
            result += f"- {item['name']} (ID: {item['id']}) - Weights: {', '.join([f'{w}g: Rs.{p}' for w, p in item['weights'].items()])}\n"
    return result


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False, "idempotentHint": True})
def get_product_details(product_id_or_name: str):
    """
    Get detailed information about a product, including energy index/nutrition, pricing, and pairing suggestions.
    
    Args:
        product_id_or_name (str): The ID (e.g. '7') or the name (e.g. 'Mango Pickle') of the product.
    """
    item = find_product_by_id_or_name(product_id_or_name)
    if not item:
        return f"Product '{product_id_or_name}' not found in the catalog."
    
    energy = item.get('energy_index', {})
    name_lower = item['name'].lower()
    is_sweet = any(kw in name_lower for kw in ['laddu', 'papad', 'acchu', 'gavvalu', 'chikki'])
    
    details = [
        f"Product Name: {item['name']}",
        f"Product ID: {item['id']}",
        f"Pricing by Weight: {', '.join([f'{w}g: Rs.{p}' for w, p in item['weights'].items()])}",
        f"Spice Level: {'Sweet' if is_sweet else 'Medium'}",
        f"Sweetness: {'Medium' if is_sweet else 'N/A'}",
        f"Pairing Recommendation: {'Sweets/Dessert' if is_sweet else 'Rice/Rotis/Snacks'}",
        "\nNutritional Info (per 100g):",
        f"- Calories: {energy.get('calories', 'N/A')}",
        f"- Protein: {energy.get('protein', 'N/A')}",
        f"- Carbs: {energy.get('carbs', 'N/A')}",
        f"- Fat: {energy.get('fat', 'N/A')}"
    ]
    return "\n".join(details)


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False, "idempotentHint": True})
def list_orders(username: str = None, limit: int = 10):
    """
    Retrieve customer orders from the MongoDB database, ordered by latest first.
    
    Args:
        username (str, optional): Filter orders by customer username.
        limit (int, optional): The maximum number of orders to return (default 10).
    """
    query = {}
    if username:
        query['username'] = username
    
    try:
        cursor = orders_table.find(query).sort('timestamp', -1).limit(limit)
        orders = list(cursor)
        if not orders:
            return f"No orders found{' for user ' + username if username else ''}."
        
        result = f"Showing last {len(orders)} orders:\n"
        for o in orders:
            items_summary = ", ".join([f"{item.get('name')} (Weight: {item.get('weight')}g) x{item.get('quantity', 1)}" for item in o.get('items', [])])
            result += f"- Order ID: {o.get('Order_id')} | User: {o.get('username')} | Total: Rs.{o.get('total_amount')} | Date: {o.get('timestamp')} | Items: [{items_summary}]\n"
        return result
    except PyMongoError as e:
        return f"Database error occurred: {str(e)}"


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False, "idempotentHint": True})
def get_order_details(order_id: str):
    """
    Get detailed customer profile, order items, and shipping address details for a single order by its UUID.
    
    Args:
        order_id (str): The unique Order ID UUID.
    """
    try:
        order = orders_table.find_one({'Order_id': order_id})
        if not order:
            return f"Order with ID '{order_id}' not found."
        
        # Format the order details nicely
        lines = [
            f"Order ID: {order.get('Order_id')}",
            f"Username: {order.get('username')}",
            f"Delivery Contact Name: {order.get('name')}",
            f"Delivery Phone: {order.get('phone')}",
            f"Delivery Address: {order.get('address')}",
            f"Total Amount: Rs.{order.get('total_amount')}",
            f"Timestamp: {order.get('timestamp')}",
            "\nItems Ordered:"
        ]
        for item in order.get('items', []):
            lines.append(f"- {item.get('name')} (Weight: {item.get('weight')}g) x{item.get('quantity', 1)} - Rs.{item.get('price')}")
        
        return "\n".join(lines)
    except PyMongoError as e:
        return f"Database error occurred: {str(e)}"


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False, "idempotentHint": True})
def get_user_profile(username: str):
    """
    Retrieve default contact details and delivery profile for a customer.
    
    Args:
        username (str): The customer's username.
    """
    try:
        user = users_table.find_one({'Username': username})
        if not user:
            return f"User '{username}' not found in database."
        
        profile = [
            f"Username: {user.get('Username')}",
            f"Email: {user.get('email')}",
            f"Profile Name: {user.get('profile_name', 'N/A')}",
            f"Contact Phone: {user.get('phone', 'N/A')}",
            f"Delivery Address: {user.get('address', 'N/A')}"
        ]
        return "\n".join(profile)
    except PyMongoError as e:
        return f"Database error occurred: {str(e)}"


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False, "idempotentHint": False})
def create_order(username: str, name: str, address: str, phone: str, items_json: str, total_amount: float):
    """
    Place a new order in the storefront database and update the user's default shipping profile.
    
    Args:
        username (str): The username of the customer placing the order.
        name (str): Full name for delivery contact.
        address (str): Full delivery destination address.
        phone (str): Contact phone number.
        items_json (str): A JSON array string representing the items, e.g. '[{"name": "Chicken Pickle", "weight": "250", "quantity": 1, "price": 600}]'.
        total_amount (float): The total cost of the order.
    """
    try:
        try:
            items = json.loads(items_json)
        except json.JSONDecodeError:
            return "Error: 'items_json' must be a valid JSON array string."
        
        if not isinstance(items, list):
            return "Error: 'items_json' must deserialize to a list of item dictionaries."

        order_id = str(uuid.uuid4())
        order_doc = {
            'Order_id': order_id,
            'username': username,
            'name': name,
            'address': address,
            'phone': phone,
            'items': items,
            'total_amount': total_amount,
            'timestamp': datetime.now().isoformat()
        }
        
        orders_table.insert_one(order_doc)
        
        # Save profile details on user record for future autofills
        users_table.update_one(
            {'Username': username},
            {'$set': {
                'profile_name': name,
                'phone': phone,
                'address': address
            }}
        )
        
        return f"Success! Order placed successfully with ID: {order_id}"
    except PyMongoError as e:
        return f"Database error occurred while creating order: {str(e)}"


if __name__ == "__main__":
    # Start FastMCP server via stdio transport
    mcp.run()
