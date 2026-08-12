import os
import io
import sqlite3
import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SUPPORT_CHAT_ID = int(os.getenv("SUPPORT_CHAT_ID", "0") or 0)
LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID", "0") or 0)

OWNER_IDS = {
    int(x.strip())
    for x in os.getenv("OWNER_IDS", "").split(",")
    if x.strip().isdigit()
}

DATABASE = os.getenv("DATABASE", "tickets.db")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ticket-bot")

ROLES = {
    "admin": {"name": "👑 Administrador", "level": 4},
    "supervisor": {"name": "🛡️ Supervisor", "level": 3},
    "support": {"name": "👨‍💻 Suporte", "level": 2},
    "trainee": {"name": "🎓 Treinando", "level": 1},
}

CATEGORIES = {
    "compras": "🛒 Compras",
    "suporte": "🛠️ Suporte",
    "financeiro": "💰 Financeiro",
    "outros": "📦 Outros",
}

PRIORITIES = {
    "low": "🟢 Baixa",
    "normal": "🟡 Normal",
    "high": "🟠 Alta",
    "urgent": "🔴 Urgente",
}


# ============================================================
# DATABASE
# ============================================================

def db():
    conn = sqlite3.connect(DATABASE, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            full_name TEXT,
            category TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            priority TEXT NOT NULL DEFAULT 'normal',
            topic_id INTEGER,
            assigned_to INTEGER,
            created_at TEXT NOT NULL,
            closed_at TEXT,
            closed_by INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            role TEXT NOT NULL DEFAULT 'support',
            added_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ticket_staff (
            ticket_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            added_at TEXT NOT NULL,
            PRIMARY KEY(ticket_id, user_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            sender_type TEXT NOT NULL,
            message_type TEXT,
            content TEXT,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def now():
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def get_ticket(ticket_id):
    conn = db()
    row = conn.execute(
        "SELECT * FROM tickets WHERE id = ? LIMIT 1",
        (ticket_id,),
    ).fetchone()
    conn.close()
    return row


def get_open_ticket(user_id):
    conn = db()
    row = conn.execute("""
        SELECT * FROM tickets
        WHERE user_id = ? AND status = 'open'
        ORDER BY id DESC LIMIT 1
    """, (user_id,)).fetchone()
    conn.close()
    return row


def get_ticket_by_topic(topic_id):
    conn = db()
    row = conn.execute("""
        SELECT * FROM tickets
        WHERE topic_id = ? AND status = 'open'
        LIMIT 1
    """, (topic_id,)).fetchone()
    conn.close()
    return row


def create_ticket(user, category):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO tickets
        (user_id, username, full_name, category, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        user.id,
        f"@{user.username}" if user.username else "",
        user.full_name,
        category,
        now(),
    ))
    ticket_id = cur.lastrowid
    conn.commit()
    conn.close()
    return ticket_id


def update_ticket(ticket_id, field, value):
    allowed = {
        "topic_id", "assigned_to", "priority",
        "status", "closed_at", "closed_by"
    }
    if field not in allowed:
        raise ValueError("Campo inválido.")
    conn = db()
    conn.execute(
        f"UPDATE tickets SET {field} = ? WHERE id = ?",
        (value, ticket_id),
    )
    conn.commit()
    conn.close()


def close_ticket_db(ticket_id, user_id):
    conn = db()
    conn.execute("""
        UPDATE tickets
        SET status = 'closed', closed_at = ?, closed_by = ?
        WHERE id = ?
    """, (now(), user_id, ticket_id))
    conn.commit()
    conn.close()


def get_staff(user_id):
    conn = db()
    row = conn.execute("""
        SELECT user_id, username, full_name, role
        FROM staff WHERE user_id = ?
    """, (user_id,)).fetchone()
    conn.close()
    return row


def add_staff_db(user_id, username, full_name, role):
    conn = db()
    conn.execute("""
        INSERT OR REPLACE INTO staff
        (user_id, username, full_name, role, added_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, username, full_name, role, now()))
    conn.commit()
    conn.close()


def remove_staff_db(user_id):
    conn = db()
    conn.execute("DELETE FROM staff WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def add_ticket_staff_db(ticket_id, user_id):
    conn = db()
    conn.execute("""
        INSERT OR IGNORE INTO ticket_staff
        (ticket_id, user_id, added_at)
        VALUES (?, ?, ?)
    """, (ticket_id, user_id, now()))
    conn.commit()
    conn.close()


def remove_ticket_staff_db(ticket_id, user_id):
    conn = db()
    conn.execute("""
        DELETE FROM ticket_staff
        WHERE ticket_id = ? AND user_id = ?
    """, (ticket_id, user_id))
    conn.commit()
    conn.close()


def ticket_staff_list(ticket_id):
    conn = db()
    rows = conn.execute("""
        SELECT user_id FROM ticket_staff
        WHERE ticket_id = ? ORDER BY added_at
    """, (ticket_id,)).fetchall()
    conn.close()
    return [r[0] for r in rows]


def has_staff_permission(user_id, minimum="support"):
    if user_id in OWNER_IDS:
        return True
    staff = get_staff(user_id)
    if not staff:
        return False
    role = staff[3]
    return (
        role in ROLES
        and minimum in ROLES
        and ROLES[role]["level"] >= ROLES[minimum]["level"]
    )


def has_ticket_access(ticket_id, user_id):
    if has_staff_permission(user_id, "support"):
        return True
    return user_id in ticket_staff_list(ticket_id)


def save_message(ticket_id, sender_id, sender_type, message_type, content):
    conn = db()
    conn.execute("""
        INSERT INTO messages
        (ticket_id, sender_id, sender_type, message_type, content, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        ticket_id,
        sender_id,
        sender_type,
        message_type,
        content or "",
        now(),
    ))
    conn.commit()
    conn.close()


def get_messages(ticket_id):
    conn = db()
    rows = conn.execute("""
        SELECT sender_id, sender_type, message_type, content, created_at
        FROM messages WHERE ticket_id = ? ORDER BY id ASC
    """, (ticket_id,)).fetchall()
    conn.close()
    return rows


# ============================================================
# HELPERS
# ============================================================

def display_user(user):
    if user.username:
        return f"@{user.username}"
    return user.full_name or str(user.id)


def topic_id_from_message(message):
    return getattr(message, "message_thread_id", None)


def ticket_info(ticket):
    if not ticket:
        return "❌ Ticket não encontrado."

    assigned = (
        f"`{ticket[7]}`" if ticket[7] else "Ninguém"
    )
    return (
        f"🎫 **Ticket #{ticket[0]:04d}**\n"
        f"👤 Usuário: {ticket[2] or ticket[3]}\n"
        f"🆔 ID: `{ticket[1]}`\n"
        f"📂 Categoria: {ticket[4]}\n"
        f"📌 Status: `{ticket[5]}`\n"
        f"🚨 Prioridade: {PRIORITIES.get(ticket[6], ticket[6])}\n"
        f"🎯 Responsável: {assigned}\n"
        f"🕒 Criado: {ticket[9]}"
    )


def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎫 Abrir Ticket", callback_data="open")],
        [InlineKeyboardButton("📌 Meu Ticket", callback_data="mine")],
    ])


