import requests
import json
from django.core.management.base import BaseCommand
from django.conf import settings
from Pedidos.models import Pedido
from payment.models import CheckoutLink, PaymentTransaction


class Command(BaseCommand):
    help = 'Consulta status de pagamento na Cielo e-Commerce'

    def add_arguments(self, parser):
        parser.add_argument(
            '--pedido',
            type=str,
            help='ID do pedido (string) para buscar o transaction_id no banco'
        )
        parser.add_argument(
            '--transaction-id',
            type=str,
            help='Transaction ID (PaymentId) direto da Cielo'
        )

    def handle(self, *args, **options):
        pedido_id = options.get('pedido')
        transaction_id = options.get('transaction_id')

        if not pedido_id and not transaction_id:
            self.stdout.write(self.style.ERROR('Informe --pedido ou --transaction-id'))
            return

        # Se passou o pedido, busca no banco com select_related
        if pedido_id:
            transaction = PaymentTransaction.objects.filter(
                checkout_link__pedido_id=pedido_id
            ).select_related('checkout_link__pedido'
                             ).order_by('-data_criacao').first()
            
            if not transaction:
                self.stdout.write(self.style.ERROR(f'Nenhuma transação encontrada para o pedido {pedido_id}'))
                return
            
            if not transaction.transaction_id:
                self.stdout.write(self.style.WARNING(f'Transação sem PaymentId'))
                return
            
            # Mostra dados do banco
            self.stdout.write(self.style.SUCCESS(f'Pedido: {transaction.checkout_link.pedido.id}'))
            self.stdout.write(self.style.SUCCESS(f'DADOS NO BANCO:'))
            self.stdout.write(f'   Status: {transaction.get_status_display()}')
            self.stdout.write(f'   Valor: R$ {transaction.valor / 100:.2f}')
            self.stdout.write(f'   Parcelas: {transaction.installments}x')
            self.stdout.write(f'   Criado: {transaction.data_criacao.strftime("%d/%m/%Y %H:%M")}')
            if transaction.data_pagamento:
                self.stdout.write(f'   Pago em: {transaction.data_pagamento.strftime("%d/%m/%Y %H:%M")}')
            self.stdout.write('')
            
            transaction_id = transaction.transaction_id

        # Consulta na API
        self.consultar_payment_id(transaction_id)

    def consultar_payment_id(self, payment_id):
        self.stdout.write(self.style.SUCCESS(
            f'Consultando na API da Cielo: {payment_id}\n'
        ))

        dados_cielo = self.consultar_cielo_api(payment_id)

        if not dados_cielo:
            self.stdout.write(self.style.ERROR('Falha ao consultar a API da Cielo'))
            return

        if 'error' in dados_cielo:
            self.stdout.write(self.style.ERROR(dados_cielo['error']))
            if 'response' in dados_cielo:
                self.stdout.write(dados_cielo['response'])
            return

        self.mostrar_dados_cielo(dados_cielo)

    def consultar_cielo_api(self, payment_id):
        """
        Consulta a API da Cielo e-Commerce
        Endpoint: GET /1/sales/{paymentId}
        """
        merchant_id = getattr(settings, 'CIELO_MERCHANT_ID', '')
        merchant_key = getattr(settings, 'CIELO_MERCHANT_KEY', '')
        query_url = getattr(
            settings,
            'CIELO_QUERY_URL',
            'https://apiquerysandbox.cieloecommerce.cielo.com.br/1/sales/'
        )

        self.stdout.write('API Query URL: ' + query_url + '\n')

        if not merchant_id or not merchant_key:
            return {'error': 'CIELO_MERCHANT_ID ou CIELO_MERCHANT_KEY não configurados'}

        url = f'{query_url}{payment_id}'

        headers = {
            'Content-Type': 'application/json',
            'MerchantId': merchant_id,
            'MerchantKey': merchant_key,
        }

        self.stdout.write(f'URL: {url}\n')

        try:
            response = requests.get(url, headers=headers, timeout=30)

            if response.status_code == 200:
                return response.json()

            if response.status_code == 404:
                return {'error': 'Pagamento não encontrado'}

            if response.status_code == 401:
                return {
                    'error': 'Não autorizado (credenciais inválidas)',
                    'response': response.text
                }

            return {
                'error': f'Erro HTTP {response.status_code}',
                'response': response.text
            }

        except requests.RequestException as e:
            return {'error': f'Erro de conexão: {str(e)}'}

    def mostrar_dados_cielo(self, dados):
        self.stdout.write(self.style.SUCCESS('🌐 DADOS NA CIELO:\n'))

        payment = dados.get('Payment', {})

        status_map = {
            0: 'NotFinished',
            1: 'Authorized',
            2: 'Confirmed',
            3: 'Denied',
            10: 'Voided',
            11: 'Refunded',
            12: 'Pending',
            13: 'Aborted',
            20: 'Scheduled',
        }

        self.stdout.write(f'PaymentId: {payment.get("PaymentId")}')
        self.stdout.write(f'Tipo: {payment.get("Type")}')
        self.stdout.write(
            f'Status: {status_map.get(payment.get("Status"), "Unknown")}'
        )
        self.stdout.write(f'Valor: R$ {payment.get("Amount", 0) / 100:.2f}')
        self.stdout.write(f'Parcelas: {payment.get("Installments", 1)}')

        if payment.get('AuthorizationCode'):
            self.stdout.write(f'Auth Code: {payment["AuthorizationCode"]}')

        if payment.get('ProofOfSale'):
            self.stdout.write(f'NSU: {payment["ProofOfSale"]}')

        self.stdout.write('\n📄 JSON COMPLETO:\n')
        self.stdout.write(json.dumps(dados, indent=2, ensure_ascii=False))
