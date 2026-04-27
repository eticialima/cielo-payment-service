from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from .models import (
    CheckoutLink,
    PaymentCieloLio,
    PaymentTransaction,
    PaymentAttempt,
    PaymentWebhook
)


class PaymentTransactionInline(admin.StackedInline):
    model = PaymentTransaction
    extra = 0
    can_delete = False

    fields = (
        'link_objeto',
        'status',
        'metodo_pagamento',
        'valor',
        'installments',
        'valor_com_juros',
        'transaction_id',
        'merchant_order_id',
        'data_criacao',
        'data_pagamento',
    )

    readonly_fields = (
        'link_objeto',
        'data_criacao',
        'data_pagamento',
    )

    def link_objeto(self, obj):
        if not obj.pk:
            return "-"
        url = reverse(
            'admin:payment_paymenttransaction_change',
            args=[obj.pk]
        )
        return format_html(
            '<a ' \
            'class="button" ' \
            'href="{}" ' \
            'target="_blank" ' \
            'style="padding: 10px 15px; background-color: #417690; color: white; text-decoration: none; border-radius: 4px; display: inline-block;">' \
            'Ver Transição</a>',
            url)

    link_objeto.short_description = 'Detalhes'
    


@admin.register(CheckoutLink)
class CheckoutLinkAdmin(admin.ModelAdmin):
    list_display = (
        'chave',
        'pedido', 
        'get_feira',
        'get_origem',
        'get_valor_formatado',
        'max_parcelas',
        'get_cliente',
        'criado_em',
        'expira_em',
        'get_status_badge',
        'get_validation_status'
    )
    list_filter = ('usado', 'cancelado', 'criado_em', 'expira_em')
    search_fields = ('chave', 'pedido__id', 'pedido__comprador__name')
    autocomplete_fields = ['pedido']
    readonly_fields = (
        'chave',
        'valor_total',
        'get_valor_formatado',
        'criado_em',
        'get_validation_status',
        'get_link_url',
        'get_cliente',
        'get_endereco'
    )
    fieldsets = (
        ('Informações do Link', {
            'fields': ('chave', 'get_link_url', 'valor_total', 'get_valor_formatado', 'max_parcelas')
        }),
        ('Pedido', {
            'fields': ('pedido', 'get_cliente', 'get_endereco')
        }),
        ('Datas', {
            'fields': ('criado_em', 'expira_em')
        }),
        ('Status', {
            'fields': ('usado', 'cancelado', 'get_validation_status')
        }),
    )
    inlines = [PaymentTransactionInline]
    actions = ['recalcular_valor_total']
    date_hierarchy = 'criado_em'
    
    @admin.action(description='Recalcular valor total dos links selecionados')
    def recalcular_valor_total(self, request, queryset):
        """Recalcula o valor_total baseado nos produtos do pedido"""
        count = 0
        for checkout in queryset:
            if checkout.pedido:
                checkout.save(recalculate_valor=True)
                count += 1
        
        self.message_user(
            request,
            f'{count} link(s) de pagamento tiveram o valor recalculado com sucesso.'
        )
    recalcular_valor_total.short_description = 'Recalcular valor total'
    
    def get_valor_formatado(self, obj):
        """
        Mostra o valor do link
        - Se usado/cancelado: mostra valor_total histórico (congelado)
        - Se ativo: mostra valor_total atual do banco
        """
        # Sempre mostrar o valor_total salvo no banco (é o valor histórico correto)
        if obj.valor_total is not None:
            return f"R$ {obj.valor_total / 100:.2f}"
        return "R$ 0,00"
    get_valor_formatado.short_description = 'Valor do Link'
    
    def get_cliente(self, obj):
        if obj.pedido and obj.pedido.comprador:
            return obj.pedido.comprador.name
        return "-"
    get_cliente.short_description = 'Comprador'
    
    def get_endereco(self, obj):
        if obj.pedido and obj.pedido.endereco_entrega:
            end = obj.pedido.endereco_entrega
            return f"{end.rua}, {end.numero} - {end.cidade}"
        return "-"
    get_endereco.short_description = 'Endereço'
    
    def get_status_badge(self, obj):
        if obj.usado:
            color = 'green'
            text = 'USADO'
        elif obj.cancelado:
            color = 'red'
            text = 'CANCELADO'
        elif obj.is_valid():
            color = 'blue'
            text = 'ATIVO'
        else:
            color = 'orange'
            text = 'EXPIRADO'
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px; font-weight: bold;">{}</span>',
            color, text
        )
    get_status_badge.short_description = 'Status'
    
    def get_validation_status(self, obj):
        return obj.validation_status()
    get_validation_status.short_description = 'Validação'
    
    def get_link_url(self, obj):
        if obj.chave:
            from django.utils.http import urlsafe_base64_encode
            from django.utils.encoding import force_bytes
            
            # Codificar chave em base64
            chave_encoded = urlsafe_base64_encode(force_bytes(obj.chave))
            if isinstance(chave_encoded, bytes):
                chave_encoded = chave_encoded.decode()
            
            # Gerar URL completa
            url = f"https://d-m-c.group/pay?c={chave_encoded}"
            return format_html('<a href="{}" target="_blank">{}</a>', url, url)
        return "-"
    get_link_url.short_description = 'URL do Link'


    def get_feira(self, obj):
        if obj.pedido and obj.pedido.feira:
            return obj.pedido.feira
        return "-"
    get_feira.short_description = 'Feira'


    def get_origem(self, obj):
        if obj.pedido:
            return obj.pedido.origem
        return "-"
    get_origem.short_description = 'Origem do Pedido'

