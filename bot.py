# ============================================================
# TICKET BOT — TELEGRAM
# Versão avançada estilo Ticket King
#
# Recursos:
# 🎫 Tickets privados
# 🛒 Categorias
# 🔢 Numeração automática
# 👨‍💻 Equipe de suporte
# 👑 Sistema de cargos
# 🎯 Assumir ticket
# ➕ Adicionar agente
# ➖ Remover agente
# 🚨 Prioridades
# 📊 Painel
# 📈 Estatísticas
# 📝 Logs
# 📜 Transcrição automática
# 💾 SQLite
#
# Requer:
# python-telegram-bot >= 22
# ============================================================

import os
import io
import sqlite3
import logging
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
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
# CONFIGURAÇÃO
# ============================================================

BOT_TOKEN = os.getenv(
    "BOT_TOKEN",
    "COLOQUE_SEU_TOKEN_AQUI"
)

# Grupo privado da equipe.
# Deve ser um SUPERGRUPO com TÓPICOS/FÓRUM ativados.
SUPPORT_CHAT_ID = int(
    os.getenv("SUPPORT_CHAT_ID", "0")
)

# Grupo/canal onde serão enviados os logs.
LOG_CHAT_ID = int(
    os.getenv("LOG_CHAT_ID", "0")
)

# IDs dos administradores principais.
#
# Exemplo:
# OWNER_IDS=123456789,987654321
OWNER_IDS = {
    int(x.strip())
    for x in os.getenv("OWNER_IDS", "").split(",")
    if x.strip().isdigit()
}

DATABASE = "tickets.db"


# ============================================================
# LOG
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    )
)

logger = logging.getLogger("ticket_bot")


# ============================================================
# BANCO
# ============================================================

def get_db():
    return sqlite3.connect(
        DATABASE,
        check_same_thread=False
    )


def init_db():

    conn = get_db()
    cur = conn.cursor()

    # --------------------------------------------------------
    # TICKETS
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # EQUIPE
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            user_id INTEGER PRIMARY KEY,

            username TEXT,

            full_name TEXT,

            role TEXT NOT NULL DEFAULT 'support',

            added_at TEXT NOT NULL
        )
    """)

    # --------------------------------------------------------
    # AGENTES POR TICKET
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ticket_staff (
            ticket_id INTEGER NOT NULL,

            user_id INTEGER NOT NULL,

            added_at TEXT NOT NULL,

            PRIMARY KEY(ticket_id, user_id)
        )
    """)

    # --------------------------------------------------------
    # MENSAGENS
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # CONFIGURAÇÕES
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,

            value TEXT
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# UTILITÁRIOS
# ============================================================

def now():
    return datetime.now().strftime(
        "%d/%m/%Y %H:%M:%S"
    )


def safe_username(user):

    if user.username:
        return f"@{user.username}"

    return user.full_name or str(user.id)


def is_owner(user_id):
    return user_id in OWNER_IDS


# ============================================================
# EQUIPE / CARGOS
# ============================================================

ROLES = {
    "admin": {
        "name": "👑 Administrador",
        "level": 4,
    },

    "supervisor": {
        "name": "🛡️ Supervisor",
        "level": 3,
    },

    "support": {
        "name": "👨‍💻 Suporte",
        "level": 2,
    },

    "trainee": {
        "name": "🎓 Treinando",
        "level": 1,
    },
}


def get_staff(user_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT user_id, username, full_name, role
        FROM staff
        WHERE user_id = ?
    """, (user_id,))

    result = cur.fetchone()

    conn.close()

    return result


def add_staff(
    user_id,
    username,
    full_name,
    role="support"
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR REPLACE INTO staff
        (
            user_id,
            username,
            full_name,
            role,
            added_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        user_id,
        username,
        full_name,
        role,
        now()
    ))

    conn.commit()
    conn.close()


def remove_staff(user_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM staff WHERE user_id = ?",
        (user_id,)
    )

    conn.commit()
    conn.close()


def staff_role(user_id):

    if is_owner(user_id):
        return "admin"

    staff = get_staff(user_id)

    if not staff:
        return None

    return staff[3]


def has_staff_permission(
    user_id,
    minimum_role="support"
):

    role = staff_role(user_id)

    if not role:
        return False

    if role not in ROLES:
        return False

    if minimum_role not in ROLES:
        return False

    return (
        ROLES[role]["level"]
        >= ROLES[minimum_role]["level"]
    )


# ============================================================
# TICKETS
# ============================================================

def create_ticket(
    user_id,
    username,
    full_name,
    category
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO tickets
        (
            user_id,
            username,
            full_name,
            category,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        user_id,
        username,
        full_name,
        category,
        now()
    ))

    ticket_id = cur.lastrowid

    conn.commit()
    conn.close()

    return ticket_id


def get_ticket(ticket_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM tickets
        WHERE id = ?
        LIMIT 1
    """, (ticket_id,))

    result = cur.fetchone()

    conn.close()

    return result


