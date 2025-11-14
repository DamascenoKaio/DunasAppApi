# app.py

from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import firestore
import json
import os
import base64
from lxml import etree # Importando a biblioteca robusta de XML

app = Flask(__name__)

# --- INICIALIZAÇÃO SEGURA DO FIREBASE ADMIN SDK ---
# Esta função usa a chave codificada em Base64 da variável de ambiente.
def initialize_firebase():
    """Tenta inicializar o Firebase Admin SDK usando a chave Base64 do Render."""
    
    key_b64 = os.environ.get('FIREBASE_ADMIN_KEY_BASE64')
    
    if not key_b64:
        # Se a variável de ambiente estiver faltando, falha o startup
        print("ERRO: Variável FIREBASE_ADMIN_KEY_BASE64 não encontrada.")
        return None

    try:
        # 1. Decodifica a string Base64 de volta para uma string JSON
        key_json_str = base64.b64decode(key_b64).decode('utf-8')
        
        # 2. Carrega o JSON para um dicionário Python
        cred_data = json.loads(key_json_str)
        
        # 3. Inicializa o Firebase
        cred = firebase_admin.credentials.Certificate(cred_data)
        firebase_app = firebase_admin.initialize_app(cred)
        
        print("INFO: Firebase Admin SDK inicializado com sucesso.")
        return firestore.client()

    except Exception as e:
        print(f"FALHA CRÍTICA na inicialização do Firebase: {e}")
        return None

db = initialize_firebase()
# -----------------------------------------------------------------


@app.route('/api/uploadXML', methods=['POST'])
def upload_xml():
    start_time = os.times()[4] # Tempo de início (para Python)
    notaId = 'N/A'
    produtos_nao_encontrados = []
    
    if db is None:
        return jsonify({"sucesso": False, "mensagem": "Falha na conexão com o banco de dados."}), 500

    if not request.data:
        print("ERRO: Conteúdo XML ausente.")
        return jsonify({"sucesso": False, "mensagem": "Conteúdo XML não fornecido."}), 400
    
    xml_content = request.data
    
    try:
        # --- 1. Parsear XML (Usando lxml) ---
        # A lógica de extração do XML é complexa e deve ser adaptada
        # para a estrutura exata da NF-e com lxml ou xml.etree.
        # Placeholder da lógica:
        root = etree.fromstring(xml_content)
        
        # Exemplo de como você extrairia o número da NF-e (isso varia!)
        # notaId = root.xpath('//ide/nNF')[0].text 
        # Supondo que você extraiu com sucesso:
        notaId = "123456789" 
        
        # --- 2. Validação de EANs (Lógica de consulta ao Firestore) ---
        # Exemplo de consulta:
        # product_snap = db.collection('produtos').where('eans', 'array_contains', 'EAN_DO_PRODUTO').get()
        
        # --- 3. Salvar Nota Fiscal e Alertas no Firestore ---
        
        # Salvando a Nota Fiscal
        db.collection('notasFiscais').add({
            'numeroNota': notaId,
            'supplier': 'Nome do Fornecedor',
            'createdAt': firestore.SERVER_TIMESTAMP,
            'status': 'importado_render',
            'products': [{'nome': 'exemplo', 'ean': 'exemplo_ean'}]
        })
        
        # Salvando Alertas (se houver)
        if produtos_nao_encontrados:
            # db.collection('alertasCadastro').add({...})
            pass

        # --- 4. Resposta de Sucesso ---
        duration_ms = (os.times()[4] - start_time) * 1000
        print(f"SUCESSO NF {notaId}: Importação concluída em {duration_ms:.2f}ms.")
        
        return jsonify({
            "sucesso": True,
            "mensagem": f"NF {notaId} importada com sucesso.",
            "numeroNota": notaId,
            "tempo_processamento_ms": f"{duration_ms:.2f}"
        }), 200

    except Exception as e:
        duration_ms = (os.times()[4] - start_time) * 1000
        print(f"ERRO CRÍTICO NF {notaId}: {e}")
        return jsonify({
            "sucesso": False,
            "mensagem": f"Erro ao processar NF {notaId}.",
            "erro": str(e),
            "tempo_processamento_ms": f"{duration_ms:.2f}"
        }), 500

# Se o Render iniciar o servidor, ele usará o Gunicorn.
if __name__ == '__main__':
    # Usado apenas para testes locais
    app.run(debug=True)