class PaymentAttemptInline(admin.TabularInline):
    model = PaymentAttempt
    extra = 0
    fields = ('attempted_at', 'status', 'get_3ds_badge', 'error_code', 'error_message')
    readonly_fields = ('attempted_at', 'get_3ds_badge')
    can_delete = False
    
    def get_3ds_badge(self, obj):
        if not obj.three_ds_attempted:
            return format_html('<span style="color: gray;">-</span>')
        
        colors = {
            'auth_success': 'green',
            'auth_failure': 'red',
            'not_enrolled': 'orange',
            'error': 'darkred',
            'disabled': 'gray',
            'script_ready': 'blue',
        }
        color = colors.get(obj.three_ds_status, 'gray')
        summary = obj.get_three_ds_summary()
        
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; border-radius: 3px; font-size: 11px;">{}</span>',
            color, summary
        )
    get_3ds_badge.short_description = '3DS'


class PaymentWebhookInline(admin.TabularInline):
    model = PaymentWebhook
    extra = 0
    fields = ('received_at', 'event_type', 'processed', 'processing_error')
    readonly_fields = ('received_at',)
    can_delete = False


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = (
        'checkout_link',
        'get_pedido',
        'get_feira',
        'get_status_badge',
        'metodo_pagamento',
        'get_valor_formatado',
        'get_parcelas_info', 
        'transaction_id',
        'merchant_order_id',
        'data_criacao',
        'data_pagamento'
    )
    list_filter = (
        'checkout_link__pedido__feira', 
        'checkout_link__pedido__origem', 
        'status', 
        'metodo_pagamento', 
        'gateway_provider', 
        'data_criacao'
        )
    
    search_fields = (
        'transaction_id', 
        'merchant_order_id',
        'checkout_link__chave', 
        'checkout_link__pedido__id', 
        'checkout_link__pedido__comprador__cpf',
        'checkout_link__pedido__comprador__name')
    
    readonly_fields = (
        'data_criacao',
        'data_pagamento',
        'last_update',
        'get_valor_formatado',
        'payment_response',
        'get_payment_response_preview'
    )
    
    fieldsets = (
        ('Link de Pagamento', {
            'fields': ('checkout_link',)
        }),
        ('Informações da Transação', {
            'fields': (
                'status',
                'metodo_pagamento',
                'gateway_provider',
                'valor',
                'get_valor_formatado',
                'installments',
                'valor_com_juros',
                'transaction_id',
                'merchant_order_id'
            )
        }),
        ('Datas', {
            'fields': ('data_criacao', 'data_pagamento', 'last_update')
        }),
        ('Resposta do Gateway', {
            'fields': ('get_payment_response_preview', 'payment_response', 'error_message'),
            'classes': ('collapse',)
        }),
    )
    
    inlines = [PaymentAttemptInline, PaymentWebhookInline]
    date_hierarchy = 'data_criacao'
    
    def get_pedido(self, obj):
        """Retorna o pedido relacionado ao checkout_link"""
        if obj.checkout_link and obj.checkout_link.pedido:
            pedido = obj.checkout_link.pedido 
            return format_html(
                '<a href="/admin/Pedidos/pedido/{}/change/">{}</a>',
                pedido.id,
                pedido.id
            )
        return "-"
    get_pedido.short_description = 'Pedido'
    
    def get_valor_formatado(self, obj):
        if obj.valor is None:
            return "R$ 0,00"
        return f"R$ {obj.valor / 100:.2f}"
    get_valor_formatado.short_description = 'Valor'
    
    def get_parcelas_info(self, obj):
        if obj.installments and obj.installments > 1:
            if obj.valor_com_juros:
                valor_parcela = float(obj.valor_com_juros) / obj.installments
                return format_html(
                    '<span style="color: #0066cc; font-weight: bold;">{} x R$ {}</span>',
                    obj.installments,
                    f"{valor_parcela:.2f}"
                )
            return f"{obj.installments}x"
        return "À vista"
    get_parcelas_info.short_description = 'Parcelas'
    
    def get_status_badge(self, obj):
        colors = {
            'pending': 'gray',
            'processing': 'blue',
            'approved': 'green',
            'denied': 'red',
            'canceled': 'orange',
            'refunded': 'purple',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px; font-weight: bold;">{}</span>',
            color, obj.get_status_display()
        )
    get_status_badge.short_description = 'Status'
    
    def get_payment_response_preview(self, obj):
        """Preview formatado do payment_response"""
        if not obj.payment_response:
            return format_html('<em style="color: #999;">Nenhuma resposta ainda</em>')
        
        import json
        try:
            formatted = json.dumps(obj.payment_response, indent=2, ensure_ascii=False)
            return format_html(
                '<pre style="background: #f5f5f5; padding: 15px; border-radius: 5px; '
                'border: 1px solid #ddd; max-height: 400px; overflow: auto; '
                'font-family: monospace; font-size: 12px; line-height: 1.5;">{}</pre>',
                formatted
            )
        except Exception as e:
            return format_html('<em style="color: #dc3545;">Erro ao formatar: {}</em>', str(e))
    get_payment_response_preview.short_description = 'Preview Response'

    def get_feira(self, obj):
        """Retorna a feira do pedido"""
        if obj.checkout_link and obj.checkout_link.pedido and obj.checkout_link.pedido.feira:
            feira = obj.checkout_link.pedido.feira
            return feira.nome
        return "-"
    get_feira.short_description = 'Feira'
    
    def get_origem(self, obj):
        """Retorna a origem do pedido (feira, ecommerce, catalogo)"""
        if obj.checkout_link and obj.checkout_link.pedido:
            return obj.checkout_link.pedido.get_origem_display()
        return "-"
    get_origem.short_description = 'Origem'
    
    def get_comprador(self, obj):
        """Retorna o nome do comprador"""
        if obj.checkout_link and obj.checkout_link.pedido and obj.checkout_link.pedido.comprador:
            comprador = obj.checkout_link.pedido.comprador
            return format_html(
                '<span title="{}">{}...</span>',
                comprador.name,
                comprador.name[:30] if len(comprador.name) > 30 else comprador.name
            )
        return "-"
    get_comprador.short_description = 'Comprador'


