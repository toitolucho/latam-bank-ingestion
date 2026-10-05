"""Conjunto de evaluacion del NLU: frases en es/pt con la intencion esperada.

ETIQUETAS ESCRITAS POR UN SOLO ANOTADOR (no por humanos independientes): el equipo debe revisarlas antes de usarlas
como evidencia. Ninguna frase aqui aparece como ejemplo en los prompts del LLM (evita fuga entre ejemplos y prueba).
Formato: (texto, intencion, idioma, tema_sensible)
"""
CASES: list[tuple[str, str, str, bool]] = [
    # credit_offers: tasas, limites, ofertas, cuanto podrian prestar (sin pedir un monto concreto)
    ("¿cuáles son las tasas de interés de los préstamos?", "credit_offers", "es", False),
    ("quisiera saber cuánto me podrían prestar", "credit_offers", "es", False),
    ("¿tienen alguna oferta de crédito para mí?", "credit_offers", "es", False),
    ("¿qué créditos tengo preaprobados?", "credit_offers", "es", False),
    ("cuál es el límite que me pueden dar", "credit_offers", "es", False),
    ("quais são os juros do empréstimo?", "credit_offers", "pt", False),
    ("quanto o banco poderia me emprestar?", "credit_offers", "pt", False),
    ("vocês têm alguma oferta de crédito para mim?", "credit_offers", "pt", False),
    ("tenho algum crédito pré-aprovado?", "credit_offers", "pt", False),
    ("qual a taxa do financiamento imobiliário?", "credit_offers", "pt", False),
    # credit_eligibility: quiere un credito / pregunta si califica para un monto o producto
    ("necesito 15 mil pesos prestados para una reforma", "credit_eligibility", "es", False),
    ("me interesa un crédito hipotecario", "credit_eligibility", "es", False),
    ("quiero solicitar una tarjeta de crédito", "credit_eligibility", "es", False),
    ("¿podría sacar un préstamo de 20.000 a 36 meses?", "credit_eligibility", "es", False),
    ("ocupo financiar un auto", "credit_eligibility", "es", False),
    ("preciso de um empréstimo de 10 mil", "credit_eligibility", "pt", False),
    ("quero financiar um carro", "credit_eligibility", "pt", False),
    ("gostaria de solicitar um cartão de crédito", "credit_eligibility", "pt", False),
    ("posso pegar 8.000 emprestados em 24 meses?", "credit_eligibility", "pt", False),
    ("tenho interesse em um crédito imobiliário", "credit_eligibility", "pt", False),
    # update_income
    ("mi sueldo subió a 5.200 mensuales", "update_income", "es", False),
    ("ahora mi ingreso es de 7000 al mes", "update_income", "es", False),
    ("mi esposa también trabaja, juntos ganamos 9000", "update_income", "es", False),
    ("agora ganho 4.500 por mês", "update_income", "pt", False),
    ("meu salário passou para 6.000", "update_income", "pt", False),
    # request_human (peticion explicita)
    ("quiero hablar con una persona", "request_human", "es", False),
    ("pásame con un asesor, por favor", "request_human", "es", False),
    ("me comunica con un ejecutivo", "request_human", "es", False),
    ("preciso falar com um atendente", "request_human", "pt", False),
    ("quero falar com uma pessoa de verdade", "request_human", "pt", False),
    # greeting / thanks / closing
    ("hola, buenos días", "greeting", "es", False),
    ("buenas tardes", "greeting", "es", False),
    ("olá, bom dia", "greeting", "pt", False),
    ("oi, tudo bem?", "greeting", "pt", False),
    ("muchas gracias por la ayuda", "thanks", "es", False),
    ("te agradezco mucho", "thanks", "es", False),
    ("valeu, muito obrigado", "thanks", "pt", False),
    ("eso es todo, hasta luego", "closing", "es", False),
    ("no necesito nada más, chao", "closing", "es", False),
    ("isso é tudo, até logo", "closing", "pt", False),
    ("era só isso, tchau", "closing", "pt", False),
    # other_topic (no sensible)
    ("¿cuál es el horario de la sucursal más cercana?", "other_topic", "es", False),
    ("olvidé la clave de mi app", "other_topic", "es", False),
    ("necesito una constancia de saldo", "account_inquiry", "es", False),
    ("quanto tenho de saldo na minha conta?", "account_inquiry", "pt", False),
    ("como atualizo meu endereço no aplicativo?", "other_topic", "pt", False),
    # other_topic sensible (fraude, reclamo, robo)
    ("no reconozco un cargo de 300 dólares en mi tarjeta", "other_topic", "es", True),
    ("me robaron la tarjeta ayer", "other_topic", "es", True),
    ("creo que me clonaron la tarjeta", "other_topic", "es", True),
    ("quero contestar uma cobrança indevida", "other_topic", "pt", True),
    ("estoy muy enojado, llevo semanas con un reclamo sin respuesta", "case_status", "es", True),
    ("usaron mi cuenta sin mi autorización", "other_topic", "es", True),
    ("alguém fez compras no meu cartão sem minha permissão", "other_topic", "pt", True),
    # account_inquiry: pregunta por SUS productos o cuenta (sin pedir un credito)
    ("¿qué productos tengo con el banco?", "account_inquiry", "es", False),
    ("quisiera ver los movimientos de mi cuenta corriente", "account_inquiry", "es", False),
    ("¿todavía tengo activa mi tarjeta de débito?", "account_inquiry", "es", False),
    ("quais produtos eu tenho no banco?", "account_inquiry", "pt", False),
    ("preciso ver os movimentos da minha conta", "account_inquiry", "pt", False),
    ("¿tengo un crédito hipotecario con ustedes?", "account_inquiry", "es", False),
    # case_status: pregunta por un reclamo, queja o caso que YA tiene abierto
    ("quiero saber cómo va el seguimiento de mi queja", "case_status", "es", True),
    ("¿mi reclamo sigue abierto?", "case_status", "es", True),
    ("¿en qué estado está mi solicitud?", "case_status", "es", False),
    ("qual o andamento da minha reclamação?", "case_status", "pt", True),
    ("meu chamado ainda está aberto?", "case_status", "pt", False),
    # ask_identity: pregunta quien o que atiende (la respuesta debe ser honesta)
    ("¿eres un robot?", "ask_identity", "es", False),
    ("¿hablo con una persona real?", "ask_identity", "es", False),
    ("¿con quién hablo?", "ask_identity", "es", False),
    ("você é um robô?", "ask_identity", "pt", False),
    ("estou falando com uma pessoa?", "ask_identity", "pt", False),
    # confirmaciones
    ("sí, por favor", "confirm_yes", "es", False),
    ("claro que sí", "confirm_yes", "es", False),
    ("sim, pode ser", "confirm_yes", "pt", False),
    ("no gracias", "confirm_no", "es", False),
    ("prefiero que no", "confirm_no", "es", False),
    ("não, obrigado", "confirm_no", "pt", False),
    # fuera de alcance
    ("asdfgh", "unknown", "es", False),
    ("¿cuál es la capital de Francia?", "unknown", "es", False),
    ("qual é a previsão do tempo para amanhã?", "unknown", "pt", False),
]


