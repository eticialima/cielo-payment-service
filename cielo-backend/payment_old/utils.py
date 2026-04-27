import re
import unicodedata
import requests
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


# Remove Acentos da String
def remover_acentos(txt):
    return ''.join((c for c in unicodedata.normalize('NFD', txt) if unicodedata.category(c) != 'Mn'))
 

# Formata E-mail
def formatEmail(email):
    regex = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    match_obj = re.fullmatch(regex, (email).lower())
    email = match_obj.group() if match_obj else None
    return email 


# Gera link com token
def gerar_chave(chave_pk_flag):
    chave_bytes = force_bytes(str(chave_pk_flag))
    chave_base64 = urlsafe_base64_encode(chave_bytes)
    return str(chave_base64)
 

# API para gerar link de acesso
def gera_link_short(link_url, title): 
    data = {
        'signature': '4fe0c5e83e',  # Chave de autenticação da API
        'action': 'shorturl',        # Ação para encurtar a URL
        'url': link_url,             # URL a ser encurtada
        'title': title,              # Título opcional para a URL curta
        'format': 'json'             # Formato de resposta esperado
    }
    
    # URL da API
    api_url = 'https://d-m-c.group/yourls-api.php'
    
    # Faça uma requisição POST à API
    response = requests.post(api_url, data=data)
    
    # Verifique se a requisição foi bem-sucedida
    if response.status_code == 200:
        res = response.json()
        return res.get('shorturl', None)
    return None  