@admin.register(PaymentAttempt)
class PaymentAttemptAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'get_pedido',
        'get_feira',
        'status', 
        'get_3ds_badge',
        'three_ds_eci',
        'attempted_at'
    )
    list_filter = ( 
        'transaction__checkout_link__pedido__feira',
        'transaction__checkout_link__pedido__origem', 
        'status', 
        'three_ds_attempted',
        'three_ds_status',
        'three_ds_eci',
        'attempted_at'
    )
    search_fields = (
        'transaction__transaction_id',
        'transaction__merchant_order_id',
        'transaction__checkout_link__pedido__id',
        'transaction__checkout_link__pedido__comprador__name',
        'error_code', 
        'error_message',
        'three_ds_reference_id',
        'three_ds_return_code'
    )
    readonly_fields = (
        'attempted_at',
        'three_ds_completed_at',
        'get_3ds_summary_display',
        'response_data',
        'three_ds_payload',
        'get_response_data_preview',
        'get_three_ds_payload_preview'
    )
    
    fieldsets = (
        ('Transação', {
            'fields': ('transaction',)
        }),
        ('Tentativa', {
            'fields': ('attempted_at', 'status')
        }),
        ('Autenticação 3DS', {
            'fields': (
                'three_ds_attempted',
                'three_ds_status',
                'get_3ds_summary_display',
                'three_ds_eci',
                'three_ds_cavv',
                'three_ds_xid',
                'three_ds_version',
                'three_ds_reference_id',
                'three_ds_return_code',
                'three_ds_return_message',
                'three_ds_completed_at'
            )
        }),
        ('Erro', {
            'fields': ('error_code', 'error_message'),
            'classes': ('collapse',)
        }),
        ('Dados Completos', {
            'fields': ('get_response_data_preview', 'response_data', 'get_three_ds_payload_preview', 'three_ds_payload')
        }),
    )
    
    date_hierarchy = 'attempted_at'
    
    def get_3ds_badge(self, obj):
        if not obj.three_ds_attempted:
            return format_html('<span style="color: #999;">Sem 3DS</span>')
        
        colors = {
            'auth_success': '#28a745',
            'auth_failure': '#dc3545',
            'not_enrolled': '#ffc107',
            'error': '#721c24',
            'disabled': '#6c757d',
            'script_ready': '#007bff',
            'unsupported_brand': '#e83e8c',
        }
        color = colors.get(obj.three_ds_status, '#6c757d')
        summary = obj.get_three_ds_summary()
        
        return format_html(
            '<span style="background-color: {}; color: white; padding: 4px 12px; border-radius: 4px; font-weight: 500; display: inline-block;">{}</span>',
            color, summary
        )
    get_3ds_badge.short_description = 'Status 3DS'
    
    def get_3ds_summary_display(self, obj):
        if not obj.three_ds_attempted:
            return 'Sem autenticação 3DS'
        return obj.get_three_ds_summary()
    get_3ds_summary_display.short_description = 'Resumo 3DS'
    
    def get_response_data_preview(self, obj):
        """Preview formatado do response_data"""
        if not obj.response_data:
            return format_html('<em style="color: #999;">Nenhuma resposta ainda</em>')
        
        import json
        try:
            formatted = json.dumps(obj.response_data, indent=2, ensure_ascii=False)
            return format_html(
                '<pre style="background: #f5f5f5; padding: 15px; border-radius: 5px; '
                'border: 1px solid #ddd; max-height: 400px; overflow: auto; '
                'font-family: monospace; font-size: 12px; line-height: 1.5;">{}</pre>',
                formatted
            )
        except Exception as e:
            return format_html('<em style="color: #dc3545;">Erro ao formatar: {}</em>', str(e))
    get_response_data_preview.short_description = 'Preview Response Data'
    
    def get_three_ds_payload_preview(self, obj):
        """Preview formatado do three_ds_payload"""
        if not obj.three_ds_payload:
            return format_html('<em style="color: #999;">Nenhum payload 3DS</em>')
        
        import json
        try:
            formatted = json.dumps(obj.three_ds_payload, indent=2, ensure_ascii=False)
            return format_html(
                '<pre style="background: #f0f8ff; padding: 15px; border-radius: 5px; '
                'border: 1px solid #b3d9ff; max-height: 400px; overflow: auto; '
                'font-family: monospace; font-size: 12px; line-height: 1.5;">{}</pre>',
                formatted
            )
        except Exception as e:
            return format_html('<em style="color: #dc3545;">Erro ao formatar: {}</em>', str(e))
    get_three_ds_payload_preview.short_description = 'Preview 3DS Payload'
    
    def get_pedido(self, obj):
        """Retorna o pedido relacionado"""
        if obj.transaction and obj.transaction.checkout_link and obj.transaction.checkout_link.pedido:
            pedido = obj.transaction.checkout_link.pedido
            return format_html(
                '<a href="/admin/Pedidos/pedido/{}/change/">{}</a>',
                pedido.id,
                pedido.id
            )
        return "-"
    get_pedido.short_description = 'Pedido'
    
    def get_feira(self, obj):
        """Retorna a feira do pedido"""
        if obj.transaction and obj.transaction.checkout_link and obj.transaction.checkout_link.pedido:
            pedido = obj.transaction.checkout_link.pedido
            if pedido.feira:
                return pedido.feira.nome
        return "-"
    get_feira.short_description = 'Feira'
    
    def get_origem(self, obj):
        """Retorna a origem do pedido"""
        if obj.transaction and obj.transaction.checkout_link and obj.transaction.checkout_link.pedido:
            pedido = obj.transaction.checkout_link.pedido
            return pedido.get_origem_display()
        return "-"
    get_origem.short_description = 'Origem'
    
    def get_comprador(self, obj):
        """Retorna o comprador do pedido"""
        if obj.transaction and obj.transaction.checkout_link and obj.transaction.checkout_link.pedido:
            pedido = obj.transaction.checkout_link.pedido
            if pedido.comprador:
                nome = pedido.comprador.name
                return format_html(
                    '<span title="{}">{}...</span>',
                    nome,
                    nome[:25] if len(nome) > 25 else nome
                )
        return "-"
    get_comprador.short_description = 'Comprador'


