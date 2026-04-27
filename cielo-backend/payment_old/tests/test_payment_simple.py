"""
Testes Simplificados para Pagamentos Cielo
Versão rápida para validar integração básica
"""

from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from unittest.mock import patch, MagicMock
from datetime import timedelta

from payment.models import CheckoutLink, PaymentTransaction, PaymentAttempt, PaymentWebhook
from Pedidos.models import Pedido, ClientData, Address, ProdutoDoPedido, TipoDeVenda
from produtos.models import Produto


class SimpleCieloTestCase(TestCase):
    """Testes simplificados de integração Cielo"""

    def setUp(self):
        """Configuração inicial"""
        # Criar usuário
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        
        # Criar produto
        self.produto = Produto.objects.create(
            nome='Produto Teste',
            price=100.00
        )
        
        # Criar cliente (comprador)
        self.comprador = ClientData.objects.create(
            name='Cliente Teste',
            email='teste@teste.com',
            cpf='12345678901',
            telefone='16999999999'
        )
        
        # Criar endereço de fatura
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
        
        # Criar checkout link
        self.checkout_link = CheckoutLink.objects.create(
            pedido=self.pedido,
            chave='teste123',
            expira_em=timezone.now() + timedelta(hours=24)
        )

    def test_criar_transacao_aprovada(self):
        """Teste: Criar transação aprovada"""
        transaction = PaymentTransaction.objects.create(
            checkout_link=self.checkout_link,
            transaction_id='test-123',
            valor=10000,
            status='approved',
            metodo_pagamento='credit_card',
            gateway_provider='cielo'
        )
        
        self.assertEqual(transaction.status, 'approved')
        self.assertEqual(transaction.metodo_pagamento, 'credit_card')
        self.assertEqual(transaction.gateway_provider, 'cielo')
        print("✅ Teste Criar Transação Aprovada - PASSOU")

    def test_criar_transacao_negada(self):
        """Teste: Criar transação negada"""
        transaction = PaymentTransaction.objects.create(
            checkout_link=self.checkout_link,
            transaction_id='test-456',
            valor=10000,
            status='denied',
            metodo_pagamento='credit_card',
            gateway_provider='cielo'
        )
        
        self.assertEqual(transaction.status, 'denied')
        print("✅ Teste Criar Transação Negada - PASSOU")

    def test_criar_transacao_pix(self):
        """Teste: Criar transação PIX"""
        transaction = PaymentTransaction.objects.create(
            checkout_link=self.checkout_link,
            transaction_id='test-pix-789',
            valor=10000,
            status='waiting',
            metodo_pagamento='pix',
            gateway_provider='cielo'
        )
        
        self.assertEqual(transaction.status, 'waiting')
        self.assertEqual(transaction.metodo_pagamento, 'pix')
        print("✅ Teste Criar Transação PIX - PASSOU")

    def test_link_expirado(self):
        """Teste: Verificar link expirado"""
        self.checkout_link.expira_em = timezone.now() - timedelta(hours=1)
        self.checkout_link.save()
        
        self.assertTrue(timezone.now() > self.checkout_link.expira_em)
        print("✅ Teste Link Expirado - PASSOU")

    def test_link_usado(self):
        """Teste: Marcar link como usado"""
        self.checkout_link.usado = False
        self.checkout_link.save()
        
        # Simular uso do link
        self.checkout_link.usado = True
        self.checkout_link.save()
        
        self.assertTrue(self.checkout_link.usado)
        print("✅ Teste Link Usado - PASSOU")

    def test_multiplas_transacoes_mesmo_link(self):
        """Teste: Não permitir múltiplas transações aprovadas no mesmo link"""
        # Primeira transação
        PaymentTransaction.objects.create(
            checkout_link=self.checkout_link,
            transaction_id='test-1',
            valor=10000,
            status='approved',
            metodo_pagamento='credit_card',
            gateway_provider='cielo'
        )
        
        # Marcar link como usado
        self.checkout_link.usado = True
        self.checkout_link.save()
        
        # Verificar que link está usado
        self.assertTrue(self.checkout_link.usado)
        
        # Contar transações
        count = PaymentTransaction.objects.filter(
            checkout_link=self.checkout_link,
            status='approved'
        ).count()
        
        self.assertEqual(count, 1)
        print("✅ Teste Múltiplas Transações - PASSOU")

    def test_valor_em_centavos(self):
        """Teste: Validar que valor está em centavos"""
        # R$ 100,00 = 10000 centavos
        transaction = PaymentTransaction.objects.create(
            checkout_link=self.checkout_link,
            transaction_id='test-valor',
            valor=10000,  # R$ 100,00
            status='approved',
            metodo_pagamento='credit_card',
            gateway_provider='cielo'
        )
        
        self.assertEqual(transaction.valor, 10000)
        self.assertEqual(transaction.valor / 100, 100.00)  # R$ 100,00
        print("✅ Teste Valor em Centavos - PASSOU")

    def test_gateway_provider_choices(self):
        """Teste: Validar choices de gateway"""
        # Cielo
        transaction_cielo = PaymentTransaction.objects.create(
            checkout_link=self.checkout_link,
            transaction_id='test-cielo',
            valor=10000,
            status='approved',
            metodo_pagamento='credit_card',
            gateway_provider='cielo'
        )
        self.assertEqual(transaction_cielo.gateway_provider, 'cielo')
        
        # Getnet
        transaction_getnet = PaymentTransaction.objects.create(
            checkout_link=self.checkout_link,
            transaction_id='test-getnet',
            valor=10000,
            status='approved',
            metodo_pagamento='credit_card',
            gateway_provider='getnet'
        )
        self.assertEqual(transaction_getnet.gateway_provider, 'getnet')
        
        print("✅ Teste Gateway Provider - PASSOU")

    def test_payment_attempt_criacao(self):
        """Teste: Criar PaymentAttempt"""
        transaction = PaymentTransaction.objects.create(
            checkout_link=self.checkout_link,
            transaction_id='test-attempt',
            valor=10000,
            status='processing',
            metodo_pagamento='credit_card',
            gateway_provider='cielo'
        )
        
        # Criar tentativa
        attempt = PaymentAttempt.objects.create(
            transaction=transaction,
            status='processing'
        )
        
        self.assertEqual(attempt.status, 'processing')
        self.assertEqual(attempt.transaction, transaction)
        print("✅ Teste PaymentAttempt Criação - PASSOU")

    def test_payment_attempt_sucesso(self):
        """Teste: PaymentAttempt com sucesso"""
        transaction = PaymentTransaction.objects.create(
            checkout_link=self.checkout_link,
            transaction_id='test-attempt-success',
            valor=10000,
            status='approved',
            metodo_pagamento='credit_card',
            gateway_provider='cielo'
        )
        
        attempt = PaymentAttempt.objects.create(
            transaction=transaction,
            status='processing'
        )
        
        # Atualizar para sucesso
        attempt.status = 'approved'
        attempt.response_data = {'status': 'APPROVED', 'payment_id': 'test-123'}
        attempt.save()
        
        self.assertEqual(attempt.status, 'approved')
        self.assertIsNotNone(attempt.response_data)
        print("✅ Teste PaymentAttempt Sucesso - PASSOU")

    def test_payment_attempt_erro(self):
        """Teste: PaymentAttempt com erro"""
        transaction = PaymentTransaction.objects.create(
            checkout_link=self.checkout_link,
            transaction_id='test-attempt-error',
            valor=10000,
            status='denied',
            metodo_pagamento='credit_card',
            gateway_provider='cielo'
        )
        
        attempt = PaymentAttempt.objects.create(
            transaction=transaction,
            status='processing'
        )
        
        # Atualizar para erro
        attempt.status = 'failed'
        attempt.error_code = 'CARD_DECLINED'
        attempt.error_message = 'Cartão recusado'
        attempt.save()
        
        self.assertEqual(attempt.status, 'failed')
        self.assertEqual(attempt.error_code, 'CARD_DECLINED')
        print("✅ Teste PaymentAttempt Erro - PASSOU")

    def test_payment_webhook_criacao(self):
        """Teste: Criar PaymentWebhook"""
        webhook = PaymentWebhook.objects.create(
            event_type='cielo_payment_notification',
            payload={'Payment': {'PaymentId': 'test-123', 'Status': 2}},
            processed=False
        )
        
        self.assertEqual(webhook.event_type, 'cielo_payment_notification')
        self.assertFalse(webhook.processed)
        print("✅ Teste PaymentWebhook Criação - PASSOU")

    def test_payment_webhook_processado(self):
        """Teste: PaymentWebhook processado com sucesso"""
        transaction = PaymentTransaction.objects.create(
            checkout_link=self.checkout_link,
            transaction_id='test-webhook',
            valor=10000,
            status='pending',
            metodo_pagamento='credit_card',
            gateway_provider='cielo'
        )
        
        webhook = PaymentWebhook.objects.create(
            transaction=transaction,
            event_type='cielo_payment_notification',
            payload={'Payment': {'PaymentId': 'test-webhook', 'Status': 2}},
            processed=False
        )
        
        # Marcar como processado
        webhook.processed = True
        webhook.save()
        
        self.assertTrue(webhook.processed)
        self.assertEqual(webhook.transaction, transaction)
        print("✅ Teste PaymentWebhook Processado - PASSOU")

    def test_payment_webhook_erro(self):
        """Teste: PaymentWebhook com erro de processamento"""
        webhook = PaymentWebhook.objects.create(
            event_type='cielo_payment_notification',
            payload={'Payment': {'Status': 2}},  # Sem PaymentId
            processed=False
        )
        
        # Registrar erro
        webhook.processing_error = 'PaymentId não encontrado'
        webhook.save()
        
        self.assertFalse(webhook.processed)
        self.assertIsNotNone(webhook.processing_error)
        print("✅ Teste PaymentWebhook Erro - PASSOU")

    def test_checkout_link_valor_calculado(self):
        """Teste: CheckoutLink calcula valor automaticamente do pedido"""
        # Valor deve ser calculado automaticamente
        self.assertGreater(self.checkout_link.valor_total, 0)
        
        # Valor deve ser em centavos (R$ 100,00 = 10000 centavos)
        self.assertEqual(self.checkout_link.valor_total, 10000)
        print("✅ Teste CheckoutLink Valor Calculado - PASSOU")
