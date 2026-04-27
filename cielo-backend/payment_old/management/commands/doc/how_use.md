## Simular Webhook da Cielo aprovando pagamento (PIX, Cartão, Débito)
```
./manage simular_webhook --transaction_identifier=MOCK-PIX-f86898827df0445f abcdefgh --status 2
```

## Testa o cálculo do valor_total do CheckoutLink 
```
./manage testar_calculo_link --pedido_id=XXXXX
```

## Consulta status de pagamento na Cielo e-Commerce Link Pagamento (API)
```
./manage verifica_status_checkout --pedido=XXXXX
./manage verifica_status_checkout --transaction-id=abcdefghij
```

## Consulta status de pagamento dos pedidos da Cielo LIO (Maquininha)
```
./manage verifica_status_lio --reference=XXXXX 
```
 
## Buscar qualquer pagamento no sistema

```bash
# Por ID do Pedido (mostra APENAS transações daquele pedido)
./manage buscar_qualquer_pagamento --pedido-id c1um7n

# Por Payment ID
./manage buscar_qualquer_pagamento --payment-id cb3bd248-5943-4fa7-9c47-621b357cea31

# Por Merchant Order ID
./manage buscar_qualquer_pagamento --merchant-order DMC-DBMHHH-2D299F0F

# Por TID (mostra até 10 resultados)
./manage buscar_qualquer_pagamento --tid 11141333855GGU4PN13E

# Por Auth Code (mostra até 10 resultados)
./manage buscar_qualquer_pagamento --auth 740483

# Com consulta na API Cielo
./manage buscar_qualquer_pagamento --payment-id cb3bd248... --consultar-api
```