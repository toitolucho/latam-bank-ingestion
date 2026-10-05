"""Plantillas revisadas es/pt. Todo numero que ve el cliente entra por facts["fmt"] ya formateado.

Las plantillas son la fuente de verdad del texto con cifras; un LLM puede reescribir solo los mensajes de bajo riesgo, y su
texto se descarta si contiene numeros que no estan en facts["fmt"] (ver orchestrator.safe_text).

Voz: cordial y cercana, de "usted", frases cortas, sin jerga bancaria ni formulas rigidas. Los mensajes de bajo riesgo tienen
varias formulaciones que rotan por turno para no sonar repetitivos. Identidad: el asistente se presenta UNA vez como
"asistente virtual" (mensaje de bienvenida), nunca dice ser una persona y responde con la verdad si le preguntan.
"""
from __future__ import annotations

PRODUCT_NAME = {
    "es": {"personal_loan": "préstamo personal", "credit_card": "tarjeta de crédito", "mortgage": "préstamo hipotecario"},
    "pt": {"personal_loan": "empréstimo pessoal", "credit_card": "cartão de crédito", "mortgage": "financiamento imobiliário"},
}

REASON_TEXT = {
    "es": {"CUSTOMER_NOT_ACTIVE": "su cuenta no está activa", "DELINQUENT_REVIEW": "tiene pagos atrasados",
           "BORDERLINE_DTI": "su capacidad de pago está justo en el límite",
           "INCOME_UPLIFT_REVIEW": "el aumento de ingreso informado necesita verificación",
           "MISSING_DATA": "faltan datos para evaluarlo", "USER_REQUEST": "usted lo solicitó",
           "UNSUPPORTED_PRODUCT": "ese producto lo atiende un asesor", "UNCLEAR": "no logré entender su consulta",
           "DOCS_INCOMPLETE": "falta documentación por completar", "OTHER_TOPIC": "ese tema lo atiende un asesor"},
    "pt": {"CUSTOMER_NOT_ACTIVE": "sua conta não está ativa", "DELINQUENT_REVIEW": "há pagamentos em atraso",
           "BORDERLINE_DTI": "sua capacidade de pagamento está no limite",
           "INCOME_UPLIFT_REVIEW": "o aumento de renda informado precisa de verificação",
           "MISSING_DATA": "faltam dados para a análise", "USER_REQUEST": "você solicitou",
           "UNSUPPORTED_PRODUCT": "esse produto é atendido por um consultor", "UNCLEAR": "não consegui entender a consulta",
           "DOCS_INCOMPLETE": "falta documentação a completar", "OTHER_TOPIC": "esse assunto é atendido por um consultor"},
}

