import requests
import json
from django.core.management.base import BaseCommand

# --- Configurações da API ---
BASE_URL = 'https://api.cielo.com.br/order-management/v1'

CLIENT_ID = '3e142fd18853406c932e9d994f8125a0'
ACCESS_TOKEN = '43C2A945FF1c4c9699aAc32e16BE6077'
MERCHANT_ID = '44bbd6bb-96f8-4dea-999c-468c54433524'

HEADERS = {
    'accept': 'application/json',
    'client-id': CLIENT_ID,
    'access-token': ACCESS_TOKEN,
    'merchant-id': MERCHANT_ID
}


class Command(BaseCommand):
    help = 'Verifica o status dos pedidos da Cielo LIO'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reference',
            type=str,
            help='Buscar apenas uma referência específica'
        )
        parser.add_argument(
            '--pedido',
            type=int,
            help='Buscar pelo ID do pedido no sistema'
        )

    def handle(self, *args, **options):
        reference = options.get('reference')  
        if reference:
            print("Buscando por referência específica...", reference)
            self.buscar_por_referencia(reference) 

    def make_request(self, endpoint):
        """Faz requisição GET para a API da Cielo."""
        url = f"{BASE_URL}/{endpoint}"
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as err:
            self.stdout.write(self.style.ERROR(f"❌ Erro: {err}"))
            return None  

    def buscar_por_referencia(self, reference):
        """Busca um pedido específico pela referência."""
        self.stdout.write(self.style.SUCCESS(f'🔍 Buscando referência: {reference}\n'))
        
        # Usa o parâmetro reference direto na query
        orders_list = self.make_request(f'orders/?reference={reference}')
         
        if not orders_list or not isinstance(orders_list, list) or len(orders_list) == 0:
            self.stdout.write(self.style.WARNING('❌ Nenhum pedido encontrado com essa referência'))
            return

        # Pega o primeiro pedido (normalmente só tem um)
        details = orders_list[0]
        
        # Encontrou! Mostra detalhes completos
        self.stdout.write(self.style.SUCCESS('✅ PEDIDO ENCONTRADO!\n'))
        
        self.stdout.write('📋 DADOS DO PEDIDO:')
        self.stdout.write(f"   Cielo ID: {details.get('id', 'N/A')}")
        self.stdout.write(f"   Reference: {details.get('reference', 'N/A')}")
        self.stdout.write(f"   Status: {details.get('status', 'N/A')}")
        self.stdout.write(f"   Valor: R$ {details.get('price', 0) / 100:.2f}")
        self.stdout.write(f"   Criado em: {details.get('created_at', 'N/A')}")
        
        # Transações
        transactions = details.get('transactions', [])
        if transactions:
            self.stdout.write('\n💳 TRANSAÇÕES:')
            for i, trans in enumerate(transactions, 1):
                self.stdout.write(f"\n   Transação {i}:")
                self.stdout.write(f"      Status: {trans.get('status', 'N/A')}")
                self.stdout.write(f"      Auth Code: {trans.get('authorization_code', 'N/A')}")
                self.stdout.write(f"      Tipo: {trans.get('transaction_type', 'N/A')}")
        
        # JSON completo
        self.stdout.write('\n📄 JSON COMPLETO:')
        self.stdout.write(json.dumps(details, indent=2, ensure_ascii=False)) 