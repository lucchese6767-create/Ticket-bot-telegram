import os

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)


# =========================================================
# CONFIGURAÇÕES
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")

SUPPORT_GROUP_ID = int(
    os.getenv("SUPPORT_GROUP_ID", "0")
)


# =========================================================
# TICKETS
# user_id -> topic_id
# =========================================================

tickets = {}


# =========================================================
# /START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    keyboard = [
        [
            InlineKeyboardButton(
                "🎫 Abrir Ticket",
                callback_data="open_ticket"
            )
        ]
    ]

    await update.message.reply_text(
        "👋 Olá!\n\n"
        "Bem-vindo ao suporte.\n\n"
        "Clique no botão abaixo para abrir um ticket.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# /ID
# =========================================================

async def get_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        f"🆔 ID deste chat:\n\n"
        f"{update.effective_chat.id}"
    )


# =========================================================
# ABRIR TICKET
# =========================================================

async def open_ticket(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user = query.from_user


    # -----------------------------------------------------
    # Verificar se já existe ticket
    # -----------------------------------------------------

    if user.id in tickets:

        await query.edit_message_text(
            "⚠️ Você já possui um ticket aberto."
        )

        return


    try:

        # -------------------------------------------------
        # Criar tópico no grupo Fórum
        # -------------------------------------------------

        topic = await context.bot.create_forum_topic(
            chat_id=SUPPORT_GROUP_ID,
            name=f"🎫 Ticket - {user.first_name}"
        )


        topic_id = topic.message_thread_id


        # -------------------------------------------------
        # Salvar ticket
        # -------------------------------------------------

        tickets[user.id] = topic_id


        # -------------------------------------------------
        # Botão de fechar
        # -------------------------------------------------

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔒 Fechar Ticket",
                        callback_data=f"close_{user.id}"
                    )
                ]
            ]
        )


        # -------------------------------------------------
        # Mensagem inicial no tópico
        # -------------------------------------------------

        await context.bot.send_message(

            chat_id=SUPPORT_GROUP_ID,

            message_thread_id=topic_id,

            text=(
                "🎫 NOVO TICKET\n\n"

                f"👤 Nome: {user.full_name}\n"

                f"🆔 ID: {user.id}\n"

                f"📱 Username: "
                f"@{user.username if user.username else 'sem username'}\n\n"

                "📩 O usuário abriu um ticket.\n\n"

                "A equipe pode responder neste tópico."
            ),

            reply_markup=keyboard
        )


        # -------------------------------------------------
        # Resposta para o usuário
        # -------------------------------------------------

        await query.edit_message_text(

            "✅ Ticket criado com sucesso!\n\n"

            "📩 Envie sua mensagem aqui.\n\n"

            "Nossa equipe responderá pelo suporte."
        )


    except Exception as error:

        print(
            "❌ ERRO AO CRIAR TICKET:",
            error
        )


        await query.edit_message_text(

            "❌ Não consegui criar seu ticket.\n\n"

            "Verifique se o grupo de suporte está configurado "
            "como Fórum e se o bot é administrador."
        )


# =========================================================
# FECHAR TICKET
# =========================================================

