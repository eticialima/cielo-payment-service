from django.core.management.base import BaseCommand
from django.conf import settings
from Pedidos.models import Pedido, Payment
from payment.models import CheckoutLink, PaymentTransaction, PaymentCieloLio, PaymentWebhook
from django.db.models import Q
from django.utils import timezone
from datetime import datetime, timedelta
import pytz
import requests
import json
import base64


class Command(BaseCommand):
    help = 'Busca pagamento por PaymentID, MerchantOrderID, TID, Auth Code ou Pedido ID'

    def add_arguments(self, parser):
        parser.add_argument('--payment-id', type=str, help='Payment ID da Cielo')
        parser.add_argument('--merchant-order', type=str, help='MerchantOrderID')
        parser.add_argument('--tid', type=str, help='Transaction ID (TID)')
        parser.add_argument('--auth', type=str, help='Código de autorização')
        parser.add_argument('--pedido-id', type=str, help='ID do Pedido')
        parser.add_argument('--consultar-api', action='store_true', help='Consulta API Cielo')

    def handle(self, *args, **options):
        payment_id = options.get('payment_id')
        merchant_order = options.get('merchant_order')
        tid = options.get('tid')
        auth_code = options.get('auth')
        pedido_id = options.get('pedido_id')
        consultar_api = options.get('consultar_api', False)

        self.stdout.write(self.style.SUCCESS('\n' + '='*70))
        self.stdout.write(self.style.SUCCESS('🔍 BUSCA DE PAGAMENTO'))
        self.stdout.write(self.style.SUCCESS('='*70 + '\n'))

        # Exibe critérios
        if payment_id:
            self.stdout.write(f'💳 Payment ID: {payment_id}')
        if merchant_order:
            self.stdout.write(f'🔢 Merchant Order: {merchant_order}')
        if tid:
            self.stdout.write(f'🆔 TID: {tid}')
        if auth_code:
            self.stdout.write(f'🔐 Auth Code: {auth_code}')
        if pedido_id:
            self.stdout.write(f'📦 Pedido ID: {pedido_id}')
        self.stdout.write('')

        encontrou_algo = False

        # ===== 1. PAYMENT TRANSACTION =====
        self.stdout.write(self.style.SUCCESS('1️⃣  PAYMENT TRANSACTION (payment_response):\n'))
        
        query_trans = Q()
        
        # Se buscar por pedido_id, filtra APENAS transações daquele pedido
        if pedido_id:
            query_trans &= Q(checkout_link__pedido__id=pedido_id)
        
        # Adiciona outros filtros
        if payment_id:
            query_trans |= Q(payment_response__icontains=payment_id)
        if merchant_order:
            query_trans |= Q(merchant_order_id__icontains=merchant_order)
            query_trans |= Q(payment_response__icontains=merchant_order)
        if tid:
            query_trans |= Q(transaction_id__icontains=tid)
            query_trans |= Q(payment_response__icontains=tid)
        if auth_code:
            query_trans |= Q(payment_response__icontains=auth_code)
        
        transactions = PaymentTransaction.objects.filter(query_trans).order_by('-data_criacao')
        
        # Limita resultados apenas se NÃO for busca por pedido específico
        if not pedido_id:
            transactions = transactions[:10]  # Mostra no máximo 10
        
        if transactions.exists():
            encontrou_algo = True
            self.stdout.write(self.style.SUCCESS(f'✅ {transactions.count()} transação(ões):\n'))
            
            for t in transactions:
                self.stdout.write(f'┌─ Transaction #{t.id}')
                self.stdout.write(f'│  📊 Status: {t.status}')
                self.stdout.write(f'│  💰 Valor: R$ {t.valor/100:.2f}')
                self.stdout.write(f'│  📅 Data: {t.data_criacao.strftime("%d/%m/%Y %H:%M")}')
                
                # Extrai dados do payment_response
                if t.payment_response and isinstance(t.payment_response, dict):
                    resp = t.payment_response
                    if resp.get('payment_id'):
                        self.stdout.write(f'│  💳 Payment ID: {resp["payment_id"]}')
                    if resp.get('merchant_order_id'):
                        self.stdout.write(f'│  🔢 Merchant Order: {resp["merchant_order_id"]}')
                    
                    raw = resp.get('raw_response', {})
                    payment = raw.get('Payment', {})
                    if payment.get('Tid'):
                        self.stdout.write(f'│  🆔 TID: {payment["Tid"]}')
                    if payment.get('AuthorizationCode'):
                        self.stdout.write(f'│  🔐 Auth: {payment["AuthorizationCode"]}')
                    if payment.get('ProofOfSale'):
                        self.stdout.write(f'│  🔢 NSU: {payment["ProofOfSale"]}')
                
                # Só mostra pedido se NÃO estiver buscando por pedido_id específico
                if not pedido_id and t.checkout_link and t.checkout_link.pedido:
                    p = t.checkout_link.pedido
                    self.stdout.write(f'│')
                    self.stdout.write(f'│  📦 PEDIDO: {p.id}')
                    self.stdout.write(f'│     👤 {p.comprador.name if p.comprador else "N/A"}')
                    self.stdout.write(f'│     📊 {p.phase}')
                    self.stdout.write(f'│     💰 Total: R$ {p.precoDosProdutos():.2f}')
                
                self.stdout.write(f'└─' + '─'*68 + '\n')
        else:
            self.stdout.write('   ❌ Nenhum encontrado\n')

        # ===== 2. CIELO LIO =====
        self.stdout.write(self.style.SUCCESS('2️⃣  CIELO LIO (Maquininha):\n'))
        
        query_lio = Q()
        
        if pedido_id:
            query_lio &= Q(pedido__id=pedido_id)
        
        if tid:
            query_lio |= Q(transaction_id__icontains=tid)
        if payment_id:
            query_lio |= Q(payment_id__icontains=payment_id)
        if merchant_order:
            query_lio |= Q(merchant_order_id__icontains=merchant_order)
        if auth_code:
            query_lio |= Q(auth_code__icontains=auth_code)
        
        lio_payments = PaymentCieloLio.objects.filter(query_lio).order_by('-created_at')
        
        if not pedido_id:
            lio_payments = lio_payments[:10]
        
        if lio_payments.exists():
            encontrou_algo = True
            self.stdout.write(self.style.SUCCESS(f'✅ {lio_payments.count()} registro(s):\n'))
            
            for lio in lio_payments:
                self.stdout.write(f'┌─ CieloLio #{lio.id}')
                self.stdout.write(f'│  💰 R$ {lio.value/100:.2f}')
                self.stdout.write(f'│  📅 {lio.created_at.strftime("%d/%m/%Y %H:%M")}')
                self.stdout.write(f'│  🔐 Auth: {lio.auth_code or "N/A"}')
                self.stdout.write(f'│  🆔 TID: {lio.transaction_id or "N/A"}')
                self.stdout.write(f'│  💳 Payment ID: {lio.payment_id or "N/A"}')
                
                # Só mostra pedido se não estiver buscando por pedido específico
                if not pedido_id and lio.pedido:
                    self.stdout.write(f'│  📦 Pedido: {lio.pedido.id}')
                
                self.stdout.write(f'└─' + '─'*68 + '\n')
        else:
            self.stdout.write('   ❌ Nenhum encontrado\n')

        # ===== 3. PAYMENT =====
        if merchant_order or auth_code or pedido_id:
            self.stdout.write(self.style.SUCCESS('3️⃣  PAYMENT (Pagamentos Diretos):\n'))
            
            query_payment = Q()
            
            if pedido_id:
                query_payment &= Q(pedido__id=pedido_id)
            
            if merchant_order:
                query_payment |= Q(merchant_order_id__icontains=merchant_order)
            if auth_code:
                query_payment |= Q(cod_autenticacao__icontains=auth_code)
            
            payments = Payment.objects.filter(query_payment).order_by('-created')
            
            if not pedido_id:
                payments = payments[:10]
            
            if payments.exists():
                encontrou_algo = True
                self.stdout.write(self.style.SUCCESS(f'✅ {payments.count()} pagamento(s):\n'))
                
                for p in payments:
                    self.stdout.write(f'┌─ Payment #{p.id}')
                    self.stdout.write(f'│  💰 R$ {p.valor:.2f}')
                    self.stdout.write(f'│  💳 {p.payment_type}')
                    self.stdout.write(f'│  📅 {p.created.strftime("%d/%m/%Y %H:%M")}')
                    self.stdout.write(f'│  🔐 Auth: {p.cod_autenticacao or "N/A"}')
                    self.stdout.write(f'│  🔢 Merchant: {p.merchant_order_id or "N/A"}')
                    
                    # Só mostra pedido se não estiver buscando por pedido específico
                    if not pedido_id and p.pedido:
                        self.stdout.write(f'│  📦 Pedido: {p.pedido.id}')
                        self.stdout.write(f'│     👤 {p.pedido.comprador.name if p.pedido.comprador else "N/A"}')
                    
                    self.stdout.write(f'└─' + '─'*68 + '\n')
            else:
                self.stdout.write('   ❌ Nenhum encontrado\n')

        # ===== 4. CONSULTAR API CIELO =====
        if consultar_api and (payment_id or merchant_order):
            self.stdout.write(self.style.SUCCESS('4️⃣  API CIELO:\n'))
            
            if payment_id:
                self.stdout.write(f'🔍 Consultando Payment ID: {payment_id}\n')
                resultado = self.consultar_por_payment_id(payment_id)
                if resultado and 'error' not in resultado:
                    encontrou_algo = True
                    self.mostrar_dados_cielo(resultado)
                elif resultado:
                    self.stdout.write(self.style.WARNING(f'⚠️  {resultado.get("error")}\n'))
            
            elif merchant_order:
                self.stdout.write(f'🔍 Consultando Merchant Order: {merchant_order}\n')
                resultado = self.consultar_por_merchant_order(merchant_order)
                if resultado and 'error' not in resultado:
                    encontrou_algo = True
                    if isinstance(resultado, list):
                        self.stdout.write(self.style.SUCCESS(f'✅ {len(resultado)} transação(ões):\n'))
                        for idx, trans in enumerate(resultado, 1):
                            self.stdout.write(f'#{idx}:')
                            self.mostrar_dados_cielo(trans)
                    else:
                        self.mostrar_dados_cielo(resultado)
                elif resultado:
                    self.stdout.write(self.style.WARNING(f'⚠️  {resultado.get("error")}\n'))

        # ===== RESULTADO =====
        self.stdout.write('\n' + '='*70)
        if encontrou_algo:
            self.stdout.write(self.style.SUCCESS('✅ PAGAMENTO ENCONTRADO!'))
        else:
            self.stdout.write(self.style.ERROR('❌ PAGAMENTO NÃO REGISTRADO'))
        self.stdout.write('='*70 + '\n')

    def get_token(self):
        """Gera token API Cielo"""
        client_id = getattr(settings, 'CIELO_CHECKOUT_CLIENT_ID', '')
        client_secret = getattr(settings, 'CIELO_CHECKOUT_CLIENT_SECRET', '')
        
        if not client_id or not client_secret:
            return None
        
        credentials = f"{client_id}:{client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        
        url = 'https://cieloecommerce.cielo.com.br/api/public/v2/token'
        headers = {
            'Authorization': f'Basic {encoded}',
            'Content-Type': 'application/json'
        }
        
        try:
            response = requests.post(url, headers=headers, timeout=10)
            if response.status_code == 201:
                return response.json().get('access_token')
        except:
            pass
        
        return None

    def consultar_por_payment_id(self, payment_id):
        """Consulta por PaymentID na API Cielo e-Commerce"""
        merchant_id = getattr(settings, 'CIELO_MERCHANT_ID', '')
        merchant_key = getattr(settings, 'CIELO_MERCHANT_KEY', '')
        
        if not merchant_id or not merchant_key:
            return {'error': 'CIELO_MERCHANT_ID/KEY não configurados'}
        
        url = f'https://apiquery.cieloecommerce.cielo.com.br/1/sales/{payment_id}'
        headers = {
            'MerchantId': merchant_id,
            'MerchantKey': merchant_key
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                return response.json()
            if response.status_code == 404:
                return {'error': 'Payment ID não encontrado'}
            return {'error': f'HTTP {response.status_code}'}
        except Exception as e:
            return {'error': str(e)}

    def consultar_por_merchant_order(self, merchant_order):
        """Consulta por MerchantOrderID no Checkout Cielo"""
        token = self.get_token()
        if not token:
            return {'error': 'Falha ao obter token'}
        
        url = f'https://cieloecommerce.cielo.com.br/api/public/v2/merchantOrderNumber/{merchant_order}'
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                return response.json()
            if response.status_code == 404:
                return {'error': 'Merchant Order não encontrado'}
            return {'error': f'HTTP {response.status_code}'}
        except Exception as e:
            return {'error': str(e)}

    def mostrar_dados_cielo(self, dados):
        """Exibe dados da API Cielo"""
        self.stdout.write(f'┌─ API Cielo')
        
        if 'order_number' in dados:
            self.stdout.write(f'│  🔢 Order: {dados["order_number"]}')
        
        payment = dados.get('payment', dados.get('Payment', {}))
        if payment:
            if payment.get('PaymentId'):
                self.stdout.write(f'│  💳 Payment ID: {payment["PaymentId"]}')
            if payment.get('Status'):
                self.stdout.write(f'│  📊 Status: {payment["Status"]}')
            if payment.get('Tid'):
                self.stdout.write(f'│  🆔 TID: {payment["Tid"]}')
            if payment.get('AuthorizationCode'):
                self.stdout.write(f'│  🔐 Auth: {payment["AuthorizationCode"]}')
            if payment.get('Amount'):
                self.stdout.write(f'│  💰 Valor: R$ {payment["Amount"]/100:.2f}')
        
        self.stdout.write(f'└─' + '─'*68 + '\n')