@admin.register(PaymentWebhook)
class PaymentWebhookAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'get_pedido',
        'get_feira',
        'get_origem',
        'event_type',
        'received_at',
        'get_processed_badge'
    )
    list_filter = (
        'processed', 
        'event_type', 
        'received_at',
        'transaction__checkout_link__pedido__feira',
        'transaction__checkout_link__pedido__origem'
    )
    search_fields = (
        'transaction__transaction_id',
        'transaction__merchant_order_id',
        'transaction__checkout_link__pedido__id',
        'transaction__checkout_link__pedido__comprador__name',
        'event_type'
    )
    readonly_fields = ('received_at', 'payload')
    
    fieldsets = (
        ('Transação', {
            'fields': ('transaction',)
        }),
        ('Webhook', {
            'fields': ('received_at', 'event_type', 'processed')
        }),
        ('Processamento', {
            'fields': ('processing_error',)
        }),
        ('Payload Completo', {
            'fields': ('payload',),
            'classes': ('collapse',)
        }),
    )
    
    date_hierarchy = 'received_at'
    
    def get_processed_badge(self, obj):
        if obj.processed:
            return format_html(
                '<span style="background-color: green; color: white; padding: 3px 10px; border-radius: 3px;">✓ Processado</span>'
            )
        return format_html(
            '<span style="background-color: orange; color: white; padding: 3px 10px; border-radius: 3px;">⏳ Pendente</span>'
        )
    get_processed_badge.short_description = 'Processado'
    
    def get_pedido(self, obj):
        """Retorna o pedido relacionado"""
        if obj.transaction and obj.transaction.checkout_link and obj.transaction.checkout_link.pedido:
            pedido = obj.transaction.checkout_link.pedido
            return format_html(
                '<a href="/admin/Pedidos/pedido/{}/change/">{}</a>',
                pedido.id,
                pedido.id
            )
        return "-"
    get_pedido.short_description = 'Pedido'
    
    def get_feira(self, obj):
        """Retorna a feira do pedido"""
        if obj.transaction and obj.transaction.checkout_link and obj.transaction.checkout_link.pedido:
            pedido = obj.transaction.checkout_link.pedido
            if pedido.feira:
                return pedido.feira.nome
        return "-"
    get_feira.short_description = 'Feira'
    
    def get_origem(self, obj):
        """Retorna a origem do pedido"""
        if obj.transaction and obj.transaction.checkout_link and obj.transaction.checkout_link.pedido:
            pedido = obj.transaction.checkout_link.pedido
            return pedido.get_origem_display()
        return "-"
    get_origem.short_description = 'Origem'

