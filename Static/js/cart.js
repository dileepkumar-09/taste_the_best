function addToCart(name, id) {
    const select = document.getElementById(`weight-${id}`);
    const price = select.value;
    // Captures just the numeric weight value for the database
    const weight = select.options[select.selectedIndex].text.split('g')[0];

    let cart = JSON.parse(localStorage.getItem('cart') || '[]');
    cart.push({ 
        name: name, 
        price: price, 
        weight: weight 
    });
    
    localStorage.setItem('cart', JSON.stringify(cart));
    
    alert(name + " added to cart!");
    updateCartCount();
}

function updateCartCount() {
    const cart = JSON.parse(localStorage.getItem('cart') || '[]');
    const countElements = document.querySelectorAll('.cart-count');
    countElements.forEach(el => {
        el.textContent = cart.length;
    });
}

// Ensure the count is correct when the page loads
document.addEventListener('DOMContentLoaded', updateCartCount);