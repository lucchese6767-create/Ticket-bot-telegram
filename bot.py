import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

TOKEN = os.getenv("BOT_TOKEN")
SUPPORT_GROUP_ID = int(os.getenv("SUPPORT_GROUP_ID", "0"))

tickets = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎫 Abrir Ticket", callback_data="open_ticket")]
    ]

    await update.message.reply_text(
        "👋 Olá!\n\n"
        "Bem-vindo ao suporte.\n\n"
        "Clique abaixo para abrir um ticket.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆔 ID deste chat:\n\n{update.effective_chat.id}"
    )


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user

    if query.data == "open_ticket":

        if user.id in tickets:
            await query.edit_message_text(
                "⚠️ Você já possui um ticket aberto."
            )
            return

        tickets[user.id] = True

        await query.edit_message_text(
            "✅ Ticket aberto!\n\n"
            "Envie sua mensagem para o suporte."
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔒 Fechar Ticket",
                    callback_data=f"close_{user.id}"
                )
            ]
        ])

        await context.bot.send_message(
            chat_id=SUPPORT_GROUP_ID,
            text=(
                "🎫 NOVO TICKET\n\n"
                f"👤 Nome: {user.full_name}\n"
                f"🆔 ID: {user.id}\n"
                f"📱 Username: "
                f"@{user.username if user.username else 'sem username'}\n\n"
                "📩 O usuário abriu um ticket."
            ),
            reply_markup=keyboard
        )

    elif query.data.startswith("close_"):

        user_id = int(query.data.split("_")[1])

        if user_id in tickets:

            del tickets[user_id]

            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="🔒 Seu ticket foi fechado pela equipe."
                )
            except Exception:
                pass

            await query.edit_message_text(
                "🔒 Ticket fechado com sucesso."
            )

        else:
            await query.edit_message_text(
                "⚠️ Esse ticket já está fechado."
            )


async def user_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if user.id not in tickets:

        await update.message.reply_text(
            "⚠️ Você não possui um ticket aberto.\n"
            "Use /start para abrir um."
        )

        return

    text = update.message.text or "(mensagem sem texto)"

    await context.bot.send_message(
        chat_id=SUPPORT_GROUP_ID,
        text=(
            "📩 NOVA MENSAGEM\n\n"
            f"👤 {user.full_name}\n"
            f"🆔 ID: {user.id}\n\n"
            f"💬 {text}"
        )
    )

    await update.message.reply_text(
        "✅ Mensagem enviada para o suporte."
    )


async def post_init(application: Application):

    me = await application.bot.get_me()

    print(
        f"🤖 Bot conectado: @{me.username}"
    )


def main():

    if not TOKEN:
        raise RuntimeError(
            "BOT_TOKEN não configurado."
        )

    if SUPPORT_GROUP_ID == 0:
        raise RuntimeError(
            "SUPPORT_GROUP_ID não configurado."
        )

    application = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("id", get_id)
    )

    application.add_handler(
        CallbackQueryHandler(button)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            user_message
        )
    )

    print("🚀 Iniciando bot...")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