def category_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Compras", callback_data="cat:compras")],
        [InlineKeyboardButton("🛠️ Suporte", callback_data="cat:suporte")],
        [InlineKeyboardButton("💰 Financeiro", callback_data="cat:financeiro")],
        [InlineKeyboardButton("📦 Outros", callback_data="cat:outros")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="back")],
    ])


def staff_ticket_keyboard(ticket_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎯 Assumir", callback_data=f"claim:{ticket_id}"),
            InlineKeyboardButton("🔒 Fechar", callback_data=f"close:{ticket_id}"),
        ],
        [
            InlineKeyboardButton("🚨 Prioridade", callback_data=f"priority:{ticket_id}"),
        ],
    ])


async def send_log(context, text):
    if not LOG_CHAT_ID:
        return
    try:
        await context.bot.send_message(
            chat_id=LOG_CHAT_ID,
            text=text,
            parse_mode="Markdown",
        )
    except Exception:
        logger.exception("Falha ao enviar log.")


def message_content(message):
    if message.text:
        return message.text
    if message.caption:
        return message.caption
    if message.photo:
        return "[foto]"
    if message.video:
        return "[vídeo]"
    if message.document:
        return f"[documento: {message.document.file_name or 'arquivo'}]"
    if message.audio:
        return "[áudio]"
    if message.voice:
        return "[mensagem de voz]"
    if message.sticker:
        return "[sticker]"
    if message.animation:
        return "[GIF/animação]"
    if message.contact:
        return "[contato]"
    if message.location:
        return "[localização]"
    return "[mensagem não textual]"


