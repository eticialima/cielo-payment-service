import json
from rest_framework import status, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view
from rest_framework.pagination import PageNumberPagination

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils import timezone 
from django.utils.http import urlsafe_base64_decode
from django.conf import settings
from Pedidos.models import Payment
from payment.models import (
    CheckoutLink, 
    PaymentTransaction,
    PaymentAttempt, 
    PaymentWebhook
)
from payment.payment_serializers import (
    CheckoutLinkSerializer,
    PaymentRequestSerializer, 
    PaymentTransactionSerializer,
    PaymentTransactionDetailSerializer,
    PaymentAttemptDetailSerializer,
    PaymentWebhookDetailSerializer,
    ApiRecaptchaPaymentSerializer
) 
from payment.payment_cielo import CieloPaymentGateway
from payment.payment_3ds import Cielo3DSAuthenticator
from payment.payment_status_handler import PaymentStatusHandler

# Classe de paginação
class StandardResultsSetPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 1000


def get_client_ip(request):
    """Obtém o IP do cliente"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip 


@api_view(['GET'])
def validar_checkout_link(request, chave):
    """
    Valida um link de pagamento

    Args:
        request: Requisição HTTP
        chave: Chave do link de pagamento
    
    Returns:
        Response: Resposta HTTP com o status do link de pagamento
    """
    try:
        # Decodifica a chave
        decode_chave = str(urlsafe_base64_decode(chave), 'utf-8')
        
        # Busca o checkout link
        checkout = CheckoutLink.objects.select_related(
            'pedido', 
            'pedido__comprador'
            ).get(
                chave=decode_chave
                )
        print("\n[CHECKOUT LINK ENCONTRADO]", checkout,
              "\nPedido ID:", checkout.pedido.id
            )

        if not checkout:
            return Response(
                {"detail": "Link de pagamento inválido ou não encontrado."}, 
                status=status.HTTP_404_NOT_FOUND
            )

        # Verifica se o link foi cancelado
        if checkout.cancelado:
            return PaymentStatusHandler.get_link_status_response(
                link_status='canceled',
                pedido_id=checkout.pedido.id
            )

        # Se encontrou o link mas já foi usado
        if checkout.usado:
            # Buscar informações do pagamento para feedback
            try:
                payment_transaction = PaymentTransaction.objects.filter(
                    checkout_link=checkout
                    ).first()

                print("Tem transação de Pagamento:", payment_transaction)
                
                # Se tem transação, retornar status da transação
                if payment_transaction:
                    return PaymentStatusHandler.get_transaction_status_response(
                        payment_status=payment_transaction.status,
                        pedido_id=checkout.pedido.id,
                        transaction_id=payment_transaction.transaction_id
                    )
                else:
                    # Se não tem transação, retornar status de link usado
                    return PaymentStatusHandler.get_link_status_response(
                        link_status='used',
                        pedido_id=checkout.pedido.id
                    )
                    
            except Exception as e:
                print(f"Erro ao buscar transação: {e}")
                return PaymentStatusHandler.get_link_status_response(
                    link_status='used',
                    pedido_id=checkout.pedido.id
                )
 
        # Verifica se expirou
        if timezone.now() > checkout.expira_em:
            # Link expirado não é "usado" - apenas expirou sem ser utilizado
            return PaymentStatusHandler.get_link_status_response(
                link_status='expired',
                pedido_id=checkout.pedido.id
            )
        
        # Retornar dados do pedido para o checkout usando serializer
        serializer = CheckoutLinkSerializer(checkout)
        return Response(serializer.data, status=status.HTTP_200_OK)
        
    except (ValueError, TypeError):
        return Response({
            "detail": "Link de pagamento inválido.", 
            "required": "codigo"
            }, 
            status=status.HTTP_404_NOT_FOUND
        )


def atualiza_dados_cliente_endereco(checkout_link, cliente_data, billing_address):
    """
    Atualiza os dados do cliente e endereço de fatura com as informações enviadas pelo frontend no checkout
    Importante: Essa função é opcional e deve ser usada com cuidado para evitar inconsistências nos dados do pedido.
    Args:
        checkout_link: Instância do CheckoutLink relacionada ao pedido
        cliente_data: Dicionário com os dados do cliente
        billing_address: Dicionário com os dados do endereço de fatura
    """
    comprador = checkout_link.pedido.comprador
    if cliente_data:
        if cliente_data.get('nome'):
            comprador.name = cliente_data.get('nome')
        if cliente_data.get('email'):
            comprador.email = cliente_data.get('email')
        if cliente_data.get('cpf_cnpj'):
            comprador.cpf = cliente_data.get('cpf_cnpj')
        if cliente_data.get('telefone'):
            comprador.telefone = cliente_data.get('telefone')
        comprador.save()
        print(f"[COMPRADOR] - Dados do comprador atualizados: {comprador.name}")

    if billing_address:
        endereco = checkout_link.pedido.endereco_fatura
        if billing_address.get('postal_code'):
            # Atualizar endereço existente
            endereco.cep = billing_address.get('postal_code', '')
        if billing_address.get('street'):
            endereco.endereco = billing_address.get('street', '')
        if billing_address.get('number'):
            endereco.numero = billing_address.get('number', '')
        if billing_address.get('complement'):
            endereco.complemento = billing_address.get('complement', '')
        if billing_address.get('district'):
            endereco.bairro = billing_address.get('district', '')
        if billing_address.get('city'):
            endereco.cidade = billing_address.get('city', '')
        if billing_address.get('state'):
            endereco.estado = billing_address.get('state', '')
        if billing_address.get('country'):
            endereco.pais = billing_address.get('country', 'Brasil')

        endereco.save()
        print(f"[ENDERECO] - Endereço de fatura atualizado")


class PaymentProcessView(APIView):
    """
    View para processar um pagamento a partir do checkout
        - Valida recaptcha
        - Valida link de pagamento
        - Workflow de pré-venda
        - Processa pagamento via gateway (Cielo)
        - Registra transação e tentativa de pagamento
        - Retorna status da transação para o frontend
            - Para PIX, retorna dados do QR Code para o frontend
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        # Primeiro valida o recaptcha 
        recaptcha_serializer = ApiRecaptchaPaymentSerializer(
            data=request.data, 
            context={"request": request}
        )

        if not recaptcha_serializer.is_valid():
            return Response(
                {"detail": "Verificação de segurança falhou"}, 
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = PaymentRequestSerializer(data=request.data)
        
        if serializer.is_valid():
            
            # Get validated data
            data = serializer.validated_data 
            chave = data.get('chave')
            checkout_link = CheckoutLink.objects.get(
                chave=str(urlsafe_base64_decode(chave), 'utf-8')
                ) 
            if not checkout_link:
                return Response(
                    {"detail": "Erro ao processar pagamento. Token de checkout inválido."}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # VALIDAÇÃO PRÉ-VENDA: Workflow limpo
            from prevenda.services import PreVendaWorkflow
            
            pedido = checkout_link.pedido
            pode_pagar, info = PreVendaWorkflow.pode_prosseguir_pagamento(pedido)
            
            if not pode_pagar:
                return Response(
                    {
                        "detail": "Termo de ciência de pré-venda pendente",
                        "code": info['code'],
                        "requer_assinatura": True,
                        **info
                    }, 
                    status=status.HTTP_403_FORBIDDEN
                )

            # DESABILITADO - 
            # Não editar dados do cliente e endereço via checkout 
            # (pode causar inconsistências com dados do pedido)

            # cliente_data = data.get('cliente_data')
            # billing_address = data.get('billing_address')
            
            # IMPORTANTE: Usar valor_com_juros se tiver parcelamento
            # Valor total do pedido em centavos (já calculado no checkout_link) - 
            # NÃO USAR valor do frontend para evitar fraudes
            valor = checkout_link.valor_total
            
            # Método de pagamento (credit_card, debit_card, pix)
            metodo_pagamento = data.get('metodo_pagamento')
            
            # Gateway provider (cielo, etc) - opcional, default para 'cielo'
            gateway_provider = data.get('gateway_provider', 'cielo')
            
            # Dados do cartão (número, validade, cvv, nome, etc)
            card_data = data.get('card_data')
            
            # ID da Session do Antifraude (opcional, vem do frontend se tiver integração de antifraude)
            session_id = data.get('session_id')

            # Resultado do 3DS (opcional, vem do frontend após autenticação 3DS)
            three_ds_result = data.get('three_ds_result')

            print(
                "\n[DEBUG]", 
                "\n[CHAVE]: ", chave, 
                "[PEDIDO ID]: ", checkout_link.pedido.id, 
                # "\n[CLIENTE DATA]: ", cliente_data,  #  
                # "\n[BILLING ADDRESS]: ", billing_address,  # 
                "\n[PEDIDO VALOR]: ", valor, 
                "\n[METODO DE PAGAMENTO]: ", metodo_pagamento,
                "\n[GATEWAY PROVIDER]: ", gateway_provider,
                "\n[CARD DATA]:",
                "\n  - [cardholder_name]: ", card_data.get('cardholder_name') if card_data else None,
                "\n  - [card_number]: ", card_data.get('card_number') if card_data else None,
                "\n  - [expiration_month]: ", card_data.get('expiration_month') if card_data else None,
                "\n  - [expiration_year]: ", card_data.get('expiration_year') if card_data else None,
                "\n  - [security_code]: ", card_data.get('security_code') if card_data else None,
                "\n  - [brand]: ", card_data.get('brand') if card_data else None,
                "\n  - [installments]: ", card_data.get('installments') if card_data else None,
                "\n  - [interest]: ", card_data.get('interest') if card_data else None,
                "\n  - [valor_com_juros]: ", f"Decimal: {card_data.get('valor_com_juros') if card_data else None}",
                "\n[ANTIFRAUD SESSION ID]: ", session_id,
                "\n[3DS RESULT]: ", three_ds_result,  # Log 3DS
            ) 

            # DESABILITADO - NÃO ATUALIZA ENDEREÇO DO CLIENTE VIA CHECKOUT PARA EVITAR INCONSISTÊNCIAS
            # atualiza_dados_cliente_endereco(checkout_link, cliente_data, billing_address)

            print("\n[INICIANDO PROCESSAMENTO DE PAGAMENTO] - Pedido ID:", checkout_link.pedido.id)
            
            installments = 1
            valor_com_juros = None
            if card_data:
                installments = card_data.get('installments', 1) # Número de parcelas (default 1 para pagamento à vista)
                valor_com_juros = card_data.get('valor_com_juros') # Valor com juros (REAIS) se parcelado
            
            transaction = PaymentTransaction.objects.create(
                checkout_link=checkout_link,
                valor=valor,
                installments=installments,
                valor_com_juros=valor_com_juros,
                metodo_pagamento=metodo_pagamento,
                gateway_provider=gateway_provider,
                status='processing'
            )

            print("\n[PAYMENT TRANSITION]",
                  "\n - Transaction criada: ID:", transaction.id,
                  "\n - Status:", transaction.status,
                  )
            
            # Captura IP do cliente
            client_ip = get_client_ip(request)
            
            # Usar apenas Cielo como gateway por enquanto 
            # - pode ser extendido para outros gateways no futuro
            payment_gateway = CieloPaymentGateway()
             
            print(
                "\n[CIELO] GATEWAY_PROVIDER", gateway_provider,
                "\n[CIELO] CLIENT_IP", client_ip
            ) 

            # REGISTRAR TENTATIVA DE PAGAMENTO (PaymentAttempt)
            # Cria registro antes de tentar processar para auditoria completa
            attempt = PaymentAttempt.objects.create(
                transaction=transaction,
                status='processing'
            )

            print(f"\n[PAYMENT ATTEMPT]", 
                  "\n - Attempt ID:", attempt.id,
                  "\n - Status:", attempt.status
                  )
            
            try: 
                # IMPORTANTE: Incluir resultado 3DS no card_data
                # Se veio 3DS do frontend, adicionar ao card_data para o gateway processar
                if three_ds_result and card_data:
                    card_data['auth_3ds'] = three_ds_result
                    print("\n[3DS RESULT INCLUÍDO NO CARD DATA]", three_ds_result)
                
                if metodo_pagamento == 'credit_card': # CRÉDITO
                    # Pode ser com ou sem 3DS (depende se veio three_ds_result)
                    payment_response = payment_gateway.create_credit_payment(
                        card_data=card_data,
                        transaction=transaction,
                        client_ip=client_ip,
                        session_id=session_id
                    )
                elif metodo_pagamento == 'debit_card':  # DÉBITO
                    # SEMPRE com 3DS obrigatório
                    payment_response = payment_gateway.create_debit_payment(
                        card_data=card_data,
                        transaction=transaction,
                        client_ip=client_ip,
                        session_id=session_id
                    )
                elif metodo_pagamento == 'pix':
                    # Para PIX, podemos aceitar um tempo de expiração customizado
                    # Nova integração Cielo2: Máximo 86400 segundos (24 horas)
                    qr_expiration_time = data.get('qr_expiration_time', 1800)  # Default 30 minutos
                    if qr_expiration_time > 86400:  # Máximo 24 horas conforme documentação Cielo2
                        qr_expiration_time = 86400
                    
                    payment_response = payment_gateway.create_pix_payment(
                        transaction=transaction,
                        qr_expiration_time=qr_expiration_time
                    )
                else:
                    raise ValueError(f"Método de pagamento não suportado: {metodo_pagamento}")
                
                # Update transaction with response
                transaction.payment_response = payment_response
                
                # DEBUG: Logs detalhados da resposta do gateway
                if metodo_pagamento == 'credit_card' or metodo_pagamento == 'debit_card':
                    print("\n" + "="*80)
                    print("\n[PAYMENT GATEWAY] RESPOSTA CARTÃO (CRÉDITO/DÉBITO):")   
                    print(f"\nStatus: {payment_response.get('status', '')} - Cielo Status: {payment_response.get('cielo_status', '')}",
                        f"\n[CAMPOS]:",
                        f"\n   PaymentId: {payment_response.get('payment_id', '')}",
                        f"\n   MerchantOrderId: {payment_response.get('merchant_order_id', '')}",
                        f"\n   AuthorizationCode: {payment_response.get('raw_response', {}).get('Payment', {}).get('AuthorizationCode')}", 
                        "\n ERROS (Se houver):"
                        f"\n   ReturnCode: {payment_response.get('return_code', '')}"
                        f"\n   ReturnMessage: {payment_response.get('return_message', '')}"
                        f"\n   DenialReason: {payment_response.get('denial_reason', '')}"
                    )
                    print("="*80 + "\n")

                if metodo_pagamento == 'pix': 
                    print("\n" + "="*80)
                    print("\n[PAYMENT GATEWAY] RESPOSTA PIX:")   
                    print(f"\nStatus: {payment_response.get('status', '')}",
                        f"\n[CAMPOS]:",
                        f"\n   PaymentId: {payment_response.get('payment_id', '')}",
                        f"\n   MerchantOrderId: {payment_response.get('merchant_order_id', '')}",
                        f"\n   Txid: {payment_response.get('txid', '')}",  
                    )
                    print("="*80 + "\n")


                # Check payment status
                payment_status = payment_response.get('status')

                if payment_status == 'APPROVED':
                    transaction.status = 'approved'
                    
                    print("\n" + "="*80)
                    print("[PAGAMENTO DIRETO] CRIANDO PAYMENT RECORD (CARTÃO)")
                    print(f"VALIDAÇÃO: payment_status={payment_status}, transaction.status={transaction.status}")
                    print("="*80)
                    
                    tipo_calculo_parcelamento = data.get('tipo_calculo_parcelamento')

                    # CRIAR REGISTRO DE PAGAMENTO (Payment)
                    # IMPORTANTE: PIX nunca chega aqui! Sempre é aprovado via webhook
                    installments = card_data.get("installments", 1) if metodo_pagamento == 'credit_card' else 1
                    valor_com_juros_cents = card_data.get("valor_com_juros") if metodo_pagamento == 'credit_card' else None
                    
                    # IMPORTANTE: Frontend envia valor_com_juros em REAIS (ex: 8362.35)
                    # NÃO dividir por 100 - já está em REAIS!
                    valor_com_juros = valor_com_juros_cents if valor_com_juros_cents else None
                    
                    # Calcular valor da parcela (em reais)
                    valor_parcela = None
                    if installments > 1 and valor_com_juros:
                        valor_parcela = float(valor_com_juros) / installments

                    print(f"\n[1] MÉTODO DE PAGAMENTO: {metodo_pagamento}")
                    print(
                        f"\n[2] VALORES CARD_DATA",
                        f"\n -    VALOR TOTAL: {transaction.valor} (centavos, valor original do pedido sem juros)", 
                        f"\n -    VALOR COM JUROS: {card_data.get('valor_com_juros') if card_data else None} (REAIS)",   
                        f"\n -    INSTALLMENTS: {card_data.get('installments') if card_data else None}x", 
                        f"\n -    VALOR DA PARCELA: {card_data.get('valor_parcela') if card_data else None} (REAIS)", 
                    )
                         
                    # Mapear metodo_pagamento para payment_type
                    payment_type_map = {
                        'credit_card': 'credito',
                        'debit_card': 'debito',
                        'pix': 'pix'  # PIX nunca chega aqui (apenas webhook)
                    }
                    payment_type = payment_type_map.get(metodo_pagamento, 'credito')
                    
                    # Converter para centavos para os campos *_cents
                    valor_com_juros_em_centavos = int(valor_com_juros * 100) if valor_com_juros else transaction.valor
                    
                    print(f"[3] PAYMENT SERA SALVO:")
                    print(f"    payment_type: {payment_type}")
                    print(f"    installments: {installments}")
                    print(f"    valor_parcela: {valor_parcela}")
                    print(f"    valor_com_juros (REAIS): {valor_com_juros}")
                    print(f"    valor (REAIS): {transaction.valor / 100}")
                    print(f"    tipo_calculo_parcelamento: {tipo_calculo_parcelamento or 'padrao'}")
                    print(f"    valor_principal_solicitado_cents: {transaction.valor}")
                    print(f"    valor_acessorio_solicitado_cents: 0")
                    print(f"    valor_principal_com_juros_cents: {valor_com_juros_em_centavos}")
                    print(f"    total_cobrado_cents: {valor_com_juros_em_centavos}") 
                    print("="*80 + "\n")

                    identif = payment_response.get('payment_id', '')
                    merchant_order_id = payment_response.get('merchant_order_id', '')
                    authorization_code = payment_response.get('raw_response', {}).get('Payment', {}).get('AuthorizationCode')
                    
                    # VERIFICAÇÃO DE SEGURANÇA: Garantir que transaction.status seja realmente 'approved'
                    if transaction.status != 'approved':
                        print(f"[ERRO CRÍTICO] Tentativa de criar Payment com transaction.status={transaction.status} (deveria ser 'approved')")
                        print(f"   payment_status={payment_status}, transaction.id={transaction.id}, cielo_status={cielo_status}")
                        raise ValueError(f"Não é possível criar Payment para transação com status {transaction.status}")
                    
                    # CRIAR PAYMENT RECORD
                    payment_record = Payment.objects.create(
                        pedido=pedido,
                        payment_type=payment_type,
                        payment_condition=f"{installments}x" if installments > 1 else "à vista",
                        installments=installments,
                        valor_parcela=valor_parcela,
                        valor_com_juros=valor_com_juros, # valor com Juros se parcelado
                        valor=transaction.valor / 100, # valor pago (reais) (valor original sem juros)
                        cod_autenticacao=authorization_code,
                        identif=identif,
                        merchant_order_id=merchant_order_id,
                        notes=f"Pago via link de Pagamento gateway {gateway_provider} - identif: {identif} - Status: {payment_status}",
                        
                        # Campos de auditoria de parcelamento (calculados no backend, todos em CENTAVOS)
                        tipo_calculo_parcelamento=tipo_calculo_parcelamento or 'padrao',
                        valor_principal_solicitado_cents=transaction.valor,  # Valor do pedido sem juros (já em cents)
                        valor_acessorio_solicitado_cents=0,  # Sempre 0 para cálculo 'padrao'
                        valor_principal_com_juros_cents=valor_com_juros_em_centavos,  # Frontend envia REAIS, multiplicamos por 100
                        total_cobrado_cents=valor_com_juros_em_centavos  # Frontend envia REAIS, multiplicamos por 100
                    )
                    print(
                        f" \n[PAYMENT INSTANCIA] ID={payment_record.id}",
                        f"\n  Tipo={payment_record.payment_type}",
                        f"\n  Valor={payment_record.valor}",
                        f"\n  Valor com juros={payment_record.valor_com_juros}",
                        f"\n  Parcelas={payment_record.installments}"
                        )
                    
                    # Marcar link como usado
                    checkout_link.usado = True
                    checkout_link.save()
                    print(f"\n[CHECKOUT LINK] ID={checkout_link.id} MARCADO COM USADO")
                    

                    # [PEDIDO] VERIFICAR SE PEDIDO FOI TOTALMENTE PAGO
                    # Recalcula o total pago após adicionar o novo pagamento
                    pedido.refresh_from_db()

                    # DEBUG: Logs detalhados dos valores (decimal)
                    preco_produtos = float(pedido.precoDosProdutos() or 0)
                    descontos = float(pedido.descontosTotais() or 0)
                    pagamentos = float(pedido.valor_pago() or 0)
                    
                    print(f"\n{'='*80}")
                    print(f"\n[PAYMENT DEBUG VALORES PAGOS]",
                        f"\n  PedidoID {pedido.id}:",
                        f"\n  Valor total dos produtos (precoDosProdutos()): R$ {preco_produtos:.2f}",
                        f"\n  Descontos totais (descontosTotais()): R$ {descontos:.2f}",
                        f"\n  Valores pagos (valor_pago()): R$ {pagamentos:.2f}",
                        f"\n  Total de pagamentos feitos: {pedido.pagamentos.count()}"
                    ) 
                    # Listar todos os pagamentos que foram feitos para esse pedido
                    for i, pag in enumerate(pedido.pagamentos.all(), 1):
                        print(f"    PAYMENT #{i}: {pag.valor} (cents) / R$ {float(pag.valor):.2f} - {pag.payment_type} - {pag.notes}")

                    # Calcular o valor total do pedido subtraindo descontos e somando pagamentos
                    valor_total_pedido = preco_produtos - descontos
                    valor_ja_pago = pagamentos
                     
                    print(f"\n[PAYMENT VERIFICAÇÃO]",
                        f"\n  PedidoId {pedido.id}"
                        f"\n  Valor total do pedido: R$ {valor_total_pedido:.2f}"
                        f"\n  Valor já pago: R$ {valor_ja_pago:.2f}"
                        f"\n  Diferença: R$ {(valor_total_pedido - valor_ja_pago):.2f}" # 0 é para pedido totalmente pago
                          )
                    
                    # Se pagamento completo (com tolerância de 1 centavo para arredondamento)
                    if valor_ja_pago >= (valor_total_pedido - 0.01): 
                        pedido.phase = "pago"
                        pedido.save()

                        print(f"[PEDIDO] TOTALMENTE PAGO - phase atualizado para {pedido.phase}")
                    else:
                        print(f"[PEDIDO] PAGO PARCIAL - pedido continua em phase='{pedido.phase}'")
                    print(f"{'='*80}\n")
                    
                    print(f"[PAYMENT] APPROVED - Pedido: {pedido.id}")

                    ## DISPARAR AÇÕES PÓS-PAGAMENTO ##
                    ## Somente para feira ecommerce
                    if pedido.origem == 'ecommerce':
                        print("[PEDIDO] Enviar termo de pré-venda por email (ecommerce)...")
                        
                        # Enviar termo de pré-venda por email se aplicável
                        try:
                            from prevenda.views import processar_envio_termo_email
                            resultado = processar_envio_termo_email(pedido)
                            
                            if resultado['success']:
                                print(f"[TERMO] Termo de pré-venda enviado: Envelope {resultado['envelope_id']}")
                            else:
                                print(f"[TERMO] Não foi possível enviar termo: {resultado.get('error', 'Erro desconhecido')}")
                        except Exception as e:
                            print(f"[TERMO] Erro ao enviar termo de pré-venda: {str(e)}")
                            # Não bloqueia o webhook, apenas registra o erro 

                elif payment_status == 'DENIED':
                    transaction.status = 'denied'
                elif payment_status == 'WAITING':
                    # Status específico para PIX - QR Code gerado, aguardando pagamento
                    # IMPORTANTE: Aprovação virá via webhook
                    transaction.status = 'waiting'
                else:
                    transaction.status = 'pending'
                
                # Save transaction ID
                transaction.transaction_id = payment_response.get('payment_id')
                transaction.save()
                
                # ATUALIZAR PaymentAttempt COM STATUS
                attempt.status = payment_status.lower()
                attempt.response_data = payment_response
                
                # Se pagamento negado, adicionar códigos e mensagens de erro
                if payment_status == 'DENIED':
                    attempt.error_code = payment_response.get('return_code', 'UNKNOWN')
                    attempt.error_message = payment_response.get('denial_reason') or payment_response.get('return_message', 'Pagamento negado')
                
                attempt.save()
                print(f"[PAYMENT ATTEMPT] ATUALIZADO",
                      f"status={attempt.status}, "
                      f"error_code={getattr(attempt, 'error_code', None)}"
                      )
                
                # Return transaction data
                serializer = PaymentTransactionSerializer(transaction)
                response_data = serializer.data
                
                # Adicionar o status original da Cielo para o frontend
                response_data['status'] = payment_status
                response_data['denial_reason'] = payment_response.get('denial_reason', '')
                
                # Para PIX, adicionar dados do QR Code na resposta
                if metodo_pagamento == 'pix' and payment_status == 'WAITING':
                    additional_data = payment_response.get('additional_data', {})
                    response_data['qr_code'] = additional_data.get('qr_code', '')
                    response_data['qr_code_base64'] = additional_data.get('qr_code_base64', '')
                    response_data['qr_code_expiration'] = additional_data.get('expiration_date_qrcode', '')
                    response_data['qr_code_creation'] = additional_data.get('creation_date_qrcode', '')
                    response_data['transaction_id_cielo'] = additional_data.get('transaction_id', '')
                    
                    # DEBUG: Verificar se QR Code está presente
                    print(f"[PIX] QRCODE ENVIADO:",
                        f"   qr_code: {'SIM' if response_data['qr_code'] else 'NÃO'} ({len(response_data['qr_code'])} chars)",
                        f"   qr_code_base64: {'SIM' if response_data['qr_code_base64'] else 'NÃO'} ({len(response_data['qr_code_base64'])} chars)"
                        )
                
                return Response(response_data, status=status.HTTP_200_OK)
                
            except Exception as e:

                print("[TRANSACTION] Erro ao processar pagamento:", e)

                transaction.status = 'denied'
                error_message = str(e)
                error_response = {
                    'error': 'Falha na comunicação com o provedor de pagamento.',
                    'details': error_message,
                    'status': 'DENIED',
                    'denial_reason': 'O sistema de pagamento está indisponível. Por favor, tente novamente.'
                }
                
                transaction.payment_response = error_response
                transaction.save()
                
                # ATUALIZAR PaymentAttempt COM ERRO
                attempt.status = 'failed'
                attempt.error_code = 'EXCEPTION'
                attempt.error_message = error_message
                attempt.response_data = error_response
                attempt.save()
                print(f"[PAYMENT ATTEMPT] ERROR: {error_message}")
                
                # Incluir informações detalhadas sobre o erro na resposta
                serializer = PaymentTransactionSerializer(transaction)
                response_data = serializer.data
                response_data.update(error_response)
                
                return Response(
                    response_data,
                    status=status.HTTP_200_OK  # Retornar 200 para o frontend poder processar o erro
                )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PaymentTransactionViewSet(viewsets.ModelViewSet):
    """
    ViewSet para listar transações de pagamento com informações completas
    Permite filtrar por pedido, status e feira via query params
        - GET /api/payments/ - lista transações com filtros opcionais
            - ?pedido_id=123
            - ?status=approved
            - ?feira=feira-slug
        - GET /api/payments/{id}/ - detalhes completos da transação, incluindo tentativas de pagamento e resposta do gateway
    """
    queryset = PaymentTransaction.objects.select_related(
        'checkout_link', 
        'checkout_link__pedido', 
        'checkout_link__pedido__feira').all()
    serializer_class = PaymentTransactionSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    
    def get_serializer_class(self):
        if self.action == 'retrieve':
            return PaymentTransactionDetailSerializer
        return PaymentTransactionSerializer
    
    def get_queryset(self):
        qs = super().get_queryset()
        
        # Filtros opcionais
        pedido_id = self.request.query_params.get('pedido_id')
        status_filter = self.request.query_params.get('status')
        feira = self.request.query_params.get('feira')
        
        # print(f"[PaymentTransactionListViewSet] Query params: pedido_id={pedido_id}, status={status_filter}, feira={feira}")
        
        if feira:
            qs = qs.filter(checkout_link__pedido__feira=feira)
            # print(f"[PaymentTransactionListViewSet] Filtrando por feira: {feira}")
        
        if pedido_id:
            qs = qs.filter(checkout_link__pedido__id=pedido_id)
            # print(f"[PaymentTransactionListViewSet] Filtrando por pedido_id: {pedido_id}")
        
        if status_filter:
            qs = qs.filter(status=status_filter)
            # print(f"[PaymentTransactionListViewSet] Filtrando por status: {status_filter}") 

        # Ordenar por mais recente
        qs = qs.order_by('-data_criacao')
        
        # print(f"[PaymentTransactionListViewSet] Total de transações: {qs.count()}")
        
        return qs


class PaymentListView(APIView):
    """
    View para listar pagamentos
    Permite filtrar por pedido e status via query params
        - GET /api/payments/list/?pedido_id=123&status=approved
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        # Get query parameters
        pedido_id = request.query_params.get('pedido_id')
        status_filter = request.query_params.get('status')
        
        # Filter transactions
        transactions = PaymentTransaction.objects.all()
        
        if pedido_id:
            transactions = transactions.filter(checkout_link__pedido_id=pedido_id)
        
        if status_filter:
            transactions = transactions.filter(status=status_filter)
        
        # Serialize and return
        serializer = PaymentTransactionSerializer(transactions, many=True)
        return Response(serializer.data)



class PaymentAttemptDetailView(APIView):
    """
    View para obter detalhes completos de uma tentativa de pagamento específica
    Endpoint: GET /api/payment-attempts/{attempt_id}/
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, attempt_id):
        try:
            attempt = PaymentAttempt.objects.select_related('transaction').get(id=attempt_id)
            serializer = PaymentAttemptDetailSerializer(attempt)
            return Response(serializer.data)
        except PaymentAttempt.DoesNotExist:
            return Response(
                {'error': 'Tentativa não encontrada'}, 
                status=status.HTTP_404_NOT_FOUND
            )

 
@method_decorator(csrf_exempt, name='dispatch')
class PaymentWebhookView(APIView):
    """
    View to handle webhooks from Cielo
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        # Get webhook data
        try:
            print("[WEBHOOK]: Webhook recebido da Cielo")

            data = json.loads(request.body) 
            
            print("[WEBHOOK DATA]", json.dumps(data, indent=2))
            
            # Detectar qual gateway enviou o webhook
            # Processar apenas webhook Cielo
            # Aceita dois formatos: {"Payment": {"PaymentId": "..."}} ou {"PaymentId": "...", "ChangeType": ...}
            has_payment_nested = 'Payment' in data and 'PaymentId' in data.get('Payment', {})
            has_payment_direct = 'PaymentId' in data
            
            if has_payment_nested or has_payment_direct:
                return self._process_cielo_webhook(data)
            else:
                print("[WEBHOOK] inválido - formato não reconhecido")
                return HttpResponse(status=400)
            
        except Exception as e:
            print(f"[WEBHOOK] Erro ao processar webhook: {str(e)}")
            return HttpResponse(status=500)
    
    
    def _process_cielo_webhook(self, data):
        """
        Processa webhook da Cielo
        """
        # REGISTRAR WEBHOOK RECEBIDO (PaymentWebhook)
        # Cria registro assim que recebe, antes de processar
        webhook = PaymentWebhook.objects.create(
            event_type='cielo_payment_notification',
            payload=data,
            processed=False
        )

        print(f"[WEBHOOK] CRIADO ID={webhook.id}")
        
        try:
            # Extrair PaymentId - pode estar em Payment.PaymentId ou direto na raiz
            payment_data = data.get('Payment', {})
            payment_id = payment_data.get('PaymentId') or data.get('PaymentId')
            change_type = data.get('ChangeType')
            
            # Mapear ChangeType para descrição
            change_type_map = {
                1: "Mudança de status da transação",
                2: "Recorrência criada",
                3: "Mudança de status do Antifraude",
                4: "Mudança de status do pagamento recorrente",
                5: "Cancelamento negado",
                7: "Notificação de chargeback",
                8: "Alerta de fraude",
                25: "Transação cancelada ou estornada parcialmente"
            }
            change_desc = change_type_map.get(change_type, f"Tipo desconhecido: {change_type}")
            print(f"[WEBHOOK] ChangeType {change_type}: {change_desc}")
            
            if not payment_id:
                print("[WEBHOOK] PaymentId não encontrado no webhook Cielo")
                # Marcar webhook com erro
                webhook.processing_error = "PaymentId não encontrado"
                webhook.save()
                return HttpResponse(status=400)
            
            try:
                transaction = PaymentTransaction.objects.get(transaction_id=payment_id)
                
                # ASSOCIAR WEBHOOK À TRANSAÇÃO
                webhook.transaction = transaction
                webhook.save()

                print(f"[WEBHOOK] Associado à transação: {transaction.id}")
                
                # Consultar status atualizado diretamente na Cielo para garantir precisão
                gateway = CieloPaymentGateway()
                payment_info = gateway.query_payment(payment_id)
                
                # Determinar fonte dos dados (API ou payload do webhook)
                payment_data_obj = None
                cielo_status = None
                return_code = ''
                return_message = ''
                
                if payment_info:
                    # FONTE 1: Usar dados atualizados da API (preferencial)
                    payment_data_obj = payment_info.get('Payment', {})
                    cielo_status = payment_data_obj.get('Status')
                    return_code = payment_data_obj.get('ReturnCode', '')
                    return_message = payment_data_obj.get('ReturnMessage', '')
                    
                    print(f"\n[WEBHOOK] Status consultado na Cielo API:",
                        f"   Status: {cielo_status}",
                        f"   ReturnCode: {return_code}",
                        f"   ReturnMessage: {return_message}",
                    )
                else:
                    # FONTE 2: Fallback apenas se PIX_MOCK_MODE estiver ativo
                    # Em produção, não podemos confiar apenas no payload do webhook
                    print(f"\n[WEBHOOK] Não foi possível consultar API Cielo",
                        f"   PaymentId: {payment_id}",
                        f"   PIX_MOCK_MODE: {settings.PIX_MOCK_MODE}"
                    )
                    # MODO MOCK: Usar dados do payload do webhook 
                    if settings.PIX_MOCK_MODE: 
                        print(f"\n[WEBHOOK] MOCK MODE ATIVO")

                        payment_data_obj = payment_data  # Já extraído no início
                        cielo_status = payment_data_obj.get('Status')
                        return_code = payment_data_obj.get('ReturnCode', '')
                        return_message = payment_data_obj.get('ReturnMessage', '')
                        
                        if cielo_status is not None:
                            print(f"\n[WEBHOOK] Usando dados do payload do webhook:",
                                f"   Status: {cielo_status}",
                                f"   ReturnCode: {return_code}",
                                f"   ReturnMessage: {return_message}",
                            )
                        else:
                            # Sem status mesmo no webhook
                            print(f"[WEBHOOK] ERROR: Status não encontrado no webhook")
                            webhook.processed = False
                            webhook.processing_error = "Status não disponível no payload do webhook"
                            webhook.save()
                            return HttpResponse(status=200)
                    else:
                        # PRODUÇÃO: Falha é crítica, não processar sem API
                        print(f"\n[WEBHOOK] PRODUÇÃO: Falha ao consultar API Cielo (credenciais ou conectividade)")
                        webhook.processed = False
                        webhook.processing_error = "Falha ao consultar status na API Cielo (produção requer validação via API)"
                        webhook.save()
                        return HttpResponse(status=200)
                
                # Mapear status Cielo (numérico) para nosso sistema
                status_map = {
                    0: "pending",      # NotFinished - Aguardando atualização
                    1: "processing",   # Authorized - Apto a ser capturado (ainda não confirmado)
                    2: "approved",     # PaymentConfirmed - Pagamento confirmado
                    3: "denied",       # Denied - Negado por autorizador
                    10: "canceled",    # Voided - Cancelado
                    11: "refunded",    # Refunded - Reembolsado
                    12: "pending",     # Pending - Aguardando instituição financeira
                    13: "denied",      # Aborted - Cancelado por erro/antifraude
                    20: "pending"      # Scheduled - Recorrência agendada
                }
                
                new_status = status_map.get(cielo_status, "pending")
                transaction.status = new_status
                transaction.payment_response = payment_info if payment_info else data
                transaction.save()

                print("[STATUS]", f"Cielo: {cielo_status} → Sistema: {new_status}")
                
                # ATUALIZAR PEDIDO QUANDO PAGAMENTO FOR APROVADO
                if new_status == "approved":
                    print(f"\n{'='*80}") 
                    print(f"[WEBHOOK] PAGAMENTO APROVADO",
                        f"  Transaction ID: {transaction.id}",
                        f"  Cielo Status: {cielo_status} → Sistema Status: {new_status}",
                        f"  ⚠️ VALIDAÇÃO: transaction.status={transaction.status}",
                    )
                    print(f"{'='*80}\n")
                    
                    pedido = transaction.checkout_link.pedido
                    checkout_link = transaction.checkout_link
 
                    # CRIAR REGISTRO DE PAGAMENTO (Payment)
                    # Verificar se já não existe Payment para evitar duplicação
                    from Pedidos.models import Payment
                    existing_payment = Payment.objects.filter(
                        pedido=pedido,
                        identif=payment_id
                    ).first()
                    
                    print("[WEBHOOK] Verificando existência", existing_payment)

                    if not existing_payment:
                        print("\n" + "="*80)
                        print("[WEBHOOK] CRIANDO PAYMENT RECORD")
                        print("="*80) 
                        
                        # Determinar tipo de pagamento pelo método da transação
                        payment_type = 'pix'  # Default PIX (mais comum no webhook)
                        if transaction.metodo_pagamento == 'credit_card':
                            payment_type = 'credito'
                        elif transaction.metodo_pagamento == 'debit_card':
                            payment_type = 'debito' 
                            
                        if payment_type == 'pix':
                            print(f"\n[WEBHOOK PAYMENT INFO DEBUG]:",
                               f"\n   payment_data_obj: {payment_data_obj}",
                                 f"\n   payment_id: {payment_id}",
                                 f"\n   payment_type: {payment_type}",
                                 f"\n   AuthorizationCode: {payment_data_obj.get('AuthorizationCode', '')}",
                                 f"\n   CIELO STATUS: {cielo_status}"
                               ) 
                            print("="*80 + "\n")
                        else: 
                            print(f"\n[WEBHOOK PAYMENT INFO DEBUG]:" 
                                # f"\n   payment_info completo: {payment_info}",
                                f"\n   payment_id: {payment_id}",
                                f"\n   payment_type: {payment_type}",
                                f"\n   MerchantOrderId: {payment_info.get('MerchantOrderId', '')}",
                                f"\n   Payment.AuthorizationCode: {payment_info.get('Payment', {}).get('AuthorizationCode', '')}",
                                f"\n   CIELO STATUS: {cielo_status}"
                            )
                            print("="*80 + "\n") 
 
                        # Parcelas e valor
                        installments = transaction.installments or 1
                        valor_com_juros = transaction.valor_com_juros  # Já está em REAIS do frontend
                        
                        # Calcular valor_parcela
                        valor_parcela = None
                        if installments > 1 and valor_com_juros:
                            valor_parcela = round(float(valor_com_juros) / installments, 2)
                            print(f"    valor_parcela (REAIS): {valor_parcela}")
                        else:
                            print(f"    valor_parcela: None (à vista ou sem juros)")

                        print(f"\n[1] MÉTODO DE PAGAMENTO: {transaction.metodo_pagamento}")
                        print(
                                f"\n[2] VALORES CARD_DATA" 
                                f"\n -    VALOR TOTAL: {transaction.valor} (centavos, valor original do pedido sem juros)", 
                                f"\n -    VALOR COM JUROS: {valor_com_juros} (REAIS)",   
                                f"\n -    INSTALLMENTS: {installments}x", 
                                f"\n -    VALOR DA PARCELA: {valor_parcela} (REAIS)", 
                            )
                            
                        # Mapear metodo_pagamento para payment_type
                        payment_type_map = {
                            'credit_card': 'credito',
                            'debit_card': 'debito',
                            'pix': 'pix'  # PIX nunca chega aqui (apenas webhook)
                        }
                        payment_type = payment_type_map.get(transaction.metodo_pagamento, 'credito')
                        
                        # Converter para centavos para os campos *_cents
                        valor_com_juros_em_centavos = int(valor_com_juros * 100) if valor_com_juros else transaction.valor
                        
                        print(f"[3] PAYMENT SERA SALVO:")
                        print(f"    payment_type: {payment_type}")
                        print(f"    installments: {installments}")
                        print(f"    valor_parcela: {valor_parcela}")
                        print(f"    valor_com_juros (REAIS): {valor_com_juros}")
                        print(f"    valor (REAIS): {transaction.valor / 100}")
                        print(f"    tipo_calculo_parcelamento: 'padrao'")
                        print(f"    valor_principal_solicitado_cents: {transaction.valor}")
                        print(f"    valor_acessorio_solicitado_cents: 0")
                        print(f"    valor_principal_com_juros_cents: {valor_com_juros_em_centavos}")
                        print(f"    total_cobrado_cents: {valor_com_juros_em_centavos}") 
                        print("="*80 + "\n")

                        if payment_type == 'pix':
                            cod_autenticacao = payment_data_obj.get('AuthorizationCode', '')
                            merchant_order_id = '' 
                        else:
                            # Para cartão: estrutura aninhada payment_info['Payment']['campo']
                            payment_obj = payment_info.get('Payment', {})
                            cod_autenticacao = payment_obj.get('AuthorizationCode', '')
                            merchant_order_id = payment_info.get('MerchantOrderId', '')
                        
                        payment_record = Payment.objects.create(
                            pedido=pedido,
                            payment_type=payment_type,
                            payment_condition=f"{installments}x" if installments > 1 else "à vista",
                            installments=installments,
                            valor_parcela=valor_parcela,
                            valor_com_juros=valor_com_juros,
                            valor=transaction.valor / 100,  # Converter centavos para reais
                            cod_autenticacao=cod_autenticacao,
                            identif=payment_id,
                            merchant_order_id=merchant_order_id,
                            notes=f"Pago via link de Pagamento gateway Cielo - identif: {payment_id} - Status: APPROVED", 

                            # Campos de auditoria de parcelamento (calculados no backend, todos em CENTAVOS)
                            tipo_calculo_parcelamento='padrao',
                            valor_principal_solicitado_cents=transaction.valor,  # Valor do pedido sem juros (já em cents)
                            valor_acessorio_solicitado_cents=0,  # Sempre 0 para cálculo 'padrao'
                            valor_principal_com_juros_cents=valor_com_juros_em_centavos,  # Frontend envia REAIS, multiplicamos por 100
                            total_cobrado_cents=valor_com_juros_em_centavos  # Frontend envia REAIS, multiplicamos por 100
                        )
                        print(
                            f" \n[PAYMENT INSTANCIA] ID={payment_record.id}",
                            f"\n  Tipo={payment_record.payment_type}",
                            f"\n  Valor={payment_record.valor}",
                            f"\n  Valor com juros={payment_record.valor_com_juros}",
                            f"\n  Parcelas={payment_record.installments}"
                            )
                    else: 
                        print(f"\n[WEBHOOK] Payment já existe para identif={payment_id} - ID={existing_payment.id}")

                    # Marcar link como usado
                    checkout_link.usado = True
                    checkout_link.save()
                    print(f"\n[CHECKOUT LINK] ID={checkout_link.id} MARCADO COM USADO")
                    

                    # [PEDIDO] VERIFICAR SE PEDIDO FOI TOTALMENTE PAGO
                    # =================================================
                    # Recalcula o total pago após adicionar o novo pagamento
                    pedido.refresh_from_db()

                    # DEBUG: Logs detalhados dos valores (decimal)
                    preco_produtos = float(pedido.precoDosProdutos() or 0)
                    descontos = float(pedido.descontosTotais() or 0)
                    pagamentos = float(pedido.valor_pago() or 0)
                    
                    print(f"\n{'='*80}")
                    print(f"\n[PAYMENT DEBUG VALORES PAGOS]",
                        f"\n  PedidoID {pedido.id}:",
                        f"\n  Valor total dos produtos (precoDosProdutos()): R$ {preco_produtos:.2f}",
                        f"\n  Descontos totais (descontosTotais()): R$ {descontos:.2f}",
                        f"\n  Valores pagos (valor_pago()): R$ {pagamentos:.2f}",
                        f"\n  Total de pagamentos feitos: {pedido.pagamentos.count()}"
                    ) 
                    # Listar todos os pagamentos que foram feitos para esse pedido
                    for i, pag in enumerate(pedido.pagamentos.all(), 1):
                        print(f"    PAYMENT #{i}: {pag.valor} (cents) / R$ {float(pag.valor):.2f} - {pag.payment_type} - {pag.notes}")

                    # Calcular o valor total do pedido subtraindo descontos e somando pagamentos
                    valor_total_pedido = preco_produtos - descontos
                    valor_ja_pago = pagamentos

                    print(f"\n[PAYMENT VERIFICAÇÃO]",
                        f"\n  PedidoId {pedido.id}"
                        f"\n  Valor total do pedido: R$ {valor_total_pedido:.2f}"
                        f"\n  Valor já pago: R$ {valor_ja_pago:.2f}"
                        f"\n  Diferença: R$ {(valor_total_pedido - valor_ja_pago):.2f}" # 0 é para pedido totalmente pago
                          )
                    
                    # Se pagamento completo (com tolerância de 1 centavo para arredondamento)
                    if valor_ja_pago >= (valor_total_pedido - 0.01): 
                        pedido.phase = "pago"
                        pedido.save()

                        print(f"[PEDIDO] TOTALMENTE PAGO - phase atualizado para {pedido.phase}")
                    else:
                        print(f"[PEDIDO] PAGO PARCIAL - pedido continua em phase='{pedido.phase}'")
                    print(f"{'='*80}\n")
                    
                    print(f"[PAYMENT] APPROVED - Pedido: {pedido.id}")
                    
                    ## DISPARAR AÇÕES PÓS-PAGAMENTO ##
                    ## Somente para feira ecommerce
                    if pedido.origem == 'ecommerce':
                        print("[PEDIDO] Enviar termo de pré-venda por email (ecommerce)...")
                        
                        # Enviar termo de pré-venda por email se aplicável
                        # Enviar termo de pré-venda por email se aplicável
                        try:
                            from prevenda.views import processar_envio_termo_email
                            resultado = processar_envio_termo_email(pedido)
                            
                            if resultado['success']:
                                print(f"[TERMO] Termo de pré-venda enviado: Envelope {resultado['envelope_id']}")
                            else:
                                print(f"[TERMO] Não foi possível enviar termo: {resultado.get('error', 'Erro desconhecido')}")
                        except Exception as e:
                            print(f"[TERMO] Erro ao enviar termo de pré-venda: {str(e)}")
                            # Não bloqueia o webhook, apenas registra o erro 

                # MARCAR WEBHOOK COMO PROCESSADO COM SUCESSO
                webhook.processed = True
                webhook.save()
                print(f"[WEBHOOK] Webhook processado com sucesso")
                print(f"Cielo webhook processado - Status Cielo: {cielo_status} → Sistema: {new_status}")
                
                return HttpResponse(status=200)
                
            except PaymentTransaction.DoesNotExist:
                # Pagamento não tem transação no sistema
                print(f"[TRANSACTION] Transação não encontrada no banco: {payment_id}")
                print(f"[TRANSACTION] Pode ser pagamento de maquininha ou outro canal")
                
                # MARCAR WEBHOOK COMO PROCESSADO (não é erro, apenas não temos a transação)
                webhook.processed = True
                webhook.processing_error = f"Transação não encontrada (possível pagamento externo): {payment_id}"
                webhook.save()
                
                # Retornar 200 OK para a Cielo não reenviar
                return HttpResponse(status=200)
                
        except Exception as e:
            print(f"Erro ao processar webhook Cielo: {str(e)}")
            # Marcar webhook com erro
            webhook.processing_error = str(e)
            webhook.save()
            return HttpResponse(status=500)


class PaymentStatusView(APIView):
    """
    Verifica o status de uma transação (Polling)
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, transaction_id):
        """
        Get payment status by transaction ID
        """
        try:
            # Find transaction by transaction_id
            transaction = PaymentTransaction.objects.get(
                transaction_id=transaction_id
            )
            
            # Return transaction data
            serializer = PaymentTransactionSerializer(transaction)
            
            # Extrair denial_reason do payment_response se disponível
            denial_reason = ''
            if transaction.payment_response and isinstance(transaction.payment_response, dict):
                denial_reason = transaction.payment_response.get('denial_reason', '') or \
                               transaction.payment_response.get('return_message', '') or \
                               transaction.payment_response.get('ReturnMessage', '')
            
            return Response({
                'status': transaction.status,
                'transaction_id': transaction.transaction_id,
                'payment_method': transaction.metodo_pagamento,
                'amount': transaction.valor,
                'created_at': transaction.data_pagamento,
                'updated_at': transaction.last_update,
                'denial_reason': denial_reason,  # Adicionar mensagem específica do erro
                'payment_response': transaction.payment_response,
                'transaction_data': serializer.data
            })
            
        except PaymentTransaction.DoesNotExist:
            return Response(
                {'error': 'Transaction not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
            
        except Exception as e:
            print(f"Erro ao consultar status: {str(e)}")
            return Response(
                {'error': 'Internal server error'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PaymentWebhookDetailView(APIView):
    """
    View para obter detalhes completos de um webhook específico
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, webhook_id):
        try:
            webhook = PaymentWebhook.objects.select_related('transaction').get(id=webhook_id)
            serializer = PaymentWebhookDetailSerializer(webhook)
            return Response(serializer.data)
        except PaymentWebhook.DoesNotExist:
            return Response(
                {'error': 'Webhook não encontrado'}, 
                status=status.HTTP_404_NOT_FOUND
            )


class Get3DSTokenView(APIView):
    """
    Endpoint para obter token e dados necessários para autenticação 3DS
    
    FLUXO COMPLETO 3DS:
    ==================
    1. Frontend coleta dados do cartão
    2. Frontend chama ESTE endpoint com chave do checkout
    3. Backend valida checkout e cria transação temporária (status='authenticating')
    4. Backend gera token OAuth2 3DS
    5. Backend retorna token + dados estruturados (order_data, customer_data, etc)
    6. Frontend carrega script 3DS da Cielo
    7. Script 3DS autentica portador do cartão (com/sem desafio)
    8. Script retorna resultado (Cavv, Xid, Eci, Version, ReferenceId)
    9. Frontend envia TUDO (card_data + auth_3ds) para PaymentProcessView
    10. Backend valida resultado 3DS (via Cielo3DSAuthenticator)
    11. Backend processa pagamento incluindo dados 3DS na requisição
    12. Cielo valida autenticação e processa transação
    
    IMPORTANTE: 
    - Endpoint público (sem autenticação JWT)
    - Validação de segurança via checkout_link válido
    - Cria transação temporária para tracking
    - NÃO processa pagamento (apenas prepara 3DS)
    """
    permission_classes = []  # Público - validação via chave do checkout
    
    def post(self, request):
        """
        Gera token 3DS e retorna dados estruturados para o frontend
        
        Request body:
        {
            "chave": "base64_encoded_checkout_key",
            "card_data": {  // Opcional - para pré-preencher
                "card_number": "4000000000002503",
                "cardholder_name": "TESTE 3DS",
                "expiration_month": "12",
                "expiration_year": "30"
            }
        }
        
        Response:
        {
            "success": true,
            "access_token": "eyJhbGciOiJSUzI1NiIsInR5...",
            "script_url": "https://mpisandbox.braspag.com.br/Scripts/BP.Mpi.3ds20.min.js",
            "order_data": {...},
            "customer_data": {...},
            "billing_address": {...},
            "transaction_id": 123
        }
        """
        print("\n" + "="*80)
        print("REQUISIÇÃO DE TOKEN 3DS RECEBIDA")
        print("="*80)
        
        try:
            data = request.data
            chave = data.get('chave')
            card_data = data.get('card_data', {})
            
            print(f"Dados recebidos:", json.dumps(data, indent=2))
            print(f"   Chave: {chave[:30] if chave else 'NÃO FORNECIDA'}...")
            print(f"   Card Data: {'SIM' if card_data else 'NÃO'}")
            
            if not chave:
                print("Chave não fornecida")
                print("="*80 + "\n")
                return Response(
                    {'error': 'Chave do checkout não fornecida'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # ETAPA 1: VALIDAÇÃO DE CHECKOUT LINK
            # ============================================
            print(f"\nETAPA 1: Validando checkout link...")
            try:
                decoded_chave = str(urlsafe_base64_decode(chave), 'utf-8')
                checkout_link = CheckoutLink.objects.get(chave=decoded_chave)
                print(f"Checkout encontrado: Pedido {checkout_link.pedido.id}")

            except CheckoutLink.DoesNotExist:
                print("Checkout não encontrado")
                print("="*80 + "\n")
                return Response(
                    {'error': 'Checkout link inválido ou não encontrado'},
                    status=status.HTTP_404_NOT_FOUND
                )
            except Exception as e:
                print(f"Erro ao decodificar chave: {str(e)}")
                print("="*80 + "\n")
                return Response(
                    {'error': 'Chave de checkout inválida'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validar se o link ainda é válido
            if checkout_link.usado:
                print("Link já foi usado")
                print("="*80 + "\n")
                return Response(
                    {'error': 'Link de pagamento já foi utilizado'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if checkout_link.cancelado:
                print("Link foi cancelado")
                print("="*80 + "\n")
                return Response(
                    {'error': 'Link de pagamento foi cancelado'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if timezone.now() > checkout_link.expira_em:
                print("Link expirou")
                print("="*80 + "\n")
                return Response(
                    {'error': 'Link de pagamento expirou'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            installments = card_data.get("installments", 1) # Total de Parcelas se tiver 1 = à vista

            valor_com_juros = card_data.get("valor_com_juros") # Valor com Juros se tiver, em reais (ex: 150.00)

            valor_com_juros_em_cents = int(valor_com_juros * 100) if valor_com_juros else checkout_link.valor_total
            
            # ETAPA 2: CRIAÇÃO DE TRANSACAO TEMPORÁRIA
            # ============================================
            print(f"\nETAPA 2: Criando transação temporária..."
                  f"\n   Valor total (centavos): {checkout_link.valor_total}",
                  f"\n   Valor com juros: {valor_com_juros} / {valor_com_juros_em_cents} (cents)",
                  f"\n   Installments: {installments}"
                  )
            transaction = PaymentTransaction.objects.create(
                checkout_link=checkout_link,
                valor=checkout_link.valor_total,
                installments=installments,
                valor_com_juros=valor_com_juros,  # Inicialmente igual, pode ser atualizado depois
                metodo_pagamento='credit_card',
                gateway_provider='cielo',
                status='authenticating'  # Status temporário durante 3DS
            )
            print(f"Transação temporária criada: ID {transaction.id}")
            
            # ETAPA 3: INICIALIZAÇÃO DE AUTENTICADOR 3DS
            # ============================================
            print(f"\nETAPA 3: Inicializando autenticador 3DS...")
            authenticator = Cielo3DSAuthenticator()
            client_ip = get_client_ip(request)
            print(f"   Client IP: {client_ip}")
            
            # ETAPA 4: PREPARAÇÃO DE DADOS PARA AUTENTICAÇÃO
            # ============================================
            print(f"\nETAPA 4: Preparando dados para o script 3DS...")
            auth_data = authenticator.prepare_authentication_data(
                transaction=transaction,
                card_data=card_data if card_data else None,
                client_ip=client_ip
            )
            
            if not auth_data.get('success'):
                error_msg = auth_data.get('error', 'Erro ao preparar autenticação 3DS')
                print(f"Erro ao preparar dados: {error_msg}")
                print("="*80 + "\n")
                return Response(
                    {'error': error_msg, 'details': auth_data},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            print(f"Dados preparados com sucesso!")
            print(f"   Token gerado: {auth_data['access_token'][:30]}...")
            print(f"   Script URL: {auth_data['script_url']}")
            print(f"   Transaction ID: {transaction.id}")
            print("="*80 + "\n")
            
            # Retornar dados estruturados para o frontend (flat, não nested)
            response_data = auth_data.copy()  # Copiar todos os campos de auth_data
            response_data['transaction_id'] = transaction.id  # Adicionar transaction_id
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except CheckoutLink.DoesNotExist:
            print("Checkout link não encontrado (exceção)")
            print("="*80 + "\n")
            return Response(
                {'error': 'Checkout link inválido'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            print(f"EXCEÇÃO ao gerar token 3DS: {str(e)}")
            import traceback
            traceback.print_exc()
            print("="*80 + "\n")
            return Response(
                {'error': f'Erro interno: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class Log3DSEventView(APIView):
    """
    Endpoint para registrar eventos do fluxo 3DS
    
    Registra todos os eventos 3DS (onReady, onSuccess, onFailure, etc)
    no PaymentAttempt correspondente para auditoria completa.
    
    EVENTOS REGISTRADOS:
    - onReady: Script carregado
    - onSuccess: Autenticação bem-sucedida (com Cavv, Xid, Eci)
    - onFailure: Autenticação falhou
    - onNotEnrolled/onUnenrolled: Cartão não está em programa 3DS
    - onDisabled: 3DS desabilitado para o estabelecimento
    - onError: Erro técnico
    - onUnsupportedBrand: Bandeira não suportada
    
    AUDITORIA COMPLETA:
    - PaymentAttempt.three_ds_status
    - PaymentAttempt.three_ds_cavv
    - PaymentAttempt.three_ds_xid
    - PaymentAttempt.three_ds_eci
    - PaymentAttempt.three_ds_version
    - PaymentAttempt.three_ds_reference_id
    - PaymentAttempt.three_ds_return_code
    - PaymentAttempt.three_ds_return_message
    - PaymentAttempt.three_ds_payload (JSON completo)
    - PaymentAttempt.three_ds_completed_at (timestamp)
    
    Endpoint: POST /api/payment/3ds/log/
    """
    permission_classes = []  # Público - chamado pelo frontend
    
    def post(self, request):
        try:
            print("\n" + "="*80)
            print("[3DS Log] Registro de evento 3DS recebido")
            print("="*80)
            
            transaction_id = request.data.get('transaction_id')
            event_type = request.data.get('event_type')  # onReady, onSuccess, onFailure, etc
            event_data = request.data.get('event_data', {})
            
            print(f"   Transaction ID: {transaction_id}")
            print(f"   Event Type: {event_type}")
            print(f"   Event Data: {json.dumps(event_data, indent=2)}")
            
            if not transaction_id or not event_type:
                print("Dados insuficientes")
                print("="*80 + "\n")
                return Response(
                    {'error': 'transaction_id e event_type são obrigatórios'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Buscar ou criar PaymentAttempt
            try:
                transaction = PaymentTransaction.objects.get(id=transaction_id)
                print(f"   Transação encontrada: {transaction}")
                
                # Buscar último attempt ou criar um novo
                attempt = transaction.attempts.filter(
                    status__in=['processing', 'pending']
                ).order_by('-attempted_at').first()
                
                if not attempt:
                    print("   Nenhum attempt em andamento, criando novo...")
                    attempt = PaymentAttempt.objects.create(
                        transaction=transaction,
                        status='processing',
                        three_ds_attempted=True
                    )
                    print(f"   PaymentAttempt criado: ID={attempt.id}")
                else:
                    print(f"   PaymentAttempt existente: ID={attempt.id}")
                
                # Marcar que houve tentativa 3DS
                attempt.three_ds_attempted = True
                
                # Mapear event_type para status do banco
                event_status_map = {
                    'onReady': 'script_ready',
                    'onSuccess': 'auth_success',
                    'onFailure': 'auth_failure',
                    'onNotEnrolled': 'not_enrolled',
                    'onUnenrolled': 'not_enrolled',  # alias
                    'onDisabled': 'disabled',
                    'onError': 'error',
                    'onUnsupportedBrand': 'unsupported_brand',
                }
                
                new_status = event_status_map.get(event_type)
                if new_status:
                    attempt.three_ds_status = new_status
                    print(f"   Status 3DS atualizado: {new_status}")
                
                # Extrair campos do event_data
                if isinstance(event_data, dict):
                    if 'Cavv' in event_data:
                        attempt.three_ds_cavv = event_data.get('Cavv') or ''
                    if 'Xid' in event_data:
                        attempt.three_ds_xid = event_data.get('Xid') or ''
                    if 'Eci' in event_data:
                        attempt.three_ds_eci = event_data.get('Eci') or ''
                    if 'Version' in event_data:
                        attempt.three_ds_version = event_data.get('Version') or ''
                    if 'ReferenceId' in event_data:
                        attempt.three_ds_reference_id = event_data.get('ReferenceId') or ''
                    if 'ReturnCode' in event_data:
                        attempt.three_ds_return_code = event_data.get('ReturnCode') or ''
                    if 'ReturnMessage' in event_data:
                        attempt.three_ds_return_message = event_data.get('ReturnMessage') or ''
                
                # Salvar payload completo
                attempt.three_ds_payload = {
                    'event_type': event_type,
                    'event_data': event_data,
                    'timestamp': timezone.now().isoformat()
                }
                
                # Se é um evento final (success/failure/notEnrolled), marcar timestamp
                if event_type in ['onSuccess', 'onFailure', 'onNotEnrolled', 'onUnenrolled', 'onError']:
                    attempt.three_ds_completed_at = timezone.now()
                    print(f"   3DS concluído em: {attempt.three_ds_completed_at}")
                
                attempt.save()
                print(f"   PaymentAttempt atualizado com sucesso")
                print(f"   Resumo: {attempt.get_three_ds_summary()}")
                print("="*80 + "\n")
                
                return Response({
                    'success': True,
                    'attempt_id': attempt.id,
                    'three_ds_status': attempt.three_ds_status,
                    'three_ds_summary': attempt.get_three_ds_summary()
                }, status=status.HTTP_200_OK)
                
            except PaymentTransaction.DoesNotExist:
                print(f"Transação não encontrada: {transaction_id}")
                print("="*80 + "\n")
                return Response(
                    {'error': 'Transação não encontrada'},
                    status=status.HTTP_404_NOT_FOUND
                )
                
        except Exception as e:
            print(f"EXCEÇÃO ao registrar evento 3DS: {str(e)}")
            import traceback
            traceback.print_exc()
            print("="*80 + "\n")
            return Response(
                {'error': f'Erro interno: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class Test3DSCredentialsView(APIView):
    """
    Endpoint de teste para validar credenciais 3DS
    
    UTILITÁRIO DE DIAGNÓSTICO:
    - Testa geração de token OAuth2 sem criar transação
    - Valida credenciais ClientId, ClientSecret, EstablishmentCode
    - Útil para diagnosticar problemas de integração
    - Retorna preview do token e configurações
    
    USO:
    GET /api/payment/3ds/test-credentials/
    
    RESPOSTA DE SUCESSO:
    {
        "success": true,
        "message": "Credenciais 3DS válidas e funcionando",
        "token_preview": "eyJhbGc...",
        "token_type": "Bearer",
        "expires_in": 1200,
        "establishment_code": "...",
        "merchant_name": "...",
        "mcc": "5411",
        "environment": "sandbox",
        "script_url": "https://..."
    }
    
    RESPOSTA DE ERRO:
    {
        "success": false,
        "message": "Falha ao gerar token 3DS",
        "error": "401 Client Error...",
        "details": {...}
    }
    """
    permission_classes = []  # Público para facilitar testes
    
    def get(self, request):
        """
        Testa geração de token 3DS
        
        Response:
        {
            "success": true,
            "message": "Credenciais 3DS válidas e funcionando",
            "token_preview": "eyJhbGc...",
            "token_type": "Bearer",
            "expires_in": 1200,
            "establishment_code": "...",
            "merchant_name": "...",
            "mcc": "5411",
            "environment": "sandbox",
            "script_url": "https://..."
        }
        """
        print("\n" + "="*80)
        print("TESTE DE CREDENCIAIS 3DS")
        print("="*80)
        
        try:
            # Inicializar autenticador
            authenticator = Cielo3DSAuthenticator()
            
            # Tentar gerar token
            token_result = authenticator.generate_access_token()
            
            if token_result.get('success'):
                print("TESTE PASSOU: Token gerado com sucesso!")
                print("="*80 + "\n")
                
                return Response({
                    'success': True,
                    'message': 'Credenciais 3DS válidas e funcionando',
                    'token_preview': token_result['access_token'][:50] + '...',
                    'token_type': token_result['token_type'],
                    'expires_in': token_result['expires_in'],
                    'establishment_code': authenticator.establishment_code,
                    'merchant_name': authenticator.merchant_name,
                    'mcc': authenticator.mcc,
                    'environment': authenticator.env,
                    'script_url': authenticator.script_url
                }, status=status.HTTP_200_OK)
            else:
                error_msg = token_result.get('error', 'Erro desconhecido')
                print(f"TESTE FALHOU: {error_msg}")
                print("="*80 + "\n")
                
                return Response({
                    'success': False,
                    'message': 'Falha ao gerar token 3DS',
                    'error': error_msg,
                    'details': token_result
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            print(f"EXCEÇÃO no teste: {str(e)}")
            import traceback
            traceback.print_exc()
            print("="*80 + "\n")
            
            return Response({
                'success': False,
                'message': 'Exceção ao testar credenciais',
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)