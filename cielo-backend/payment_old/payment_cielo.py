import uuid
import json
import requests

from django.conf import settings
from django.utils import timezone 


# doc: https://developercielo.github.io/manual/cielo-ecommerce
class CieloPaymentGateway:
    """
    Class to handle Cielo payment gateway integration
    
    IMPORTANTE: Credenciais diferentes para Sandbox vs Produção
    """
    
    BASE_URL = getattr(settings, 'CIELO_BASE_URL')
    SALES_URL = f"{BASE_URL}/1/sales/"
    
    # IMPORTANTE: URL de consulta é diferente da URL de criação
    # Criação (POST): api.cieloecommerce.cielo.com.br
    # Consulta (GET):  apiquery.cieloecommerce.cielo.com.br
    QUERY_URL = getattr(settings, 'CIELO_QUERY_URL')
    
    def __init__(self):
        self.merchant_id = getattr(settings, 'CIELO_MERCHANT_ID', '')
        self.merchant_key = getattr(settings, 'CIELO_MERCHANT_KEY', '')
        
        print( 
            "\n[CIELO] - Inicia Cielo Payment Gateway", 
            "\n - BASE_URL: ", self.BASE_URL, 
            "\n - SALES_URL: ", self.SALES_URL, 
            "\n - QUERY_URL: ", self.QUERY_URL, 
            "\n - merchant_id: ", self.merchant_id, 
            "\n - merchant_key: ", self.merchant_key, 
        )  

    
    def _get_headers(self):
        """
        Generate headers for Cielo API requests
        """
        return {
            "accept": "application/json",
            "MerchantId": self.merchant_id,
            "MerchantKey": self.merchant_key,
            "Content-Type": "application/json"
        }
    


    def _detect_card_brand(self, card_number):
        """
        Detecta a bandeira do cartão baseado no número

        Automaticamente a cielo faz isso, se estiver usando "recorrência programada" 
        (via Recurrent.Payment), a Cielo cuida disso automaticamente.

        Cielo: https://docs.cielo.com.br/ecommerce-cielo/docs/identificadores-da-bandeira
        """
        # Remove espaços e caracteres não numéricos
        card_number = card_number.replace(" ", "").replace("-", "")
        
        # Regras básicas de detecção
        if card_number.startswith('4'):
            return 'Visa'
        elif card_number.startswith(('51', '52', '53', '54', '55')):
            return 'Master'
        elif card_number.startswith(('34', '37')):
            return 'Amex'
        elif card_number.startswith('6011') or card_number.startswith('65'):
            return 'Discover'
        elif card_number.startswith('35'):
            return 'JCB'
        elif card_number.startswith('36') or card_number.startswith('38'):
            return 'Diners'
        elif card_number.startswith('606282'):
            return 'Hipercard'
        elif card_number.startswith('636368') or card_number.startswith('438935') or card_number.startswith('504175'):
            return 'Elo'
        else:
            return 'Visa'  # Default para evitar erros se não detectar


    
    def _clean_security_code(self, security_code):
        """
        Limpa o código de segurança, removendo qualquer caractere não-numérico
        
        Args:
            security_code: Código de segurança (CVV) do cartão
            
        Returns:
            str: Apenas os dígitos numéricos
        """
        if not security_code:
            return ""
        
        # Converter para string e remover tudo que não for dígito
        cleaned = ''.join(filter(str.isdigit, str(security_code)))
        
        print(f"[DEBUG] SecurityCode original: '{security_code}' (tipo: {type(security_code).__name__})")
        print(f"[DEBUG] SecurityCode limpo: '{cleaned}' (len: {len(cleaned)})")
        
        return cleaned
    
    

    def _validate_card_data(self, card_data):
        """
        Valida dados do cartão antes de enviar para Cielo (como plugin WordPress)
        
        Args:
            card_data: Dicionário com dados do cartão
            
        Returns:
            tuple: (is_valid, error_message)
        """
        from datetime import datetime
        
        # Validar nome do titular
        cardholder_name = card_data.get('cardholder_name', '').strip()
        if not cardholder_name or len(cardholder_name) < 3:
            return False, "Nome do titular do cartão é obrigatório"
        
        # Validar número do cartão
        card_number = card_data.get('card_number', '').replace(' ', '').replace('-', '')
        if not card_number or len(card_number) < 12 or not card_number.isdigit():
            return False, "Número do cartão inválido"
        
        # Validar data de expiração
        exp_month = card_data.get('expiration_month', '').strip()
        exp_year = card_data.get('expiration_year', '').strip()
        
        if not exp_month or not exp_year:
            return False, "Data de expiração é obrigatória"
        
        try:
            month = int(exp_month)
            year = int(exp_year)
            
            # Adicionar 2000 se ano tem 2 dígitos
            if year < 100:
                year += 2000
            
            # Verificar se é uma data válida
            if month < 1 or month > 12:
                return False, "Mês de expiração inválido"
            
            # Verificar se o cartão não está expirado
            today = datetime.now()
            exp_date = datetime(year, month, 1)
            
            if exp_date < today:
                return False, "Cartão expirado"
                
        except ValueError:
            return False, "Data de expiração inválida"
        
        # Validar CVV
        security_code = str(card_data.get('security_code', '')).strip()
        cleaned_cvv = ''.join(filter(str.isdigit, security_code))
        
        if not cleaned_cvv or len(cleaned_cvv) < 3 or len(cleaned_cvv) > 4:
            return False, "Código de segurança (CVV) inválido"
        
        return True, ""



    def create_credit_payment(self, card_data, transaction, client_ip=None, session_id=None):
        """
        Cria um pagamento com cartão de crédito com Cielo
        
        Args:
            card_data: Dicionário com informações do cartão
            transaction: Instância de PaymentTransaction
            client_ip: Endereço IP do cliente (opcional)
            session_id: ID da sessão de antifraude do frontend (opcional)
        """

        pedido = transaction.checkout_link.pedido

        comprador = pedido.comprador

        endereco_fatura = pedido.endereco_fatura
        
        # IMPORTANTE: Usar valor_com_juros se tiver parcelamento, senão usar valor original
        amount = transaction.valor  # Valor original em centavos
        
        installments = card_data.get("installments", 1) # Número de parcelas enviado pelo frontend (pode ser 1 para à vista)

        valor_com_juros_frontend = card_data.get("valor_com_juros")  # Valor (Decimal) já com juros calculado
        
        # Se tiver parcelamento e valor com juros do frontend, usar esse valor
        if installments > 1 and valor_com_juros_frontend: 
            amount = int(float(valor_com_juros_frontend) * 100) # Frontend envia em reais, converter para centavos
            print(f"[PAYMENT CREDITO] COM JUROS: R$ {valor_com_juros_frontend} = {amount} centavos ({installments}x)")
        else:
            print(f"[PAYMENT CREDITO] SEM JUROS: R$ {amount/100:.2f} = {amount} centavos (1x)")

        print("\n===== INICIANDO PROCESSAMENTO DE PAGAMENTO CIELO =====\n"
              "\n",
              f"Pedido: {pedido.id}"
              "\n",
              f"\nDados do Comprador:"
              f"\n - Nome: {comprador.name}",
              f"\n - Email: {comprador.email}",
              f"\n - Telefone: {comprador.telefone}",
              "\n",
              f"Valor Total: R$ {amount/100:.2f} ({amount} centavos)"
              "\n"
              f"Parcelas: {installments}x"
              "\n",
              f"Produtos: {pedido.produtos.count()}"
              "\n",
            )
        
        # VALIDAR DADOS DO CARTÃO (como plugin WordPress)
        is_valid, error_message = self._validate_card_data(card_data)
        if not is_valid: # Se não for válido
            print(f"[VALIDATE CARD]: {error_message}")

            transaction.status = "denied"
            transaction.error_message = error_message
            transaction.save()

            return {
                "status": "DENIED",
                "error": error_message,
                "error_code": "VALIDATION_ERROR"
            }
        
        print(f"[VALIDATE CARD]: Dados do cartão validados com sucesso")

        # Gerar MerchantOrderId único
        merchant_order_id = f"DMC-{pedido.id}-{uuid.uuid4().hex[:8]}".upper()
        
        # Detectar bandeira do cartão
        card_brand = self._detect_card_brand(card_data.get("card_number"))
        
        # Preparar dados do comprador
        customer_name = comprador.name

        # campo field {cpf} = cpf e cnpj
        customer_identity = comprador.cpf.replace(".", "").replace("-", "").replace("/", "") if comprador.cpf else "00000000000"
        
        # Preparar dados do endereço de fatura
        address_data = {}
        if endereco_fatura: 
            address_data = {
                "Street": endereco_fatura.endereco or "Rua Não Informada",
                "Number": endereco_fatura.numero or "S/N",
                "Complement": endereco_fatura.complemento or "",
                "ZipCode": endereco_fatura.cep.replace("-", "") if endereco_fatura.cep else "00000000",
                "City": endereco_fatura.cidade or "Cidade",
                "State": endereco_fatura.estado or "SP",
                "Country": "BRA"
            } 
            
        # Preparar payload para Cielo
        payload = {
            "MerchantOrderId": merchant_order_id,
            "Customer": {
                "Name": customer_name,
                "Email": comprador.email,
                "Identity": customer_identity,
                "IdentityType": "CPF" if len(customer_identity) == 11 else "CNPJ",
                "Address": address_data,
                "DeliveryAddress": address_data,
                "Billing": {
                    "Street": address_data.get("Street"),
                    "Number": address_data.get("Number"),
                    "Complement": address_data.get("Complement"),
                    "Neighborhood": endereco_fatura.bairro if endereco_fatura and endereco_fatura.bairro else "Centro",
                    "City": address_data.get("City"),
                    "State": address_data.get("State"),
                    "Country": "BR",
                    "ZipCode": address_data.get("ZipCode")
                }
            },
            "Payment": {
                "Type": "CreditCard",
                "Amount": amount, # Valor em centavos
                "Currency": "BRL",
                "Country": "BRA",
                "Installments": card_data.get("installments", 1),  # Número de parcelas do frontend
                "Interest": card_data.get("interest", "ByMerchant"),  # Tipo de juros do frontend
                "Capture": True,  # Captura automática
                "Authenticate": False, # Sem 3DS por padrão
                "SoftDescriptor": "DMC*CHECKOUT",
                "CreditCard": {
                    "CardNumber": card_data.get("card_number", "").replace(" ", ""),
                    "Holder": card_data.get("cardholder_name", ""),
                    "ExpirationDate": f"{card_data.get('expiration_month', '')}/20{card_data.get('expiration_year', '')}",
                    "SecurityCode": self._clean_security_code(card_data.get("security_code", "")),
                    "SaveCard": False,
                    "Brand": card_brand,
                    "CardOnFile": {
                        "Usage": "First",  # Primeira transação com este cartão
                        "Reason": "Recurring"  # Permite cobranças futuras
                    }
                }
            }
        }
        
        # ADICIONAR AUTENTICAÇÃO 3DS SE DISPONÍVEL
        # O frontend envia o resultado da autenticação 3DS em card_data['auth_3ds']
        if 'auth_3ds' in card_data:
            auth_3ds = card_data['auth_3ds']
 
            print(
                "\n[3DS] RESULTADO DA AUTENTICAÇÃO 3DS DETECTADO" 
                "\n",
                f"   ECI: {auth_3ds.get('Eci') or auth_3ds.get('eci')}",
                "\n",
                f"   CAVV: {(auth_3ds.get('Cavv') or auth_3ds.get('cavv', ''))[:40]}...",
                "\n",
                f"   XID: {auth_3ds.get('Xid') or auth_3ds.get('xid', 'N/A')}",
                "\n",
                f"   Version: {auth_3ds.get('Version') or auth_3ds.get('version', '2')}",
                "\n",
                f"   ReferenceId: {auth_3ds.get('ReferenceId') or auth_3ds.get('reference_id', 'N/A')}"
                "\n"
            )
            
            # Validar resultado usando o módulo 3DS
            from .payment_3ds import Cielo3DSAuthenticator
            authenticator = Cielo3DSAuthenticator()
            validation_result = authenticator.validate_authentication_result(auth_3ds)
            
            print(f"\n[3DS] VALIDAÇÃO DO RESULTADO 3DS:",
                    f"\n  Status: {validation_result['status'].upper()}",
                    f"\n  Mensagem: {validation_result['message']}",
                    f"\n  Liability Shift: {'SIM' if validation_result['liability_shift'] else 'NÃO'}"
                  )
            
            # Adicionar autenticação externa ao payload
            payload["Payment"]["ExternalAuthentication"] = {
                "Cavv": auth_3ds.get('Cavv') or auth_3ds.get('cavv'),
                "Xid": auth_3ds.get('Xid') or auth_3ds.get('xid'),
                "Eci": auth_3ds.get('Eci') or auth_3ds.get('eci'),
                "Version": auth_3ds.get('Version') or auth_3ds.get('version', '2'),
                "ReferenceId": auth_3ds.get('ReferenceId') or auth_3ds.get('reference_id')
            }
            
            # VALIDAÇÃO CRÍTICA: Cavv obrigatório para transações autenticadas (ECI 5)
            eci_normalized = str(validation_result['eci']).lstrip('0') or '0'
            if eci_normalized == '5' and not payload["Payment"]["ExternalAuthentication"]["Cavv"]:
                print(f"\n[3DS] AVISO CRÍTICO: ECI 5 (autenticado) mas SEM Cavv!")
                # Isso PODE SER REJEITADO pela Cielo na autorização!
            
            print(f"\n[3DS] Autenticação 3DS adicionada ao payload Cielo") 
        else:
            print(f"\n[3DS] Nenhum resultado 3DS fornecido - transação SEM autenticação")
        

        # Adicionar antifraude se session_id foi fornecido
        if session_id:
            
            # Preparar itens do carrinho para antifraude
            cart_items = []
            for produto_pedido in pedido.produtos.all():
                cart_items.append({
                    "Name": produto_pedido.produto.nome[:50],  # Nome do produto (max 50 chars)
                    "Quantity": produto_pedido.quantidade, # Quantidade do produto
                    "Sku": str(produto_pedido.produto.id), # ID do produto como SKU
                    "UnitPrice": int(produto_pedido.preco_unitario * 100)  # Converter para centavos
                })
            
            payload["Payment"]["FraudAnalysis"] = {
                "Sequence": "AnalyseFirst",
                "SequenceCriteria": "Always",
                "FingerPrintId": session_id, # ID da sessão de antifraude do frontend 
                "Provider": "Cybersource", # Provedor de antifraude
                "TotalOrderAmount": amount, # Valor total (com juros se tiver) do pedido em centavos
                "Browser": {
                    "Email": comprador.email, # Email do comprador
                    "IpAddress": client_ip, # IP do cliente
                    "CookiesAccepted": False 
                },
                "Cart": {
                    "Items": cart_items
                },
                "MerchantDefinedFields": [
                    {
                        "Id": 1,
                        "Value": "Produtos Feira"
                    }
                ],
                "Shipping": {
                    "Addressee": customer_name,
                    "Method": "None"  # Retirada na feira
                }
            }

            print(f"[ANTIFRAUDE] habilitado com FingerPrintId: {session_id}")
        
        if settings.DEBUG: 
            payment = payload.get("Payment", {})
            card = payment.get("CreditCard", {})

            print(
                "\n[PAYLOAD] ENVIANDO REQUISIÇÃO DE PAGAMENTO CIELO",
                f"\n - URL: {self.SALES_URL}",
                f"\n - MerchantOrderId: {merchant_order_id}",
                f"\n - Valor: R$ {payment.get('Amount', 0)/100:.2f}",
                f"\n - Parcelas: {payment.get('Installments')}",
                f"\n - Cartão final: **** **** **** {card.get('CardNumber', '')[-4:]}",
                f"\n - Bandeira: {card.get('Brand')}",
                f"\n - Authenticate: {payment.get('Authenticate')}",
                f"\n - Capture: {payment.get('Capture')}",
                f"\n - Provider: {payment.get('Provider')}",
                f"\n - Headers: {json.dumps(self._get_headers(), indent=2)}",
                # f"\n - Payload:", json.dumps(payload, indent=2)
            ) 

        headers = self._get_headers()

        try:
            response = requests.post(self.SALES_URL, json=payload, headers=headers, timeout=30)
            
            print("\n [CIELO] RESPOSTA DA REQUISIÇÃO DE PAGAMENTO CIELO",
                f"\nStatus code: {response.status_code}"
                ) 
            
            try:
                response_json = response.json() 

                payment = response_json.get("Payment", {})
                customer = response_json.get("Customer", {})

                print(
                    f"""\n
                    [CIELO] Transação criada (CRÉDITO)
                    Pedido: {response_json.get("MerchantOrderId")}
                    Cliente: {customer.get("Name")} ({customer.get("Identity")})

                    Status: {payment.get("Status")}
                    Mensagem: {payment.get("ReturnMessage")}
                    Código Retorno: {payment.get("ReturnCode")}

                    Valor: R$ {payment.get("Amount", 0) / 100:.2f}
                    Valor Capturado: {payment.get("CapturedAmount", 0)} (em cents)
                    Parcelas: {payment.get("Installments")}
                    Tipo Juros: {payment.get("Interest", "N/A")}
                    Bandeira: {payment.get("CreditCard", {}).get("Brand")}

                    TID: {payment.get("Tid")}
                    ProofOfSale: {payment.get("ProofOfSale")}
                    AuthCode: {payment.get("AuthorizationCode")}
                    PaymentId: {payment.get("PaymentId")}
                    """
                )

            except Exception as e:
                print(f"[CIELO] Erro ao processar resposta JSON: {e}")
                print(f"[CIELO] Resposta raw: {response.text}")
                return {
                    "status": "DENIED",
                    "error": "Erro ao processar resposta da Cielo",
                    "details": response.text
                }
            
            # [CIELO] Processar resposta da Cielo
            if response.status_code in [200, 201]: 
                payment_data = response_json.get("Payment", {})
                payment_status = payment_data.get("Status")
                payment_id = payment_data.get("PaymentId")
                merchant_order_id = response_json.get("MerchantOrderId", '') 
                return_code = payment_data.get('ReturnCode', '')
                return_message = payment_data.get('ReturnMessage', '')
                
                # [CIELO] VALIDAÇÃO CRÍTICA: Verificar ReturnCode ANTES de mapear Status
                # ReturnCode != "00" (ou "000" ou "0000") = ERRO, mesmo com Status 0 ou 1
                # Códigos de erro comuns:
                # - "002" = Credenciais Inválidas
                # - "057" = Cartão expirado
                # - "051" = Saldo insuficiente
                # - "070" = Problemas com cartão
                # - "099" = Timeout
                
                # Lista de ReturnCodes de SUCESSO (todos os outros são erro)
                SUCCESS_CODES = ["00", "000", "0000", "4", "6"]  # 4=aprovado, 6=aprovado com retry
                if return_code not in SUCCESS_CODES:
                    # ERRO detectado via ReturnCode - Forçar status DENIED
                    print("="*70)
                    print(f"\n[CIELO] Pagamento NEGADO via ReturnCode:"
                        f"   ReturnCode: {return_code}",
                        f"   ReturnMessage: {return_message}",
                        f"   Status original Cielo: {payment_status}",
                    )
                    print("="*70)

                    # [CIELO] ERRO ESPECIAL: GF = Problema grave com credenciais/integração
                    if return_code == "GF":
                        error_msg = f"ERRO CRÍTICO CIELO (GF): {return_message}. Entre em contato com o suporte da Cielo."
                        print(f"{error_msg}")  
                        # Aqui poderíamos enviar um alerta por email para o time de suporte 
                        # ou logar em sistema de monitoramento
                    
                    transaction.status = "denied" # Forçar status denied se ReturnCode indica erro, mesmo que Status seja 0 ou 1
                    transaction.transaction_id = payment_id # Registrar PaymentId mesmo em caso de erro para facilitar rastreamento
                    transaction.merchant_order_id = merchant_order_id # Registrar MerchantOrderId para rastreamento
                    transaction.payment_response = response_json # Registrar resposta completa para análise futura
                    transaction.error_message = return_message # Registrar mensagem de erro da Cielo
                    transaction.save() # Salvar alterações no banco de dados
                    
                    return {
                        "status": "DENIED",
                        "payment_id": payment_id,
                        "merchant_order_id": merchant_order_id,
                        "return_code": return_code,
                        "return_message": return_message,
                        "denial_reason": return_message,
                        "raw_response": response_json
                    }
                
                # [CIELO] Mapear status da Cielo para nosso padrão
                # Status Cielo: 
                # 0=NotFinished, 
                # 1=Authorized, 
                # 2=PaymentConfirmed, 
                # 3=Denied, 
                # 10=Voided, 
                # 11=Refunded, 
                # 12=Pending, 
                # 13=Aborted
                status_map = {
                    0: "processing",  # NotFinished
                    1: "approved",    # Authorized
                    2: "approved",    # PaymentConfirmed
                    3: "denied",      # Denied
                    10: "canceled",   # Voided
                    11: "refunded",   # Refunded
                    12: "pending",    # Pending
                    13: "canceled"    # Aborted
                }
                
                mapped_status = status_map.get(payment_status, "pending")
                
                # Atualizar transação
                transaction.status = mapped_status
                transaction.transaction_id = payment_id
                transaction.merchant_order_id = merchant_order_id
                transaction.payment_response = response_json
                
                # Armazenar mensagem de erro se houver
                if mapped_status in ["denied", "canceled"]:
                    transaction.error_message = return_message
                
                transaction.save()
                
                print(
                    f"\n[CIELO] PAYMENT PROCESSED (CRÉDITO)",
                    f"\n  Status Cielo: {payment_status} → Sistema: {mapped_status}",
                    f"\n  PaymentId: {payment_id}",
                    f"\n  ReturnCode: {return_code}",
                    f"\n  ReturnMessage: {return_message}"
                )
                
                ## [CIELO] LOG ADICIONAL PARA ANÁLISE DE 3DS
                ## [3DS] VALIDAÇÃO DO ECI NA RESPOSTA (se houve autenticação 3DS)
                ## Documentação: "Para validar se a autenticação foi acatada na resposta da autorização,
                ## considere o ECI fora do nó Payment.ExternalAuthentication"
                # eci_response = payment_data.get('Eci')
                # if eci_response:
                #     print(
                #         f"\n[3DS][ECI] Retornado pela Cielo na autorização:",
                #         f"\n   ECI: {eci_response}" 
                #     )

                #     # [3DS] Validar ECI usando módulo 3DS
                #     from .payment_3ds import Cielo3DSAuthenticator
                #     authenticator = Cielo3DSAuthenticator()
                #     eci_validation = authenticator._validate_eci(eci_response)
                    
                #     print(f"\n[3DS] VALIDAÇÃO DO RESULTADO 3DS:",
                #         f"\n  Status: {eci_validation['status'].upper()}",
                #         f"\n  Mensagem: {eci_validation['message']}",
                #         f"\n  Liability Shift: {'SIM' if eci_validation['liability_shift'] else 'NÃO'}"
                #     ) 

                #     # IMPORTANTE: Se foi enviado 3DS mas Cielo retornou ECI diferente, alertar
                #     if 'auth_3ds' in card_data:
                #         eci_sent = card_data['auth_3ds'].get('Eci') or card_data['auth_3ds'].get('eci')
                #         if str(eci_sent) != str(eci_response):
                #             print(f"\n [3DS] ATENÇÃO: ECI MUDOU durante autorização!",
                #                 f"   ECI enviado: {eci_sent}",
                #                 f"   ECI retornado: {eci_response}",
                #                 f"   Possível motivo: Cielo reavaliou autenticação",
                #                 f"   Impacto: Pode afetar análise de risco e regras de negócio baseadas em ECI"
                #             )

                # Log adicional se foi negado ou cancelado
                if mapped_status in ["denied", "canceled"]:
                    print(f"\n[3DS] Motivo negação (CRÉDITO): {payment_data.get('ReturnMessage', 'Não informado')}")
                    if payment_data.get('ProofOfSale'):
                        print(f"[3DS] ProofOfSale: {payment_data.get('ProofOfSale')}")

                # Retornar resposta padronizada
                # Mapear status interno para status de resposta
                if mapped_status == "approved":
                    response_status = "APPROVED"
                elif mapped_status == "denied":
                    response_status = "DENIED"
                elif mapped_status == "canceled":
                    response_status = "CANCELED"
                elif mapped_status == "processing":
                    response_status = "PROCESSING"
                else: # Senao é "pending"
                    response_status = "PENDING"
                
                return {
                    "status": response_status,
                    "payment_id": payment_id,
                    "merchant_order_id": merchant_order_id,
                    "cielo_status": payment_status,
                    "return_code": payment_data.get("ReturnCode"),
                    "return_message": payment_data.get("ReturnMessage"),
                    "denial_reason": payment_data.get("ReturnMessage") if mapped_status == "denied" else "",
                    "raw_response": response_json
                }
            
            else:
                # Erro na requisição
                if isinstance(response_json, list) and len(response_json) > 0:
                    error_message = response_json[0].get("Message", "Erro desconhecido")
                    error_code = response_json[0].get("Code", "")

                elif isinstance(response_json, dict):
                    error_message = response_json.get("Message", "Erro desconhecido")
                    error_code = response_json.get("Code", "")

                else:
                    error_message = "Erro desconhecido"
                    error_code = ""
                
                print(f"[CIELO] Erro na requisição (CRÉDITO): [{error_code}] {error_message}")
                
                transaction.status = "denied"
                transaction.payment_response = response_json if isinstance(response_json, dict) else {"errors": response_json}
                transaction.save()
                
                return {
                    "status": "DENIED",
                    "error": error_message,
                    "error_code": error_code,
                    "details": response_json
                }
                
        except requests.exceptions.Timeout:
            print("[CIELO] Timeout na requisição para Cielo (CRÉDITO)")
            return {
                "status": "DENIED",
                "error": "Timeout na comunicação com Cielo"
            }
        except Exception as e:
            print(f"[CIELO] Exceção ao processar (CRÉDITO): {str(e)}")
            return {
                "status": "DENIED",
                "error": str(e)
            }



    def create_debit_payment(self, card_data, transaction, client_ip=None, session_id=None):
        """
        Cria um pagamento com cartão de DÉBITO na Cielo
        
        IMPORTANTE: Cartão de débito REQUER autenticação 3DS obrigatória
        Documentação Cielo: "Para débito, Authenticate deve ser true"
        
        Args:
            card_data: Dicionário com informações do cartão
            transaction: Instância de PaymentTransaction
            client_ip: Endereço IP do cliente (opcional)
            session_id: ID da sessão de antifraude do frontend (opcional)
        """
        pedido = transaction.checkout_link.pedido

        comprador = pedido.comprador

        endereco_fatura = pedido.endereco_fatura
        
        # DÉBITO: Sempre 1x (à vista)
        amount = transaction.valor  # Valor em centavos

        installments = 1
        
        print("\n===== INICIANDO PROCESSAMENTO DE PAGAMENTO CIELO (DÉBITO) =====\n"
              "\n",
              f"Pedido: {pedido.id}"
              "\n",
              f"\nDados do Comprador:"
              f"\n - Nome: {comprador.name}",
              f"\n - Email: {comprador.email}",
              f"\n - Telefone: {comprador.telefone}",
              "\n",
              f"Valor: R$ {amount/100:.2f} ({amount} centavos)"
              "\n",
              f"Parcelas: {installments}x (DÉBITO - sempre à vista)\n"
              "\n",
              f"Produtos: {pedido.produtos.count()}"
              "\n",
            ) 
        
        # VALIDAR DADOS DO CARTÃO
        is_valid, error_message = self._validate_card_data(card_data)
        if not is_valid:
            print(f"Validação falhou: {error_message}")
            transaction.status = "denied"
            transaction.error_message = error_message
            transaction.save()
            return {
                "status": "DENIED",
                "error": error_message,
                "error_code": "VALIDATION_ERROR"
            }
        
        print(f"[VALIDATE CARD]: Dados do cartão validados com sucesso")
        
        # Gerar MerchantOrderId único
        merchant_order_id = f"DMC-DEB-{pedido.id}-{uuid.uuid4().hex[:8]}".upper()
        
        # Detectar bandeira do cartão
        card_brand = self._detect_card_brand(card_data.get("card_number"))
        
        # Preparar dados do comprador
        customer_name = comprador.name

        # campo field {cpf} = cpf e cnpj
        customer_identity = comprador.cpf.replace(".", "").replace("-", "").replace("/", "") if comprador.cpf else "00000000000"
        
        # Preparar dados do endereço
        address_data = {}
        if endereco_fatura:
            address_data = {
                "Street": endereco_fatura.endereco or "Rua Não Informada",
                "Number": endereco_fatura.numero or "S/N",
                "Complement": endereco_fatura.complemento or "",
                "ZipCode": endereco_fatura.cep.replace("-", "") if endereco_fatura.cep else "00000000",
                "City": endereco_fatura.cidade or "Cidade",
                "State": endereco_fatura.estado or "SP",
                "Country": "BRA"
            }
        
        # Preparar payload Cielo
        payload = {
            "MerchantOrderId": merchant_order_id,
            "Customer": {
                "Name": customer_name,
                "Email": comprador.email,
                "Identity": customer_identity,
                "IdentityType": "CPF" if len(customer_identity) == 11 else "CNPJ",
                "Address": address_data,
                "DeliveryAddress": address_data,
                "Billing": {
                    "Street": address_data.get("Street"),
                    "Number": address_data.get("Number"),
                    "Complement": address_data.get("Complement"),
                    "Neighborhood": endereco_fatura.bairro if endereco_fatura and endereco_fatura.bairro else "Centro",
                    "City": address_data.get("City"),
                    "State": address_data.get("State"),
                    "Country": "BR",
                    "ZipCode": address_data.get("ZipCode")
                }
            },
            "Payment": {
                "Type": "DebitCard",  # DÉBITO
                "Amount": amount,
                "Currency": "BRL",
                "Country": "BRA",
                "Installments": 1,  # DÉBITO = sempre 1x
                "Capture": True,
                "Authenticate": True,  # 3DS OBRIGATÓRIO para débito
                "SoftDescriptor": "DMC*FEIRA",
                "DebitCard": {  # Usar DebitCard em vez de CreditCard
                    "CardNumber": card_data.get("card_number", "").replace(" ", ""),
                    "Holder": card_data.get("cardholder_name", ""),
                    "ExpirationDate": f"{card_data.get('expiration_month', '')}/20{card_data.get('expiration_year', '')}",
                    "SecurityCode": self._clean_security_code(card_data.get("security_code", "")),
                    "Brand": card_brand
                }
            }
        }
        
        # ADICIONAR AUTENTICAÇÃO 3DS SE DISPONÍVEL
        # O frontend envia o resultado da autenticação 3DS em card_data['auth_3ds']
        if 'auth_3ds' in card_data:
            auth_3ds = card_data['auth_3ds']
            
            print(
                "\n[3DS] RESULTADO DA AUTENTICAÇÃO 3DS DETECTADO" 
                "\n",
                f"   ECI: {auth_3ds.get('Eci') or auth_3ds.get('eci')}",
                "\n",
                f"   CAVV: {(auth_3ds.get('Cavv') or auth_3ds.get('cavv', ''))[:40]}...",
                "\n",
                f"   XID: {auth_3ds.get('Xid') or auth_3ds.get('xid', 'N/A')}",
                "\n",
                f"   Version: {auth_3ds.get('Version') or auth_3ds.get('version', '2')}",
                "\n",
                f"   ReferenceId: {auth_3ds.get('ReferenceId') or auth_3ds.get('reference_id', 'N/A')}"
                "\n"
            )
            
            # Validar resultado
            from .payment_3ds import Cielo3DSAuthenticator
            authenticator = Cielo3DSAuthenticator()
            validation_result = authenticator.validate_authentication_result(auth_3ds)
            
            print(f"\n[3DS] VALIDAÇÃO DO RESULTADO:",
                    f"\n  Status: {validation_result['status'].upper()}",
                    f"\n  Mensagem: {validation_result['message']}",
                    f"\n  Liability Shift: {'SIM' if validation_result['liability_shift'] else 'NÃO'}"
                  )
            
            # Adicionar ao payload
            payload["Payment"]["ExternalAuthentication"] = {
                "Cavv": auth_3ds.get('Cavv') or auth_3ds.get('cavv'),
                "Xid": auth_3ds.get('Xid') or auth_3ds.get('xid'),
                "Eci": auth_3ds.get('Eci') or auth_3ds.get('eci'),
                "Version": auth_3ds.get('Version') or auth_3ds.get('version', '2'),
                "ReferenceId": auth_3ds.get('ReferenceId') or auth_3ds.get('reference_id')
            }

            # VALIDAÇÃO CRÍTICA: Cavv obrigatório para transações autenticadas (ECI 5)
            eci_normalized = str(validation_result['eci']).lstrip('0') or '0'
            if eci_normalized == '5' and not payload["Payment"]["ExternalAuthentication"]["Cavv"]:
                print(f"\n[3DS] AVISO CRÍTICO: ECI 5 (autenticado) mas SEM Cavv!")
                # Isso PODE SER REJEITADO pela Cielo na autorização!
            
            print(f"\n[3DS] Autenticação 3DS adicionada ao payload DÉBITO")  
        else:
            print(f"\n[3DS] Nenhum resultado 3DS fornecido - transação SEM autenticação")
            print(f"\n[3DS] Débito REQUER autenticação 3DS obrigatória")

        if settings.DEBUG:
            payment = payload.get("Payment", {})
            card = payment.get("DebitCard", {}) 
            print(
                "\n[PAYLOAD] ENVIANDO REQUISIÇÃO DE PAGAMENTO CIELO (DÉBITO)",
                f"\n - URL: {self.SALES_URL}",
                f"\n - MerchantOrderId: {merchant_order_id}",
                f"\n - Valor: R$ {payment.get('Amount', 0)/100:.2f}",
                f"\n - Cartão final: **** **** **** {card.get('CardNumber', '')[-4:]}",
                f"\n - Bandeira: {card.get('Brand')}",
                f"\n - Provider: {payment.get('Provider')}",
                f"\n - Authenticate: {payment.get('Authenticate')}",
                # f"\n - Payload:", json.dumps(payload, indent=2)
            )
        
        headers = self._get_headers()
        
        try:
            response = requests.post(self.SALES_URL, json=payload, headers=headers, timeout=30)
            
            print("\n [CIELO] RESPOSTA DA REQUISIÇÃO DE PAGAMENTO CIELO (DÉBITO)",
                f"\nStatus code: {response.status_code}"
                ) 
            
            try:
                response_json = response.json()

                payment = response_json.get("Payment", {})
                customer = response_json.get("Customer", {})

                print(
                    f"""\n
                    [CIELO] Transação criada (DÉBITO)
                    Pedido: {response_json.get("MerchantOrderId")}
                    Cliente: {customer.get("Name")} ({customer.get("Identity")})

                    Status: {payment.get("Status")}
                    Mensagem: {payment.get("ReturnMessage")}
                    Código Retorno: {payment.get("ReturnCode")}

                    Valor: R$ {payment.get("Amount", 0) / 100:.2f}
                    Tipo: {payment.get("Type")}
                    Bandeira: {payment.get("DebitCard", {}).get("Brand")}

                    TID: {payment.get("Tid")}
                    ProofOfSale: {payment.get("ProofOfSale")}
                    AuthCode: {payment.get("AuthorizationCode")}
                    PaymentId: {payment.get("PaymentId")}
                    
                    Autenticação 3DS:
                    - Authenticate: {payment.get("Authenticate")}
                    - ECI: {payment.get("Eci")}
                    - ExternalAuth Version: {payment.get("ExternalAuthentication", {}).get("Version", "N/A")}
                    - CAVV: {payment.get("ExternalAuthentication", {}).get("Cavv", "N/A")[:30]}...
                    - XID: {payment.get("ExternalAuthentication", {}).get("Xid", "N/A")[:30]}...
                    - ReferenceId: {payment.get("ExternalAuthentication", {}).get("ReferenceId", "N/A")}
                    
                    Captura:
                    - CapturedAmount: R$ {payment.get("CapturedAmount", 0) / 100:.2f}
                    - CapturedDate: {payment.get("CapturedDate", "N/A")}
                    
                    Outros:
                    - SentOrderId: {payment.get("SentOrderId")}
                    - ReceivedDate: {payment.get("ReceivedDate")}
                    - Provider: {payment.get("Provider")}
                    - SolutionType: {payment.get("SolutionType", "N/A")}
                    """
                )

            except Exception as e:
                print(f"Erro ao processar resposta JSON: {e}")
                print(f"Resposta raw: {response.text}")
                return {
                    "status": "DENIED",
                    "error": "Erro ao processar resposta da Cielo",
                    "details": response.text
                }
            
            # Processar resposta
            if response.status_code in [200, 201]:
                payment_data = response_json.get("Payment", {})
                payment_status = payment_data.get("Status")
                payment_id = payment_data.get("PaymentId")
                merchant_order_id = response_json.get("MerchantOrderId", '') 
                return_code = payment_data.get('ReturnCode', '')
                return_message = payment_data.get('ReturnMessage', '')
                
                # [CIELO] VALIDAÇÃO CRÍTICA: Verificar ReturnCode ANTES de mapear Status
                # ReturnCode != "00" (ou "000" ou "0000") = ERRO, mesmo com Status 0 ou 1
                # Códigos de erro comuns:
                # - "002" = Credenciais Inválidas
                # - "057" = Cartão expirado
                # - "051" = Saldo insuficiente
                # - "070" = Problemas com cartão
                # - "099" = Timeout

                # Validar ReturnCode
                SUCCESS_CODES = ["00", "000", "0000", "4", "6"]
                if return_code not in SUCCESS_CODES:
                    # ERRO detectado via ReturnCode - Forçar status DENIED
                    print("="*70)
                    print(f"\n[CIELO] Pagamento NEGADO (DÉBITO) via ReturnCode:"
                        f"   ReturnCode: {return_code}",
                        f"   ReturnMessage: {return_message}",
                        f"   Status original Cielo: {payment_status}",
                    )
                    print("="*70)
                    
                    # [CIELO] ERRO ESPECIAL: GF = Problema grave com credenciais/integração
                    if return_code == "GF":
                        error_msg = f"ERRO CRÍTICO CIELO (GF): {return_message}. Entre em contato com o suporte da Cielo."
                        print(f"{error_msg}")  
                        # Aqui poderíamos enviar um alerta por email para o time de suporte 
                        # ou logar em sistema de monitoramento

                    transaction.status = "denied"
                    transaction.transaction_id = payment_id
                    transaction.merchant_order_id = merchant_order_id
                    transaction.payment_response = response_json
                    transaction.error_message = return_message
                    transaction.save()
                    
                    return {
                        "status": "DENIED",
                        "payment_id": payment_id,
                        "merchant_order_id": merchant_order_id,
                        "return_code": return_code,
                        "return_message": return_message,
                        "denial_reason": return_message,
                        "raw_response": response_json
                    }
                
                # [CIELO] Mapear status da Cielo para nosso padrão
                # Status Cielo: 
                # 0=NotFinished, 
                # 1=Authorized, 
                # 2=PaymentConfirmed, 
                # 3=Denied, 
                # 10=Voided, 
                # 11=Refunded, 
                # 12=Pending, 
                # 13=Aborted 
                status_map = {
                    0: "processing",  # NotFinished
                    1: "approved",    # Authorized
                    2: "approved",    # PaymentConfirmed
                    3: "denied",      # Denied
                    10: "canceled",   # Voided
                    11: "refunded",   # Refunded
                    12: "pending",    # Pending
                    13: "canceled"    # Aborted
                }
                
                mapped_status = status_map.get(payment_status, "pending")
                
                # Atualizar transação
                transaction.status = mapped_status
                transaction.transaction_id = payment_id
                transaction.merchant_order_id = merchant_order_id
                transaction.payment_response = response_json
                
                if mapped_status in ["denied", "canceled"]:
                    transaction.error_message = return_message
                
                transaction.save()
                
                print(
                    f"\n[CIELO] PAYMENT PROCESSED (CRÉDITO)",
                    f"\n  Status Cielo: {payment_status} → Sistema: {mapped_status}",
                    f"\n  PaymentId: {payment_id}",
                    f"\n  ReturnCode: {return_code}",
                    f"\n  ReturnMessage: {return_message}",
                    f"\n  Authenticate: {payment_data.get('Authenticate')}",
                    f"\n  ECI: {payment_data.get('Eci')}",
                    f"\n  ProofOfSale: {payment_data.get('ProofOfSale')}",
                    f"\n  CapturedAmount: R$ {payment_data.get('CapturedAmount', 0)/100:.2f}"
                )

                ## [CIELO] LOG ADICIONAL PARA ANÁLISE DE 3DS
                ## [3DS] VALIDAÇÃO DO ECI NA RESPOSTA (se houve autenticação 3DS)
                ## Documentação: "Para validar se a autenticação foi acatada na resposta da autorização,
                ## considere o ECI fora do nó Payment.ExternalAuthentication"
                # eci_response = payment_data.get('Eci')
                # if eci_response:
                #     print(
                #         f"\n[3DS][ECI] Retornado pela Cielo na autorização:",
                #         f"\n   ECI: {eci_response}" 
                #     )

                #     # [3DS] Validar ECI usando módulo 3DS
                #     from .payment_3ds import Cielo3DSAuthenticator
                #     authenticator = Cielo3DSAuthenticator()
                #     eci_validation = authenticator._validate_eci(eci_response)
                    
                #     print(f"\n[3DS] VALIDAÇÃO DO RESULTADO 3DS:",
                #         f"\n  Status: {eci_validation['status'].upper()}",
                #         f"\n  Mensagem: {eci_validation['message']}",
                #         f"\n  Liability Shift: {'SIM' if eci_validation['liability_shift'] else 'NÃO'}"
                #     ) 

                #     # IMPORTANTE: Se foi enviado 3DS mas Cielo retornou ECI diferente, alertar
                #     if 'auth_3ds' in card_data:
                #         eci_sent = card_data['auth_3ds'].get('Eci') or card_data['auth_3ds'].get('eci')
                #         if str(eci_sent) != str(eci_response):
                #             print(f"\n [3DS] ATENÇÃO: ECI MUDOU durante autorização!",
                #                 f"   ECI enviado: {eci_sent}",
                #                 f"   ECI retornado: {eci_response}",
                #                 f"   Possível motivo: Cielo reavaliou autenticação",
                #                 f"   Impacto: Pode afetar análise de risco e regras de negócio baseadas em ECI"
                #             )

                # Log adicional se foi negado ou cancelado
                if mapped_status in ["denied", "canceled"]:
                    print(f"\n[3DS] Motivo negação (CRÉDITO): {payment_data.get('ReturnMessage', 'Não informado')}")
                    if payment_data.get('ProofOfSale'):
                        print(f"[3DS] ProofOfSale (CRÉDITO): {payment_data.get('ProofOfSale')}")

                # Mapear para resposta
                if mapped_status == "approved":
                    response_status = "APPROVED"
                elif mapped_status == "denied":
                    response_status = "DENIED"
                elif mapped_status == "canceled":
                    response_status = "CANCELED"
                elif mapped_status == "processing":
                    response_status = "PROCESSING"
                else:
                    response_status = "PENDING"
                
                return {
                    "status": response_status,
                    "payment_id": payment_id,
                    "merchant_order_id": merchant_order_id,
                    "cielo_status": payment_status,
                    "return_code": return_code,
                    "return_message": return_message,
                    "denial_reason": return_message if mapped_status == "denied" else "",
                    "raw_response": response_json
                }
            
            else:
                # Erro na requisição
                if isinstance(response_json, list) and len(response_json) > 0:
                    error_message = response_json[0].get("Message", "Erro desconhecido")
                    error_code = response_json[0].get("Code", "")
                elif isinstance(response_json, dict):
                    error_message = response_json.get("Message", "Erro desconhecido")
                    error_code = response_json.get("Code", "")
                else:
                    error_message = "Erro desconhecido"
                    error_code = ""
                
                print(f"[CIELO] Erro na requisição (DÉBITO): [{error_code}] {error_message}")
                
                transaction.status = "denied"
                transaction.payment_response = response_json if isinstance(response_json, dict) else {"errors": response_json}
                transaction.save()
                
                return {
                    "status": "DENIED",
                    "error": error_message,
                    "error_code": error_code,
                    "details": response_json
                }
                
        except requests.exceptions.Timeout:
            print("\n[CIELO] Timeout DÉBITO na requisição para Cielo (DÉBITO)")
            return {
                "status": "DENIED",
                "error": "Timeout na comunicação com Cielo"
            }
        except Exception as e:
            print(f"\n[CIELO] Exceção ao processar (DÉBITO): {str(e)}")
            return {
                "status": "DENIED",
                "error": str(e)
            }



    def create_pix_payment(self, transaction, qr_expiration_time=3600):
        """
        Cria um pagamento PIX com Cielo
        
        Args:
            transaction: Instância de PaymentTransaction
            qr_expiration_time: Tempo de expiração do QR Code em segundos (padrão 3600s = 1 hora)
        """
        pedido = transaction.checkout_link.pedido

        comprador = pedido.comprador

        valor = transaction.valor
        
        print("\n===== INICIANDO PROCESSAMENTO DE PAGAMENTO CIELO (PIX) =====\n"
              "\n",
              f"Pedido: {pedido.id}"
              "\n",
              f"\nDados do Comprador:"
              f"\n - Nome: {comprador.name}",
              f"\n - Email: {comprador.email}",
              f"\n - Telefone: {comprador.telefone}",
              "\n",
              f"Valor Total: R$ {valor/100:.2f} ({valor} centavos)" 
              "\n",
              f"Produtos: {pedido.produtos.count()}"
              "\n",
            )
        
        # IMPORTANTE: A nova integração Pix (Cielo2) ainda não tem ambiente sandbox disponível
        # Referência: https://developercielo.github.io/manual/cielo-ecommerce#criar-pagamento-com-qr-code-pix
        # MODO MOCK: Retornar dados simulados para testes
        # Configuração movida para payment/config.py
        from .config import is_mock_mode
        USE_MOCK = is_mock_mode()  # Controlado por variável de ambiente PIX_MOCK_MODE 
        
        if USE_MOCK:
            print("[DEV] USANDO MODO MOCK - Sandbox PIX não disponível")

            payment_id = f"MOCK-PIX-{uuid.uuid4().hex[:16]}"
            
            # QR Code simulado (válido para testes visuais)
            mock_qr_code = f"00020126580014br.gov.bcb.pix0136{payment_id}520400005303986540{valor/100:.2f}5802BR5925{comprador.name[:25]}6009SAO PAULO62070503***6304"
            
            # Frontend gera QR Code via API (qrserver.com)
            # Não precisa gerar imagem no backend
            mock_qr_base64 = ""  # Vazio - frontend usa getQrCodeUrl(): mock_qr_base64
            
            transaction.status = "waiting"
            transaction.transaction_id = payment_id
            transaction.payment_response = {
                "MOCK": True,
                "PaymentId": payment_id,
                "Status": 12,
                "QrCodeString": mock_qr_code,
                "QrCodeBase64Image": mock_qr_base64
            }
            transaction.save()
            
            print(f"\n[DEV] QRCODE GERADO (MODO MOCK)",
                f"\n  PaymentId: {payment_id}",
                f"\n  QrCodeString: {mock_qr_code[:50]}..."
            )
            
            return {
                "status": "WAITING",
                "payment_id": payment_id,
                "merchant_order_id": f"PIX-MOCK-{pedido.id}",
                "additional_data": {
                    "qr_code": mock_qr_code,
                    "qr_code_base64": mock_qr_base64,
                    "expiration_date_qrcode": None,
                    "creation_date_qrcode": timezone.now().isoformat()
                },
                "raw_response": {"MOCK": True}
            }
        
        
        # Gerar MerchantOrderId único
        merchant_order_id = f"PIX-DMC-{pedido.id}-{uuid.uuid4().hex[:8]}"
        
        # Preparar CPF/CNPJ (Identity é obrigatório para PIX)
        customer_identity = comprador.cpf.replace(".", "").replace("-", "").replace("/", "") if comprador.cpf else "00000000000"
        
        customer_identity_type = "CPF" if not comprador.pessoa_juridica else "CNPJ"
        
        # Preparar payload para PIX (Nova integração Cielo2 - a partir de 01/09/2025)
        payload = {
            "MerchantOrderId": merchant_order_id,
            "Customer": {
                "Name": comprador.name,
                "Identity": customer_identity,
                "IdentityType": customer_identity_type
            },
            "Payment": {
                "Type": "Pix",
                "Provider": "Cielo2",  # Nova integração PIX (Cielo2)
                "Amount": int(valor),  # Garantir que é inteiro
                "QrCode": {
                    "Expiration": qr_expiration_time  # Tempo em segundos (máx 86400 = 24h)
                }
            }
        }
        
        if settings.DEBUG:
            payment = payload.get("Payment", {})
            print(
                "\n[PAYLOAD] ENVIANDO REQUISIÇÃO DE PAGAMENTO CIELO (PIX)",
                f"\n - URL: {self.SALES_URL}",
                f"\n - MerchantOrderId: {merchant_order_id}",
                f"\n - Valor: R$ {payment.get('Amount', 0)/100:.2f}",
                f"\n - Provider: {payment.get('Provider')}",
                f"\n - QR Code Expiration: {payment.get('QrCode', {}).get('Expiration')} segundos",
                # f"\n - Payload:", json.dumps(payload, indent=2
            )
        
        headers = self._get_headers()
        
        try:
            response = requests.post(self.SALES_URL, json=payload, headers=headers, timeout=30)
            
            print("\n [CIELO] RESPOSTA DA REQUISIÇÃO DE PAGAMENTO CIELO (PIX)",
                f"\nStatus code: {response.status_code}"
                ) 
            
            try:
                response_json = response.json()
                
                payment = response_json.get("Payment", {})
                customer = response_json.get("Customer", {})
                
                print(
                    f"""\n
                    [CIELO] Transação criada (PIX)
                    - Pedido: {response_json.get("MerchantOrderId")}
                    - Cliente: {customer.get("Name")} ({customer.get("Identity")})

                    - Status: {payment.get("Status")}
                    - Mensagem: {payment.get("ReturnMessage")}
                    - Código Retorno: {payment.get("ReturnCode")}

                    - Valor: R$ {payment.get("Amount", 0) / 100:.2f}
                    - Tipo: {payment.get("Type")}
                    - Provider: {payment.get("Provider")}
                    - PaymentId: {payment.get("PaymentId")}
                    
                    QR Code:
                    - SentOrderId (txid): {payment.get("SentOrderId")}
                    - QrCodeString: {payment.get("QrCodeString", "N/A")[:50]}...
                    - QrCodeBase64Image: {("Presente" if payment.get("QrCodeBase64Image") else "Ausente")}
                    - Expiration: {payment.get("QrCode", {}).get("Expiration", "N/A")} segundos
                    
                    Outros:
                    - ReceivedDate: {payment.get("ReceivedDate")}
                    - Currency: {payment.get("Currency", "N/A")}
                    - Country: {payment.get("Country", "N/A")}
                    - IsSplitted: {payment.get("IsSplitted", False)}
                    """
                )

            except Exception as e:
                print(f"[CIELO] Erro ao processar resposta JSON: {e}")
                print(f"[CIELO] Resposta raw: {response.text}")
                return {
                    "status": "ERROR",
                    "error": str(e)
                }
            
            if response.status_code in [200, 201]:
                payment_data = response_json.get("Payment", {})
                payment_id = payment_data.get("PaymentId")
                payment_status = payment_data.get("Status")
                return_code = payment_data.get("ReturnCode", "")
                return_message = payment_data.get("ReturnMessage", "")
                
                # Nova integração Cielo2 - Campos alterados
                qr_code_string = payment_data.get("QrCodeString")  # Código Pix (copia e cola)
                qr_code_base64 = payment_data.get("QrCodeBase64Image")  # Base64 da imagem do QR Code
                sent_order_id = payment_data.get("SentOrderId")  # txid (identificador da transação Pix)
                
                # VALIDAÇÃO 1: Verificar se houve erro mesmo com status 201
                # ReturnCode "0" = Sucesso, qualquer outro valor indica erro
                if return_code != "0":
                    # ERRO detectado via ReturnCode - Forçar status DENIED
                    print("="*70)
                    print(f"\n[CIELO] Pagamento NEGADO via ReturnCode:"
                        f"   ReturnCode: {return_code}",
                        f"   ReturnMessage: {return_message}",
                        f"   Status original Cielo: {payment_status}",
                    )
                    print("="*70)
                    
                    transaction.status = "error"
                    transaction.payment_response = response_json
                    transaction.save()
                    
                    return {
                        "status": "ERROR",
                        "error": return_message,
                        "error_code": return_code,
                        "details": response_json
                    }
                
                # VALIDAÇÃO 2: Verificar se QR Code foi realmente gerado
                if not qr_code_string or not qr_code_base64:
                    print(
                        f"\n[CIELO] QRCODE NAO FOI GERADO NA RESPOSTA (PIX)",
                        f"\n  Status Cielo: {payment_status}", 
                        f"\n  ReturnCode: {return_code}",
                        f"\n  ReturnMessage: {return_message}"
                    )
                                     
                    transaction.status = "error"
                    transaction.payment_response = response_json
                    transaction.save()
                    
                    return {
                        "status": "ERROR",
                        "error": "QR Code não foi gerado. " + return_message,
                        "error_code": return_code,
                        "details": response_json
                    }
                
                # Tudo OK - Atualizar transação
                # Status 12 = Pending (aguardando pagamento Pix)
                transaction.status = "waiting"
                transaction.transaction_id = payment_id
                transaction.payment_response = response_json
                transaction.save()
                
                print(
                    f"\n[CIELO] QRCODE GERADO COM SUCESSO (PIX)",
                    f"\n  PaymentId: {payment_id}",
                    f"\n  SentOrderId (txid): {sent_order_id}",
                    f"\n  Status: {payment_status} (12 = Pending/Aguardando)",
                    f"\n  ReturnCode: {return_code}",
                    f"\n  ReturnMessage: {return_message}",
                    f"\n  QrCodeString: {qr_code_string[:50] if qr_code_string else 'VAZIO'}...",
                    f"\n  QrCodeBase64: {'Presente' if qr_code_base64 else 'AUSENTE'}"
                )
                
                # Retornar resposta padronizada
                return {
                    "status": "WAITING",
                    "payment_id": payment_id,
                    "merchant_order_id": merchant_order_id,
                    "txid": sent_order_id,  # Identificador da transação Pix (novo campo Cielo2)
                    "additional_data": {
                        "qr_code": qr_code_string,
                        "qr_code_base64": qr_code_base64,
                        "expiration_date_qrcode": None,  # Cielo não retorna data de expiração explícita
                        "creation_date_qrcode": timezone.now().isoformat(),
                        "expiration_seconds": qr_expiration_time  # Tempo configurado
                    },
                    "raw_response": response_json
                }
            
            else:
                # Cielo pode retornar erro como lista ou dict
                if isinstance(response_json, list) and len(response_json) > 0:
                    error_message = response_json[0].get("Message", "Erro desconhecido")
                    error_code = response_json[0].get("Code", "")

                else:
                    error_message = response_json.get("Message", "Erro desconhecido") if isinstance(response_json, dict) else "Erro ao gerar PIX"
                    error_code = response_json.get("Code", "") if isinstance(response_json, dict) else ""
                
                print("\n [CIELO] Erro ao gerar PIX:",
                    f"\n  Status Code: {response.status_code}",
                    f"\n  Error Code: {error_code}",
                    f"\n  Message: {error_message}",
                    f"\n  Response completa: {json.dumps(response_json, indent=2)}"
                )

                return {
                    "status": "ERROR",
                    "error": error_message,
                    "error_code": error_code,
                    "details": response_json
                }
                
        except Exception as e:
            print(f"Exceção ao gerar PIX: {str(e)}")
            return {
                "status": "ERROR",
                "error": str(e)
            }



    def query_payment(self, payment_id):
        """
        Consulta o status de um pagamento pelo PaymentId
        
        Args:
            payment_id: Cielo PaymentId
        """
        url = f"{self.QUERY_URL}{payment_id}"
        headers = self._get_headers()
        
        print(f"\n===== [CIELO] CONSULTANDO STATUS DO PAGAMENTO NA CIELO ====="
                f"\n URL: {url}",
                f"\n PaymentId: {payment_id}"
                )
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                response_json = response.json()
                print(f"[CIELO] CONSULTA BEM-SUCEDIDA")
                print(f"Resposta: {json.dumps(response_json, indent=2)}")
                return response_json
            else:
                print(f"\n[CIELO] ERRO AO CONSULTAR PAGAMENTO:",
                    f"\n   Status Code: {response.status_code}",
                    f"\n   Response: {response.text}",
                )
                
                # Tentar parsear erro JSON
                try:
                    error_json = response.json()
                    print(f"[CIELO] Error JSON: {json.dumps(error_json, indent=2)}")
                except:
                    pass
                
                return None
                
        except Exception as e:
            print(f"[CIELO] Exceção ao consultar pagamento: {str(e)}")
            return None


    
    def process_webhook(self, data):
        """
        Process webhook data from Cielo (LOGICA NA VIEW)
        """
        # Implementar lógica de webhook da Cielo
        return data