# Frases cuya evaluacion incluye una pregunta de si/no pendiente (la respuesta del cliente es a esa pregunta)
PENDING_TEXTS = {"sí, por favor", "claro que sí", "sim, pode ser", "no gracias", "prefiero que no", "não, obrigado",
                 "dale, cuéntame", "por ahora no, gracias", "sim, quero saber mais", "agora não"}

# CONJUNTO RESERVADO: escrito antes de ajustar prompts y reglas y no se usa para afinar. Se mide una sola vez al final.
HELDOUT: list[tuple[str, str, str, bool]] = [
    ("¿qué tasa me darían por un préstamo personal?", "credit_offers", "es", False),
    ("o banco tem alguma proposta de crédito para mim?", "credit_offers", "pt", False),
    ("¿cuánto dinero podría pedir prestado hoy?", "credit_offers", "es", False),
    ("qual seria meu limite de crédito?", "credit_offers", "pt", False),
    ("quiero un préstamo de 12.000 para pagar mis deudas", "credit_eligibility", "es", False),
    ("necesito dinero prestado para abrir un negocio", "credit_eligibility", "es", False),
    ("preciso de 5 mil reais emprestados", "credit_eligibility", "pt", False),
    ("quero um cartão de crédito com limite maior", "credit_eligibility", "pt", False),
    ("¿me alcanza para una hipoteca de 800 mil?", "credit_eligibility", "es", False),
    ("cambié de trabajo y ahora cobro 6.800", "update_income", "es", False),
    ("meu rendimento mensal agora é 5.500", "update_income", "pt", False),
    ("necesito que me atienda una persona", "request_human", "es", False),
    ("quero ser atendido por um humano", "request_human", "pt", False),
    ("hola, ¿cómo están?", "greeting", "es", False),
    ("boa tarde", "greeting", "pt", False),
    ("gracias, muy amable", "thanks", "es", False),
    ("obrigada pela ajuda", "thanks", "pt", False),
    ("listo, es todo por hoy", "closing", "es", False),
    ("pode encerrar, era só isso", "closing", "pt", False),
    ("¿dónde queda el cajero más cercano?", "other_topic", "es", False),
    ("preciso do extrato da minha conta", "account_inquiry", "pt", False),
    ("alguien usó mi tarjeta sin permiso", "other_topic", "es", True),
    ("fui vítima de um golpe no pix", "other_topic", "pt", True),
    ("dale, cuéntame", "confirm_yes", "es", False),
    ("sim, quero saber mais", "confirm_yes", "pt", False),
    ("por ahora no, gracias", "confirm_no", "es", False),
    ("agora não", "confirm_no", "pt", False),
    ("¿cuánto es 15 por 12?", "unknown", "es", False),
    ("me gusta el fútbol", "unknown", "es", False),
]