def get_open_ticket(user_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM tickets
        WHERE user_id = ?
        AND status = 'open'
        ORDER BY id DESC
        LIMIT 1
    """, (user_id,))

    result = cur.fetchone()

    conn.close()

    return result


def get_ticket_by_topic(topic_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM tickets
        WHERE topic_id = ?
        AND status = 'open'
        LIMIT 1
    """, (topic_id,))

    result = cur.fetchone()

    conn.close()

    return result


def set_topic(
    ticket_id,
    topic_id
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE tickets
        SET topic_id = ?
        WHERE id = ?
    """, (
        topic_id,
        ticket_id
    ))

    conn.commit()
    conn.close()


def assign_ticket(
    ticket_id,
    user_id
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE tickets
        SET assigned_to = ?
        WHERE id = ?
    """, (
        user_id,
        ticket_id
    ))

    conn.commit()
    conn.close()


def set_priority(
    ticket_id,
    priority
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE tickets
        SET priority = ?
        WHERE id = ?
    """, (
        priority,
        ticket_id
    ))

    conn.commit()
    conn.close()


def close_ticket(
    ticket_id,
    closed_by
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE tickets
        SET
            status = 'closed',
            closed_at = ?,
            closed_by = ?
        WHERE id = ?
    """, (
        now(),
        closed_by,
        ticket_id
    ))

    conn.commit()
    conn.close()


# ============================================================
# AGENTES DO TICKET
# ============================================================

def add_ticket_staff(
    ticket_id,
    user_id
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR IGNORE INTO ticket_staff
        (
            ticket_id,
            user_id,
            added_at
        )
        VALUES (?, ?, ?)
    """, (
        ticket_id,
        user_id,
        now()
    ))

    conn.commit()
    conn.close()


def remove_ticket_staff(
    ticket_id,
    user_id
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM ticket_staff
        WHERE ticket_id = ?
        AND user_id = ?
    """, (
        ticket_id,
        user_id
    ))

    conn.commit()
    conn.close()


def has_ticket_access(
    ticket_id,
    user_id
):

    if has_staff_permission(
        user_id,
        "support"
    ):
        return True

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT 1
        FROM ticket_staff
        WHERE ticket_id = ?
        AND user_id = ?
    """, (
        ticket_id,
        user_id
    ))

    result = cur.fetchone()

    conn.close()

    return result is not None


# ============================================================
# MENSAGENS
# ============================================================

def save_message(
    ticket_id,
    sender_id,
    sender_type,
    message_type,
    content
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO messages
        (
            ticket_id,
            sender_id,
            sender_type,
            message_type,
            content,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        ticket_id,
        sender_id,
        sender_type,
        message_type,
        content,
        now()
    ))

    conn.commit()
    conn.close()


def get_messages(ticket_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            sender_id,
            sender_type,
            message_type,
            content,
            created_at
        FROM messages
        WHERE ticket_id = ?
        ORDER BY id ASC
    """, (ticket_id,))

    results = cur.fetchall()

    conn.close()

    return results


# ============================================================
# TRANSCRIÇÃO
# ============================================================

def generate_transcript(ticket):

    ticket_id = ticket[0]
    user_id = ticket[1]
    username = ticket[2]
    full_name = ticket[3]
    category = ticket[4]
    status = ticket[5]
    priority = ticket[6]
    assigned_to = ticket[7]
    created_at = ticket[9]
    closed_at = ticket[10]

    messages = get_messages(ticket_id)

    lines = []

    lines.append(
        "========================================"
    )

    lines.append(
        f"TICKET #{ticket_id:04d}"
    )

    lines.append(
        "========================================"
    )

    lines.append(
        f"Usuário: {username or full_name}"
    )

    lines.append(
        f"ID: {user_id}"
    )

    lines.append(
        f"Categoria: {category}"
    )

    lines.append(
        f"Prioridade: {priority}"
    )

    lines.append(
        f"Status: {status}"
    )

    lines.append(
        f"Criado: {created_at}"
    )

    lines.append(
        f"Fechado: {closed_at or '-'}"
    )

    lines.append("")

    lines.append(
        "-------------- MENSAGENS --------------"
    )

    lines.append("")

    for message in messages:

        sender_id = message[0]
        sender_type = message[1]
        message_type = message[2]
        content = message[3]
        created = message[4]

        lines.append(
            f"[{created}] "
            f"{sender_type.upper()} "
            f"({sender_id}) "
            f"[{message_type}]"
        )

        lines.append(
            content or "[sem texto]"
        )

        lines.append("")

    lines.append(
        "========================================"
    )

    return "\n".join(lines)


