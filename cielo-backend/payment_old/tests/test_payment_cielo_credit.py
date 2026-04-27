"""
Testes para pagamentos com Cartão de Crédito via Cielo

Testa todos os cartões de teste da Cielo conforme documentação:
https://developercielo.github.io/manual/cielo-ecommerce#cart%C3%B5es-para-teste
"""

from django.test import TestCase, Client
from django.utils import timezone
from django.contrib.auth.models import User
from django.utils.http import urlsafe_base64_encode
from unittest.mock import patch, MagicMock
from datetime import timedelta
import json

from payment.models import CheckoutLink, PaymentTransaction, PaymentAttempt
from Pedidos.models import Pedido, ClientData, Address, ProdutoDoPedido, TipoDeVenda, Payment, CalculationType
from produtos.models import Produto


class CieloCreditCardTestCase(TestCase):
    """Testes de pagamento com cartão de crédito Cielo"""

    def setUp(self):
        """Configuração inicial para todos os testes"""
        self.client = Client()
        
        # Criar usuário de teste e fazer login
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@test.com'
        )
        self.client.force_login(self.user)

        # Criar produto de teste
        self.produto = Produto.objects.create(
            nome='Produto Teste Cartão',
            price=100.00
        )

        # Criar cliente (comprador) de teste
        self.comprador = ClientData.objects.create(
            name='Cliente Teste',
            email='teste@teste.com',
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
        chave_original = 'teste123'
        self.chave_base64 = urlsafe_base64_encode(chave_original.encode('utf-8'))
        if isinstance(self.chave_base64, bytes):
            self.chave_base64 = self.chave_base64.decode('utf-8')
        
        self.checkout_link = CheckoutLink.objects.create(
            pedido=self.pedido,
            chave=chave_original,
            expira_em=timezone.now() + timedelta(hours=24)
        )

        # Dados base para pagamento
        self.payment_data = {
            'chave': self.chave_base64,  # Usar chave em base64
            'cliente_data': {
                'name': 'Cliente Teste',
                'email': 'teste@teste.com',
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
            'metodo_pagamento': 'credit_card',
            'gateway_provider': 'cielo',
            'session_id': 'test-session-123',
            'recaptcha_token': 'test-recaptcha-token'
        }

    def _create_card_data(self, card_number, brand='visa'):
        """Helper para criar dados de cartão"""
        return {
            'card_number': card_number,
            'cardholder_name': 'TESTE TESTE',
            'expiration_month': '12',
            'expiration_year': '30',
            'security_code': '123',
            'brand': brand
        }

    def _mock_cielo_response(self, cielo_status, return_code, return_message):
        """
        Helper para criar resposta mockada do CieloPaymentGateway.create_credit_payment()
        
        Args:
            cielo_status: Status numérico da Cielo (0-13)
            return_code: Código de retorno (ex: '4', '6', '05', '57')
            return_message: Mensagem de retorno
        
        Returns:
            Dict no formato que o CieloPaymentGateway retorna (já processado)
        """
        # Mapear status Cielo para status de resposta
        status_map = {
            0: "PROCESSING",  # NotFinished
            1: "APPROVED",    # Authorized
            2: "APPROVED",    # PaymentConfirmed
            3: "DENIED",      # Denied
            10: "CANCELED",   # Voided
            11: "REFUNDED",   # Refunded
            12: "PENDING",    # Pending
            13: "CANCELED"    # Aborted
        }
        
        response_status = status_map.get(cielo_status, "PENDING")
        
        return {
            "status": response_status,
            "payment_id": "test-payment-id-123",
            "merchant_order_id": "TEST-123",
            "cielo_status": cielo_status,
            "return_code": return_code,
            "return_message": return_message,
            "denial_reason": return_message if response_status == "DENIED" else "",
            "proof_of_sale": "123456",
            "authorization_code": "123456",
            "tid": "1234567890"
        }

    @patch('payment.payment_views.ApiRecaptchaPaymentSerializer')
    @patch('payment.payment_cielo.CieloPaymentGateway.create_credit_payment')
    def test_cartao_autorizado_xxx0(self, mock_payment, mock_recaptcha_class):
        """
        Teste: Cartão final XXX0 - Autorizado
        Esperado: Status 2, ReturnCode 4 ou 6, Pagamento aprovado
        """
        # Configurar mocks
        mock_recaptcha_instance = MagicMock()
        mock_recaptcha_instance.is_valid.return_value = True
        mock_recaptcha_class.return_value = mock_recaptcha_instance
        mock_payment.return_value = self._mock_cielo_response(2, '6', 'Operation Successful')

        # Dados do pagamento
        data = self.payment_data.copy()
        data['card_data'] = self._create_card_data('4024007197692930')  # Final XXX0

        # Fazer requisição
        response = self.client.post(
            '/api/payment/process/',
            data=json.dumps(data),
            content_type='application/json'
        )

        # Validações
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        
        self.assertEqual(response_data['status'], 'APPROVED')
        self.assertIn('transaction_id', response_data)
        
        # Verificar se transação foi criada
        transaction = PaymentTransaction.objects.filter(checkout_link=self.checkout_link).first()
        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.status, 'approved')
        
        # Verificar se PaymentAttempt foi criado
        attempt = PaymentAttempt.objects.filter(transaction=transaction).first()
        self.assertIsNotNone(attempt)
        self.assertEqual(attempt.status, 'approved')

        print("✅ Teste XXX0 (Autorizado) - PASSOU")
        print(f"   💳 Cartão Final XXX0: {data['card_data']['card_number'][-4:]}")
        print(f"   ✅ Status: {response_data['status']}")
        print(f"   📝 Mensagem: Operação realizada com sucesso")

    @patch('payment.payment_views.ApiRecaptchaPaymentSerializer')
    @patch('payment.payment_cielo.CieloPaymentGateway.create_credit_payment')
    def test_cartao_autorizado_xxx1(self, mock_payment, mock_recaptcha_class):
        """
        Teste: Cartão final XXX1 - Autorizado
        Esperado: Status 2, ReturnCode 4 ou 6, Pagamento aprovado
        """
        # Configurar mocks
        mock_recaptcha_instance = MagicMock()
        mock_recaptcha_instance.is_valid.return_value = True
        mock_recaptcha_class.return_value = mock_recaptcha_instance
        mock_payment.return_value = self._mock_cielo_response(2, '4', 'Operation Successful')

        # Dados do pagamento
        data = self.payment_data.copy()
        data['card_data'] = self._create_card_data('4024007197692931')  # Final XXX1

        # Fazer requisição
        response = self.client.post(
            '/api/payment/process/',
            data=json.dumps(data),
            content_type='application/json'
        )

        # Verificar resposta
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data['status'], 'APPROVED')
        
        # Verificar se transação foi criada
        transaction = PaymentTransaction.objects.filter(checkout_link=self.checkout_link).first()
        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.status, 'approved')
        
        # Verificar se PaymentAttempt foi criado
        attempt = PaymentAttempt.objects.filter(transaction=transaction).first()
        self.assertIsNotNone(attempt)
        self.assertEqual(attempt.status, 'approved')

        print("✅ Teste XXX1 (Autorizado) - PASSOU")

    @patch('payment.payment_views.ApiRecaptchaPaymentSerializer')
    @patch('payment.payment_cielo.CieloPaymentGateway.create_credit_payment')
    def test_campos_parcelamento_opcionais(self, mock_payment, mock_recaptcha_class):
        """
        Teste: Garante que campos opcionais de parcelamento são persistidos corretamente
        """
        # Configurar mocks
        mock_recaptcha_instance = MagicMock()
        mock_recaptcha_instance.is_valid.return_value = True
        mock_recaptcha_class.return_value = mock_recaptcha_instance
        mock_payment.return_value = self._mock_cielo_response(2, '6', 'Operation Successful')

        # Dados do pagamento com campos de parcelamento
        data = self.payment_data.copy()
        data['card_data'] = self._create_card_data('4024007197692930')
        data.update({
            'tipo_calculo_parcelamento': CalculationType.misto,
            'valor_principal_solicitado_cents': 10000,
            'valor_acessorio_solicitado_cents': 500,
            'valor_principal_com_juros_cents': 10800,
            'total_cobrado_cents': 11300,
        })

        # Fazer requisição
        response = self.client.post(
            '/api/payment/process/',
            data=json.dumps(data),
            content_type='application/json'
        )

        # Verificar resposta
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'APPROVED')
        
        # Verificar se Payment foi criado com os campos corretos
        payment_record = Payment.objects.filter(pedido=self.pedido).first()
        self.assertIsNotNone(payment_record, "Payment deve ser criado")
        self.assertEqual(payment_record.tipo_calculo_parcelamento, CalculationType.misto)
        self.assertEqual(payment_record.valor_principal_solicitado_cents, 10000)
        self.assertEqual(payment_record.valor_acessorio_solicitado_cents, 500)
        self.assertEqual(payment_record.valor_principal_com_juros_cents, 10800)
        self.assertEqual(payment_record.total_cobrado_cents, 11300)

        print("Teste Campos Parcelamento - PASSOU")
        print(f"   Tipo: {payment_record.tipo_calculo_parcelamento}")
        print(f"   Principal: {payment_record.valor_principal_solicitado_cents}")
        print(f"   Acessório: {payment_record.valor_acessorio_solicitado_cents}")
        print(f"   Com Juros: {payment_record.valor_principal_com_juros_cents}")
        print(f"   Total: {payment_record.total_cobrado_cents}")

    @patch('payment.payment_views.ApiRecaptchaPaymentSerializer')
    @patch('payment.payment_cielo.CieloPaymentGateway.create_credit_payment')
    def test_campos_parcelamento_ausentes_nao_quebra(self, mock_payment, mock_recaptcha_class):
        """
        Teste: Garante compatibilidade - pagamento sem novos campos continua funcionando
        """
        # Configurar mocks
        mock_recaptcha_instance = MagicMock()
        mock_recaptcha_instance.is_valid.return_value = True
        mock_recaptcha_class.return_value = mock_recaptcha_instance
        mock_payment.return_value = self._mock_cielo_response(2, '6', 'Operation Successful')

        # Dados do pagamento SEM campos de parcelamento (fluxo antigo)
        data = self.payment_data.copy()
        data['card_data'] = self._create_card_data('4024007197692930')
        # Não inclui campos de parcelamento

        # Fazer requisição
        response = self.client.post(
            '/api/payment/process/',
            data=json.dumps(data),
            content_type='application/json'
        )

        # Verificar resposta
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'APPROVED')
        
        # Verificar se Payment foi criado com valores padrão
        payment_record = Payment.objects.filter(pedido=self.pedido).first()
        self.assertIsNotNone(payment_record)
        self.assertIsNone(payment_record.tipo_calculo_parcelamento)
        self.assertEqual(payment_record.valor_principal_solicitado_cents, 0)
        self.assertEqual(payment_record.valor_acessorio_solicitado_cents, 0)
        self.assertEqual(payment_record.valor_principal_com_juros_cents, 0)
        self.assertEqual(payment_record.total_cobrado_cents, 0)

        print("✅ Teste Compatibilidade (sem campos) - PASSOU")
        print(f"   💳 Cartão Final XXX1: {data['card_data']['card_number'][-4:]}")
        print(f"   ✅ Status: {response_data['status']}")
        print(f"   📝 Mensagem: Operação realizada com sucesso")

    @patch('payment.payment_views.ApiRecaptchaPaymentSerializer')
    @patch('payment.payment_cielo.CieloPaymentGateway.create_credit_payment')
    def test_cartao_nao_autorizado_xxx2(self, mock_payment, mock_recaptcha_class):
        """
        Teste: Cartão final XXX2 - Não Autorizado
        Esperado: Status 3, ReturnCode 05, Pagamento negado
        """
        # Configurar mocks
        mock_recaptcha_instance = MagicMock()
        mock_recaptcha_instance.is_valid.return_value = True
        mock_recaptcha_class.return_value = mock_recaptcha_instance
        mock_payment.return_value = self._mock_cielo_response(3, '05', 'Não autorizada')

        # Dados do pagamento
        data = self.payment_data.copy()
        data['card_data'] = self._create_card_data('4024007197692932')  # Final XXX2

        # Fazer requisição
        response = self.client.post(
            '/api/payment/process/',
            data=json.dumps(data),
            content_type='application/json'
        )

        # Validações
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        
        self.assertEqual(response_data['status'], 'DENIED')
        self.assertIn('denial_reason', response_data)
        
        # Verificar se transação foi criada
        transaction = PaymentTransaction.objects.filter(checkout_link=self.checkout_link).first()
        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.status, 'denied')

        print("✅ Teste XXX2 (Não Autorizado) - PASSOU")
        print(f"   💳 Cartão Final XXX2: {data['card_data']['card_number'][-4:]}")
        print(f"   ❌ Status: {response_data['status']}")
        print(f"   📝 Mensagem: Não autorizada")

    @patch('payment.payment_views.ApiRecaptchaPaymentSerializer')
    @patch('payment.payment_cielo.CieloPaymentGateway.create_credit_payment')
    def test_cartao_expirado_xxx3(self, mock_payment, mock_recaptcha_class):
        """
        Teste: Cartão final XXX3 - Cartão Expirado
        Esperado: Status 3, ReturnCode 57, Pagamento negado
        """
        mock_recaptcha_instance = MagicMock()
        mock_recaptcha_instance.is_valid.return_value = True
        mock_recaptcha_class.return_value = mock_recaptcha_instance
        mock_payment.return_value = self._mock_cielo_response(3, '57', 'Cartão expirado')

        data = self.payment_data.copy()
        data['card_data'] = self._create_card_data('4024007197692933')  # Final XXX3

        response = self.client.post(
            '/api/payment/process/',
            data=json.dumps(data),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data['status'], 'DENIED')

        print("✅ Teste XXX3 (Cartão Expirado) - PASSOU")
        print(f"   💳 Cartão Final XXX3: {data['card_data']['card_number'][-4:]}")
        print(f"   ❌ Status: {response_data['status']}")
        print(f"   📝 Mensagem: Cartão expirado")

    @patch('payment.payment_views.ApiRecaptchaPaymentSerializer')
    @patch('payment.payment_cielo.CieloPaymentGateway.create_credit_payment')
    def test_cartao_bloqueado_xxx5(self, mock_payment, mock_recaptcha_class):
        """
        Teste: Cartão final XXX5 - Cartão Bloqueado
        Esperado: Status 3, ReturnCode 78, Pagamento negado
        """
        mock_recaptcha_instance = MagicMock()
        mock_recaptcha_instance.is_valid.return_value = True
        mock_recaptcha_class.return_value = mock_recaptcha_instance
        mock_payment.return_value = self._mock_cielo_response(3, '78', 'Cartão bloqueado')

        data = self.payment_data.copy()
        data['card_data'] = self._create_card_data('4024007197692935')  # Final XXX5

        response = self.client.post(
            '/api/payment/process/',
            data=json.dumps(data),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data['status'], 'DENIED')

        print("✅ Teste XXX5 (Cartão Bloqueado) - PASSOU")
        print(f"   💳 Cartão Final XXX5: {data['card_data']['card_number'][-4:]}")
        print(f"   ❌ Status: {response_data['status']}")
        print(f"   📝 Mensagem: Cartão bloqueado")

    @patch('payment.payment_views.ApiRecaptchaPaymentSerializer')
    @patch('payment.payment_cielo.CieloPaymentGateway.create_credit_payment')
    def test_cartao_timeout_xxx6(self, mock_payment, mock_recaptcha_class):
        """
        Teste: Cartão final XXX6 - Timeout
        Esperado: Status 3, ReturnCode 99, Pagamento negado
        """
        mock_recaptcha_instance = MagicMock()
        mock_recaptcha_instance.is_valid.return_value = True
        mock_recaptcha_class.return_value = mock_recaptcha_instance
        mock_payment.return_value = self._mock_cielo_response(3, '99', 'Timeout')

        data = self.payment_data.copy()
        data['card_data'] = self._create_card_data('4024007197692936')  # Final XXX6

        response = self.client.post(
            '/api/payment/process/',
            data=json.dumps(data),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data['status'], 'DENIED')

        print("✅ Teste XXX6 (Timeout) - PASSOU")
        print(f"   💳 Cartão Final XXX6: {data['card_data']['card_number'][-4:]}")
        print(f"   ❌ Status: {response_data['status']}")
        print(f"   📝 Mensagem: Timeout")

    @patch('payment.payment_views.ApiRecaptchaPaymentSerializer')
    @patch('payment.payment_cielo.CieloPaymentGateway.create_credit_payment')
    def test_cartao_cancelado_xxx7(self, mock_payment, mock_recaptcha_class):
        """
        Teste: Cartão final XXX7 - Cartão Cancelado
        Esperado: Status 3, ReturnCode 77, Pagamento negado
        """
        mock_recaptcha_instance = MagicMock()
        mock_recaptcha_instance.is_valid.return_value = True
        mock_recaptcha_class.return_value = mock_recaptcha_instance
        mock_payment.return_value = self._mock_cielo_response(3, '77', 'Cartão cancelado')

        data = self.payment_data.copy()
        data['card_data'] = self._create_card_data('4024007197692937')  # Final XXX7

        response = self.client.post(
            '/api/payment/process/',
            data=json.dumps(data),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data['status'], 'DENIED')

        print("✅ Teste XXX7 (Cartão Cancelado) - PASSOU")
        print(f"   💳 Cartão Final XXX7: {data['card_data']['card_number'][-4:]}")
        print(f"   ❌ Status: {response_data['status']}")
        print(f"   📝 Mensagem: Cartão cancelado")

    @patch('payment.payment_views.ApiRecaptchaPaymentSerializer')
    @patch('payment.payment_cielo.CieloPaymentGateway.create_credit_payment')
    def test_cartao_problema_xxx8(self, mock_payment, mock_recaptcha_class):
        """
        Teste: Cartão final XXX8 - Problemas com o Cartão
        Esperado: Status 3, ReturnCode 70, Pagamento negado
        """
        mock_recaptcha_instance = MagicMock()
        mock_recaptcha_instance.is_valid.return_value = True
        mock_recaptcha_class.return_value = mock_recaptcha_instance
        mock_payment.return_value = self._mock_cielo_response(3, '70', 'Problemas com o cartão de crédito')

        data = self.payment_data.copy()
        data['card_data'] = self._create_card_data('4024007197692938')  # Final XXX8

        response = self.client.post(
            '/api/payment/process/',
            data=json.dumps(data),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data['status'], 'DENIED')

        print("✅ Teste XXX8 (Problemas com Cartão) - PASSOU")
        print(f"   💳 Cartão Final XXX8: {data['card_data']['card_number'][-4:]}")
        print(f"   ❌ Status: {response_data['status']}")
        print(f"   📝 Mensagem: Problemas com o cartão de crédito")

    @patch('payment.payment_views.ApiRecaptchaPaymentSerializer')
    @patch('payment.payment_cielo.CieloPaymentGateway.create_credit_payment')
    def test_cartao_autorizado_xxx4(self, mock_payment, mock_recaptcha_class):
        """
        Teste: Cartão final XXX4 - Autorizado
        Esperado: Status 2, ReturnCode 4 ou 6, Pagamento aprovado
        """
        # Configurar mocks
        mock_recaptcha_instance = MagicMock()
        mock_recaptcha_instance.is_valid.return_value = True
        mock_recaptcha_class.return_value = mock_recaptcha_instance
        mock_payment.return_value = self._mock_cielo_response(2, '6', 'Operation Successful')

        # Dados do pagamento
        data = self.payment_data.copy()
        data['card_data'] = self._create_card_data('4024007197692934')  # Final XXX4

        # Fazer requisição
        response = self.client.post(
            '/api/payment/process/',
            data=json.dumps(data),
            content_type='application/json'
        )

        # Verificar resposta
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data['status'], 'APPROVED')
        
        # Verificar se transação foi criada
        transaction = PaymentTransaction.objects.filter(checkout_link=self.checkout_link).first()
        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.status, 'approved')
        
        # Verificar se PaymentAttempt foi criado
        attempt = PaymentAttempt.objects.filter(transaction=transaction).first()
        self.assertIsNotNone(attempt)
        self.assertEqual(attempt.status, 'approved')

        print("✅ Teste XXX4 (Autorizado) - PASSOU")
        print(f"   💳 Cartão Final XXX4: {data['card_data']['card_number'][-4:]}")
        print(f"   ✅ Status: {response_data['status']}")
        print(f"   📝 Mensagem: Operação realizada com sucesso")

    @patch('payment.payment_views.ApiRecaptchaPaymentSerializer')
    @patch('payment.payment_cielo.CieloPaymentGateway.create_credit_payment')
    def test_cartao_autorizacao_aleatoria_xxx9(self, mock_payment, mock_recaptcha_class):
        """
        Teste: Cartão final XXX9 - Autorização Aleatória
        Esperado: Status 2 (aprovado) ou 3 (negado) aleatoriamente
        """
        # Configurar mocks - vamos simular aprovação
        mock_recaptcha_instance = MagicMock()
        mock_recaptcha_instance.is_valid.return_value = True
        mock_recaptcha_class.return_value = mock_recaptcha_instance
        mock_payment.return_value = self._mock_cielo_response(2, '4', 'Operation Successful')

        # Dados do pagamento
        data = self.payment_data.copy()
        data['card_data'] = self._create_card_data('4024007197692939')  # Final XXX9

        # Fazer requisição
        response = self.client.post(
            '/api/payment/process/',
            data=json.dumps(data),
            content_type='application/json'
        )

        # Verificar resposta
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        
        # XXX9 pode retornar APPROVED ou DENIED aleatoriamente
        self.assertIn(response_data['status'], ['APPROVED', 'DENIED'])
        
        print("✅ Teste XXX9 (Autorização Aleatória) - PASSOU")
        print(f"   💳 Cartão Final XXX9: {data['card_data']['card_number'][-4:]}")
        print(f"   🎲 Status: {response_data['status']} (Aleatório)")
        print(f"   📝 Mensagem: Autorização aleatória - pode aprovar ou negar")

    @patch('payment.payment_views.ApiRecaptchaPaymentSerializer')
    def test_link_expirado(self, mock_recaptcha_class):
        """
        Teste: Link de checkout expirado
        Esperado: Erro 403, mensagem de link expirado
        """
        # Mock do recaptcha
        mock_recaptcha_instance = MagicMock()
        mock_recaptcha_instance.is_valid.return_value = True
        mock_recaptcha_class.return_value = mock_recaptcha_instance
        
        # Expirar o link
        self.checkout_link.expira_em = timezone.now() - timedelta(hours=1)
        self.checkout_link.save()

        data = self.payment_data.copy()
        data['card_data'] = self._create_card_data('4024007197692930')

        response = self.client.post(
            '/api/payment/process/',
            data=json.dumps(data),
            content_type='application/json'
        )

        # API retorna 400 para link expirado (validação do serializer)
        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        # A resposta 400 contém o erro de validação da chave
        self.assertIn('chave', response_data)

        print("✅ Teste Link Expirado - PASSOU")

    @patch('payment.payment_views.ApiRecaptchaPaymentSerializer')
    @patch('payment.payment_cielo.CieloPaymentGateway.create_credit_payment')
    def test_link_ja_usado(self, mock_payment, mock_recaptcha_class):
        """
        Teste: Tentar usar link que já foi usado (pagamento aprovado)
        Esperado: Retorna status do pagamento anterior
        """
        # Primeiro pagamento
        mock_recaptcha_instance = MagicMock()
        mock_recaptcha_instance.is_valid.return_value = True
        mock_recaptcha_class.return_value = mock_recaptcha_instance
        mock_payment.return_value = self._mock_cielo_response(2, '6', 'Operation Successful')

        data = self.payment_data.copy()
        data['card_data'] = self._create_card_data('4024007197692930')

        # Primeira requisição
        response1 = self.client.post(
            '/api/payment/process/',
            data=json.dumps(data),
            content_type='application/json'
        )
        self.assertEqual(response1.status_code, 200)

        # Marcar link como usado
        self.checkout_link.usado = True
        self.checkout_link.save()

        # Segunda requisição (deve retornar status do primeiro pagamento)
        # Usar chave em base64 no endpoint
        response2 = self.client.get(f'/api/payment/validar-checkout-link/{self.chave_base64}/')
        
        self.assertEqual(response2.status_code, 200)
        response_data = response2.json()
        self.assertEqual(response_data['payment_status'], 'approved')

        print("✅ Teste Link Já Usado - PASSOU")
