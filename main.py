import firebase_admin
from firebase_admin import credentials, firestore, auth
from flask import Flask, request, jsonify, render_template, make_response
from flask_cors import CORS
import os

# Inicializa la aplicación Flask
app = Flask(__name__)
CORS(app)  # Habilita CORS para toda la aplicación

# Configuración de Firebase
try:
    if os.path.exists("firebase-credentials.json"):
        cred = credentials.Certificate("firebase-credentials.json")
    else:
        # En entornos sin servidor, usa variables de entorno
        cred = credentials.Certificate({
            "type": os.environ.get("FIREBASE_TYPE"),
            "project_id": os.environ.get("FIREBASE_PROJECT_ID"),
            "private_key_id": os.environ.get("FIREBASE_PRIVATE_KEY_ID"),
            "private_key": os.environ.get("FIREBASE_PRIVATE_KEY").replace('\\n', '\n'),
            "client_email": os.environ.get("FIREBASE_CLIENT_EMAIL"),
            "client_id": os.environ.get("FIREBASE_CLIENT_ID"),
            "auth_uri": os.environ.get("FIREBASE_AUTH_URI"),
            "token_uri": os.environ.get("FIREBASE_TOKEN_URI"),
            "auth_provider_x509_cert_url": os.environ.get("FIREBASE_AUTH_PROVIDER_X509_CERT_URL"),
            "client_x509_cert_url": os.environ.get("FIREBASE_CLIENT_X509_CERT_URL")
        })
    firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception as e:
    print(f"Error initializing Firebase: {e}")
    db = None

# Middleware para verificar el token de Firebase
def check_auth(request):
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None, make_response(jsonify({"error": "No se proporcionó token de autorización"}), 401)
    
    try:
        id_token = auth_header.split(" ").pop()
        decoded_token = auth.verify_id_token(id_token)
        return decoded_token, None
    except Exception as e:
        return None, make_response(jsonify({"error": "Token inválido o expirado", "details": str(e)}), 401)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/get_all_products")
def get_all_products():
    decoded_token, error_response = check_auth(request)
    if error_response:
        return error_response
    
    try:
        all_products = []
        products_ref = db.collection('products')
        for doc in products_ref.stream():
            product_data = doc.to_dict()
            product_data['id'] = doc.id
            all_products.append(product_data)
        return jsonify(all_products)
    except Exception as e:
        return make_response(jsonify({"error": f"Error al obtener productos: {str(e)}"}), 500)

@app.route("/api/get_offers")
def get_offers():
    decoded_token, error_response = check_auth(request)
    if error_response:
        return error_response
        
    try:
        offer_products = []
        products_ref = db.collection('products').where('isOffer', '==', True)
        for doc in products_ref.stream():
            product_data = doc.to_dict()
            product_data['id'] = doc.id
            offer_products.append(product_data)
        return jsonify(offer_products)
    except Exception as e:
        return make_response(jsonify({"error": f"Error al obtener ofertas: {str(e)}"}), 500)

@app.route("/api/offer_suggestions")
def offer_suggestions():
    decoded_token, error_response = check_auth(request)
    if error_response:
        return error_response

    try:
        # Esta es una lógica de sugerencia simple: productos que nunca se han vendido.
        # Una lógica más avanzada podría usar IA o análisis más profundos.
        all_products_docs = db.collection('products').stream()
        all_product_ids = {doc.id for doc in all_products_docs}

        sold_product_ids = set()
        orders_docs = db.collection('orders').stream()
        for order in orders_docs:
            for item in order.to_dict().get('items', []):
                sold_product_ids.add(item['productId'])

        unsold_product_ids = all_product_ids - sold_product_ids
        
        suggestions = []
        if unsold_product_ids:
            # Limita el número de sugerencias para no abrumar
            for product_id in list(unsold_product_ids)[:5]: 
                product_doc = db.collection('products').document(product_id).get()
                if product_doc.exists:
                    product_data = product_doc.to_dict()
                    # Asegurarse de que no sea ya una oferta
                    if not product_data.get('isOffer', False):
                        product_data['id'] = product_doc.id
                        suggestions.append(product_data)

        return jsonify(suggestions)
    except Exception as e:
        return make_response(jsonify({"error": f"Error al generar sugerencias: {str(e)}"}), 500)

@app.route("/api/create_offers", methods=['POST'])
def create_offers():
    decoded_token, error_response = check_auth(request)
    if error_response:
        return error_response

    data = request.get_json()
    product_ids = data.get('productIds')
    discount = data.get('discountPercentage')

    if not product_ids or not isinstance(product_ids, list) or not discount:
        return make_response(jsonify({"error": "Datos inválidos"}), 400)

    try:
        batch = db.batch()
        for product_id in product_ids:
            product_ref = db.collection('products').document(product_id)
            product_doc = product_ref.get()
            if product_doc.exists:
                original_price = product_doc.to_dict().get('price', 0)
                offer_price = original_price * (1 - discount / 100)
                
                batch.update(product_ref, {
                    'isOffer': True,
                    'offerPrice': offer_price,
                    'discountPercentage': discount
                })
        batch.commit()
        return jsonify({"success": True, "message": "Ofertas creadas correctamente"})
    except Exception as e:
        return make_response(jsonify({"error": f"Error al crear ofertas: {str(e)}"}), 500)


@app.route("/api/remove_offer", methods=['POST'])
def remove_offer():
    decoded_token, error_response = check_auth(request)
    if error_response:
        return error_response

    data = request.get_json()
    product_id = data.get('productId')

    if not product_id:
        return make_response(jsonify({"error": "ID de producto no proporcionado"}), 400)

    try:
        product_ref = db.collection('products').document(product_id)
        # Usamos FieldValue para eliminar campos específicos
        product_ref.update({
            'isOffer': firestore.DELETE_FIELD,
            'offerPrice': firestore.DELETE_FIELD,
            'discountPercentage': firestore.DELETE_FIELD
        })
        return jsonify({"success": True, "message": "Oferta eliminada."})
    except Exception as e:
        return make_response(jsonify({"error": f"Error al eliminar la oferta: {str(e)}"}), 500)

# Sirve los archivos estáticos para las rutas del frontend
@app.route("/<path:path>")
def serve_static(path):
    return render_template(path)

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