@admin.register(PaymentCieloLio)
class PaymentCieloLioAdmin(admin.ModelAdmin):
    list_display = [
        'id', 
        'get_tipo_badge', 
        'reference', 
        'get_pedido_link',
        'value_display', 
        'installments',
        'get_payment_info',
        'created_at'
    ]
    list_filter = ['tipo', 'created_at', 'pedido__feira']
    search_fields = [
        'reference', 
        'transaction_id', 
        'payment_id', 
        'auth_code',
        'pedido__id'
    ]
    readonly_fields = [
        'created_at', 
        'updated_at', 
        'payload',
        'get_payload_preview'
    ]
    autocomplete_fields = ['pedido']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Informações Gerais', {
            'fields': ('pedido', 'tipo')
        }),
        ('Dados da Transação', {
            'fields': ('reference', 'value', 'installments', 'payment_code')
        }),
        ('Resposta Cielo (Response)', {
            'fields': (
                'transaction_id', 
                'payment_id', 
                'auth_code', 
                'cielo_code', 
                'merchant_code', 
                'product_name'
            ),
            'classes': ('collapse',)
        }),
        ('Payload JSON', {
            'fields': ('get_payload_preview', 'payload'),
            'classes': ('collapse',)
        }),
        ('Erro', {
            'fields': ('error_message',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
        }),
        ('API CIELO', {
            'fields': ('response_api',),
            'classes': ('collapse',)
        }),
    )
    
    def get_tipo_badge(self, obj):
        if obj.tipo == 'request':
            return format_html(
                '<span style="background-color: #007bff; color: white; padding: 3px 10px; border-radius: 3px;">REQUEST</span>'
            )
        return format_html(
            '<span style="background-color: #28a745; color: white; padding: 3px 10px; border-radius: 3px;">RESPONSE</span>'
        )
    get_tipo_badge.short_description = 'Tipo'
    
    def get_pedido_link(self, obj):
        if obj.pedido:
            url = f"/admin/Pedidos/pedido/{obj.pedido.id}/change/"
            return format_html(
                '<a href="{}" target="_blank">Pedido #{}</a>',
                url,
                obj.pedido.id
            )
        return "-"
    get_pedido_link.short_description = 'Pedido'
    
    def value_display(self, obj):
        return f"R$ {obj.value/100:.2f}"
    value_display.short_description = 'Valor'
    
    def get_payment_info(self, obj):
        if obj.tipo == 'response' and obj.auth_code:
            return format_html(
                '<span title="Auth: {} | Cielo: {}">✓ {}</span>',
                obj.auth_code,
                obj.cielo_code or '-',
                obj.auth_code[:10]
            )
        elif obj.tipo == 'request' and obj.payment_code:
            return obj.payment_code
        return "-"
    get_payment_info.short_description = 'Info Pagamento'
    
    def get_payload_preview(self, obj):
        """Mostra preview formatado do payload"""
        import json
        if obj.payload:
            try:
                formatted = json.dumps(obj.payload, indent=2, ensure_ascii=False)
                # Limitar preview a 1000 caracteres
                if len(formatted) > 1000:
                    formatted = formatted[:1000] + "\n... (truncado)"
                return format_html('<pre style="max-height: 400px; overflow: auto;">{}</pre>', formatted)
            except:
                return str(obj.payload)
        return "-"
    get_payload_preview.short_description = 'Preview Payload'