def message_type(message):
    if message.text:
        return "text"
    if message.photo:
        return "photo"
    if message.video:
        return "video"
    if message.document:
        return "document"
    if message.audio:
        return "audio"
    if message.voice:
        return "voice"
    if message.sticker:
        return "sticker"
    if message.animation:
        return "animation"
    if message.contact:
        return "contact"
    if message.location:
        return "location"
    return "other"


# ============================================================
# TRANSCRIPT
# ============================================================

def transcript(ticket):
    lines = [
        "=" * 60,
        f"TICKET #{ticket[0]:04d}",
        "=" * 60,
        f"Usuário: {ticket[2] or ticket[3]}",
        f"ID: {ticket[1]}",
        f"Categoria: {ticket[4]}",
        f"Prioridade: {ticket[6]}",
        f"Status: {ticket[5]}",
        f"Criado: {ticket[9]}",
        f"Fechado: {ticket[10] or '-'}",
        "",
        "-" * 60,
        "MENSAGENS",
        "-" * 60,
    ]

    for sender_id, sender_type, mtype, content, created in get_messages(ticket[0]):
        lines.append(
            f"[{created}] {sender_type.upper()} | {sender_id} | {mtype}"
        )
        lines.append(content or "[sem conteúdo]")
        lines.append("")

    return "\n".join(lines)


async def send_transcript(context, ticket):
    if not LOG_CHAT_ID:
        return

    data = transcript(ticket).encode("utf-8")
    file = io.BytesIO(data)
    file.name = f"ticket-{ticket[0]:04d}.txt"

    try:
        await context.bot.send_document(
            chat_id=LOG_CHAT_ID,
            document=file,
            caption=f"📜 Transcrição do Ticket #{ticket[0]:04d}",
        )
    except Exception:
        logger.exception("Falha ao enviar transcrição.")


# ============================================================
# COMMANDS - USER
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return

    await update.message.reply_text(
        "👋 Olá!\n\n"
        "🎫 **CENTRAL DE ATENDIMENTO**\n\n"
        "Abra um ticket para falar com nossa equipe.",
        parse_mode="Markdown",
        reply_markup=main_keyboard(),
    )


async def ticket_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return

    await update.message.reply_text(
        "🎫 **CENTRAL DE TICKETS**\n\nEscolha a categoria:",
        parse_mode="Markdown",
        reply_markup=category_keyboard(),
    )


# ============================================================
# COMMANDS - STAFF
# ============================================================

