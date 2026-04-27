import random
import string
from django.db import models
from django.utils import timezone
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from auditlog.registry import auditlog
from Pedidos.models import Pedido


class CheckoutLink(models.Model):
    """
    Cria link de pagamento para um produto específico
    """
    # Pedido relacionado (pode ser null se o link for criado sem associação direta, ex: links parciais para feira)
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, null=True, related_name="checkout_pedido")
    
    # Chave única do link (usada para validação e acesso)
    chave = models.CharField(max_length=100, unique=True, db_index=True)
    
    # Valor total do link em centavos (calculado a partir do pedido e produtos)
    valor_total = models.BigIntegerField(default=0, help_text="Valor em centavos (calculado a partir dos produtos)")
    
    # Campo para valor customizado (links parciais)
    valor_customizado = models.BigIntegerField(
        null=True,
        blank=True,
        default=None,
        help_text="Valor customizado em centavos (para links parciais). \
              Se preenchido, sobrescreve cálculo automático"
    )
    
    # Controle de parcelas específico do link (sobrescreve max_parcelas dos produtos)
    max_parcelas = models.IntegerField(
        null=True, 
        blank=True, 
        default=None,
        help_text="Máximo de parcelas permitidas para este link \
                (sobrescreve configuração dos produtos)"
    )
    
    # Criado em timestamp
    criado_em = models.DateTimeField(auto_now_add=True)

    # Data de expiração do link (padrão: 24h após criação)
    expira_em = models.DateTimeField()
    
    # Controle de uso
    usado = models.BooleanField(default=False)

    # Controle de cancelamento (links cancelados não podem ser usados e não são considerados no cálculo de valor)
    cancelado = models.BooleanField(default=False)
 
    def calcular_valor_total(self):
        """
        Calcula o valor total baseado no pedido
        
        Valor = (Preço dos Produtos - Descontos) - Pagamentos Já Feitos - Links Ativos
        """
        if self.pedido:
            preco_produtos = float(self.pedido.precoDosProdutos())
            descontos = float(self.pedido.descontosTotais() or 0)
            pagamentos_feitos = float(self.pedido.valor_pago() or 0)
            
            # Somar valores de links ativos com valor_customizado (excluindo o próprio link)
            links_ativos = CheckoutLink.objects.filter(
                pedido=self.pedido,
                usado=False,
                cancelado=False,
                valor_customizado__isnull=False
            )
            # Se estiver atualizando um link existente, excluir ele próprio do cálculo
            if self.pk:
                links_ativos = links_ativos.exclude(pk=self.pk)
            
            valor_links_ativos = sum(link.valor_customizado for link in links_ativos) / 100  # Converter de centavos
            
            valor_restante = preco_produtos - descontos - pagamentos_feitos - valor_links_ativos
            
            # Garantir que não seja negativo (já foi pago tudo ou mais)
            if valor_restante < 0:
                valor_restante = 0
            
            return int(valor_restante * 100)  # Converter para centavos
        return 0
    
    def save(self, *args, **kwargs):
        # Forçar recálculo se update_fields contém 'valor_total' ou se for criação
        force_recalculate = kwargs.pop('recalculate_valor', False)
        
        if not self.chave:
            self.chave = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
        if not self.expira_em:
            self.expira_em = timezone.now() + timezone.timedelta(hours=24)
        
        # REGRA: Links cancelados ou usados NÃO devem ter valor recalculado
        # Apenas links ativos podem ter o valor atualizado
        pode_recalcular = not self.usado and not self.cancelado
        
        # Se tem valor_customizado, usar ele. Caso contrário, calcular automaticamente
        if self.valor_customizado is not None:
            self.valor_total = self.valor_customizado
        elif self.pedido and pode_recalcular and (not self.pk or self.valor_total == 0 or force_recalculate):
            # Atualizar valor_total baseado no pedido
            # - Na criação (não tem pk)
            # - Se valor_total for 0
            # - Se forçar recálculo (via action do admin)
            # - SOMENTE se o link não estiver usado/cancelado
            self.valor_total = self.calcular_valor_total()
        
        # Invalidar links anteriores APENAS se origem != 'feira'
        # Para origem 'feira', permite múltiplos links ativos (pagamentos parciais)
        if self.pedido and self.pedido.origem != 'feira':
            CheckoutLink.objects.filter(
                pedido=self.pedido,
                usado=False,
                cancelado=False
            ).exclude(pk=self.pk if self.pk else None).update(cancelado=True)

        super().save(*args, **kwargs)

    def is_valid(self):
        """Verifica se o link ainda é válido"""
        if not self.expira_em:
            return False
        return not self.usado and not self.cancelado and timezone.now() < self.expira_em

    def validation_status(self):
        """Retorna motivo da invalidez"""
        if self.usado:
            return "Link já usado"
        if self.cancelado:
            return "Link cancelado"
        if not self.expira_em:
            return "Sem data de expiração"
        if timezone.now() > self.expira_em:
            return "Link expirado"
        return "Válido"

    def __str__(self):
        return self.chave

    class Meta:
        verbose_name = '01 - Link Pagamento (Checkout)'
        verbose_name_plural = '01 - Link Pagamento (Checkout)'
        ordering = ['-criado_em']
 

