from rest_framework import serializers
from .models import PaymentTransaction, CheckoutLink, PaymentCieloLio, PaymentAttempt, PaymentWebhook
from Pedidos.models import Pedido, ProdutoDoPedido, TipoDeVenda, CalculationType
from drf_recaptcha.fields import ReCaptchaV3Field
from Pedidos.serializers import ClientDataSerializer, AddressSerializer
from produtos.serializers import ProdutoSerializer, ComboSerializer


class ApiRecaptchaPaymentSerializer(serializers.Serializer):
    """
    Validação do recaptcha
    """
    # campo de validação do recaptcha, para coisas miuto importamtes, talvez aumentar
    # o score para 0.8
    recaptcha = ReCaptchaV3Field(action="VerifyPayment", required_score=0.6)



# CHECKOUT 
class ProdutoCheckoutSerializer(serializers.ModelSerializer):
    """
    Serializer customizado para produtos no checkout
    Expande dados do produto e combo
    """
    produto = ProdutoSerializer(read_only=True)
    combo_choice = ComboSerializer(read_only=True)
    
    class Meta:
        model = ProdutoDoPedido
        fields = ['id', 'produto', 'quantidade', 'combo_choice', 'tipo_de_venda']


class PedidoCheckoutSerializer(serializers.ModelSerializer):
    """
    Serializer customizado para pedido no checkout
    Filtra apenas produtos com tipo_de_venda = 'vendas'
    """
    comprador = ClientDataSerializer(read_only=True)
    endereco_fatura = AddressSerializer(read_only=True)
    produtos = serializers.SerializerMethodField()
    
    class Meta:
        model = Pedido
        fields = ['id', 'comprador', 'produtos', 'endereco_fatura', 'origem']
    
    def get_produtos(self, obj):
        """Retorna apenas produtos com tipo_de_venda = 'vendas'"""
        produtos_vendas = obj.produtos.filter(tipo_de_venda=TipoDeVenda.vendas)
        return ProdutoCheckoutSerializer(produtos_vendas, many=True).data


class CheckoutLinkSerializer(serializers.ModelSerializer):
    """
    Serializer para CheckoutLink com dados simplificados do pedido
    """
    pedido = PedidoCheckoutSerializer(read_only=True)
    valor_formatado = serializers.SerializerMethodField()
    valor_descontos = serializers.SerializerMethodField()
    valor_ja_pago = serializers.SerializerMethodField()
    is_valid_status = serializers.SerializerMethodField()
    validation_message = serializers.SerializerMethodField()
    
    class Meta:
        model = CheckoutLink
        fields = [
            'id', 
            'chave', 
            'pedido', 
            'valor_total', 
            'valor_formatado', 
            'valor_descontos', 
            'valor_ja_pago', 
            'criado_em', 
            'expira_em',
            'usado', 
            'cancelado', 
            'is_valid_status', 
            'validation_message', 
            'max_parcelas'
        ]
        read_only_fields = ['chave', 'valor_total', 'criado_em', 'usado']
    
    def get_valor_formatado(self, obj):
        if obj.valor_total is None:
            return "R$ 0,00"
        return f"R$ {obj.valor_total / 100:.2f}"
    
    def get_valor_descontos(self, obj):
        """Retorna valor dos descontos em centavos"""
        if obj.pedido:
            descontos = obj.pedido.descontosTotais()
            if descontos:
                return int(descontos * 100)
        return 0
    
    def get_valor_ja_pago(self, obj):
        """Retorna valor já pago em pagamentos anteriores (em centavos)"""
        if obj.pedido:
            valor_pago = obj.pedido.valor_pago()
            if valor_pago:
                return int(valor_pago * 100)
        return 0
        return 0
    
    def get_is_valid_status(self, obj):
        return obj.is_valid()
    
    def get_validation_message(self, obj):
        return obj.validation_status()



