# app.py - API Python no Render (Completo)

from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import firestore
import json
import os
import base64
from xml.etree import ElementTree as ET # Biblioteca nativa para parsing XML

# --- CONFIGURAÇÃO E INICIALIZAÇÃO DO FLASK ---
app = Flask(__name__)

# --- CONFIGURAÇÃO E INICIALIZAÇÃO SEGURA DO FIREBASE ADMIN SDK ---

def initialize_firebase():
    """Inicializa o Firebase Admin SDK usando a chave Base64 do Render."""
    key_b64 = os.environ.get('FIREBASE_ADMIN_KEY_BASE64')
    
    if not key_b64:
        print("ERRO: Variável FIREBASE_ADMIN_KEY_BASE64 não encontrada.")
        # Retornar None fará com que a API retorne erro 500 no endpoint,
        # alertando sobre a falha na conexão.
        return None

    try:
        # Decodifica a string Base64 de volta para JSON
        key_json_str = base64.b64decode(key_b64).decode('utf-8')
        cred_data = json.loads(key_json_str)
        
        # Inicializa o Firebase
        cred = firebase_admin.credentials.Certificate(cred_data)
        firebase_admin.initialize_app(cred)
        
        print("INFO: Firebase Admin SDK inicializado com sucesso.")
        return firestore.client()

    except Exception as e:
        print(f"FALHA CRÍTICA na inicialização do Firebase: {e}")
        return None

# Inicializa o Firestore Client globalmente
db = initialize_firebase()
# -----------------------------------------------------------------

# --- CONSTANTE DE NAMESPACE XML ---
# O namespace padrão da NF-e, crucial para buscas XPath
NAMESPACE = {'nfe': 'http://www.portalfiscal.inf.br/nfe'} 

# Função auxiliar para extrair texto de um elemento XML com namespace
def get_xml_text_ns(element, xpath, default=''):
    """Tenta encontrar um elemento usando namespace e retorna seu texto ou valor padrão."""
    # O XPath deve ser formatado como './nfe:tag'
    found = element.find(xpath, NAMESPACE)
    return found.text.strip() if found is not None and found.text else default

# --- ENDPOINT DA API ---

@app.route('/api/uploadXML', methods=['POST'])
def upload_xml():
    start_time = os.times()[4] 
    notaId = 'N/A'
    produtos_nao_encontrados = []
    
    if db is None:
        # Retorna erro se a conexão com o Firebase falhou na inicialização
        return jsonify({"sucesso": False, "mensagem": "Falha na conexão com o banco de dados."}), 500

    if not request.data:
        return jsonify({"sucesso": False, "mensagem": "Conteúdo XML ausente."}), 400
    
    xml_content = request.data.decode('utf-8')
    
    try:
        # --- 1. Parsing do XML e Extração de Dados ---
        
        root = ET.fromstring(xml_content)
        
        # Busca a tag infNFe usando o namespace
        infNFe = root.find('.//nfe:infNFe', NAMESPACE) 
        
        if infNFe is None:
             raise ValueError("Estrutura inválida: 'infNFe' não encontrado. Verifique o namespace.")

        # Extraindo dados da Nota
        # XPATH formatado com namespace: './nfe:tag_pai/nfe:tag_filha'
        notaId = get_xml_text_ns(infNFe, './nfe:ide/nfe:nNF')
        if not notaId:
            raise ValueError("Tag <nNF> (Número da Nota Fiscal) não encontrada.")
            
        supplierName = get_xml_text_ns(infNFe, './nfe:emit/nfe:xNome') or 'Fornecedor não identificado'
        
        products = []
        
        # Encontra todos os itens detalhados (det)
        for det_element in infNFe.findall('./nfe:det', NAMESPACE):
            prod_element = det_element.find('./nfe:prod', NAMESPACE)
            if prod_element is not None:
                ean = get_xml_text_ns(prod_element, './nfe:cEAN')
                
                products.append({
                    'productName': get_xml_text_ns(prod_element, './nfe:xProd') or 'Produto sem nome',
                    # Converte para float, tratando possíveis erros de conversão
                    'quantity': float(get_xml_text_ns(prod_element, './nfe:qCom') or 0), 
                    'ean': ean if ean else 'Sem EAN',
                })

        # --- 2. Validação de EANs no cadastro principal e coleta de alertas ---
        for product in products:
            ean_string = product['ean']
            
            if ean_string and ean_string != 'Sem EAN':
                # Consulta ao Firebase Admin SDK (Admin SDK usa .stream() para buscar)
                products_ref = db.collection('produtos')
                q = products_ref.where('eans', 'array_contains', ean_string).limit(1)
                
                # Se a lista estiver vazia, o produto não foi encontrado
                if not list(q.stream()): 
                    produtos_nao_encontrados.append({
                        'nome': product['productName'],
                        'ean': ean_string,
                        'numeroNota': notaId,
                        'fileName': 'API_UPLOAD', 
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
            'createdAt': firestore.SERVER_TIMESTAMP,
            'products': products, 
            'status': 'pendente',
        })
        
        # Salva cada alerta na coleção alertasCadastro
        for p in produtos_nao_encontrados:
            db.collection('alertasCadastro').add({
                'ean': p['ean'],
                'nomeProduto': p['nome'],
                'numeroNota': p['numeroNota'],
                'fileName': p['fileName'],
                'dataAlerta': firestore.SERVER_TIMESTAMP,
                'mensagem': 'Produto dFa nota fiscal não encontrado no cadastro de produtos principal (ou EAN inválido/desconhecido).'
            })

        # --- 4. Resposta de Sucesso ---
        duration_ms = (os.times()[4] - start_time) * 1000
        
        return jsonify({
            "sucesso": True,
            "mensagem": f"NF {notaId} importada com sucesso.",
            "numeroNota": notaId,
            "produtosComAlerta": [p['nome'] for p in produtos_nao_encontrados], # Retorna apenas nomes no JSON
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