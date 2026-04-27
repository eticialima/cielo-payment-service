"""
Cielo 3DS 2.2 Authentication Handler

Implementa autenticação 3-Domain Secure (3DS) para transações de cartão.
O 3DS adiciona uma camada extra de segurança ao validar o portador do cartão com o banco emissor.

Documentação oficial Cielo:
- https://developercielo.github.io/manual/3ds
- https://developercielo.github.io/manual/cielo-ecommerce#autenticação-3ds-nas-transações-de-cartão-de-crédito

FLUXO DE AUTENTICAÇÃO:
1. Backend gera token OAuth2 (método generate_access_token)
2. Frontend carrega script 3DS com token e dados do pedido
3. Script coleta dados do comprador e envia para banco emissor
4. Banco autentica portador (com ou sem desafio)
5. Script retorna resultado (Cavv, Xid, Eci)
6. Frontend envia resultado + dados cartão para backend
7. Backend processa pagamento com autenticação validada

BENEFÍCIOS:
    Liability shift - Responsabilidade de chargeback passa para o emissor
    Redução de fraudes em transações CNP (cartão não presente)
    Autenticação silenciosa quando possível (sem desafio)
"""

import requests
import json
import base64
from django.conf import settings
from django.utils import timezone
from datetime import timedelta


class Cielo3DSAuthenticator:
    """
    Gerenciador de autenticação 3DS 2.2 da Cielo
    
    IMPORTANTE: Credenciais 3DS são diferentes de MerchantId/MerchantKey
    
    Para obter ClientId e ClientSecret:
    1. Acesse https://www.cielo.com.br
    2. Entre na área de credenciamento/3DS
    3. Gere as credenciais específicas para 3DS
    4. Configure em settings.py: CIELO_3DS_CLIENT_ID e CIELO_3DS_CLIENT_SECRET
    """
    
    # URLs para obter token de acesso - Braspag MPI (NÃO Cielo E-commerce!)
    # Documentação: https://braspag.github.io/manual/emv3ds#criando-o-token-de-acesso
    AUTH_URL_SANDBOX = "https://mpisandbox.braspag.com.br/v2/auth/token"
    AUTH_URL_PRODUCTION = "https://mpi.braspag.com.br/v2/auth/token"
    
    # URLs do script JavaScript 3DS - Documentação oficial Cielo E-commerce
    # https://docs.cielo.com.br/ecommerce-cielo/docs/implementando-script
    SCRIPT_URL_SANDBOX = "https://mpisandbox.braspag.com.br/Scripts/BP.Mpi.3ds20.min.js"
    SCRIPT_URL_PRODUCTION = "https://mpi.braspag.com.br/Scripts/BP.Mpi.3ds20.min.js"  # produção
    # SCRIPT_URL_PRODUCTION = "https://mpisandbox.braspag.com.br/Scripts/BP.Mpi.3ds20.min.js"  # Usando sandbox por enquanto
    
    def __init__(self):
        """
        Inicializa autenticador 3DS com credenciais do settings
        
        Variáveis de ambiente necessárias:
        - CIELO_3DS_CLIENT_ID: ClientId obtido no site Cielo
        - CIELO_3DS_CLIENT_SECRET: ClientSecret obtido no site Cielo
        - CIELO_ESTABLISHMENT_CODE: Código do estabelecimento (EC)
        - CIELO_MERCHANT_NAME: Nome do estabelecimento
        - CIELO_MCC: Código de categoria (4 dígitos)
        - CIELO_ENV: 'sandbox' ou 'production' (padrão: sandbox)
        """
        self.client_id = getattr(settings, 'CIELO_3DS_CLIENT_ID', '')
        self.client_secret = getattr(settings, 'CIELO_3DS_CLIENT_SECRET', '')
        self.establishment_code = getattr(settings, 'CIELO_ESTABLISHMENT_CODE', '')
        self.merchant_name = getattr(settings, 'CIELO_MERCHANT_NAME', '')
        self.mcc = getattr(settings, 'CIELO_MCC', '')
        self.env = getattr(settings, 'CIELO_ENV', 'sandbox')
        
        # Selecionar URLs baseado no ambiente
        if self.env == 'production':
            self.auth_url = self.AUTH_URL_PRODUCTION
            self.script_url = self.SCRIPT_URL_PRODUCTION
        else:
            self.auth_url = self.AUTH_URL_SANDBOX
            self.script_url = self.SCRIPT_URL_SANDBOX
        
        print("\n" + "="*80)
        print("INICIALIZANDO CIELO 3DS AUTHENTICATOR")
        print("="*80)
        print(f" - Ambiente: {self.env.upper()}")
        print(f" - Auth URL: {self.auth_url}")
        print(f" - Script URL: {self.script_url}")
        print(f" - ClientId: {'SIM' if self.client_id else 'NÃO'}")
        print(f" - ClientSecret: {'SIM' if self.client_secret else 'NÃO'}")
        print(f" - EstablishmentCode: {self.establishment_code if self.establishment_code else 'NÃO'}")
        print(f" - MerchantName: {self.merchant_name if self.merchant_name else 'NÃO'}")
        print(f" - MCC: {self.mcc if self.mcc else 'NÃO'}")
        
        if not self.client_id or not self.client_secret:
            print("\nAVISO CRÍTICO: Credenciais 3DS não configuradas!")
            print("     Para obter as credenciais:")
            print("      1. Acesse https://www.cielo.com.br")
            print("      2. Entre na seção de autenticação 3DS")
            print("      3. Gere ClientId e ClientSecret")
            print("      4. Configure no settings.py:")
            print("         CIELO_3DS_CLIENT_ID = 'seu_client_id'")
            print("         CIELO_3DS_CLIENT_SECRET = 'seu_client_secret'")
        
        print("="*80 + "\n")
    
    
    def generate_access_token(self):
        """
        Gera token de acesso para o script 3DS usando autenticação Braspag MPI
        
        Conforme documentação oficial Braspag:
        https://braspag.github.io/manual/emv3ds#criando-o-token-de-acesso
        
        Método: Basic Authentication
        - Concatenar ClientId:ClientSecret
        - Codificar em Base64
        - Enviar no header Authorization
        
        Body JSON:
        - EstablishmentCode: Código do estabelecimento Cielo E-commerce
        - MerchantName: Nome do estabelecimento
        - MCC: Código de categoria (4 dígitos)
        
        Returns:
            dict: {
                'success': bool,
                'access_token': str,
                'token_type': str,
                'expires_in': int (segundos),
                'expires_at': str (ISO timestamp),
                'error': str (se falhar)
            }
        """
        print("\n" + "-"*80)
        print("GERANDO TOKEN DE ACESSO BRASPAG MPI")
        print("-"*80)
        
        if not self.client_id or not self.client_secret:
            error_msg = "Credenciais 3DS não configuradas (CIELO_3DS_CLIENT_ID / CIELO_3DS_CLIENT_SECRET)"
            print(f"ERRO: {error_msg}")
            print("-"*80 + "\n")
            return {
                'success': False,
                'error': error_msg
            }
        
        try:
            # PASSO 1: Concatenar ClientId:ClientSecret
            credentials = f"{self.client_id}:{self.client_secret}"
            
            # PASSO 2: Codificar em Base64
            credentials_base64 = base64.b64encode(credentials.encode()).decode()
            
            # PASSO 3: Preparar headers com Basic Authentication
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Basic {credentials_base64}'
            }
            
            # PASSO 4: Preparar body JSON
            # Para sandbox, usar valores de teste se não configurado
            if self.env == 'sandbox':
                establishment_code = self.establishment_code or '1006993069'
                merchant_name = self.merchant_name or 'Loja Teste Ltda'
                mcc = self.mcc or '5912'
            else:
                establishment_code = self.establishment_code
                merchant_name = self.merchant_name
                mcc = self.mcc
            
            body = {
                'EstablishmentCode': establishment_code,
                'MerchantName': merchant_name,
                'MCC': mcc
            }
            
            print(f"Enviando requisição Braspag MPI:")
            print(f"   URL: {self.auth_url}")
            print(f"   ClientId: {self.client_id[:15]}...{self.client_id[-5:]}")
            print(f"   Basic Auth: {credentials_base64[:30]}...{credentials_base64[-10:]}")
            print(f"   EstablishmentCode: {establishment_code}")
            print(f"   MerchantName: {merchant_name}")
            print(f"   MCC: {mcc}")
            
            # PASSO 5: Fazer requisição
            response = requests.post(
                self.auth_url,
                headers=headers,
                json=body,
                timeout=30
            )
            
            print(f"\nResposta recebida:")
            print(f"   Status Code: {response.status_code}")
            
            if response.status_code == 201 or response.status_code == 200:
                response_data = response.json()
                access_token = response_data.get('access_token')
                token_type = response_data.get('token_type', 'Bearer')
                expires_in = response_data.get('expires_in', 86399)
                
                # Converter expires_in para inteiro se vier como string
                if isinstance(expires_in, str):
                    expires_in = int(expires_in)
                
                print(f"\nTOKEN GERADO COM SUCESSO!")
                print(f"   Token Type: {token_type}")
                print(f"   Expires In: {expires_in} segundos ({expires_in/60:.1f} minutos)")
                print(f"   Access Token: {access_token[:30]}...{access_token[-15:]}")
                print("-"*80 + "\n")
                
                return {
                    'success': True,
                    'access_token': access_token,
                    'token_type': token_type,
                    'expires_in': expires_in,
                    'expires_at': (timezone.now() + timedelta(seconds=expires_in)).isoformat()
                }
            else:
                error_msg = f"Erro HTTP {response.status_code} ao gerar token"
                print(f"\n{error_msg}")
                print(f"   Response Body: {response.text[:500]}")
                print("-"*80 + "\n")
                
                return {
                    'success': False,
                    'error': error_msg,
                    'details': response.text,
                    'status_code': response.status_code
                }
                
        except requests.exceptions.Timeout:
            error_msg = "Timeout ao solicitar token OAuth2 (30s)"
            print(f"\n{error_msg}")
            print("-"*80 + "\n")
            return {
                'success': False,
                'error': error_msg
            }
        except Exception as e:
            error_msg = f"Exceção ao gerar token: {str(e)}"
            print(f"\n{error_msg}")
            import traceback
            traceback.print_exc()
            print("-"*80 + "\n")
            return {
                'success': False,
                'error': error_msg
            }
    
    def prepare_authentication_data(self, transaction, card_data=None, client_ip=None):
        """
        Prepara todos os dados necessários para o frontend executar autenticação 3DS
        
        Conforme documentação Cielo, o script 3DS precisa receber:
        1. Token de acesso (access_token)
        2. Dados do pedido (order_number, amount, currency)
        3. Dados do comprador (nome, email, CPF)
        4. Dados de endereço (billing e shipping)
        5. Dados do cartão (opcionais - podem ser preenchidos pelo script)
        
        Args:
            transaction: Instância de PaymentTransaction
            card_data: Dados do cartão (opcional)
            client_ip: IP do cliente
        
        Returns:
            dict: {
                'success': bool,
                'access_token': str,
                'script_url': str,
                'environment': str,
                'order_data': dict,
                'customer_data': dict,
                'billing_address': dict,
                'shipping_address': dict,
                'error': str (se falhar)
            }
        """
        print("\n" + "="*80)
        print("PREPARANDO DADOS PARA AUTENTICAÇÃO 3DS")
        print("="*80)
        
        # ETAPA 1: Gerar token de acesso
        print("ETAPA 1: Gerando token de acesso...")
        token_result = self.generate_access_token()
        
        if not token_result.get('success'):
            print("Falha ao gerar token - abortando preparação")
            print("="*80 + "\n")
            return token_result
        
        # ETAPA 2: Coletar dados do pedido
        print("\nETAPA 2: Coletando dados do pedido...")
        checkout_link = transaction.checkout_link
        pedido = checkout_link.pedido
        comprador = pedido.comprador
        endereco = pedido.endereco_fatura 
        
        print(f"   Pedido ID: {pedido.id}")
        print(f"   Comprador: {comprador.name}")
        print(f"   Email: {comprador.email}")
        print(f"   Valor: R$ {transaction.valor/100:.2f} ({transaction.valor} centavos)")
        print(f"   Endereço: {'SIM' if endereco else 'NÃO'}")

        valor_total = transaction.valor

        installments = card_data.get("installments", 1) # Total de Parcelas se tiver 1 = à vista

        valor_com_juros = card_data.get("valor_com_juros") # Valor com Juros se tiver, em reais (ex: 150.00)

        valor_com_juros_em_cents = int(valor_com_juros * 100) if valor_com_juros else transaction.valor

        if settings.DEBUG:
            print(f'\n[CARD DATA RECEBIDO]: {"SIM" if card_data else "NÃO"}'
                    f'\nCARTÃO NÚMERO: {card_data.get("card_number") if card_data else "N/A"}',
                    f'\n NOME NO CARTÃO: {card_data.get("cardholder_name") if card_data else "N/A"}',
                    f'\n VALIDADE: {card_data.get("expiration_month", "MM")}/{card_data.get("expiration_year", "YY") if card_data else "N/A"}',
                    f'\n CVV: {"SIM" if card_data and card_data.get("security_code") else "N/A"}',
                    f'\n BANDEIRA: {card_data.get("brand") if card_data else "N/A"}',
                    f'\n MERCHANT: {card_data.get("interest") if card_data else "N/A"}',
                    f'\n VALOR TOTAL: R$ {valor_total/100:.2f} ({valor_total} centavos)',
                    f'\n PARCELAS: {installments if card_data else "N/A"}', 
                    f'\n VALOR COM JUROS: R$ {valor_com_juros} ({valor_com_juros_em_cents} centavos)' if card_data and valor_com_juros else 'N/A'      
                )
        
        # ETAPA 3: Preparar dados estruturados
        print("\nETAPA 3: Estruturando dados para o script...")
        
        # Dados do pedido
        order_data = {
            'order_number': f"DMC-{pedido.id}-{transaction.id}",
            'currency_code': '986',  # BRL (ISO 4217)
            'total_amount': valor_com_juros_em_cents,  # Em centavos
            'installments': installments,
            'transaction_mode': 'S',  # S = eCommerce (não 3D Secure nativo)
            'merchant_url': getattr(settings, 'SITE_URL', 'https://feira.dmc.com.br')
        }
        print(f"   Order Data: {order_data['order_number']}")
        
        # Dados do comprador
        customer_identity = comprador.cpf.replace(".", "").replace("-", "").replace("/", "") if comprador.cpf else ''
        customer_data = {
            'customer_name': comprador.name[:50],  # Máx 50 chars
            'customer_email': comprador.email,
            'customer_phone': comprador.telefone if comprador.telefone else '',
            'customer_identity': customer_identity,
            'customer_identity_type': 'CPF' if len(customer_identity) == 11 else 'CNPJ' if customer_identity else ''
        }
        print(f"   Customer Data: {customer_data['customer_name']} ({customer_data['customer_identity_type']})")
        
        # Dados do endereço de cobrança
        billing_address = {}
        if endereco:
            billing_address = {
                'street': endereco.endereco[:100] if endereco.endereco else '',
                'number': endereco.numero[:10] if endereco.numero else 'S/N',
                'complement': endereco.complemento[:50] if endereco.complemento else '',
                'district': endereco.bairro[:50] if endereco.bairro else 'Centro',
                'city': endereco.cidade[:50] if endereco.cidade else '',
                'state': endereco.estado[:2] if endereco.estado else 'SP',
                'zip_code': endereco.cep.replace("-", "") if endereco.cep else '00000000',
                'country': 'BR'
            }
            print(f"   Billing Address: {billing_address['city']}/{billing_address['state']}")
        else:
            print(f"   Billing Address: Não disponível")
        
        # Dados de envio (mesmo que cobrança - retirada na feira)
        shipping_address = billing_address.copy() if billing_address else {}
        if shipping_address:
            shipping_address['addressee'] = comprador.name[:60]
            shipping_address['method'] = 'SameDay'  # Retirada imediata
            print(f"   Shipping Address: Mesmo que cobrança (retirada na feira)")
        
        # Dados do cartão (se fornecidos)
        card_info = {}
        if card_data:
            card_info = {
                'card_number': card_data.get('card_number', '').replace(' ', ''),
                'card_holder': card_data.get('cardholder_name', ''),
                'expiration_date': f"{card_data.get('expiration_month', '')}/20{card_data.get('expiration_year', '')}"
            }
            print(f"   Card Info: {card_info['card_number'][:6]}****{card_info['card_number'][-4:]}")
        
        print(f"\nTodos os dados preparados com sucesso!")
        
        # VALIDAÇÃO CRÍTICA: Verificar campos obrigatórios do Braspag/Cielo
        print(f"\nVALIDANDO CAMPOS OBRIGATÓRIOS...")
        campos_obrigatorios = {
            'EstablishmentCode': self.establishment_code,
            'AccessToken': token_result['access_token'],
            'OrderNumber': order_data['order_number'],
            'CurrencyCode': order_data['currency_code'],
            'TotalAmount': order_data['total_amount'],
            'Installments': order_data['installments'],
            'CustomerName': customer_data['customer_name'],
            'CustomerEmail': customer_data['customer_email'],
        }
        
        campos_faltando = []
        for campo, valor in campos_obrigatorios.items():
            if not valor:
                campos_faltando.append(campo)
                print(f"   {campo}: VAZIO OU AUSENTE")
            else:
                # Mostrar apenas primeiros chars para segurança
                valor_str = str(valor)
                if len(valor_str) > 50:
                    print(f"   {campo}: {valor_str[:30]}...{valor_str[-10:]}")
                else:
                    print(f"   {campo}: {valor_str}")
        
        if campos_faltando:
            erro = f"Campos obrigatórios faltando: {', '.join(campos_faltando)}"
            print(f"\nERRO: {erro}")
            print("="*80 + "\n")
            return {
                'success': False,
                'error': erro,
                'missing_fields': campos_faltando
            }
        
        print(f"\nTodos os campos obrigatórios validados!")
        print("="*80 + "\n")
        
        response_data = {
            'success': True,
            'access_token': token_result['access_token'],
            'token_type': token_result['token_type'],
            'expires_in': token_result['expires_in'],
            'expires_at': token_result['expires_at'],
            'script_url': self.script_url,
            'environment': self.env,
            'establishment_code': self.establishment_code or '1006993069',  # EC para sandbox
            'merchant_name': self.merchant_name or 'Loja Teste Ltda',
            'order_data': order_data,
            'customer_data': customer_data,
            'billing_address': billing_address,
            'shipping_address': shipping_address,
            'card_info': card_info,
            'transaction_id': transaction.id,
            'client_ip': client_ip or ''
        }
        
        # LOG COMPLETO DOS DADOS (apenas em debug)
        print(f"\nPAYLOAD COMPLETO SENDO RETORNADO:")
        import json
        safe_response = response_data.copy()
        if safe_response.get('access_token'):
            token = safe_response['access_token']
            safe_response['access_token'] = f"{token[:30]}...{token[-15:]}"
        print(json.dumps(safe_response, indent=2, ensure_ascii=False))
        print("="*80 + "\n")
        
        return response_data
    
    def validate_authentication_result(self, auth_result):
        """
        Valida resultado da autenticação 3DS retornado pelo script
        
        O script 3DS retorna os seguintes campos após autenticação:
        - Cavv: Assinatura da autenticação (obrigatório quando autenticado)
        - Xid: ID da transação 3DS (opcional)
        - Eci: Electronic Commerce Indicator - indica nível de autenticação
        - Version: Versão do protocolo 3DS (2.2.0 para Visa/Master, 2.1.0 para Elo/Amex)
        - ReferenceId: Request ID da autenticação (opcional)
        
        Args:
            auth_result: dict com resultado do script 3DS
        
        Returns:
            dict: {
                'is_valid': bool,
                'eci': str,
                'status': str (authenticated/not_authenticated/not_available/error),
                'message': str,
                'liability_shift': bool,
                'cavv': str,
                'xid': str,
                'version': str,
                'reference_id': str
            }
        """
        print("\n" + "="*80)
        print("VALIDANDO RESULTADO DA AUTENTICAÇÃO 3DS")
        print("="*80)
        
        if not auth_result:
            print("Resultado vazio ou None")
            print("="*80 + "\n")
            return {
                'is_valid': False,
                'status': 'error',
                'message': 'Resultado da autenticação não fornecido',
                'liability_shift': False
            }
        
        # Extrair campos (aceitar maiúsculas e minúsculas)
        cavv = auth_result.get('Cavv') or auth_result.get('cavv', '')
        xid = auth_result.get('Xid') or auth_result.get('xid', '')
        eci = auth_result.get('Eci') or auth_result.get('eci', '')
        version = auth_result.get('Version') or auth_result.get('version', '2')
        reference_id = auth_result.get('ReferenceId') or auth_result.get('reference_id', '')
        return_code = auth_result.get('ReturnCode') or auth_result.get('return_code', '')
        return_message = auth_result.get('ReturnMessage') or auth_result.get('return_message', '')
        
        print(f"Dados recebidos do script 3DS:")
        print(f"   Cavv: {cavv[:40] if cavv else 'NÃO FORNECIDO'}...")
        print(f"   Xid: {xid if xid else 'NÃO FORNECIDO'}")
        print(f"   Eci: {eci if eci else 'NÃO FORNECIDO'}")
        print(f"    - Version: {version}")
        print(f"   ReferenceId: {reference_id if reference_id else 'NÃO FORNECIDO'}")
        print(f"   ReturnCode: {return_code if return_code else 'NÃO FORNECIDO'}")
        print(f"   ReturnMessage: {return_message if return_message else 'NÃO FORNECIDO'}")
        
        # Validar ECI (campo mais importante)
        if not eci:
            print("\nECI não fornecido - autenticação inválida")
            print("="*80 + "\n")
            return {
                'is_valid': False,
                'status': 'error',
                'message': 'ECI não retornado pelo script 3DS',
                'liability_shift': False
            }
        
        # Validar ECI e determinar status
        eci_validation = self._validate_eci(eci)
        
        print(f"\nRESULTADO DA VALIDAÇÃO ECI:")
        print(f"   Status: {eci_validation['status'].upper()}")
        print(f"   Mensagem: {eci_validation['message']}")
        print(f"   ⚖️  Liability Shift: {'SIM (emissor assume chargeback)' if eci_validation['liability_shift'] else 'NÃO (loja assume chargeback)'}")
        
        # VALIDAÇÃO CRÍTICA: Cavv obrigatório quando autenticado
        if eci_validation['status'] == 'authenticated' and not cavv:
            print(f"\n AVISO: Autenticado (ECI={eci}) mas SEM Cavv!")
            print(f"   Isso pode causar rejeição pela Cielo na autorização")
        
        print("="*80 + "\n")
        
        return {
            'is_valid': True,
            'eci': eci,
            'cavv': cavv,
            'xid': xid,
            'version': version,
            'reference_id': reference_id,
            'return_code': return_code,
            'return_message': return_message,
            **eci_validation
        }
    
    
    def _validate_eci(self, eci):
        """
        Valida ECI (Electronic Commerce Indicator) e retorna status
        
        TABELA DE ECI - Documentação Cielo:
        https://developercielo.github.io/manual/3ds#tabela-de-eci
        
        VISA, MASTERCARD, ELO:
        ┌─────┬───────────────────────────────────────────────────────────────┐
        │ ECI │ Descrição                                                     │
        ├─────┼───────────────────────────────────────────────────────────────┤
        │ 05  │ Autenticado com sucesso - Emissor validou portador            │
        │     │ LIABILITY SHIFT = SIM (emissor assume chargeback)             │
        ├─────┼───────────────────────────────────────────────────────────────┤
        │ 06  │ Autenticação tentada mas não completada                       │
        │     │ LIABILITY SHIFT = NÃO (loja assume risco)                     │
        ├─────┼───────────────────────────────────────────────────────────────┤
        │ 07  │ Autenticação falhou ou não foi realizada                      │
        │     │ LIABILITY SHIFT = NÃO (loja assume risco)                     │
        ├─────┼───────────────────────────────────────────────────────────────┤
        │ 00  │ Autenticação não disponível                                   │
        │     │ LIABILITY SHIFT = NÃO (loja assume risco)                     │
        └─────┴───────────────────────────────────────────────────────────────┘
        
        Args:
            eci: String com o ECI retornado
        
        Returns:
            dict: {
                'status': str,
                'message': str,
                'liability_shift': bool
            }
        """
        eci_str = str(eci).strip()
        
        # Normalizar (remover zeros à esquerda)
        eci_normalized = eci_str.lstrip('0') or '0'
        
        # Mapeamento completo de ECI
        eci_map = {
            '5': {
                'status': 'authenticated',
                'message': 'Transação AUTENTICADA com sucesso pelo emissor',
                'liability_shift': True,
                'recommendation': 'Prosseguir com autorização - risco mínimo'
            },
            '6': {
                'status': 'not_authenticated',
                'message': 'Autenticação TENTADA mas não completada',
                'liability_shift': False,
                'recommendation': 'Avaliar risco antes de autorizar'
            },
            '7': {
                'status': 'not_authenticated',
                'message': 'Autenticação FALHOU ou não foi realizada',
                'liability_shift': False,
                'recommendation': 'Alto risco - considerar rejeitar'
            },
            '0': {
                'status': 'not_available',
                'message': 'Autenticação NÃO DISPONÍVEL',
                'liability_shift': False,
                'recommendation': 'Emissor não suporta 3DS'
            }
        }
        
        # Buscar resultado
        result = eci_map.get(eci_normalized, {
            'status': 'unknown',
            'message': f'ECI DESCONHECIDO: {eci_str}',
            'liability_shift': False,
            'recommendation': 'Tratar como não autenticado'
        })
        
        return result
    
    
    def get_test_cards(self):
        """
        Retorna cartões de teste para autenticação 3DS em SANDBOX
        
        Documentação: https://developercielo.github.io/manual/3ds#cartões-de-teste-para-a-autenticação-3ds
        
        Returns:
            dict: Estrutura completa de cartões de teste
        """
        return CARTOES_TESTE_3DS