# Cada entrada es un texto o una lista de variantes equivalentes (mismos marcadores), elegidas por turno.
T: dict[str, dict[str, str | list[str]]] = {
    # ---------------------------------------------------------------- presentacion e identidad
    "welcome": {
        "es": "Hola {first_name}, soy el asistente virtual del banco. Puedo ayudarle con consultas sobre sus productos, con créditos o conectarlo con un asesor. ¿En qué le ayudo?",
        "pt": "Olá {first_name}, sou o assistente virtual do banco. Posso ajudar com consultas sobre seus produtos, com crédito ou conectar você a um consultor. Em que posso ajudar?",
    },
    # Cuando le quedo algo pendiente (caso abierto reciente): se reconoce primero, antes de cualquier otro tema.
    "welcome_case": {
        "es": "Hola {first_name}, soy el asistente virtual del banco. Veo {case}{pending} y quiero ayudarle con eso primero. ¿Quiere que le cuente lo que veo? Si prefiere otra cosa, dígamelo.",
        "pt": "Olá {first_name}, sou o assistente virtual do banco. Vejo {case}{pending} e quero ajudar você com isso primeiro. Quer que eu conte o que vejo? Se preferir outra coisa, é só dizer.",
    },
    "case_skip": {
        "es": "Claro, como prefiera. ¿En qué le ayudo?",
        "pt": "Claro, como preferir. Em que posso ajudar?",
    },
    "greeting": {
        "es": ["Hola de nuevo, {first_name}. ¿Qué necesita?", "¡Hola! Dígame, {first_name}, ¿en qué le ayudo?"],
        "pt": ["Olá de novo, {first_name}. Do que você precisa?", "Oi! Diga, {first_name}, em que posso ajudar?"],
    },
    "identity": {
        "es": "Soy el asistente virtual del banco: un programa de inteligencia artificial, no una persona. Puedo ayudarle con consultas sobre sus productos y con créditos y, si prefiere hablar con un asesor, lo conecto.",
        "pt": "Sou o assistente virtual do banco: um programa de inteligência artificial, não uma pessoa. Posso ajudar com consultas sobre seus produtos e com crédito e, se preferir falar com um consultor, eu conecto você.",
    },
    # ---------------------------------------------------------------- conversacion general
    "thanks": {
        "es": ["Con gusto. ¿Hay algo más en lo que le pueda ayudar?", "Para eso estoy. ¿Necesita algo más?"],
        "pt": ["Por nada. Posso ajudar em mais alguma coisa?", "Para isso estou aqui. Precisa de mais alguma coisa?"],
    },
    "closing": {
        "es": ["Con gusto, que tenga un buen día.", "Un gusto ayudarle. ¡Que le vaya muy bien!"],
        "pt": ["Por nada, tenha um bom dia.", "Foi um prazer ajudar. Tudo de bom!"],
    },
    "goodbye": {
        "es": ["Quedo atento por si necesita algo más. ¡Que tenga un excelente día!", "Aquí sigo si me necesita. ¡Que le vaya muy bien!"],
        "pt": ["Fico à disposição se precisar de mais alguma coisa. Tenha um ótimo dia!", "Estou por aqui se precisar. Tudo de bom!"],
    },
    "unknown": {
        "es": ["Disculpe, no estoy seguro de haberle entendido. Puedo ayudarle con sus productos, con el estado de un caso, con créditos o conectarlo con un asesor. ¿Qué prefiere?",
               "Perdone, no logré entenderle bien. ¿Quiere consultar sus productos, ver un caso que tenga abierto, ver créditos o hablar con un asesor?"],
        "pt": ["Desculpe, não tenho certeza se entendi. Posso ajudar com seus produtos, com o andamento de um caso, com crédito ou conectar a um consultor. O que prefere?",
               "Perdão, não consegui entender bem. Quer consultar seus produtos, ver um caso em aberto, ver crédito ou falar com um consultor?"],
    },
    # ---------------------------------------------------------------- soporte: productos, casos e incidentes
    # Solo se confirma que existe y se deriva el detalle. Nunca saldos, movimientos ni montos.
    "products_found": {
        "es": "Sí, veo {what} a su nombre. Por seguridad, el detalle de saldos y movimientos lo revisa un asesor. Si quiere, cuénteme qué necesita saber (producto, fecha, monto) y lo dejo anotado para que no tenga que repetirlo. ¿Lo conecto con un asesor?",
        "pt": "Sim, vejo {what} em seu nome. Por segurança, o detalhe de saldos e movimentos é visto por um consultor. Se quiser, me conte o que precisa saber (produto, data, valor) e eu deixo anotado para que você não precise repetir. Conecto você a um consultor?",
    },
    "products_none": {
        "es": "No veo {art} {noun} {adj} a su nombre. Si cree que debería aparecer, un asesor puede revisarlo. Cuénteme qué ocurre y lo dejo anotado para que no tenga que repetirlo. ¿Lo conecto con un asesor?",
        "pt": "Não vejo {art} {noun} {adj} em seu nome. Se acha que deveria aparecer, um consultor pode revisar. Me conte o que está acontecendo e eu deixo anotado para que você não precise repetir. Conecto você a um consultor?",
    },
    "products_overview": {
        "es": "Veo estos productos activos a su nombre: {what}. Por seguridad, el detalle de saldos y movimientos lo revisa un asesor. Cuénteme qué necesita saber y lo dejo anotado para que no tenga que repetirlo. ¿Lo conecto con un asesor?",
        "pt": "Vejo estes produtos ativos em seu nome: {what}. Por segurança, o detalhe de saldos e movimentos é visto por um consultor. Me conte o que precisa saber e eu deixo anotado para que você não precise repetir. Conecto você a um consultor?",
    },
    "products_empty": {
        "es": "No veo productos activos a su nombre en este momento. Un asesor puede revisar su caso. Cuénteme qué necesita y lo dejo anotado. ¿Lo conecto con un asesor?",
        "pt": "No momento não vejo produtos ativos em seu nome. Um consultor pode revisar seu caso. Me conte o que precisa e eu deixo anotado. Conecto você a um consultor?",
    },
    "case_status_open": {
        "es": "Veo {case}; su estado es {status}.{more} El detalle del avance lo maneja un asesor. Si quiere, cuénteme qué le gustaría saber y lo dejo anotado. ¿Lo conecto con un asesor?",
        "pt": "Vejo {case}; o status é {status}.{more} O detalhe do andamento é tratado por um consultor. Se quiser, me conte o que gostaria de saber e eu deixo anotado. Conecto você a um consultor?",
    },
    "case_more": {
        "es": " Además, tiene otros casos abiertos.",
        "pt": " Além disso, você tem outros casos abertos.",
    },
    "case_status_none": {
        "es": "No veo reclamos ni casos abiertos a su nombre en este momento. Si se trata de algo reciente, cuénteme qué ocurrió y lo dejo anotado para un asesor. ¿Quiere que lo conecte con uno?",
        "pt": "No momento não vejo reclamações nem casos abertos em seu nome. Se for algo recente, me conte o que aconteceu e eu deixo anotado para um consultor. Quer que eu conecte você a um?",
    },
    "incident": {
        "es": ["Lamento mucho lo ocurrido. Esto es importante y conviene que lo vea un asesor cuanto antes. Para que no tenga que repetirlo, cuénteme brevemente qué pasó (producto, fecha y monto, si los recuerda). ¿Lo conecto ahora con un asesor?",
               "Siento lo que me cuenta; es un tema que debe revisar un asesor cuanto antes. Si puede, dígame qué pasó (producto, fecha, monto) y lo dejo anotado para que no lo repita. ¿Lo conecto ahora?"],
        "pt": ["Lamento muito o ocorrido. Isso é importante e convém que um consultor veja o quanto antes. Para você não precisar repetir, me conte brevemente o que aconteceu (produto, data e valor, se lembrar). Conecto você agora a um consultor?",
               "Sinto muito pelo que você conta; é um assunto que um consultor deve revisar o quanto antes. Se puder, me diga o que houve (produto, data, valor) e eu deixo anotado para você não repetir. Conecto você agora?"],
    },
    "detail_noted": {
        "es": ["Anotado, gracias por contármelo. ¿Quiere que lo conecte ya con un asesor o desea agregar algo más?",
               "Gracias, lo dejé anotado. ¿Lo conecto con un asesor ahora o quiere contarme algo más?"],
        "pt": ["Anotado, obrigado por me contar. Quer que eu conecte você agora a um consultor ou deseja acrescentar algo?",
               "Obrigado, deixei anotado. Conecto você a um consultor agora ou quer me contar mais alguma coisa?"],
    },
    "handoff_declined_support": {
        "es": ["De acuerdo, no lo conecto por ahora. ¿Hay algo más en lo que le pueda ayudar?", "Sin problema, lo dejamos así. Si cambia de opinión, me avisa. ¿Algo más?"],
        "pt": ["Certo, não conecto por enquanto. Posso ajudar em mais alguma coisa?", "Sem problema, deixamos assim. Se mudar de ideia, é só avisar. Algo mais?"],
    },
    # Se antepone al mensaje cuando el cliente se muestra molesto (no mas de una vez cada pocos turnos).
    "empathy_negative": {
        "es": ["Entiendo su molestia y lamento los inconvenientes.", "Lamento que esté pasando por esto."],
        "pt": ["Entendo sua chateação e lamento o transtorno.", "Lamento que você esteja passando por isso."],
    },
    "ask_amount": {
        "es": ["¿Qué monto necesita para su {product}? Si quiere, dígame también el plazo en meses; si no, uso {months}.",
               "¿De cuánto sería su {product}? Puede indicarme también el plazo en meses (si no, uso {months})."],
        "pt": ["Qual valor você precisa para o seu {product}? Se quiser, diga também o prazo em meses; senão, uso {months}.",
               "De quanto seria o seu {product}? Pode informar também o prazo em meses (se não, uso {months})."],
    },
    "ask_income": {
        "es": ["No tengo su ingreso mensual registrado. Si me cuenta aproximadamente cuánto gana al mes ({ccy}), hago el cálculo de forma provisional; después un asesor lo verificaría.",
               "Me falta su ingreso mensual para calcular. ¿Cuánto gana más o menos al mes ({ccy})? Lo tomo de forma provisional y un asesor lo verificaría después."],
        "pt": ["Não tenho sua renda mensal registrada. Se me contar aproximadamente quanto ganha por mês ({ccy}), faço o cálculo de forma provisória; depois um consultor verificaria.",
               "Falta sua renda mensal para calcular. Quanto você ganha, mais ou menos, por mês ({ccy})? Uso de forma provisória e um consultor verificaria depois."],
    },
    "income_saved": {
        "es": "{fx}Anotado: ingreso mensual de {income}, sujeto a verificación. ¿Qué monto quiere consultar?",
        "pt": "{fx}Anotado: renda mensal de {income}, sujeita a verificação. Qual valor quer consultar?",
    },
    # ---------------------------------------------------------------- resultados de la politica (texto fijo, revisado)
    "eligible": {
        "es": "{fx}Buenas noticias: con los datos que tenemos, un {product} de {amount} a {months} meses es viable. La cuota sería de unos {payment} al mes, con una tasa anual de {rate}, y le dejaría un endeudamiento de {dti} de su ingreso (el máximo que manejamos es {max_dti}). Tenga en cuenta que es una simulación: la aprobación final depende de la verificación del banco.",
        "pt": "{fx}Boas notícias: com os dados que temos, um {product} de {amount} em {months} meses é viável. A parcela seria de cerca de {payment} por mês, com taxa anual de {rate}, e deixaria seu endividamento em {dti} da renda (o máximo que trabalhamos é {max_dti}). Lembre que é uma simulação: a aprovação final depende da verificação do banco.",
    },
    "eligible_provisional": {
        "es": "{fx}Con el ingreso que usted me indicó, un {product} de {amount} a {months} meses es viable, aunque queda sujeto a la verificación de sus ingresos. La cuota sería de unos {payment} al mes, con una tasa anual de {rate} (endeudamiento de {dti}, bajo el máximo de {max_dti}). Es una simulación.",
        "pt": "{fx}Com a renda que você informou, um {product} de {amount} em {months} meses é viável, mas fica sujeito à verificação da sua renda. A parcela seria de cerca de {payment} por mês, com taxa anual de {rate} (endividamento de {dti}, abaixo do máximo de {max_dti}). É uma simulação.",
    },
    "declined_dti": {
        "es": "{fx}Con esa cuota usaría {dti} de su ingreso, y el máximo que manejamos es {max_dti}. Con su situación actual, lo más alto que podríamos simular a {months} meses es {max_amount}. Si sus ingresos cambiaron, cuénteme y lo recalculo.",
        "pt": "{fx}Com essa parcela você usaria {dti} da renda, e o máximo que trabalhamos é {max_dti}. Na sua situação atual, o valor mais alto que poderíamos simular em {months} meses é {max_amount}. Se sua renda mudou, me conte e eu recalculo.",
    },
    "declined_no_capacity": {
        "es": "{fx}Con esa cuota usaría {dti} de su ingreso, por encima del máximo de {max_dti}, y con sus compromisos actuales hoy no hay margen para un nuevo crédito. Si sus ingresos cambiaron, cuénteme y lo recalculo.",
        "pt": "{fx}Com essa parcela você usaria {dti} da renda, acima do máximo de {max_dti}, e com seus compromissos atuais hoje não há margem para um novo crédito. Se sua renda mudou, me conte e eu recalculo.",
    },
    "declined_generic": {
        "es": "Por ahora no podemos ofrecerle este crédito según las políticas del banco. Si quiere, un asesor puede revisar su caso. ¿Lo conecto?",
        "pt": "Por enquanto não podemos oferecer este crédito segundo as políticas do banco. Se quiser, um consultor pode revisar seu caso. Conecto você?",
    },
    "needs_review": {
        "es": "Su caso necesita que lo revise un asesor porque {reason}. ¿Quiere que lo conecte ahora?",
        "pt": "Seu caso precisa ser revisado por um consultor porque {reason}. Quer que eu conecte agora?",
    },
    "needs_data_score": {
        "es": "No tengo información suficiente para evaluarlo yo solo; un asesor sí puede ayudarle. ¿Lo conecto?",
        "pt": "Não tenho informações suficientes para avaliar sozinho; um consultor pode ajudar. Conecto você?",
    },
    "unsupported_product": {
        "es": "Las tarjetas de crédito las atiende un asesor. ¿Quiere que lo conecte?",
        "pt": "Os cartões de crédito são atendidos por um consultor. Quer que eu conecte?",
    },
    "offers": {
        "es": "Estas son las tasas anuales de referencia para su perfil: {lines}. {capacity}",
        "pt": "Estas são as taxas anuais de referência para o seu perfil: {lines}. {capacity}",
    },
    "offers_capacity": {
        "es": "Con su situación actual, un préstamo personal a {months} meses podría llegar hasta unos {max_amount}. Es una simulación.",
        "pt": "Na sua situação atual, um empréstimo pessoal em {months} meses poderia chegar a cerca de {max_amount}. É uma simulação.",
    },
    "offers_no_capacity": {
        "es": "Para estimar un monto máximo necesito saber su ingreso mensual, ¿me lo comparte?",
        "pt": "Para estimar um valor máximo preciso saber sua renda mensal, pode me informar?",
    },
    "income_review": {
        "es": "El ingreso que me indica es bastante mayor al que tenemos registrado, así que debe verificarlo un asesor. ¿Lo conecto?",
        "pt": "A renda que você informa é bem maior do que a registrada, então precisa ser verificada por um consultor. Conecto você?",
    },
    # ---------------------------------------------------------------- derivacion a un asesor
    "handoff_created": {
        "es": "Listo, ya pasé su caso a un asesor con el resumen de esta conversación; su número de seguimiento es {ticket}. No tendrá que repetir nada.",
        "pt": "Pronto, já passei seu caso a um consultor com o resumo desta conversa; seu número de acompanhamento é {ticket}. Você não precisará repetir nada.",
    },
    "handoff_declined": {
        "es": ["De acuerdo, lo dejamos así. ¿Quiere consultar otro monto o plazo?", "Sin problema. ¿Le ayudo con otro monto o plazo?"],
        "pt": ["Certo, deixamos assim. Quer consultar outro valor ou prazo?", "Sem problema. Posso ajudar com outro valor ou prazo?"],
    },
    "handoff_exists": {
        "es": "Su caso ya está con un asesor; su número de seguimiento es {ticket}.",
        "pt": "Seu caso já está com um consultor; seu número de acompanhamento é {ticket}.",
    },
    "other_topic": {
        "es": ["Ese tema lo atiende un asesor, pero con gusto le dejo todo anotado para que no tenga que repetirlo. Cuénteme qué necesita. ¿Lo conecto ahora?",
               "Eso lo resuelve un asesor. Si quiere, cuénteme los detalles y los dejo anotados para que no tenga que repetirlos. ¿Lo conecto ahora?"],
        "pt": ["Esse assunto é atendido por um consultor, mas com prazer deixo tudo anotado para você não precisar repetir. Me conte o que precisa. Conecto você agora?",
               "Isso é resolvido por um consultor. Se quiser, me conte os detalhes e eu deixo anotados para você não precisar repetir. Conecto você agora?"],
    },
    # ---------------------------------------------------------------- oferta proactiva
    "offer_proactive": {
        "es": "Por cierto, {first_name}: según los datos del banco ya tiene una preaprobación indicativa de un {product} de hasta {max_amount} a {months} meses, con una tasa anual de {rate}. Es una simulación, sujeta a verificación y aprobación final. ¿Le interesa que le cuente más?",
        "pt": "A propósito, {first_name}: com base nos dados do banco você já tem uma pré-aprovação indicativa de um {product} de até {max_amount} em {months} meses, com taxa anual de {rate}. É uma simulação, sujeita a verificação e aprovação final. Quer que eu conte mais?",
    },
    "offer_accepted": {
        "es": "Perfecto. ¿Qué monto necesita? Puede decirme también el plazo en meses (si no, uso {months}).",
        "pt": "Perfeito. Qual valor você precisa? Pode me dizer também o prazo em meses (se não, uso {months}).",
    },
    "offer_declined": {
        "es": "Entendido, no se lo volveré a proponer en esta conversación. ¿Puedo ayudarle en algo más?",
        "pt": "Entendido, não vou propor de novo nesta conversa. Posso ajudar em mais alguma coisa?",
    },
    # ---------------------------------------------------------------- monedas
    "fx_note": {
        "es": "Convertí {src_amount} a {dst_amount} con la tasa de referencia del {date} ({rate}); no es una cotización en vivo.",
        "pt": "Converti {src_amount} para {dst_amount} com a taxa de referência de {date} ({rate}); não é uma cotação em tempo real.",
    },
    "currency_unsupported": {
        "es": "Todavía no puedo trabajar con {ccy}: manejo {supported}. ¿Me indica el monto en alguna de esas monedas?",
        "pt": "Ainda não consigo trabalhar com {ccy}: trabalho com {supported}. Pode me informar o valor em uma dessas moedas?",
    },
    "fx_unavailable": {
        "es": "En este momento no tengo una tasa de cambio disponible de {ccy} a su moneda. ¿Me indica el monto en su moneda local?",
        "pt": "No momento não tenho uma taxa de câmbio disponível de {ccy} para a sua moeda. Pode me informar o valor na sua moeda local?",
    },
    # ---------------------------------------------------------------- avanzar con la solicitud y documentos
    "ask_proceed": {
        "es": "¿Le gustaría que avancemos con la solicitud?",
        "pt": "Gostaria que avançássemos com a solicitação?",
    },
    "proceed_declined": {
        "es": ["Sin problema. Si más adelante quiere retomarla, aquí estaré.", "Claro, sin presión. Cuando quiera retomarla, me avisa."],
        "pt": ["Sem problema. Se mais adiante quiser retomar, estarei por aqui.", "Claro, sem pressa. Quando quiser retomar, é só me avisar."],
    },
    "docs_request": {
        "es": "{lead}Para avanzar necesito que tenga a la mano: {docs}. ¿Cuenta con todos?",
        "pt": "{lead}Para avançar preciso que você tenha em mãos: {docs}. Você tem todos?",
    },
    "docs_item": {
        "es": "{lead}¿Cuenta con {doc}?",
        "pt": "{lead}Você tem {doc}?",
    },
    "application_ready": {
        "es": "Perfecto, ya tengo todo lo necesario. Pasé su solicitud a un asesor para la revisión final; su número de seguimiento es {ticket}. No tendrá que repetirle lo que ya me contó.",
        "pt": "Perfeito, já tenho tudo o que preciso. Encaminhei sua solicitação a um consultor para a revisão final; seu número de acompanhamento é {ticket}. Você não precisará repetir o que já me contou.",
    },
    "docs_incomplete": {
        "es": "Todavía me falta: {missing}. Puede enviarlo respondiendo al correo con el resumen, o llevarlo a una sucursal. ¿Quiere que un asesor lo contacte para ver cómo avanzar?",
        "pt": "Ainda falta: {missing}. Você pode enviar respondendo ao e-mail com o resumo, ou levar a uma agência. Quer que um consultor entre em contato para ver como avançar?",
    },
    # ---------------------------------------------------------------- resumen final y correo
    "closing_summary": {
        "es": "Con gusto. Antes de despedirnos, le dejo el resumen de su propuesta:",
        "pt": "Com prazer. Antes de nos despedirmos, deixo o resumo da sua proposta:",
    },
    "summary": {
        "es": "• Producto: {product}\n• Monto: {amount}\n• Plazo: {months} meses\n• Tasa anual: {rate}\n• Cuota mensual estimada: {payment}\n• Endeudamiento con la cuota: {dti} de su ingreso (máximo {max_dti})\n• Estado: {status}\n• Documentación: {docs_status}{ticket_line}",
        "pt": "• Produto: {product}\n• Valor: {amount}\n• Prazo: {months} meses\n• Taxa anual: {rate}\n• Parcela mensal estimada: {payment}\n• Endividamento com a parcela: {dti} da sua renda (máximo {max_dti})\n• Situação: {status}\n• Documentação: {docs_status}{ticket_line}",
    },
    "email_notice": {
        "es": "Le enviaremos el detalle completo en un PDF al correo registrado ({email}). Es un resumen informativo: la aprobación final depende de la verificación del banco.",
        "pt": "Enviaremos o detalhe completo em um PDF para o e-mail cadastrado ({email}). É um resumo informativo: a aprovação final depende da verificação do banco.",
    },
    "email_notice_noaddr": {
        "es": "Le enviaremos el detalle completo en un PDF al correo que tenemos registrado. Es un resumen informativo: la aprobación final depende de la verificación del banco.",
        "pt": "Enviaremos o detalhe completo em um PDF para o e-mail que temos cadastrado. É um resumo informativo: a aprovação final depende da verificação do banco.",
    },
}