async def close_ticket(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()


    # -----------------------------------------------------
    # Pegar ID do usuário
    # -----------------------------------------------------

    user_id = int(
        query.data.split("_")[1]
    )


    # -----------------------------------------------------
    # Verificar ticket
    # -----------------------------------------------------

    if user_id not in tickets:

        await query.edit_message_text(
            "⚠️ Esse ticket já está fechado."
        )

        return


    # -----------------------------------------------------
    # Pegar tópico
    # -----------------------------------------------------

    topic_id = tickets[user_id]


    # -----------------------------------------------------
    # Remover ticket
    # -----------------------------------------------------

    del tickets[user_id]


    # -----------------------------------------------------
    # Avisar usuário
    # -----------------------------------------------------

    try:

        await context.bot.send_message(

            chat_id=user_id,

            text=(
                "🔒 Seu ticket foi fechado.\n\n"

                "Obrigado por entrar em contato "
                "com o suporte."
            )
        )

    except Exception as error:

        print(
            "Erro ao avisar usuário:",
            error
        )


    # -----------------------------------------------------
    # Fechar tópico
    # -----------------------------------------------------

    try:

        await context.bot.close_forum_topic(

            chat_id=SUPPORT_GROUP_ID,

            message_thread_id=topic_id
        )

    except Exception as error:

        print(
            "Erro ao fechar tópico:",
            error
        )


    # -----------------------------------------------------
    # Atualizar mensagem
    # -----------------------------------------------------

    await query.edit_message_text(
        "🔒 Ticket fechado com sucesso."
    )


# =========================================================
# MENSAGEM DO USUÁRIO
# =========================================================

async def private_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user


    # -----------------------------------------------------
    # Verificar se possui ticket
    # -----------------------------------------------------

    if user.id not in tickets:

        await update.message.reply_text(

            "⚠️ Você não possui um ticket aberto.\n\n"

            "Use /start para criar um ticket."
        )

        return


    # -----------------------------------------------------
    # Pegar tópico
    # -----------------------------------------------------

    topic_id = tickets[user.id]


    text = update.message.text


    if not text:

        return


    # -----------------------------------------------------
    # Enviar para o grupo
    # -----------------------------------------------------

    await context.bot.send_message(

        chat_id=SUPPORT_GROUP_ID,

        message_thread_id=topic_id,

        text=(
            "👤 USUÁRIO\n\n"

            f"{user.full_name}\n\n"

            f"💬 {text}"
        )
    )


    # -----------------------------------------------------
    # Confirmar para usuário
    # -----------------------------------------------------

    await update.message.reply_text(
        "✅ Mensagem enviada para o suporte."
    )


# =========================================================
# MENSAGEM DO ATENDENTE
# =========================================================

async def group_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.message


    # -----------------------------------------------------
    # Verificar se é tópico
    # -----------------------------------------------------

    if not message.message_thread_id:

        return


    topic_id = message.message_thread_id


    # -----------------------------------------------------
    # Ignorar mensagens do bot
    # -----------------------------------------------------

    if (
        message.from_user
        and message.from_user.is_bot
    ):

        return


    # -----------------------------------------------------
    # Procurar usuário desse tópico
    # -----------------------------------------------------

    user_id = None


    for uid, tid in tickets.items():

        if tid == topic_id:

            user_id = uid

            break


    if user_id is None:

        return


    # -----------------------------------------------------
    # Pegar mensagem
    # -----------------------------------------------------

    text = message.text


    if not text:

        return


    # -----------------------------------------------------
    # Enviar resposta ao usuário
    # -----------------------------------------------------

    try:

        await context.bot.send_message(

            chat_id=user_id,

            text=(
                "👨‍💻 SUPORTE\n\n"

                f"{text}"
            )
        )

    except Exception as error:

        print(
            "❌ Erro ao enviar resposta:",
            error
        )


# =========================================================
# BOT INICIADO
# =========================================================

async def post_init(
    application: Application
):

    me = await application.bot.get_me()


    print(
        f"🤖 Bot conectado: @{me.username}"
    )


# =========================================================
# MAIN
# =========================================================

def main():

    # -----------------------------------------------------
    # Verificar TOKEN
    # -----------------------------------------------------

    if not TOKEN:

        raise RuntimeError(
            "BOT_TOKEN não configurado."
        )


    # -----------------------------------------------------
    # Verificar ID do grupo
    # -----------------------------------------------------

    if SUPPORT_GROUP_ID == 0:

        raise RuntimeError(
            "SUPPORT_GROUP_ID não configurado."
        )


    # -----------------------------------------------------
    # Criar aplicação
    # -----------------------------------------------------

    application = (

        Application.builder()

        .token(TOKEN)

        .post_init(post_init)

        .build()
    )


    # -----------------------------------------------------
    # Comandos
    # -----------------------------------------------------

    application.add_handler(

        CommandHandler(
            "start",
            start
        )
    )


    application.add_handler(

        CommandHandler(
            "id",
            get_id
        )
    )


    # -----------------------------------------------------
    # Botão Abrir Ticket
    # -----------------------------------------------------

    application.add_handler(

        CallbackQueryHandler(

            open_ticket,

            pattern="^open_ticket$"
        )
    )


    # -----------------------------------------------------
    # Botão Fechar Ticket
    # -----------------------------------------------------

    application.add_handler(

        CallbackQueryHandler(

            close_ticket,

            pattern=r"^close_[0-9]+$"
        )
    )


    # -----------------------------------------------------
    # Mensagens privadas
    # -----------------------------------------------------

    application.add_handler(

        MessageHandler(

            filters.ChatType.PRIVATE
            & filters.TEXT
            & ~filters.COMMAND,

            private_message
        )
    )


    # -----------------------------------------------------
    # Mensagens do grupo
    # -----------------------------------------------------

    application.add_handler(

        MessageHandler(

            filters.ChatType.SUPERGROUP
            & filters.TEXT
            & ~filters.COMMAND,

            group_message
        )
    )


    print(
        "🚀 Iniciando bot..."
    )


    # -----------------------------------------------------
    # Iniciar bot
    # -----------------------------------------------------

    application.run_polling(

        allowed_updates=Update.ALL_TYPES
    )


# =========================================================
# EXECUTAR
# =========================================================

if __name__ == "__main__":

    main()
