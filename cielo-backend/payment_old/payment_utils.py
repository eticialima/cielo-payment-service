import copy 

def mask_sensitive_data(payload: dict, headers: dict) -> tuple[dict, dict]:
        """
        Mascarar dados sensíveis no payload e headers para logs.
        Args:
            payload (dict): O payload da requisição.
            headers (dict): Os headers da requisição.
        """

        safe_payload = copy.deepcopy(payload)
         
        # Adicionar mascaramento de dados sensíveis no log (como no plugin WordPress) 
        if "Payment" in safe_payload and "CreditCard" in safe_payload["Payment"]:
            
            safe_card = safe_payload["Payment"]["CreditCard"]

            if "CardNumber" in safe_card:

                # Mostrar primeiros 6 + últimos 4 dígitos (padrão da indústria)
                card_number = safe_card["CardNumber"]
                if len(card_number) >= 10:
                    safe_card["CardNumber"] = f"{card_number[:6]}******{card_number[-4:]}"
                else:
                    safe_card["CardNumber"] = "****"

            if "SecurityCode" in safe_card:
                safe_card["SecurityCode"] = "***"
        
        # Mascarar credenciais nos headers do log

        safe_headers = copy.deepcopy(headers)

        if "MerchantId" in safe_headers and len(safe_headers["MerchantId"]) > 20:
            mid = safe_headers["MerchantId"]
            safe_headers["MerchantId"] = f"{mid[:10]}{'*' * 8}{mid[-10:]}"

        if "MerchantKey" in safe_headers and len(safe_headers["MerchantKey"]) > 20:
            mkey = safe_headers["MerchantKey"]
            safe_headers["MerchantKey"] = f"{mkey[:10]}{'*' * 8}{mkey[-10:]}"

        return safe_payload, safe_headers