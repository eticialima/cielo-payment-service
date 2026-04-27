from datetime import timedelta
from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes, action
from django.utils import timezone
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes  
from Pedidos.models import Pedido 
from payment.models import CheckoutLink, PaymentCieloLio
from payment.payment_serializers import (
    CheckoutLinkSerializer, 
    PaymentCieloLioSerializer, 
    PaymentCieloLioCreateSerializer
    )

class CheckoutLinkViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gerenciar links de pagamento
    """
    queryset = CheckoutLink.objects.select_related(
        'pedido', 
        'pedido__comprador'
        ).order_by('-criado_em')
    serializer_class = CheckoutLinkSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """
        Filtra links por feira
        """
        qs = self.queryset
        
        feira = self.request.query_params.get('feira', None)
        
        if feira:
            qs = qs.filter(pedido__feira=feira)
        
        return qs
    
    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        """
        Cancela um link de pagamento
        """
        link = self.get_object()
        
        if link.usado:
            return Response(
                {'error': 'Link já foi usado e não pode ser cancelado'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if link.cancelado:
            return Response(
                {'error': 'Link já está cancelado'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        link.cancelado = True
        link.save()
        
        serializer = self.get_serializer(link)
        return Response({
            'success': True,
            'message': 'Link cancelado com sucesso',
            'data': serializer.data
        })
    
    @action(detail=True, methods=['get'])
    def link_completo(self, request, pk=None):
        """
        Retorna o link completo formatado
        """
        link = self.get_object() 
        
        chave_encoded = urlsafe_base64_encode(force_bytes(link.chave))
        if isinstance(chave_encoded, bytes):
            chave_encoded = chave_encoded.decode()
        
        url = f"https://d-m-c.group/pay?c={chave_encoded}"
        
        return Response({
            'link': url,
            'chave': link.chave,
            'valido': link.is_valid()
        })
    

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def criar_link_pagamento(request):
    """
    Cria um link de pagamento baseado em um pedido existente
    
    Payload esperado:
    {
        "pedido_id": 123,
        "expira_em_horas": 24  // Opcional, padrão 24h
    }
    """
    data = request.data
    pedido_id = data.get('pedido_id')
    
    if not pedido_id:
        return Response(
            {'error': 'pedido_id é obrigatório'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Buscar pedido
    try:
        pedido = Pedido.objects.get(id=pedido_id) # Validar se pedido tem produtos
        if not pedido.produtos.exists():
            return Response(
                {'error': 'Pedido não possui produtos'},
                status=status.HTTP_400_BAD_REQUEST
            )
    except Pedido.DoesNotExist:
        return Response(
            {'error': f'Pedido com ID {pedido_id} não encontrado'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Criar CheckoutLink 
    expira_em_horas = data.get('expira_em_horas', 24)
    max_parcelas = data.get('max_parcelas', None)  # Aceitar max_parcelas customizado
    valor_customizado = data.get('valor_customizado', None)  # Valor customizado em centavos (para links parciais)
    
    checkout = CheckoutLink(
        pedido=pedido,
        expira_em=timezone.now() + timedelta(hours=expira_em_horas),
        max_parcelas=max_parcelas,
        valor_customizado=valor_customizado
    )
    checkout.save()
    
    # Gerar link codificado
    chave_encoded = urlsafe_base64_encode(force_bytes(checkout.chave))
    if isinstance(chave_encoded, bytes):
        chave_encoded = chave_encoded.decode()
    
    link_formatado = f"https://d-m-c.group/pay?c={chave_encoded}"
    
    # Calcular informações adicionais sobre o pedido
    preco_produtos = float(pedido.precoDosProdutos())
    descontos = float(pedido.descontosTotais() or 0)
    valor_ja_pago = float(pedido.valor_pago() or 0)
    
    # Somar valores de outros links ativos
    outros_links_ativos = CheckoutLink.objects.filter(
        pedido=pedido,
        usado=False,
        cancelado=False
    ).exclude(pk=checkout.pk)
    
    valor_outros_links = sum(link.valor_total for link in outros_links_ativos) / 100
    
    valor_ainda_disponivel = preco_produtos - descontos - valor_ja_pago - (checkout.valor_total / 100) - valor_outros_links

    return Response({
        'success': True,
        'checkout_id': checkout.id,
        'chave': checkout.chave,
        'link_pagamento': link_formatado,
        'valor_total': checkout.valor_total,
        'valor_total_formatado': f"R$ {checkout.valor_total / 100:.2f}",
        'valor_customizado': checkout.valor_customizado,
        'expira_em': checkout.expira_em,
        'max_parcelas': checkout.max_parcelas,
        'pedido': {
            'id': pedido.id,
            'comprador': pedido.comprador.name if pedido.comprador else None,
            'produtos_count': pedido.produtos.count(),
            'valor_total_pedido': preco_produtos - descontos,
            'valor_ja_pago': valor_ja_pago,
            'valor_em_links_ativos': (checkout.valor_total / 100) + valor_outros_links,
            'valor_ainda_disponivel': max(0, valor_ainda_disponivel)
        }
    }, status=status.HTTP_201_CREATED) 


@api_view(['GET']) 
@permission_classes([IsAuthenticated])
def buscar_links_por_pedido(request, pedido_id):
    """
    Busca todos os links de pagamento ativos de um pedido
    """
    try:
        pedido = Pedido.objects.get(id=pedido_id)
    except Pedido.DoesNotExist:
        return Response(
            {'error': f'Pedido com ID {pedido_id} não encontrado'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Buscar links não cancelados e não usados
    links = CheckoutLink.objects.filter(
        pedido=pedido,
        cancelado=False,
        usado=False
    ).order_by('-criado_em')
    
    links_data = []
    for link in links:
        chave_encoded = urlsafe_base64_encode(force_bytes(link.chave))
        if isinstance(chave_encoded, bytes):
            chave_encoded = chave_encoded.decode()
        
        link_formatado = f"https://d-m-c.group/pay?c={chave_encoded}"
        
        links_data.append({
            'id': link.id,
            'chave': link.chave,
            'link_pagamento': link_formatado,
            'valor_total': link.valor_total,
            'valor_customizado': link.valor_customizado,
            'max_parcelas': link.max_parcelas,
            'criado_em': link.criado_em,
            'expira_em': link.expira_em,
            'is_valid': link.is_valid(),
            'usado': link.usado,
            'cancelado': link.cancelado
        })
    
    return Response({
        'success': True,
        'pedido_id': pedido_id,
        'links': links_data
    }, status=status.HTTP_200_OK) 


class PaymentCieloLioViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gerenciar registros de comunicação com Cielo Lio
    
    Endpoints:
    - GET /api/payment/cielo-lio/ - Lista todos os registros
    - GET /api/payment/cielo-lio/{id}/ - Detalhe de um registro
    - POST /api/payment/cielo-lio/ - Criar novo registro
    - GET /api/payment/cielo-lio/por-pedido/{pedido_id}/ - Buscar por pedido
    - GET /api/payment/cielo-lio/por-referencia/{reference}/ - Buscar por referência
    """
    queryset = PaymentCieloLio.objects.select_related('pedido').order_by('-created_at')
    permission_classes = [IsAuthenticated]
    
    def get_serializer_class(self):
        """
        Usa serializer diferente para criação
        """
        if self.action == 'create':
            return PaymentCieloLioCreateSerializer
        return PaymentCieloLioSerializer
    
    def get_queryset(self):
        """
        Filtros opcionais via query params
        """
        qs = self.queryset
        
        # Filtrar por tipo (request/response)
        tipo = self.request.query_params.get('tipo', None)
        if tipo:
            qs = qs.filter(tipo=tipo)
        
        # Filtrar por pedido
        pedido_id = self.request.query_params.get('pedido', None)
        if pedido_id:
            qs = qs.filter(pedido_id=pedido_id)
        
        # Filtrar por referência
        reference = self.request.query_params.get('reference', None)
        if reference:
            qs = qs.filter(reference=reference)
        
        # Filtrar por feira
        feira = self.request.query_params.get('feira', None)
        if feira:
            qs = qs.filter(pedido__feira=feira)
        
        return qs
    
    @action(detail=False, methods=['get'], url_path='por-pedido/(?P<pedido_id>[^/.]+)')
    def por_pedido(self, request, pedido_id=None):
        """
        Busca todos os registros de um pedido específico
        """
        registros = self.get_queryset().filter(pedido_id=pedido_id)
        serializer = self.get_serializer(registros, many=True)
        
        return Response({
            'success': True,
            'pedido_id': pedido_id,
            'total': registros.count(),
            'registros': serializer.data
        })
    
    @action(detail=False, methods=['get'], url_path='por-referencia/(?P<reference>[^/.]+)')
    def por_referencia(self, request, reference=None):
        """
        Busca todos os registros de uma referência específica
        """
        registros = self.get_queryset().filter(reference=reference)
        serializer = self.get_serializer(registros, many=True)
        
        return Response({
            'success': True,
            'reference': reference,
            'total': registros.count(),
            'registros': serializer.data
        })
    
    @action(detail=False, methods=['post'])
    def registrar_request(self, request):
        """
        Endpoint específico para registrar um request enviado para Cielo
        
        Body exemplo:
        {
            "pedido": 123,
            "payload": {...},
            "reference": "53vhwx",
            "value": 2000,
            "installments": 1,
            "payment_code": "CREDITO_PARCELADO_LOJA"
        }
        """
        data = request.data.copy()
        data['tipo'] = 'request'
        
        serializer = PaymentCieloLioCreateSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response({
                'success': True,
                'message': 'Request registrado com sucesso',
                'data': serializer.data
            }, status=status.HTTP_201_CREATED)
        
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['post'])
    def registrar_response(self, request):
        """
        Endpoint específico para registrar um response recebido da Cielo
        
        Body exemplo:
        {
            "pedido": 123,
            "reference": "53vhwx",
            "payload": {...response completo da Cielo...}
        }
        """
        data = request.data.copy()
        data['tipo'] = 'response'
        
        serializer = PaymentCieloLioCreateSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response({
                'success': True,
                'message': 'Response registrado com sucesso',
                'data': serializer.data
            }, status=status.HTTP_201_CREATED)
        
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)