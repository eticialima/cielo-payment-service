#!/bin/bash

# ========================================
# Testes de API - PaymentCieloLio
# ========================================

# Configurações
BASE_URL="http://localhost:8000"
TOKEN="28c74c7fd02ebf8c9ceb1d7dddeb5ad2530135d9"  # Substitua pelo seu token
PEDIDO_ID="2ommks"  # ID de um pedido existente

echo "======================================"
echo "Testes API PaymentCieloLio"
echo "======================================"
echo ""

# ========================================
# 1. REGISTRAR REQUEST (POST)
# ========================================
echo "1. Registrando REQUEST enviado para Cielo Lio..."
echo ""

REQUEST_RESPONSE=$(curl -s -X POST "${BASE_URL}/api/payment/cielo-lio/registrar_request/" \
  -H "Content-Type: application/json" \
  -H "Authorization: Token ${TOKEN}" \
  -d @- <<EOF
{
  "pedido": "${PEDIDO_ID}",
  "reference": "teste123abc",
  "payload": {
    "accessToken": "qtMThk1aZ1NqDKEuW1",
    "clientID": "cY2N3L5B4Hs2sIPopn",
    "email": "teste@dmcgroup.com.br",
    "installments": 1,
    "items": [
      {
        "name": "Pagamento pedido teste123abc",
        "quantity": 1,
        "sku": "teste123abc",
        "unitOfMeasure": "UN",
        "unitPrice": 5000
      }
    ],
    "paymentCode": "CREDITO_PARCELADO_LOJA",
    "value": "5000",
    "reference": "teste123abc"
  }
}
EOF
)

echo "Response:"
echo "$REQUEST_RESPONSE" | jq '.'
echo ""
echo "======================================"
echo ""

# Aguardar 1 segundo
sleep 1

# ========================================
# 2. REGISTRAR RESPONSE (POST)
# ========================================
echo "2. Registrando RESPONSE recebido da Cielo Lio..."
echo ""

RESPONSE_RESPONSE=$(curl -s -X POST "${BASE_URL}/api/payment/cielo-lio/registrar_response/" \
  -H "Content-Type: application/json" \
  -H "Authorization: Token ${TOKEN}" \
  -d @- <<EOF
{
  "pedido": "${PEDIDO_ID}",
  "reference": "teste123abc",
    "payload": {
      "createdAt": "Dec 10, 2025 10:30:00",
      "id": "abc123-def456-ghi789",
      "installments": 1,
      "items": [
        {
          "description": "",
          "details": "",
          "id": "item-123-456",
          "name": "Pagamento pedido teste123abc",
          "quantity": 1,
          "reference": "teste123abc",
          "sku": "teste123abc",
          "unitOfMeasure": "UN",
          "unitPrice": 5000
        }
      ],
      "notes": "",
      "number": "",
      "paidAmount": 5000,
      "payments": [
        {
          "accessKey": "",
          "amount": 5000,
          "applicationName": "com.example.app_feira_integracao_cielo",
          "authCode": "123456",
          "brand": "VISA",
          "cieloCode": "789012",
          "description": "",
          "discountedAmount": 0,
          "externalId": "ext-789-012",
          "id": "payment-abc-def",
          "installments": 1,
          "mask": "************1234",
          "merchantCode": "0010000234570003",
          "paymentFields": {
            "cityState": "SAO PAULO SP",
            "serviceTax": "0",
            "signatureBytes": "",
            "betterDate": "0",
            "bin": "411111",
            "hasConnectivity": "false",
            "entranceMode": "QRCODE",
            "paymentTypeCode": "0",
            "hasPassword": "false",
            "productName": "CREDITO_AVISTA",
            "hasWarranty": "false",
            "merchantName": "DMC EQUIPAMENTOS",
            "isOnlyIntegrationCancelable": "false"
          },
          "primaryCode": "00",
          "secondaryCode": "00"
        }
      ]
    }
  }
EOF
)

echo "Response:"
echo "$RESPONSE_RESPONSE" | jq '.'
echo ""
echo "======================================"
echo ""

# Aguardar 1 segundo
sleep 1

# ========================================
# 3. LISTAR TODOS (GET)
# ========================================
echo "3. Listando todos os registros..."
echo ""

LIST_RESPONSE=$(curl -X GET "${BASE_URL}/api/payment/cielo-lio/" \
  -H "Authorization: Token ${TOKEN}")

echo "Response:"
echo "$LIST_RESPONSE" | jq '.'
echo ""
echo "======================================"
echo ""

# ========================================
# 4. LISTAR POR PEDIDO (GET)
# ========================================
echo "4. Listando registros por pedido (ID: ${PEDIDO_ID})..."
echo ""

PEDIDO_RESPONSE=$(curl -X GET "${BASE_URL}/api/payment/cielo-lio/por-pedido/${PEDIDO_ID}/" \
  -H "Authorization: Token ${TOKEN}")

echo "Response:"
echo "$PEDIDO_RESPONSE" | jq '.'
echo ""
echo "======================================"
echo ""

# ========================================
# 5. LISTAR POR REFERÊNCIA (GET)
# ========================================
echo "5. Listando registros por referência (teste123abc)..."
echo ""

REF_RESPONSE=$(curl -X GET "${BASE_URL}/api/payment/cielo-lio/por-referencia/teste123abc/" \
  -H "Authorization: Token ${TOKEN}")

echo "Response:"
echo "$REF_RESPONSE" | jq '.'
echo ""
echo "======================================"
echo ""

# ========================================
# 6. FILTRAR POR TIPO (GET)
# ========================================
echo "6. Filtrando apenas REQUESTS..."
echo ""

FILTER_REQUEST=$(curl -X GET "${BASE_URL}/api/payment/cielo-lio/?tipo=request" \
  -H "Authorization: Token ${TOKEN}")

echo "Response:"
echo "$FILTER_REQUEST" | jq '.'
echo ""
echo "======================================"
echo ""

echo "7. Filtrando apenas RESPONSES..."
echo ""

FILTER_RESPONSE=$(curl -X GET "${BASE_URL}/api/payment/cielo-lio/?tipo=response" \
  -H "Authorization: Token ${TOKEN}")

echo "Response:"
echo "$FILTER_RESPONSE" | jq '.'
echo ""
echo "======================================"
echo ""

# ========================================
# 8. DETALHE DE UM REGISTRO (GET)
# ========================================
# Extrair ID do primeiro registro criado
RECORD_ID=$(echo "$REQUEST_RESPONSE" | jq -r '.data.id // .id // empty')

if [ ! -z "$RECORD_ID" ]; then
  echo "8. Buscando detalhe do registro ID: ${RECORD_ID}..."
  echo ""
  
  DETAIL_RESPONSE=$(curl -X GET "${BASE_URL}/api/payment/cielo-lio/${RECORD_ID}/" \
    -H "Authorization: Token ${TOKEN}")
  
  echo "Response:"
  echo "$DETAIL_RESPONSE" | jq '.'
  echo ""
  echo "======================================"
  echo ""
fi

echo "✅ Testes concluídos!"
echo ""
echo "💡 Dicas:"
echo "  - Verifique os registros no admin: ${BASE_URL}/admin/payment/paymentcielolio/"
echo "  - Use 'jq' para formatar JSON: curl ... | jq '.'"
echo "  - Altere TOKEN e PEDIDO_ID no início do script conforme necessário"