class PaymentTransaction(models.Model):

    STATUS_CHOICES = (
        ('pending', 'Pendente'),
        ('processing', 'Processando'),
        ('approved', 'Aprovado'),
        ('denied', 'Negado'),
        ('canceled', 'Cancelado'),
        ('refunded', 'Reembolsado'),
    )
    PAYMENT_METHOD_CHOICES = (
        ('credit_card', 'Cartão de Crédito'),
        ('debit_card', 'Cartão de Débito'),
        ('pix', 'PIX')
    )
    GATEWAY_CHOICES = (
        ('cielo', 'Cielo'),
    )

    # Link de Pagamento associado (pode ser null se for transação sem link, ex: Cielo Lio)
    checkout_link = models.ForeignKey(CheckoutLink, on_delete=models.PROTECT, related_name="transactions", null=True, blank=True)

    # Status atual da transação
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)

    # Método de pagamento utilizado (cartão, pix, etc)
    metodo_pagamento = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='credit_card', db_index=True)

    # Gateway utilizado para processar o pagamento (Cielo, etc)
    gateway_provider = models.CharField(max_length=20, choices=GATEWAY_CHOICES, default='cielo', help_text="Gateway de pagamento utilizado")
    
    # Data de criação da transação
    data_criacao = models.DateTimeField(auto_now_add=True)

    # Data de Pagamento (preenchida quando status for aprovado)
    data_pagamento = models.DateTimeField(null=True, blank=True, help_text="Data de aprovação do pagamento")
    
    # Valor original da transação (sem juros, em centavos)
    valor = models.BigIntegerField(help_text="Valor original da transação (sem juros, em centavos)")

    # Número de parcelas (1 = à vista)
    installments = models.IntegerField(default=1, help_text="Número de parcelas (1 = à vista)")

    # Valor total da transação com juros (em centavos). Para pagamentos à vista, deve ser igual ao campo 'valor'
    valor_com_juros = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Valor total com juros (quando parcelado)")
    
    # ID da transação retornado pelo gateway (ex: Cielo Transaction ID)
    transaction_id = models.CharField(max_length=100, blank=True, null=True, unique=True, db_index=True)

    # ID do pedido relacionado (para facilitar consultas, mesmo que o link seja cancelado)
    merchant_order_id = models.CharField(max_length=100, blank=True, null=True)

    # Response completo retornado pelo gateway (para auditoria e diagnóstico)
    payment_response = models.JSONField(blank=True, null=True)

    # Erros e falhas 
    error_message = models.TextField(blank=True, null=True, help_text="Mensagem de erro em caso de falha")

    # Ultima atualização (útil para rastrear mudanças de status)
    last_update = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if self.status == 'approved' and not self.data_pagamento:
            self.data_pagamento = timezone.now()

        super().save(*args, **kwargs)

        # Marca checkout como usado (só se ainda não estiver)
        if self.status == 'approved' and not self.checkout_link.usado:
            CheckoutLink.objects.filter(pk=self.checkout_link.pk).update(usado=True)

    def __str__(self):
        if self.installments > 1:
            return f"Transaction {self.id} - {self.status} \
                - {self.installments}x R$ {self.valor_com_juros/self.installments:.2f} \
                      (Total: R$ {self.valor_com_juros:.2f})"
        return f"Transaction {self.id} - {self.status} - R$ {self.valor/100:.2f}"

    class Meta:
        verbose_name = '02 - Transação de Pagamento'
        verbose_name_plural = '02 - Transações de Pagamento'
        ordering = ['-data_criacao']  