# ═══════════════════════════════════════════════════════════════════════════════
# CARTÕES DE TESTE PARA AUTENTICAÇÃO 3DS (AMBIENTE SANDBOX)
# ═══════════════════════════════════════════════════════════════════════════════
# Fonte: https://developercielo.github.io/manual/3ds#cartões-de-teste-para-a-autenticação-3ds
#
# Use estes cartões para testar diferentes cenários de autenticação 3DS
# em ambiente sandbox. Dados complementares:
# - CVV: qualquer 3 dígitos (ex: 123)
# - Validade: qualquer data futura (ex: 12/2030)
# - Nome: qualquer nome
# ═══════════════════════════════════════════════════════════════════════════════

CARTOES_TESTE_3DS = {
    # ─────────────────────────────────────────────────────────────────────────────
    # COM DESAFIO - Autenticação exige validação adicional do portador
    # (Desafio = popup/modal do banco solicitando senha, SMS, biometria, etc.)
    # ─────────────────────────────────────────────────────────────────────────────
    'com_desafio': {
        'sucesso': {
            'visa': '4000000000002503',
            'mastercard': '5200000000002151',
            'elo': '6505290000002190',
            'cenario': 'Autenticação COM DESAFIO - Portador autenticado com SUCESSO',
            'eci_esperado': '05',
            'liability_shift': True
        },
        'falha': {
            'visa': '4000000000002370',
            'mastercard': '5200000000002490',
            'elo': '6505290000002208',
            'cenario': 'Autenticação COM DESAFIO - Portador autenticado com FALHA',
            'eci_esperado': '07',
            'liability_shift': False
        },
        'indisponivel': {
            'visa': '4000000000002420',
            'mastercard': '5200000000002664',
            'elo': '6505290000002257',
            'cenario': 'Autenticação COM DESAFIO - Indisponível no momento',
            'eci_esperado': '00',
            'liability_shift': False
        },
        'erro_sistema': {
            'visa': '4000000000002644',
            'mastercard': '5200000000002656',
            'elo': '6505290000002265',
            'cenario': 'Autenticação COM DESAFIO - Erro de sistema durante autenticação',
            'eci_esperado': '00',
            'liability_shift': False
        }
    },
    
    # ─────────────────────────────────────────────────────────────────────────────
    # SEM DESAFIO - Autenticação silenciosa (frictionless)
    # (Sem desafio = banco valida automaticamente sem interação do usuário)
    # ─────────────────────────────────────────────────────────────────────────────
    'sem_desafio': {
        'sucesso': {
            'visa': '4000000000002701',
            'mastercard': '5200000000002235',
            'elo': '6505290000002000',
            'cenario': 'Autenticação SEM DESAFIO - Portador autenticado com SUCESSO (silencioso)',
            'eci_esperado': '05',
            'liability_shift': True
        },
        'falha': {
            'visa': '4000000000002925',
            'mastercard': '5200000000002276',
            'elo': '6505290000002018',
            'cenario': 'Autenticação SEM DESAFIO - Portador autenticado com FALHA',
            'eci_esperado': '07',
            'liability_shift': False
        }
    },
    
    # ─────────────────────────────────────────────────────────────────────────────
    # DATA ONLY - Apenas notificação (sem autenticação real)
    # (Data Only = envia dados mas não autentica - usado para análise de risco)
    # ─────────────────────────────────────────────────────────────────────────────
    'data_only': {
        'mastercard': '5200000000002805',
        'visa': '4000000000002024',
        'cenario': 'Transação DATA ONLY - Apenas notificação sem autenticação',
        'eci_esperado': '04 (Mastercard) ou 07 (Visa)',
        'liability_shift': False,
        'observacao': 'Requer parâmetro ExternalAuthentication.DataOnly = true'
    }
}