DOC_NAME = {
    "es": {"id_copy": "su copia del documento de identidad", "address_proof": "su comprobante de domicilio",
           "income_proof": "su comprobante de ingresos", "bank_statements_3m": "sus estados de cuenta de los últimos 3 meses",
           "property_deed": "la escritura de la propiedad", "appraisal": "el avalúo de la propiedad"},
    "pt": {"id_copy": "sua cópia do documento de identidade", "address_proof": "seu comprovante de endereço",
           "income_proof": "seu comprovante de renda", "bank_statements_3m": "seus extratos bancários dos últimos 3 meses",
           "property_deed": "a escritura do imóvel", "appraisal": "a avaliação do imóvel"},
}
SUMMARY_TEXT = {
    "es": {"eligible": "preliminarmente elegible", "provisional": "preliminarmente elegible, sujeta a verificación de ingresos",
           "docs_complete": "completa; la revisará un asesor", "docs_pending": "pendiente: {missing}", "docs_not_started": "aún sin iniciar",
           "ticket_line": "\n• Seguimiento: {ticket}"},
    "pt": {"eligible": "preliminarmente elegível", "provisional": "preliminarmente elegível, sujeita à verificação de renda",
           "docs_complete": "completa; um consultor fará a revisão", "docs_pending": "pendente: {missing}", "docs_not_started": "ainda não iniciada",
           "ticket_line": "\n• Acompanhamento: {ticket}"},
}
REASK = {"es": "Perdone, no le entendí bien. ", "pt": "Desculpe, não entendi bem. "}
SUMMARY_LABELS = {
    "es": [("product", "Producto"), ("amount", "Monto"), ("months_text", "Plazo"), ("rate", "Tasa anual"),
           ("payment", "Cuota mensual estimada"), ("dti_text", "Endeudamiento con la cuota"), ("status", "Estado"),
           ("docs_status", "Documentación")],
    "pt": [("product", "Produto"), ("amount", "Valor"), ("months_text", "Prazo"), ("rate", "Taxa anual"),
           ("payment", "Parcela mensal estimada"), ("dti_text", "Endividamento com a parcela"), ("status", "Situação"),
           ("docs_status", "Documentação")],
}
PDF_NOTES = {
    "es": ["Simulación con datos y política sintéticos: no constituye una oferta ni una aprobación de crédito.",
           "Las cifras están sujetas a la verificación de ingresos y documentos y a la aprobación final del banco."],
    "pt": ["Simulação com dados e política sintéticos: não constitui uma oferta nem uma aprovação de crédito.",
           "Os valores estão sujeitos à verificação de renda e documentos e à aprovação final do banco."],
}
EMAIL_SUBJECT = {"es": "Resumen de su propuesta de crédito", "pt": "Resumo da sua proposta de crédito"}