class PaymentAttempt(models.Model):

    # Relacionamento com PaymentTransaction (permite múltiplas tentativas por transação)
    transaction = models.ForeignKey(PaymentTransaction, on_delete=models.CASCADE, related_name="attempts")

    attempted_at = models.DateTimeField(auto_now_add=True)

    status = models.CharField(max_length=20)

    response_data = models.JSONField(blank=True, null=True)

    error_code = models.CharField(max_length=50, blank=True, null=True)

    error_message = models.TextField(blank=True, null=True)
    
    # ===== CAMPOS 3DS AUTHENTICATION =====
    # Rastreia se foi tentativa com 3DS
    three_ds_attempted = models.BooleanField(default=False, db_index=True,help_text="Indica se houve tentativa de autenticação 3DS")
    
    # Status da autenticação 3DS
    three_ds_status = models.CharField(
        max_length=30, 
        blank=True, 
        null=True,
        db_index=True,
        choices=[
            ('script_ready', 'Script Carregado'),
            ('auth_success', 'Autenticação Bem-sucedida'),
            ('auth_failure', 'Autenticação Falhou'),
            ('not_enrolled', 'Cartão Sem 3DS'),
            ('disabled', '3DS Desabilitado'),
            ('error', 'Erro no Processo'),
            ('unsupported_brand', 'Bandeira Não Suportada'),
        ],
        help_text="Status final da autenticação 3DS"
    )
    
    # Dados retornados pelo 3DS
    three_ds_cavv = models.CharField(max_length=100, blank=True, null=True, help_text="CAVV - Cardholder Authentication Verification Value"
                                     )
    three_ds_xid = models.CharField(max_length=100, blank=True, null=True, help_text="XID - Transaction Identifier")

    three_ds_eci = models.CharField(max_length=5, blank=True, null=True, db_index=True, help_text="ECI - Electronic Commerce Indicator (05=sucesso, 06=tentou, 07=sem autenticação)")

    three_ds_version = models.CharField(max_length=10, blank=True, null=True, help_text="Versão do protocolo 3DS usado")

    three_ds_reference_id = models.CharField(max_length=100, blank=True, null=True, db_index=True, help_text="ID de referência da transação 3DS na Braspag")
    
    # Informações adicionais
    three_ds_return_code = models.CharField(max_length=50, blank=True, null=True, help_text="Código de retorno do MPI")

    three_ds_return_message = models.TextField(blank=True, null=True, help_text="Mensagem de retorno do MPI")
    
    # Payload completo do 3DS (para auditoria)
    three_ds_payload = models.JSONField(blank=True, null=True, help_text="Payload completo retornado pelo script 3DS")
    
    # Timestamp de quando o 3DS foi concluído
    three_ds_completed_at = models.DateTimeField(blank=True, null=True, help_text="Momento em que a autenticação 3DS foi concluída")

    def __str__(self):
        three_ds_info = ""
        if self.three_ds_attempted:
            three_ds_info = f" [3DS: {self.three_ds_status or 'N/A'}]"
        return f"Attempt {self.id} - {self.status}{three_ds_info} - {self.attempted_at}"
    
    def get_three_ds_summary(self):
        """Retorna resumo legível da autenticação 3DS"""
        if not self.three_ds_attempted:
            return "Sem 3DS"
        
        status_map = {
            'auth_success': 'Autenticado',
            'auth_failure': 'Falhou',
            'not_enrolled': 'Sem 3DS',
            'error': 'Erro',
            'disabled': 'Desabilitado',
            'unsupported_brand': 'Não Suportado',
        }
        
        status_text = status_map.get(self.three_ds_status, self.three_ds_status or 'Desconhecido')
        eci_text = f" ECI:{self.three_ds_eci}" if self.three_ds_eci else ""
        
        return f"{status_text}{eci_text}"

    class Meta:
        verbose_name = '03 - Tentativa de Pagamento (Histórico)'
        verbose_name_plural = '03 - Tentativas de Pagamento (Histórico)'
        ordering = ['-attempted_at']
        indexes = [
            models.Index(fields=['-attempted_at', 'three_ds_attempted']),
            models.Index(fields=['three_ds_status', 'three_ds_eci']),
        ]


class PaymentWebhook(models.Model):
    # Relacionamento opcional com transação (nem todos os webhooks terão uma transação associada, ex: notificações de estorno ou chargeback)
    transaction = models.ForeignKey(PaymentTransaction, on_delete=models.SET_NULL, null=True, blank=True, related_name="webhooks")
    
    # Timestamp de recebimento do webhook
    received_at = models.DateTimeField(auto_now_add=True)

    # Tipo do evento (ex: payment_approved, payment_denied, chargeback, refund, etc)
    event_type = models.CharField(max_length=50, db_index=True)

    # Payload completo do webhook (para auditoria e diagnóstico)
    payload = models.JSONField(help_text="Payload completo do webhook")

    # Indica se o webhook já foi processado (para evitar processamento duplicado)
    processed = models.BooleanField(default=False, db_index=True, help_text="Indica se o webhook foi processado")

    # Mensagem de erro caso o processamento do webhook falhe (útil para diagnóstico)
    processing_error = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Webhook {self.id} - {self.event_type} - {self.received_at}"

    class Meta:
        verbose_name = '04 - Webhook de Pagamento'
        verbose_name_plural = '04 - Webhooks de Pagamento'
        ordering = ['-received_at']

