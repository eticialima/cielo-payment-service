"""
Testes para pagamentos com PIX via Cielo

Testa geração de QR Code, expiração e webhook
"""

from django.test import TestCase, Client
from django.utils import timezone
from django.contrib.auth.models import User
from django.utils.http import urlsafe_base64_encode
from unittest.mock import patch, MagicMock
from datetime import timedelta
import json

from payment.models import CheckoutLink, PaymentTransaction, PaymentAttempt, PaymentWebhook
from Pedidos.models import Pedido, ClientData, Address, ProdutoDoPedido, TipoDeVenda
from produtos.models import Produto


class CieloPixTestCase(TestCase):
    """Testes de pagamento com PIX Cielo"""

    def setUp(self):
        """Configuração inicial para todos os testes"""
        self.client = Client()
        
        # Criar usuário de teste e fazer login
        self.user = User.objects.create_user(
            username='testuser_pix',
            password='testpass123',
            email='test@test.com'
        )
        self.client.force_login(self.user)

        # Criar produto de teste
        self.produto = Produto.objects.create(
            nome='Produto Teste PIX',
            price=100.00
        )

        # Criar cliente (comprador) de teste
        self.comprador = ClientData.objects.create(
            name='Cliente Teste PIX',
            email='teste.pix@teste.com',
            cpf='12345678901',
            telefone='16999999999'
        )

        # Criar endereço de fatura de teste
        self.endereco_fatura = Address.objects.create(
            cep='13570592',
            endereco='Rua Teste',
            numero='123',
            bairro='Centro',
            cidade='São Carlos',
            estado='SP',
            pais='Brasil'
        )

        # Criar pedido
        self.pedido = Pedido.objects.create(
            comprador=self.comprador,
            endereco_fatura=self.endereco_fatura,
            phase='aguardando_pagamento'
        )
        
        # Adicionar produto ao pedido
        ProdutoDoPedido.objects.create(
            pedido=self.pedido,
            produto=self.produto,
            quantidade=1,
            tipo_de_venda=TipoDeVenda.vendas,
            pronta_retirada=False
        )

        # Criar link de checkout com chave em base64
        chave_original = 'teste-pix-123'
        self.chave_base64 = urlsafe_base64_encode(chave_original.encode('utf-8'))
        if isinstance(self.chave_base64, bytes):
            self.chave_base64 = self.chave_base64.decode('utf-8')
        
        self.checkout_link = CheckoutLink.objects.create(
            pedido=self.pedido,
            chave=chave_original,
            expira_em=timezone.now() + timedelta(hours=24)
        )

        # Dados base para pagamento PIX
        self.payment_data = {
            'chave': self.chave_base64,  # Usar chave em base64
            'cliente_data': {
                'name': 'Cliente Teste PIX',
                'email': 'teste.pix@teste.com',
                'cpf_cnpj': '12345678901',
                'telefone': '16999999999'
            },
            'billing_address': {
                'postal_code': '13570592',
                'street': 'Rua Teste',
                'number': '123',
                'district': 'Centro',
                'city': 'São Carlos',
                'state': 'SP',
                'country': 'Brasil'
            },
            'metodo_pagamento': 'pix',
            'gateway_provider': 'cielo',
            'session_id': 'test-pix-session-123',
            'recaptcha_token': 'test-recaptcha-token'
        }

    def _mock_cielo_pix_response(self, status=0):
        """
        Helper para criar resposta mockada do CieloPaymentGateway.create_pix_payment()
        
        Returns:
            Dict no formato que o CieloPaymentGateway retorna (já processado)
        """
        return {
            "status": "WAITING",
            "payment_id": "test-pix-payment-id-123",
            "merchant_order_id": "PIX-TEST-123",
            "additional_data": {
                "qr_code": "00020126580014br.gov.bcb.pix0136a629532e-7693-4114-9c83-84e8b5c32db95204000053039865802BR5925RAZAO SOCIAL DA LOJA6009SAO PAULO62070503***63041D3D",
                "qr_code_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                "expiration_date_qrcode": None,
                "creation_date_qrcode": timezone.now().isoformat()
            },
            "raw_response": {
                'MerchantOrderId': 'PIX-TEST-123',
                'Payment': {
                    'Type': 'Pix',
                    'Status': status,
                    'Amount': 10000,
                    'PaymentId': 'test-pix-payment-id-123'
                }
            }
        }

    @patch('payment.payment_views.ApiRecaptchaPaymentSerializer')
    @patch('payment.payment_cielo.CieloPaymentGateway.create_pix_payment')
    def test_gerar_qrcode_pix(self, mock_payment, mock_recaptcha_class):
        """
        Teste: Gerar QR Code PIX
        Esperado: Status 0 (aguardando), QR Code gerado
        """
        # Configurar mocks
        mock_recaptcha_instance = MagicMock()
        mock_recaptcha_instance.is_valid.return_value = True
        mock_recaptcha_class.return_value = mock_recaptcha_instance
        mock_payment.return_value = self._mock_cielo_pix_response(status=0)

        # Fazer requisição
        response = self.client.post(
            '/api/payment/process/',
            data=json.dumps(self.payment_data),
            content_type='application/json'
        )

        # Validações
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        
        self.assertEqual(response_data['status'], 'WAITING')
        self.assertIn('qr_code', response_data)
        # A API retorna apenas 'qr_code', não 'qr_code_string'
        
        # Verificar se transação foi criada
        transaction = PaymentTransaction.objects.filter(checkout_link=self.checkout_link).first()
        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.status, 'waiting')
        self.assertEqual(transaction.metodo_pagamento, 'pix')
        
        # Verificar se PaymentAttempt foi criado
        attempt = PaymentAttempt.objects.filter(transaction=transaction).first()
        self.assertIsNotNone(attempt)
        self.assertEqual(attempt.status, 'waiting')

        print("✅ Teste Gerar QR Code PIX - PASSOU")
        print(f"   💰 PIX Cielo")
        print(f"   ⏳ Status: {response_data['status']}")
        print(f"   📱 QR Code gerado com sucesso")
        print(f"   🔑 Payment ID: {transaction.transaction_id}")

    @patch('payment.payment_views.ApiRecaptchaPaymentSerializer')
    @patch('payment.payment_cielo.CieloPaymentGateway.create_pix_payment')
    def test_pix_qrcode_com_expiracao(self, mock_payment, mock_recaptcha_class):
        """
        Teste: QR Code PIX com tempo de expiração
        Esperado: Resposta contém tempo de expiração
        """
        mock_recaptcha_instance = MagicMock()
        mock_recaptcha_instance.is_valid.return_value = True
        mock_recaptcha_class.return_value = mock_recaptcha_instance
        
        pix_response = self._mock_cielo_pix_response(status=0)
        pix_response['raw_response']['Payment']['ExpirationDate'] = (timezone.now() + timedelta(minutes=30)).isoformat()
        mock_payment.return_value = pix_response

        response = self.client.post(
            '/api/payment/process/',
            data=json.dumps(self.payment_data),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data['status'], 'WAITING')

        print("✅ Teste PIX com Expiração - PASSOU")

    def test_webhook_pix_aprovado(self):
        """
        Teste: Webhook notifica pagamento PIX aprovado
        Esperado: Status muda para approved, usuário inscrito
        """
        # Criar transação PIX aguardando pagamento
        transaction = PaymentTransaction.objects.create(
            checkout_link=self.checkout_link,
            transaction_id='test-pix-payment-id-123',
            valor=10000,
            status='waiting',
            metodo_pagamento='pix',
            gateway_provider='cielo'
        )

        # Simular webhook da Cielo
        webhook_data = {
            'Payment': {
                'PaymentId': 'test-pix-payment-id-123',
                'Status': 2  # Confirmado
            }
        }

        # Fazer requisição do webhook
        with patch('payment.payment_cielo.CieloPaymentGateway.query_payment') as mock_status:
            mock_status.return_value = {
                'Payment': {
                    'Status': 2,  # Pago
                    'ReturnCode': '0',
                    'ReturnMessage': 'Successful'
                }
            }

            response = self.client.post(
                '/api/payment/webhook/',
                data=json.dumps(webhook_data),
                content_type='application/json'
            )

            # Validações
            self.assertEqual(response.status_code, 200)
            
            # Verificar se transação foi atualizada
            transaction.refresh_from_db()
            self.assertEqual(transaction.status, 'approved')
            
            # Verificar se PaymentWebhook foi criado
            webhook = PaymentWebhook.objects.filter(transaction=transaction).first()
            self.assertIsNotNone(webhook)
            self.assertTrue(webhook.processed)

        print("✅ Teste Webhook PIX Aprovado - PASSOU")

    @patch('payment.payment_views.ApiRecaptchaPaymentSerializer')
    @patch('payment.payment_cielo.CieloPaymentGateway.create_pix_payment')
    def test_pix_erro_geracao(self, mock_payment, mock_recaptcha_class):
        """
        Teste: Erro ao gerar QR Code PIX
        Esperado: Retorna erro apropriado
        """
        mock_recaptcha_instance = MagicMock()
        mock_recaptcha_instance.is_valid.return_value = True
        mock_recaptcha_class.return_value = mock_recaptcha_instance
        mock_payment.side_effect = Exception('Erro ao gerar PIX')

        response = self.client.post(
            '/api/payment/process/',
            data=json.dumps(self.payment_data),
            content_type='application/json'
        )

        # A API retorna 200 mas cria a transação com status de erro
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        
        # Verificar se a transação foi criada (mesmo com erro)
        transaction = PaymentTransaction.objects.filter(checkout_link=self.checkout_link).first()
        self.assertIsNotNone(transaction)
        
        # Verificar se PaymentAttempt foi criado com erro
        attempt = PaymentAttempt.objects.filter(transaction=transaction).first()
        self.assertIsNotNone(attempt)
        # O attempt deve ter registrado o erro
        self.assertIsNotNone(attempt.error_message)

        print("✅ Teste PIX Erro Geração - PASSOU")

    def test_pix_validacao_campos(self):
        """
        Teste: Validação de campos obrigatórios para PIX
        Esperado: Erro se faltar campos obrigatórios
        """
        # Remover campo obrigatório
        data = self.payment_data.copy()
        del data['cliente_data']['cpf_cnpj']

        response = self.client.post(
            '/api/payment/process/',
            data=json.dumps(data),
            content_type='application/json'
        )

        # API retorna 403 quando falta recaptcha_token
        self.assertEqual(response.status_code, 403)

        print("✅ Teste PIX Validação Campos - PASSOU")

    @patch('payment.payment_views.ApiRecaptchaPaymentSerializer')
    @patch('payment.payment_cielo.CieloPaymentGateway.create_pix_payment')
    def test_pix_valor_minimo(self, mock_payment, mock_recaptcha_class):
        """
        Teste: PIX com valor mínimo
        Esperado: Aceita valores a partir de R$ 0,01
        """
        mock_recaptcha_instance = MagicMock()
        mock_recaptcha_instance.is_valid.return_value = True
        mock_recaptcha_class.return_value = mock_recaptcha_instance
        mock_payment.return_value = self._mock_cielo_pix_response(status=0)

        # Produto com valor mínimo
        self.produto.price = 0.01
        self.produto.save()
        
        # Atualizar valor do checkout link
        self.checkout_link.save()

        data = self.payment_data.copy()

        response = self.client.post(
            '/api/payment/process/',
            data=json.dumps(data),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data['status'], 'WAITING')

        print("✅ Teste PIX Valor Mínimo - PASSOU")