## PAYMENT
class CreditCardSerializer(serializers.Serializer):
    """
    Serializer Cartão de Crédito
    """
    card_number = serializers.CharField(max_length=16)
    cardholder_name = serializers.CharField(max_length=100)
    expiration_month = serializers.CharField(max_length=2)
    expiration_year = serializers.CharField(max_length=2)
    security_code = serializers.CharField(max_length=4)
    brand = serializers.CharField(max_length=20, required=False)  # Opcional, pode ser detectado
    installments = serializers.IntegerField(default=1, min_value=1, max_value=24)  # Quantidade de parcelas
    interest = serializers.CharField(default='ByMerchant')  # Tipo de juros: ByMerchant ou ByIssuer
    valor_com_juros = serializers.DecimalField(max_digits=11, decimal_places=2, required=False, allow_null=True)  # Valor total com juros em CENTAVOS (ex: 1220774.00 = R$ 12.207,74)


class ClienteSerializer(serializers.Serializer):
    """
    Serializer Cliente
    """
    name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    # cpf é utilizado para CPF e CNPJ
    cpf = serializers.CharField(max_length=200, required=False, allow_null=True, allow_blank=True)
    telefone = serializers.CharField(max_length=20, required=False, allow_null=True, allow_blank=True)


class EnderecoSerializer(serializers.Serializer):
    """
    Serializer Endereço
    """
    postal_code = serializers.CharField(max_length=20, required=False, allow_blank=True)
    street = serializers.CharField(max_length=255, required=False, allow_blank=True)
    number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    complement = serializers.CharField(max_length=255, required=False, allow_blank=True)
    district = serializers.CharField(max_length=100, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    state = serializers.CharField(max_length=2, required=False, allow_blank=True)
    country = serializers.CharField(max_length=100, default='Brasil')


class PaymentRequestSerializer(serializers.Serializer):
    """
    Serializer para processar pagamento via link de checkout
    """
    chave = serializers.CharField(help_text="Chave do CheckoutLink")
    
    # Dados do cliente vindos do frontend (podem estar atualizados em relação ao pedido) 
    cliente_data = ClienteSerializer(required=False)  
    billing_address = EnderecoSerializer(required=False)
    metodo_pagamento = serializers.ChoiceField(choices=PaymentTransaction.PAYMENT_METHOD_CHOICES)
    gateway_provider = serializers.ChoiceField(choices=PaymentTransaction.GATEWAY_CHOICES, default='cielo')
    card_data = CreditCardSerializer(required=False)
    
    # Campos opcionais de cálculo de parcelamento
    tipo_calculo_parcelamento = serializers.ChoiceField(choices=CalculationType.choices, required=False, allow_null=True )
    valor_principal_solicitado_cents = serializers.IntegerField(required=False, min_value=0)
    valor_acessorio_solicitado_cents = serializers.IntegerField(required=False, min_value=0)
    valor_principal_com_juros_cents = serializers.IntegerField(required=False, min_value=0)
    total_cobrado_cents = serializers.IntegerField(required=False, min_value=0)
    
    def validate_chave(self, value):
        """Valida se o CheckoutLink existe e está válido"""
        from django.utils.http import urlsafe_base64_decode
        try:
            # Decodifica a chave base64
            decoded_chave = str(urlsafe_base64_decode(value), 'utf-8')
            checkout = CheckoutLink.objects.get(chave=decoded_chave)
            if not checkout.is_valid():
                raise serializers.ValidationError(f"Link inválido: {checkout.validation_status()}")
            return value
        except CheckoutLink.DoesNotExist:
            raise serializers.ValidationError("Link de pagamento não encontrado")
    
    # ⚠️ COMENTADO: cliente_data agora é opcional (dados vêm do pedido)
    # def validate_cliente_data(self, value):
    #     """Valida dados do cliente"""
    #     email = value.get('email')
    #     if not email:
    #         raise serializers.ValidationError("Email é obrigatório")
    #     return value
    
    def validate(self, data):
        """Validação customizada"""
        metodo_pagamento = data.get('metodo_pagamento')
        card_data = data.get('card_data')
        
        # Se for cartão de crédito/débito, card_data é obrigatório
        if metodo_pagamento in ['credit_card', 'debit_card'] and not card_data:
            raise serializers.ValidationError({
                'card_data': 'Dados do cartão são obrigatórios para pagamento com cartão.'
            })
        
        # Se for PIX, card_data não é necessário
        if metodo_pagamento == 'pix' and card_data:
            data.pop('card_data', None)
        
        return data

 
class PaymentTransactionSerializer(serializers.ModelSerializer):
    """
    Serializer para transação de pagamento com contexto completo (pedido, feira, origem, comprador)
    """
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    metodo_pagamento_display = serializers.CharField(source='get_metodo_pagamento_display', read_only=True)
    gateway_provider_display = serializers.CharField(source='get_gateway_provider_display', read_only=True)
    
    # Informações do pedido
    pedido_id = serializers.SerializerMethodField()
    feira = serializers.SerializerMethodField()
    origem = serializers.SerializerMethodField()
    
    # Informações do comprador
    comprador = serializers.SerializerMethodField()
    
    valor_formatado = serializers.SerializerMethodField()
    
    class Meta:
        model = PaymentTransaction
        fields = [
            'id', 
            'checkout_link', 
            'pedido_id', 
            'feira', 
            'origem', 
            'comprador',
            'status', 
            'status_display', 
            'metodo_pagamento', 
            'metodo_pagamento_display', 
            'gateway_provider', 
            'gateway_provider_display',
            'data_criacao', 
            'data_pagamento', 
            'valor', 
            'valor_formatado', 
            'installments', 
            'valor_com_juros',
            'transaction_id', 
            'merchant_order_id',
            'error_message', 
            'last_update'
        ]
        read_only_fields = [
            'id', 
            'status', 
            'data_criacao', 
            'data_pagamento', 
            'transaction_id', 
            'merchant_order_id', 
            'last_update'
        ]
    
    def get_pedido_id(self, obj):
        """Retorna o ID do pedido"""
        if obj.checkout_link and obj.checkout_link.pedido:
            return obj.checkout_link.pedido.id
        return None
    
    def get_feira(self, obj):
        """Retorna o nome da feira"""
        if obj.checkout_link and obj.checkout_link.pedido and obj.checkout_link.pedido.feira:
            return obj.checkout_link.pedido.feira.nome
        return None
    
    def get_origem(self, obj):
        """Retorna a origem do pedido (feira, ecommerce, catalogo)"""
        if obj.checkout_link and obj.checkout_link.pedido:
            return obj.checkout_link.pedido.get_origem_display()
        return None
    
    def get_comprador(self, obj):
        """Retorna o nome do comprador"""
        if obj.checkout_link and obj.checkout_link.pedido and obj.checkout_link.pedido.comprador:
            nome = obj.checkout_link.pedido.comprador.name
            # Trunca se for muito longo
            if len(nome) > 50:
                return f"{nome[:47]}..."
            return nome
        return None
    
    def get_valor_formatado(self, obj):
        """Retorna o valor formatado em reais"""
        if obj.valor is None:
            return "R$ 0,00"
        return f"R$ {obj.valor / 100:.2f}"


class PaymentAttemptSerializer(serializers.ModelSerializer):
    """
    Serializer para tentativas de pagamento (histórico de attempts) - listagem
    """
    three_ds_summary = serializers.CharField(source='get_three_ds_summary', read_only=True)
    
    class Meta:
        model = PaymentAttempt
        fields = [
            'id', 
            'attempted_at', 
            'status', 
            'response_data', 
            'error_code', 
            'error_message',
            'three_ds_attempted', 
            'three_ds_status', 
            'three_ds_summary',
            'three_ds_eci', 
            'three_ds_version', 
            'three_ds_reference_id',
            'three_ds_return_code', 
            'three_ds_return_message',
            'three_ds_payload', 
            'three_ds_completed_at'
        ]


class PaymentAttemptDetailSerializer(serializers.ModelSerializer):
    """
    Serializer detalhado para visualização completa de uma tentativa de pagamento
    Inclui informações da transação relacionada
    """
    three_ds_summary = serializers.CharField(source='get_three_ds_summary', read_only=True)
    
    # Informações da transação relacionada
    transaction_info = serializers.SerializerMethodField()
    
    class Meta:
        model = PaymentAttempt
        fields = [
            'id', 
            'transaction', 
            'transaction_info',
            'attempted_at', 
            'status', 
            'response_data', 
            'error_code', 
            'error_message',
            'three_ds_attempted', 
            'three_ds_status', 
            'three_ds_summary',
            'three_ds_eci', 
            'three_ds_version', 
            'three_ds_reference_id',
            'three_ds_cavv', 
            'three_ds_xid',
            'three_ds_return_code', 
            'three_ds_return_message',
            'three_ds_payload', 
            'three_ds_completed_at'
        ]
    
    def get_transaction_info(self, obj):
        """Retorna informações resumidas da transação"""
        if obj.transaction:
            return {
                'id': obj.transaction.id,
                'status': obj.transaction.status,
                'status_display': obj.transaction.get_status_display(),
                'valor': obj.transaction.valor,
                'valor_formatado': f"R$ {obj.transaction.valor / 100:.2f}",
                'installments': obj.transaction.installments,
                'valor_com_juros': float(obj.transaction.valor_com_juros) if obj.transaction.valor_com_juros else None,
                'metodo_pagamento_display': obj.transaction.get_metodo_pagamento_display(),
                'transaction_id': obj.transaction.transaction_id,
            }
        return None


class PaymentWebhookListSerializer(serializers.ModelSerializer):
    """
    Serializer para listagem de webhooks de pagamento
    """
    class Meta:
        model = PaymentWebhook
        fields = [
            'id', 
            'received_at', 
            'event_type', 
            'payload', 
            'processed', 
            'processing_error'
        ]


class PaymentWebhookDetailSerializer(serializers.ModelSerializer):
    """
    Serializer detalhado para visualização completa de um webhook
    Inclui informações da transação relacionada
    """
    # Informações da transação relacionada
    transaction_info = serializers.SerializerMethodField()
    
    class Meta:
        model = PaymentWebhook
        fields = [
            'id', 
            'transaction', 
            'transaction_info',
            'received_at',
            'event_type',
            'payload', 
            'processed', 
            'processing_error'
        ]
    
    def get_transaction_info(self, obj):
        """Retorna informações resumidas da transação"""
        if obj.transaction:
            return {
                'id': obj.transaction.id,
                'status': obj.transaction.status,
                'status_display': obj.transaction.get_status_display(),
                'valor': obj.transaction.valor,
                'valor_formatado': f"R$ {obj.transaction.valor / 100:.2f}",
                'installments': obj.transaction.installments,
                'metodo_pagamento_display': obj.transaction.get_metodo_pagamento_display(),
                'transaction_id': obj.transaction.transaction_id,
            }
        return None


class PaymentTransactionDetailSerializer(serializers.ModelSerializer):
    """
    Serializer detalhado para visualização completa de uma transação
    Inclui attempts e webhooks relacionados
    """
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    metodo_pagamento_display = serializers.CharField(source='get_metodo_pagamento_display', read_only=True)
    gateway_provider_display = serializers.CharField(source='get_gateway_provider_display', read_only=True)
    
    # Informações do pedido
    pedido_id = serializers.SerializerMethodField()
    feira = serializers.SerializerMethodField()
    origem = serializers.SerializerMethodField()
    comprador = serializers.SerializerMethodField()
    
    valor_formatado = serializers.SerializerMethodField()
    
    # Relacionamentos nested
    attempts = PaymentAttemptSerializer(many=True, read_only=True)
    webhooks = PaymentWebhookListSerializer(many=True, read_only=True)
    
    class Meta:
        model = PaymentTransaction
        fields = [
            'id', 
            'checkout_link',
            'pedido_id', 
            'feira', 
            'origem', 
            'comprador',
            'status', 
            'status_display',
            'metodo_pagamento', 
            'metodo_pagamento_display',
            'gateway_provider', 
            'gateway_provider_display',
            'data_criacao', 
            'data_pagamento',
            'valor', 
            'valor_formatado', 
            'installments', 
            'valor_com_juros',
            'transaction_id', 
            'payment_response', 
            'error_message',
            'last_update',
            'attempts', 
            'webhooks'
        ]
    
    def get_pedido_id(self, obj):
        if obj.checkout_link and obj.checkout_link.pedido:
            return obj.checkout_link.pedido.id
        return None
    
    def get_feira(self, obj):
        if obj.checkout_link and obj.checkout_link.pedido and obj.checkout_link.pedido.feira:
            return obj.checkout_link.pedido.feira.nome
        return None
    
    def get_origem(self, obj):
        if obj.checkout_link and obj.checkout_link.pedido:
            return obj.checkout_link.pedido.get_origem_display()
        return None
    
    def get_comprador(self, obj):
        if obj.checkout_link and obj.checkout_link.pedido and obj.checkout_link.pedido.comprador:
            return obj.checkout_link.pedido.comprador.name
        return None
    
    def get_valor_formatado(self, obj):
        if obj.valor is None:
            return "R$ 0,00"
        return f"R$ {obj.valor / 100:.2f}"


class PaymentWebhookSerializer(serializers.Serializer):
    """
    Serializer para validação básica de webhooks de pagamento.
    
    Nota: O webhook da Cielo é processado diretamente com o payload completo
    e armazenado no modelo PaymentWebhook. Este serializer serve apenas para
    validação inicial dos campos essenciais.
    """
    payment_id = serializers.CharField()
    status = serializers.CharField()
    order_id = serializers.CharField()


class PaymentCieloLioSerializer(serializers.ModelSerializer):
    """
    Serializer para PaymentCieloLio
    """
    valor_formatado = serializers.SerializerMethodField()
    tipo_display = serializers.CharField(source='get_tipo_display', read_only=True)
    
    class Meta:
        model = PaymentCieloLio
        fields = [
            'id', 
            'pedido', 
            'tipo', 
            'tipo_display', 
            'reference', 
            'value', 
            'valor_formatado', 
            'installments', 
            'payload',
            'payment_code', 
            'transaction_id', 
            'payment_id', 
            'auth_code', 
            'cielo_code', 
            'merchant_code', 
            'product_name',
            'error_message', 
            'created_at', 
            'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_valor_formatado(self, obj):
        if obj.value is None:
            return "R$ 0,00"
        return f"R$ {obj.value / 100:.2f}"


class PaymentCieloLioCreateSerializer(serializers.ModelSerializer):
    """
    Serializer simplificado para criar registros de PaymentCieloLio
    Extrai automaticamente campos do payload
    """
    # Tornar campos opcionais para serem extraídos do payload
    reference = serializers.CharField(required=False, allow_blank=True)
    value = serializers.IntegerField(required=False)
    installments = serializers.IntegerField(required=False, default=1)
    payment_code = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    
    class Meta:
        model = PaymentCieloLio
        fields = [
            'pedido', 
            'tipo', 
            'payload', 
            'response_api', 
            'reference', 
            'value', 
            'installments', 
            'payment_code'
        ]
    
    def create(self, validated_data):
        payload = validated_data.get('payload', {})
        tipo = validated_data.get('tipo')
        
        # Extrair campos do payload baseado no tipo
        if tipo == 'request':
            # Campos do request - prioriza payload, depois validated_data
            if 'reference' not in validated_data or not validated_data['reference']:
                validated_data['reference'] = payload.get('reference', '')
            
            if 'value' not in validated_data:
                # Converter string para int se necessário
                value_from_payload = payload.get('value', 0)
                if isinstance(value_from_payload, str):
                    value_from_payload = int(value_from_payload)
                validated_data['value'] = value_from_payload
            
            if 'installments' not in validated_data:
                validated_data['installments'] = payload.get('installments', 1)
            
            if 'payment_code' not in validated_data or not validated_data.get('payment_code'):
                validated_data['payment_code'] = payload.get('paymentCode', '')
        
        elif tipo == 'response':
            # Campos do response
            if 'reference' not in validated_data or not validated_data['reference']:
                validated_data['reference'] = payload.get('reference', '')
            
            if 'value' not in validated_data:
                validated_data['value'] = payload.get('paidAmount', 0)
            
            if 'installments' not in validated_data:
                validated_data['installments'] = payload.get('installments', 1)
            
            validated_data['transaction_id'] = payload.get('id', '')
            
            # Extrair dados do primeiro pagamento (se existir)
            payments = payload.get('payments', [])
            if payments:
                first_payment = payments[0]
                validated_data['payment_id'] = first_payment.get('id', '')
                validated_data['auth_code'] = first_payment.get('authCode', '')
                validated_data['cielo_code'] = first_payment.get('cieloCode', '')
                validated_data['merchant_code'] = first_payment.get('merchantCode', '')
                
                # Extrair product_name do paymentFields
                payment_fields = first_payment.get('paymentFields', {})
                validated_data['product_name'] = payment_fields.get('productName', '')
        
        return super().create(validated_data)