SUGGESTIONS = {
    "yes_no": {"es": ["Sí", "No"], "pt": ["Sim", "Não"]},
    "start": {"es": ["Consultar mis productos", "Ver mi oferta de crédito", "Hablar con un asesor"],
              "pt": ["Consultar meus produtos", "Ver minha oferta de crédito", "Falar com um consultor"]},
    # Al abrir con un caso pendiente: lo primero es ese caso.
    "start_case": {"es": ["Sí, cuénteme", "Consultar mis productos", "Hablar con un asesor"],
                   "pt": ["Sim, conte", "Consultar meus produtos", "Falar com um consultor"]},
}


def render(kind: str, lang: str, fmt: dict[str, str], variant: int = 0) -> str:
    text = T[kind][lang]
    if isinstance(text, list):
        text = text[variant % len(text)]
    return text.format(**{"fx": "", "lead": "", **fmt})


def render_facts(facts: dict, lang: str) -> str:
    """Texto base + (opcional) un segundo mensaje en la misma linea (p. ej. la pregunta de seguir) + bloques aparte."""
    v = facts.get("variant", 0)
    text = " ".join(render(p, lang, facts["fmt"], v) for p in facts.get("pre", []))
    text = (text + " " if text else "") + render(facts["kind"], lang, facts["fmt"], v)
    if facts.get("kind2"):
        text += " " + render(facts["kind2"], lang, facts["fmt"], v)
    for extra in facts.get("extras", []):
        text += "\n\n" + render(extra, lang, facts["fmt"], v)
    return text


def join_list(items: list[str], lang: str) -> str:
    """'a, b y c' / 'a, b e c'."""
    conj = {"es": "y", "pt": "e"}[lang]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {conj} {items[-1]}"