def get_cartoes_teste_3ds():
    """
    Função auxiliar para obter cartões de teste 3DS
    
    Uso:
        from payment.payment_3ds import get_cartoes_teste_3ds
        
        cartoes = get_cartoes_teste_3ds()
        
        # Cartão com desafio - sucesso
        visa_sucesso = cartoes['com_desafio']['sucesso']['visa']
        print(visa_sucesso)  # 4000000000002503
        
        # Cartão sem desafio - sucesso
        master_silencioso = cartoes['sem_desafio']['sucesso']['mastercard']
        print(master_silencioso)  # 5200000000002235
    
    Returns:
        dict: Estrutura completa de cartões de teste
    """
    return CARTOES_TESTE_3DS


def print_cartoes_teste():
    """
    Imprime tabela formatada com todos os cartões de teste 3DS
    
    Útil para desenvolvimento e debug. Execute no shell Django:
        python manage.py shell
        >>> from payment.payment_3ds import print_cartoes_teste
        >>> print_cartoes_teste()
    """
    print("\n" + "="*80)
    print("CARTÕES DE TESTE PARA AUTENTICAÇÃO 3DS - AMBIENTE SANDBOX")
    print("="*80)
    print("\nDados complementares para teste:")
    print("  CVV: qualquer 3 dígitos (ex: 123)")
    print("  Validade: qualquer data futura (ex: 12/2030)")
    print("  Nome: qualquer nome no cartão")
    
    print("\n" + "-"*80)
    print("AUTENTICAÇÃO COM DESAFIO (popup/modal do banco)")
    print("-"*80)
    
    for resultado, dados in CARTOES_TESTE_3DS['com_desafio'].items():
        print(f"\n - {resultado.upper().replace('_', ' ')}:")
        for bandeira, valor in dados.items():
            if bandeira not in ['cenario', 'eci_esperado', 'liability_shift']:
                print(f"   {bandeira.capitalize():12} {valor}")
        print(f"   Cenário: {dados['cenario']}")
        print(f"   ECI esperado: {dados['eci_esperado']}")
        print(f"   Liability Shift: {'SIM' if dados['liability_shift'] else 'NÃO'}")
    
    print("\n" + "-"*80)
    print("✨ AUTENTICAÇÃO SEM DESAFIO (silenciosa/frictionless)")
    print("-"*80)
    
    for resultado, dados in CARTOES_TESTE_3DS['sem_desafio'].items():
        print(f"\n - {resultado.upper().replace('_', ' ')}:")
        for bandeira, valor in dados.items():
            if bandeira not in ['cenario', 'eci_esperado', 'liability_shift']:
                print(f"   {bandeira.capitalize():12} {valor}")
        print(f"   Cenário: {dados['cenario']}")
        print(f"   ECI esperado: {dados['eci_esperado']}")
        print(f"   Liability Shift: {'SIM' if dados['liability_shift'] else 'NÃO'}")
    
    print("\n" + "-"*80)
    print("DATA ONLY (apenas notificação)")
    print("-"*80)
    
    dados_data_only = CARTOES_TESTE_3DS['data_only']
    print(f"\n - DATA ONLY:")
    for bandeira, valor in dados_data_only.items():
        if bandeira not in ['cenario', 'eci_esperado', 'liability_shift', 'observacao']:
            print(f"   {bandeira.capitalize():12} {valor}")
    print(f"   Cenário: {dados_data_only['cenario']}")
    print(f"   ECI esperado: {dados_data_only['eci_esperado']}")
    print(f"   Liability Shift: {'SIM' if dados_data_only['liability_shift'] else 'NÃO'}")
    if 'observacao' in dados_data_only:
        print(f"   Observação: {dados_data_only['observacao']}")
    print("\n" + "="*80 + "\n")