# Signal para atualizar valor_total do CheckoutLink quando produtos do pedido mudarem
@receiver(post_save, sender='Pedidos.Pedido')
@receiver(post_delete, sender='Pedidos.Pedido')
def atualizar_checkout_link_valor(sender, instance, **kwargs):
    """
    Atualiza o valor_total do CheckoutLink ativo quando produtos do pedido mudarem
    """
    if instance:
        # Buscar CheckoutLinks ativos (não usados e não expirados) deste pedido
        checkouts_ativos = CheckoutLink.objects.filter(
            pedido=instance,
            usado=False,
            cancelado=False,
            expira_em__gt=timezone.now()
        )
        
        # Recalcular valor de cada checkout ativo
        for checkout in checkouts_ativos:
            checkout.save(recalculate_valor=True)
            print(f"CheckoutLink {checkout.chave} atualizado: R$ {checkout.valor_total/100:.2f}")



class PaymentCieloLio(models.Model):
    """
    Modelo para armazenar informações de comunicação via DeepLink com Cielo Lio.
    Cada registro representa uma interação (request ou response) com a maquininha.
    """

    TYPE_CHOICES = (
        ('request', 'Request - Enviado para Cielo'),
        ('response', 'Response - Recebido da Cielo'),
    )

    # Relacionamentos
    pedido = models.ForeignKey(Pedido, on_delete=models.PROTECT, related_name="cielo_lio_payments",help_text="Pedido relacionado ao pagamento")

    # Tipo de registro (request ou response)
    tipo = models.CharField(max_length=20, choices=TYPE_CHOICES, db_index=True, help_text="Indica se é um request enviado ou response recebido")

    # Payload completo (JSON enviado ou recebido)
    payload = models.JSONField(help_text="Payload completo JSON (request ou response)")
    response_api = models.JSONField(blank=True, null=True, help_text="Payload completo JSON retornado pela API Cielo (se aplicável)")

    # Campos comuns extraídos do payload
    reference = models.CharField(max_length=100, db_index=True, help_text="Referência do pedido/transação")
    value = models.BigIntegerField(help_text="Valor em centavos")
    installments = models.IntegerField(default=1, help_text="Número de parcelas")

    # Campos específicos (preenchidos conforme o tipo)
    payment_code = models.CharField(max_length=100, blank=True, null=True, help_text="Código de pagamento (ex: CREDITO_PARCELADO_LOJA) - apenas request")
    transaction_id = models.CharField(max_length=100, blank=True, null=True,db_index=True, help_text="ID da transação Cielo - apenas response")
    merchant_order_id = models.CharField(max_length=100, blank=True, null=True, help_text="ID MerchantOrderID - apenas response")
    payment_id = models.CharField(max_length=100, blank=True, null=True, db_index=True, help_text="ID do pagamento - apenas response")
    auth_code = models.CharField(max_length=100, blank=True, null=True, help_text="Código de autorização - apenas response")
    cielo_code = models.CharField(max_length=100, blank=True, null=True, help_text="Código Cielo - apenas response")
    merchant_code = models.CharField(max_length=100, blank=True, null=True, help_text="Código do estabelecimento - apenas response")
    product_name = models.CharField(max_length=200, blank=True, null=True, help_text="Nome do produto/método de pagamento - apenas response")
    
    # Status e controle
    #status = models.CharField(max_length=50, default='pending', db_index=True, help_text="Status da transação (pending, approved, denied, error)")
    error_message = models.TextField(blank=True, null=True, help_text="Mensagem de erro caso a transação falhe")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        tipo_display = "REQ" if self.tipo == 'request' else "RESP"
        reference = self.reference or "N/A"
        amount = f"R$ {self.value/100:.2f}" if self.value else "R$ 0.00"
        return f"{tipo_display} Pedido {reference} - {amount}"

    class Meta:
        verbose_name = '05 - Pagamento CieloLio (Maquininha)'
        verbose_name_plural = '05 - Pagamentos CieloLio (Maquininha)'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at', 'tipo']),
            models.Index(fields=['reference']),
            models.Index(fields=['transaction_id']),
            models.Index(fields=['payment_id']),
        ]



# Registro dos modelos no auditlog para rastreamento de alterações
auditlog.register(CheckoutLink)
auditlog.register(PaymentTransaction)
auditlog.register(PaymentAttempt)
auditlog.register(PaymentWebhook)
auditlog.register(PaymentCieloLio) 