async def painel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != SUPPORT_CHAT_ID:
        return
    if not has_staff_permission(update.effective_user.id, "support"):
        await update.message.reply_text("❌ Você não faz parte da equipe.")
        return

    await update.message.reply_text(
        "🎫 **PAINEL DA EQUIPE**\n\n"
        "Use `/stats` para estatísticas.\n"
        "Use `/fechar` dentro de um ticket para fechar.\n"
        "Use `/assumir` para assumir.\n"
        "Use `/prioridade alta|urgente|normal|baixa` para alterar a prioridade.",
        parse_mode="Markdown",
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_staff_permission(update.effective_user.id, "support"):
        return

    conn = db()
    total = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
    open_count = conn.execute(
        "SELECT COUNT(*) FROM tickets WHERE status='open'"
    ).fetchone()[0]
    closed = conn.execute(
        "SELECT COUNT(*) FROM tickets WHERE status='closed'"
    ).fetchone()[0]
    urgent = conn.execute(
        "SELECT COUNT(*) FROM tickets WHERE status='open' AND priority='urgent'"
    ).fetchone()[0]
    conn.close()

    await update.message.reply_text(
        "📊 **ESTATÍSTICAS**\n\n"
        f"🎫 Total: `{total}`\n"
        f"🟢 Abertos: `{open_count}`\n"
        f"🔒 Fechados: `{closed}`\n"
        f"🔴 Urgentes: `{urgent}`",
        parse_mode="Markdown",
    )


def current_ticket_from_update(update):
    message = update.effective_message
    if not message:
        return None
    topic_id = topic_id_from_message(message)
    if not topic_id:
        return None
    return get_ticket_by_topic(topic_id)


async def assumir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not has_staff_permission(user.id, "support"):
        return

    ticket = current_ticket_from_update(update)
    if not ticket:
        await update.message.reply_text("❌ Use este comando dentro de um ticket.")
        return

    update_ticket(ticket[0], "assigned_to", user.id)
    add_ticket_staff_db(ticket[0], user.id)

    await update.message.reply_text(
        f"🎯 Ticket #{ticket[0]:04d} assumido por {display_user(user)}."
    )

    try:
        await context.bot.send_message(
            chat_id=ticket[1],
            text=f"🎯 Seu atendimento foi assumido por {display_user(user)}.",
        )
    except Exception:
        pass

    await send_log(
        context,
        f"🎯 Ticket #{ticket[0]:04d} assumido por `{user.id}`.",
    )


async def fechar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not has_staff_permission(user.id, "support"):
        return

    ticket = current_ticket_from_update(update)
    if not ticket:
        await update.message.reply_text("❌ Use este comando dentro de um ticket.")
        return

    await close_ticket_flow(context, ticket, user.id, update.message.chat_id)


async def prioridade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not has_staff_permission(user.id, "support"):
        return

    ticket = current_ticket_from_update(update)
    if not ticket:
        await update.message.reply_text("❌ Use este comando dentro de um ticket.")
        return

    if not context.args:
        await update.message.reply_text(
            "Uso: `/prioridade alta`\n"
            "Opções: baixa, normal, alta, urgente",
            parse_mode="Markdown",
        )
        return

    value = context.args[0].lower()
    aliases = {
        "baixa": "low",
        "low": "low",
        "normal": "normal",
        "alta": "high",
        "high": "high",
        "urgente": "urgent",
        "urgent": "urgent",
    }

    if value not in aliases:
        await update.message.reply_text("❌ Prioridade inválida.")
        return

    priority_value = aliases[value]
    update_ticket(ticket[0], "priority", priority_value)

    await update.message.reply_text(
        f"🚨 Prioridade alterada para {PRIORITIES[priority_value]}."
    )

    await send_log(
        context,
        f"🚨 Ticket #{ticket[0]:04d}: prioridade `{priority_value}` por `{user.id}`.",
    )


async def adicionar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not has_staff_permission(user.id, "supervisor"):
        await update.message.reply_text("❌ Apenas supervisor/admin.")
        return

    ticket = current_ticket_from_update(update)
    if not ticket:
        await update.message.reply_text("❌ Use dentro de um ticket.")
        return

    target_id = None

    if update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
    elif context.args and context.args[0].lstrip("-").isdigit():
        target_id = int(context.args[0])

    if not target_id:
        await update.message.reply_text(
            "Uso: `/adicionar ID_DO_USUARIO`\n"
            "ou responda a uma mensagem do agente.",
            parse_mode="Markdown",
        )
        return

    if not get_staff(target_id):
        await update.message.reply_text(
            "❌ Esse usuário não está cadastrado na equipe.\n"
            "Um administrador pode adicioná-lo com `/equipe_add`."
        )
        return

    add_ticket_staff_db(ticket[0], target_id)

    await update.message.reply_text(
        f"➕ Usuário `{target_id}` adicionado ao Ticket #{ticket[0]:04d}.",
        parse_mode="Markdown",
    )


async def remover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not has_staff_permission(user.id, "supervisor"):
        await update.message.reply_text("❌ Apenas supervisor/admin.")
        return

    ticket = current_ticket_from_update(update)
    if not ticket:
        await update.message.reply_text("❌ Use dentro de um ticket.")
        return

    target_id = None

    if update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
    elif context.args and context.args[0].lstrip("-").isdigit():
        target_id = int(context.args[0])

    if not target_id:
        await update.message.reply_text(
            "Uso: `/remover ID_DO_USUARIO`",
            parse_mode="Markdown",
        )
        return

    remove_ticket_staff_db(ticket[0], target_id)

    await update.message.reply_text(
        f"➖ Usuário `{target_id}` removido do Ticket #{ticket[0]:04d}.",
        parse_mode="Markdown",
    )


async def equipe_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not has_staff_permission(user.id, "admin"):
        return

    if len(context.args) < 1 or not context.args[0].lstrip("-").isdigit():
        await update.message.reply_text(
            "Uso: `/equipe_add ID [cargo]`\n"
            "Cargos: trainee, support, supervisor, admin",
            parse_mode="Markdown",
        )
        return

    target_id = int(context.args[0])
    role = context.args[1].lower() if len(context.args) > 1 else "support"

    if role not in ROLES:
        await update.message.reply_text("❌ Cargo inválido.")
        return

    add_staff_db(target_id, str(target_id), str(target_id), role)

    await update.message.reply_text(
        f"✅ `{target_id}` adicionado como {ROLES[role]['name']}.",
        parse_mode="Markdown",
    )


async def equipe_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not has_staff_permission(user.id, "admin"):
        return

    if not context.args or not context.args[0].lstrip("-").isdigit():
        await update.message.reply_text(
            "Uso: `/equipe_remove ID`",
            parse_mode="Markdown",
        )
        return

    target_id = int(context.args[0])
    if target_id in OWNER_IDS:
        await update.message.reply_text("❌ OWNER não pode ser removido por este comando.")
        return

    remove_staff_db(target_id)
    await update.message.reply_text(f"✅ `{target_id}` removido da equipe.", parse_mode="Markdown")


async def equipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not has_staff_permission(user.id, "support"):
        return

    conn = db()
    rows = conn.execute("""
        SELECT user_id, full_name, role FROM staff ORDER BY role, user_id
    """).fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("👥 Nenhum agente cadastrado.")
        return

    text = ["👥 **EQUIPE**", ""]
    for uid, name, role in rows:
        text.append(f"• `{uid}` — {name} — {ROLES[role]['name']}")
    await update.message.reply_text("\n".join(text), parse_mode="Markdown")


# ============================================================
# CLOSE
# ============================================================

async def close_ticket_flow(context, ticket, closed_by, staff_chat_id):
    if ticket[5] == "closed":
        return

    close_ticket_db(ticket[0], closed_by)

    try:
        await context.bot.send_message(
            chat_id=ticket[1],
            text=(
                f"🔒 Seu Ticket #{ticket[0]:04d} foi fechado.\n\n"
                "Se precisar de outro atendimento, use /ticket."
            ),
        )
    except Exception:
        pass

    try:
        await context.bot.send_message(
            chat_id=staff_chat_id,
            text=f"🔒 Ticket #{ticket[0]:04d} fechado.",
        )
    except Exception:
        pass

    closed_ticket = get_ticket(ticket[0])
    await send_transcript(context, closed_ticket)
    await send_log(
        context,
        f"🔒 Ticket #{ticket[0]:04d} fechado por `{closed_by}`.",
    )


# ============================================================
# CALLBACKS
# ============================================================

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    user = query.from_user

    if data == "open":
        await query.edit_message_text(
            "🎫 **CENTRAL DE TICKETS**\n\nEscolha a categoria:",
            parse_mode="Markdown",
            reply_markup=category_keyboard(),
        )
        return

    if data == "back":
        await query.edit_message_text(
            "🎫 **CENTRAL DE ATENDIMENTO**",
            reply_markup=main_keyboard(),
        )
        return

    if data == "mine":
        ticket = get_open_ticket(user.id)
        if not ticket:
            await query.edit_message_text(
                "📭 Você não possui um ticket aberto.",
                reply_markup=main_keyboard(),
            )
            return

        await query.edit_message_text(
            ticket_info(ticket),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔒 Fechar", callback_data=f"userclose:{ticket[0]}")],
                [InlineKeyboardButton("⬅️ Voltar", callback_data="back")],
            ]),
        )
        return

    if data.startswith("cat:"):
        category_key = data.split(":", 1)[1]
        category = CATEGORIES.get(category_key)
        if not category:
            return

        existing = get_open_ticket(user.id)
        if existing:
            await query.edit_message_text(
                f"⚠️ Você já possui o Ticket #{existing[0]:04d} aberto.",
                reply_markup=main_keyboard(),
            )
            return

        if not SUPPORT_CHAT_ID:
            await query.edit_message_text(
                "❌ SUPPORT_CHAT_ID não está configurado no Render."
            )
            return

        ticket_id = create_ticket(user, category)

        try:
            topic = await context.bot.create_forum_topic(
                chat_id=SUPPORT_CHAT_ID,
                name=f"🎫 #{ticket_id:04d} - {display_user(user)}",
            )
            topic_id = topic.message_thread_id
            update_ticket(ticket_id, "topic_id", topic_id)

            await context.bot.send_message(
                chat_id=SUPPORT_CHAT_ID,
                message_thread_id=topic_id,
                text=(
                    f"🎫 **NOVO TICKET #{ticket_id:04d}**\n\n"
                    f"👤 Usuário: {display_user(user)}\n"
                    f"🆔 ID: `{user.id}`\n"
                    f"📂 Categoria: {category}\n"
                    f"🚨 Prioridade: {PRIORITIES['normal']}\n\n"
                    "Use /assumir, /adicionar, /remover, "
                    "/prioridade ou /fechar."
                ),
                parse_mode="Markdown",
                reply_markup=staff_ticket_keyboard(ticket_id),
            )

            await query.edit_message_text(
                f"✅ **Ticket #{ticket_id:04d} criado!**\n\n"
                "Envie sua mensagem aqui. Nossa equipe receberá o atendimento.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📌 Meu Ticket", callback_data="mine")],
                    [InlineKeyboardButton("🔒 Fechar", callback_data=f"userclose:{ticket_id}")],
                ]),
            )

            save_message(
                ticket_id,
                user.id,
                "system",
                "ticket_created",
                f"Categoria: {category}",
            )

            await send_log(
                context,
                f"🎫 Ticket #{ticket_id:04d} aberto por `{user.id}` — {category}.",
            )

        except Exception as exc:
            logger.exception("Falha ao criar tópico.")
            close_ticket_db(ticket_id, user.id)
            await query.edit_message_text(
                "❌ Não consegui criar o ticket.\n\n"
                "Verifique se o SUPPORT_CHAT_ID é um supergrupo "
                "com modo Fórum ativado e se o bot é administrador."
            )
            await send_log(context, f"❌ Erro ao criar ticket: `{exc}`")

        return

    if data.startswith("claim:"):
        ticket_id = int(data.split(":", 1)[1])
        if not has_staff_permission(user.id, "support"):
            await query.answer("Sem permissão.", show_alert=True)
            return

        ticket = get_ticket(ticket_id)
        if not ticket or ticket[5] != "open":
            await query.answer("Ticket fechado.", show_alert=True)
            return

        update_ticket(ticket_id, "assigned_to", user.id)
        add_ticket_staff_db(ticket_id, user.id)

        await query.answer("Ticket assumido!")
        await query.edit_message_reply_markup(
            reply_markup=staff_ticket_keyboard(ticket_id)
        )

        await context.bot.send_message(
            chat_id=SUPPORT_CHAT_ID,
            message_thread_id=ticket[8],
            text=f"🎯 Ticket assumido por {display_user(user)}.",
        )
        try:
            await context.bot.send_message(
                chat_id=ticket[1],
                text=f"🎯 Seu ticket foi assumido por {display_user(user)}.",
            )
        except Exception:
            pass
        return

    if data.startswith("close:"):
        ticket_id = int(data.split(":", 1)[1])
        if not has_staff_permission(user.id, "support"):
            await query.answer("Sem permissão.", show_alert=True)
            return

        ticket = get_ticket(ticket_id)
        if not ticket:
            return

        await query.answer("Fechando...")
        await close_ticket_flow(context, ticket, user.id, SUPPORT_CHAT_ID)
        return

    if data.startswith("userclose:"):
        ticket_id = int(data.split(":", 1)[1])
        ticket = get_ticket(ticket_id)

        if not ticket or ticket[1] != user.id:
            await query.answer("Ticket inválido.", show_alert=True)
            return

        await query.answer("Fechando...")
        await close_ticket_flow(context, ticket, user.id, user.id)
        await query.edit_message_text(
            f"🔒 Ticket #{ticket_id:04d} fechado.",
            reply_markup=main_keyboard(),
        )
        return

    if data.startswith("priority:"):
        ticket_id = int(data.split(":", 1)[1])
        if not has_staff_permission(user.id, "support"):
            await query.answer("Sem permissão.", show_alert=True)
            return

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🟢 Baixa", callback_data=f"setprio:{ticket_id}:low"),
                InlineKeyboardButton("🟡 Normal", callback_data=f"setprio:{ticket_id}:normal"),
            ],
            [
                InlineKeyboardButton("🟠 Alta", callback_data=f"setprio:{ticket_id}:high"),
                InlineKeyboardButton("🔴 Urgente", callback_data=f"setprio:{ticket_id}:urgent"),
            ],
        ])
        await query.message.reply_text(
            "🚨 Escolha a prioridade:",
            reply_markup=keyboard,
        )
        return

    if data.startswith("setprio:"):
        _, ticket_id, priority_value = data.split(":")
        ticket_id = int(ticket_id)

        if not has_staff_permission(user.id, "support"):
            await query.answer("Sem permissão.", show_alert=True)
            return

        if priority_value not in PRIORITIES:
            return

        ticket = get_ticket(ticket_id)
        if not ticket:
            return

        update_ticket(ticket_id, "priority", priority_value)

        await query.answer("Prioridade alterada!")
        await context.bot.send_message(
            chat_id=SUPPORT_CHAT_ID,
            message_thread_id=ticket[8],
            text=f"🚨 Prioridade: {PRIORITIES[priority_value]}",
        )
        try:
            await context.bot.send_message(
                chat_id=ticket[1],
                text=f"🚨 A prioridade do seu ticket foi alterada para {PRIORITIES[priority_value]}.",
            )
        except Exception:
            pass
        return


