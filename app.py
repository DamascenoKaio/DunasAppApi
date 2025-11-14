# app.py - API Python no Render

from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import firestore
import json
import os
import base64
from xml.etree import ElementTree as ET # Biblioteca nativa para parsing XML

app = Flask(__name__)

# --- CONFIGURAÇÃO INICIAL (MANTIDA) ---
# Inicializa o Admin SDK com a chave Base64 (conforme passos anteriores)
def initialize_firebase():
    """Inicializa o Firebase Admin SDK usando a chave Base64 do Render."""
    key_b64 = os.environ.get('FIREBASE_ADMIN_KEY_BASE64')
    if not key_b64:
        print("ERRO: Variável FIREBASE_ADMIN_KEY_BASE64 não encontrada.")
        return None
    try:
        key_json_str = base64.b64decode(key_b64).decode('utf-8')
        cred_data = json.loads(key_json_str)
        cred = firebase_admin.credentials.Certificate(cred_data)
        firebase_admin.initialize_app(cred)
        print("INFO: Firebase Admin SDK inicializado com sucesso.")
        return firestore.client()
    except Exception as e:
        print(f"FALHA CRÍTICA na inicialização do Firebase: {e}")
        return None

db = initialize_firebase()
# ----------------------------------------


# Função auxiliar para extrair texto de um elemento XML (para simplificar)
def get_xml_text(element, xpath, default=''):
    """Tenta encontrar um elemento e retorna seu texto ou um valor padrão."""
    found = element.find(xpath)
    return found.text if found is not None and found.text else default

@app.route('/api/uploadXML', methods=['POST'])
def upload_xml():
    start_time = os.times()[4] 
    notaId = 'N/A'
    produtos_nao_encontrados = []
    
    if db is None:
        return jsonify({"sucesso": False, "mensagem": "Falha na conexão com o banco de dados. Verifique os logs."}), 500

    if not request.data:
        return jsonify({"sucesso": False, "mensagem": "Conteúdo XML ausente."}), 400
    
    # Decodifica o corpo da requisição POST (que deve ser o XML)
    xml_content = request.data.decode('utf-8')
    
    try:
        # --- 1. Parsing do XML e Extração de Dados ---
        
        # Use o ElementTree para parsear o XML.
        # Ele lida com namespaces de forma diferente, então ajustamos o XPath.
        root = ET.fromstring(xml_content)
        
        # O nó principal da NF-e (Ajuste o namespace se necessário. Ex: {http://www.portalfiscal.inf.br/nfe}infNFe)
        # Para simplificar, vamos usar a busca universal (que é mais lenta, mas funciona se o namespace for um problema)
        infNFe = root.find('.//infNFe') 
        
        if infNFe is None:
             raise ValueError("Estrutura inválida: 'infNFe' não encontrado.")

        # Extraindo dados da Nota
        notaId = get_xml_text(infNFe, './/ide/nNF')
        if not notaId:
            raise ValueError("Tag <nNF> (Número da Nota Fiscal) não encontrada.")
            
        supplierName = get_xml_text(infNFe, './/emit/xNome') or 'Fornecedor não identificado'
        
        products = []
        # Encontra todos os itens detalhados (det)
        for det_element in infNFe.findall('.//det'):
            prod_element = det_element.find('.//prod')
            if prod_element is not None:
                ean = get_xml_text(prod_element, './/cEAN')
                
                products.append({
                    'productName': get_xml_text(prod_element, './/xProd') or 'Produto sem nome',
                    'quantity': float(get_xml_text(prod_element, './/qCom') or 0),
                    'ean': ean.strip() if ean else 'Sem EAN',
                })

        # --- 2. Validação de EANs no cadastro principal e coleta de alertas ---
        for product in products:
            ean_string = product['ean']
            
            if ean_string and ean_string != 'Sem EAN':
                # ✅ Lógica da API (Consulta ao Firebase Admin SDK)
                products_ref = db.collection('produtos')
                
                # A função array_contains é o que você precisa:
                q = products_ref.where('eans', 'array_contains', ean_string).limit(1)
                
                # O .stream() é a forma Python/Admin SDK de obter os resultados
                product_snap = list(q.stream()) 

                if not product_snap:
                    # EAN não encontrado no cadastro de produtos: adiciona ao alerta
                    produtos_nao_encontrados.append({
                        'nome': product['productName'],
                        'ean': ean_string,
                        'numeroNota': notaId,
                        'fileName': 'API_UPLOAD', # Não temos o nome do arquivo, usamos um marcador
                    })
            else:
                # Produto sem EAN válido: adiciona ao alerta
                produtos_nao_encontrados.append({
                    'nome': product['productName'],
                    'ean': ean_string,
                    'numeroNota': notaId,
                    'fileName': 'API_UPLOAD',
                })
        
        # --- 3. Salvar Nota Fiscal e Alertas no Firestore ---
        
        # Salva a nota fiscal INCONDICIONALMENTE
        db.collection('notasFiscais').add({
            'numeroNota': notaId,
            'fileName': 'API_UPLOAD',
            'supplier': supplierName,
            'motorista': "Não informado (via API)",
            # serverTimestamp() no Python
            'createdAt': firestore.SERVER_TIMESTAMP,
            'products': products, 
            'status': 'pendente_via_api',
        })
        
        # Salva cada alerta na coleção alertasCadastro
        for p in produtos_nao_encontrados:
            db.collection('alertasCadastro').add({
                'ean': p['ean'],
                'nomeProduto': p['nome'],
                'numeroNota': p['numeroNota'],
                'fileName': p['fileName'],
                'dataAlerta': firestore.SERVER_TIMESTAMP,
                'mensagem': 'Produto da nota fiscal não encontrado no cadastro de produtos principal (ou EAN inválido/desconhecido).'
            })

        # --- 4. Resposta de Sucesso ---
        duration_ms = (os.times()[4] - start_time) * 1000
        
        return jsonify({
            "sucesso": True,
            "mensagem": f"NF {notaId} importada com sucesso.",
            "numeroNota": notaId,
            "produtosComAlerta": produtos_nao_encontrados,
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

if __name__ == '__main__':
    # Usado apenas para testes locais
    app.run(debug=True)