import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN")
SUPPORT_GROUP_ID = int(os.getenv("SUPPORT_GROUP_ID", "0"))
tickets = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🎫 Abrir Ticket", callback_data="open_ticket")]]
    await update.message.reply_text(
        "👋 Olá!\n\nBem-vindo ao suporte.\nClique abaixo para abrir um ticket.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if query.data == "open_ticket":
        if user.id in tickets:
            await query.edit_message_text("⚠️ Você já possui um ticket aberto.")
            return

        tickets[user.id] = {
            "name": user.full_name,
            "username": user.username
        }

        await query.edit_message_text(
            "✅ Ticket aberto!\n\nEnvie sua mensagem agora. Nossa equipe irá responder."
        )

        await context.bot.send_message(
            chat_id=SUPPORT_GROUP_ID,
            text=(
                "🎫 NOVO TICKET\n\n"
                f"👤 Nome: {user.full_name}\n"
                f"🆔 ID: {user.id}\n"
                f"📱 Username: @{user.username if user.username else 'sem username'}"
            ),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔒 Fechar Ticket", callback_data=f"close_{user.id}")
            ]])
        )

    elif query.data.startswith("close_"):
        user_id = int(query.data.split("_")[1])
        if user_id in tickets:
            del tickets[user_id]
            try:
                await context.bot.send_message(user_id, "🔒 Seu ticket foi fechado pela equipe.")
            except Exception:
                pass
            await query.edit_message_text("🔒 Ticket fechado com sucesso.")
        else:
            await query.edit_message_text("⚠️ Esse ticket já está fechado.")

async def user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if user.id not in tickets:
        await update.message.reply_text("⚠️ Você não possui um ticket aberto. Use /start para abrir um.")
        return

    message = update.message
    text = message.text or "(mensagem sem texto)"

    await context.bot.send_message(
        chat_id=SUPPORT_GROUP_ID,
        text=(
            "📩 NOVA MENSAGEM\n\n"
            f"👤 {user.full_name}\n"
            f"🆔 ID: {user.id}\n\n"
            f"💬 {text}"
        )
    )
    await message.reply_text("✅ Mensagem enviada para o suporte.")

async def error_handler(update, context):
    print("Erro:", context.error)

def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN não configurado.")
    if SUPPORT_GROUP_ID == 0:
        raise RuntimeError("SUPPORT_GROUP_ID não configurado.")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, user_message))
    app.add_error_handler(error_handler)

    print("🤖 Bot iniciado!")
    app.run_polling()

if __name__ == "__main__":
    main()