# ============================================================
# MESSAGE RELAY
# ============================================================

async def private_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user

    if not message or not user:
        return

    if message.chat.type != ChatType.PRIVATE:
        return

    ticket = get_open_ticket(user.id)
    if not ticket:
        await message.reply_text(
            "📭 Você não possui um ticket aberto.\n\n"
            "Use /ticket para abrir um."
        )
        return

    topic_id = ticket[8]
    if not topic_id:
        await message.reply_text("❌ O ticket está sem tópico de suporte.")
        return

    try:
        await context.bot.copy_message(
            chat_id=SUPPORT_CHAT_ID,
            from_chat_id=message.chat_id,
            message_id=message.message_id,
            message_thread_id=topic_id,
        )
        save_message(
            ticket[0],
            user.id,
            "user",
            message_type(message),
            message_content(message),
        )
    except Exception:
        logger.exception("Falha ao encaminhar mensagem do usuário.")
        await message.reply_text("❌ Não consegui encaminhar sua mensagem.")


async def support_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user

    if not message or not user:
        return

    if message.chat_id != SUPPORT_CHAT_ID:
        return

    topic_id = topic_id_from_message(message)
    if not topic_id:
        return

    ticket = get_ticket_by_topic(topic_id)
    if not ticket:
        return

    # Ignora mensagens do próprio bot.
    if user.is_bot:
        return

    # Comandos são tratados pelos CommandHandler.
    if message.text and message.text.startswith("/"):
        return

    if not has_ticket_access(ticket[0], user.id):
        await message.reply_text("❌ Você não tem acesso a este ticket.")
        return

    try:
        await context.bot.copy_message(
            chat_id=ticket[1],
            from_chat_id=message.chat_id,
            message_id=message.message_id,
        )

        save_message(
            ticket[0],
            user.id,
            "staff",
            message_type(message),
            message_content(message),
        )
    except Exception:
        logger.exception("Falha ao encaminhar resposta da equipe.")


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(update, context):
    logger.exception("Erro no bot: %s", context.error)


# ============================================================
# MAIN
# ============================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN não configurado.")

    if not SUPPORT_CHAT_ID:
        raise RuntimeError("SUPPORT_CHAT_ID não configurado.")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ticket", ticket_command))

    app.add_handler(CommandHandler("painel", painel))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("assumir", assumir))
    app.add_handler(CommandHandler("fechar", fechar))
    app.add_handler(CommandHandler("prioridade", prioridade))
    app.add_handler(CommandHandler("adicionar", adicionar))
    app.add_handler(CommandHandler("remover", remover))
    app.add_handler(CommandHandler("equipe_add", equipe_add))
    app.add_handler(CommandHandler("equipe_remove", equipe_remove))
    app.add_handler(CommandHandler("equipe", equipe))

    app.add_handler(CallbackQueryHandler(callbacks))

    # Mensagens privadas do usuário.
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND,
            private_messages,
        )
    )

    # Mensagens dentro do grupo de suporte/fórum.
    app.add_handler(
        MessageHandler(
            filters.Chat(SUPPORT_CHAT_ID) & ~filters.COMMAND,
            support_messages,
        )
    )

    app.add_error_handler(error_handler)

    logger.info("Ticket bot iniciado.")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