async def send_transcript(
    context,
    ticket
):

    transcript = generate_transcript(ticket)

    if LOG_CHAT_ID == 0:
        return

    ticket_id = ticket[0]

    file = io.BytesIO(
        transcript.encode("utf-8")
    )

    file.name = (
        f"ticket-{ticket_id:04d}.txt"
    )

    try:

        await context.bot.send_document(
            chat_id=LOG_CHAT_ID,
            document=file,
            caption=(
                f"📜 **Transcrição do Ticket "
                f"#{ticket_id:04d}**\n\n"
                f"📂 {ticket[4]}\n"
                f"🚨 {ticket[6]}"
            ),
            parse_mode="Markdown"
        )

    except Exception:

        logger.exception(
            "Erro enviando transcrição."
        )


# ============================================================
# LOG
# ============================================================

async def send_log(
    context,
    text
):

    if LOG_CHAT_ID == 0:
        return

    try:

        await context.bot.send_message(
            chat_id=LOG_CHAT_ID,
            text=text,
            parse_mode="Markdown"
        )

    except Exception:

        logger.exception(
            "Erro enviando log."
        )


# ============================================================
# PAINEL PRINCIPAL
# ============================================================

def main_panel():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎫 Abrir Ticket",
                callback_data="open_ticket"
            )
        ],
        [
            InlineKeyboardButton(
                "📌 Meu Ticket",
                callback_data="my_ticket"
            )
        ]
    ])


def category_panel():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🛒 Compras",
                callback_data="cat_compras"
            )
        ],
        [
            InlineKeyboardButton(
                "🛠️ Suporte",
                callback_data="cat_suporte"
            )
        ],
        [
            InlineKeyboardButton(
                "💰 Financeiro",
                callback_data="cat_financeiro"
            )
        ],
        [
            InlineKeyboardButton(
                "📦 Outros",
                callback_data="cat_outros"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Voltar",
                callback_data="back_main"
            )
        ]
    ])


def ticket_controls(ticket_id):

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🚨 Prioridade",
                callback_data=f"priority_{ticket_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🎯 Assumir",
                callback_data=f"claim_{ticket_id}"
            ),
            InlineKeyboardButton(
                "🔒 Fechar",
                callback_data=f"close_{ticket_id}"
            )
        ]
    ])


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_chat.type != ChatType.PRIVATE:
        return

    user = update.effective_user

    await update.message.reply_text(
        f"👋 Olá, {user.first_name}!\n\n"
        "🎫 **CENTRAL DE ATENDIMENTO**\n\n"
        "Escolha uma opção abaixo.",
        parse_mode="Markdown",
        reply_markup=main_panel()
    )


# ============================================================
# /TICKET
# ============================================================

async def ticket_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_chat.type != ChatType.PRIVATE:
        return

    await update.message.reply_text(
        "🎫 **CENTRAL DE TICKETS**\n\n"
        "Escolha a categoria do atendimento:",
        parse_mode="Markdown",
        reply_markup=category_panel()
    )


# ============================================================
# ABRIR PAINEL
# ============================================================

async def open_ticket_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    await query.edit_message_text(
        "🎫 **CENTRAL DE TICKETS**\n\n"
        "Escolha a categoria:",
        parse_mode="Markdown",
        reply_markup=category_panel()
    )


# ============================================================
# CRIAÇÃO DO TICKET
# ============================================================

async def category_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user = query.from_user

    existing = get_open_ticket(user.id)

    if existing:

        await query.edit_message_text(
            f"⚠️ Você já possui um ticket aberto.\n\n"
            f"🎫 **#{existing[0]:04d}**",
            parse_mode="Markdown",
            reply_markup=ticket_controls(
                existing[0]
            )
        )

        return

    categories = {
        "cat_compras": "🛒 Compras",
        "cat_suporte": "🛠️ Suporte",
        "cat_financeiro": "💰 Financeiro",
        "cat_outros": "📦 Outros"
    }

    category = categories.get(
        query.data
    )

    if not category:
        return

    if SUPPORT_CHAT_ID == 0:

        await query.edit_message_text(
            "❌ SUPPORT_CHAT_ID não configurado."
        )

        return

    # --------------------------------------------------------
    # BANCO
    # --------------------------------------------------------

    ticket_id = create_ticket(
        user.id,
        safe_username(user),
        user.full_name,
        category
    )

    # --------------------------------------------------------
    # TÓPICO
    # --------------------------------------------------------

    try:

        topic = await context.bot.create_forum_topic(
            chat_id=SUPPORT_CHAT_ID,
            name=(
                f"🎫 #{ticket_id:04d} "
                f"- {safe_username(user)}"
            )
        )

        topic_id = topic.message_thread_id

     
