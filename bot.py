# ============================================================
# TICKET BOT TELEGRAM
# Estilo Ticket King
#
# Python 3.10+
# python-telegram-bot >= 22.0
#
# Variáveis de ambiente:
#
# BOT_TOKEN=TOKEN_DO_BOT
# SUPPORT_CHAT_ID=-1001234567890
# LOG_CHAT_ID=-1001234567890
# OWNER_IDS=123456789,987654321
#
# O SUPPORT_CHAT_ID precisa ser um SUPERGRUPO com:
# - Tópicos/Fórum ativados
# - O bot como administrador
# - Permissão para gerenciar tópicos
# ============================================================

import os
import io
import html
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

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

SUPPORT_CHAT_ID = int(
    os.getenv("SUPPORT_CHAT_ID", "0")
)

LOG_CHAT_ID = int(
    os.getenv("LOG_CHAT_ID", "0")
)

OWNER_IDS = {
    int(x.strip())
    for x in os.getenv("OWNER_IDS", "").split(",")
    if x.strip().isdigit()
}

DATABASE = os.getenv(
    "DATABASE",
    "tickets.db"
)


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
# CATEGORIAS
# ============================================================

CATEGORIES = {
    "compras": "🛒 Compras",
    "suporte": "🛠️ Suporte",
    "financeiro": "💰 Financeiro",
    "outros": "📦 Outros",
}


# ============================================================
# PRIORIDADES
# ============================================================

PRIORITIES = {
    "baixa": "🟢 Baixa",
    "normal": "🟡 Normal",
    "alta": "🟠 Alta",
    "urgente": "🔴 Urgente",
}


# ============================================================
# CARGOS
# ============================================================

ROLES = {
    "trainee": {
        "name": "🎓 Treinando",
        "level": 1,
    },
    "support": {
        "name": "👨‍💻 Suporte",
        "level": 2,
    },
    "supervisor": {
        "name": "🛡️ Supervisor",
        "level": 3,
    },
    "admin": {
        "name": "👑 Administrador",
        "level": 4,
    },
}


# ============================================================
# BANCO
# ============================================================

def get_db():
    conn = sqlite3.connect(
        DATABASE,
        timeout=30,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row

    return conn


def init_db():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER NOT NULL,
            username TEXT,
            full_name TEXT,

            category TEXT NOT NULL,

            status TEXT NOT NULL
                DEFAULT 'open',

            priority TEXT NOT NULL
                DEFAULT 'normal',

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

            role TEXT NOT NULL
                DEFAULT 'support',

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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            ticket_id INTEGER,

            actor_id INTEGER,

            action TEXT NOT NULL,

            details TEXT,

            created_at TEXT NOT NULL
        )
    """)

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


def esc(value):
    if value is None:
        return ""

    return html.escape(str(value))


def user_label(user):

    if user.username:
        return f"@{user.username}"

    return user.full_name or str(user.id)


def row_to_tuple(row):

    if row is None:
        return None

    return tuple(row)


# ============================================================
# PERMISSÕES
# ============================================================

def is_owner(user_id):

    return user_id in OWNER_IDS


def get_staff(user_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM staff
        WHERE user_id = ?
    """, (user_id,))

    row = cur.fetchone()

    conn.close()

    return row


def get_staff_role(user_id):

    if is_owner(user_id):
        return "admin"

    staff = get_staff(user_id)

    if not staff:
        return None

    return staff["role"]


def has_permission(
    user_id,
    minimum_role="support"
):

    role = get_staff_role(user_id)

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
# EQUIPE
# ============================================================

def add_staff_db(
    user_id,
    username,
    full_name,
    role="support"
):

    if role not in ROLES:
        role = "support"

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


def remove_staff_db(user_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM staff
        WHERE user_id = ?
    """, (user_id,))

    conn.commit()
    conn.close()


def update_staff_role(
    user_id,
    role
):

    if role not in ROLES:
        return False

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE staff
        SET role = ?
        WHERE user_id = ?
    """, (
        role,
        user_id
    ))

    changed = cur.rowcount > 0

    conn.commit()
    conn.close()

    return changed


def list_staff():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM staff
        ORDER BY role DESC, added_at ASC
    """)

    rows = cur.fetchall()

    conn.close()

    return rows


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
            status,
            priority,
            created_at
        )
        VALUES (?, ?, ?, ?, 'open', 'normal', ?)
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

    row = cur.fetchone()

    conn.close()

    return row


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

    row = cur.fetchone()

    conn.close()

    return row


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

    row = cur.fetchone()

    conn.close()

    return row


def get_all_open_tickets():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM tickets
        WHERE status = 'open'
        ORDER BY
            CASE priority
                WHEN 'urgente' THEN 1
                WHEN 'alta' THEN 2
                WHEN 'normal' THEN 3
                WHEN 'baixa' THEN 4
                ELSE 5
            END,
            id ASC
    """)

    rows = cur.fetchall()

    conn.close()

    return rows


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

    if priority not in PRIORITIES:
        return False

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

    return True


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
        AND status = 'open'
    """, (
        now(),
        closed_by,
        ticket_id
    ))

    changed = cur.rowcount > 0

    conn.commit()
    conn.close()

    return changed


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

    changed = cur.rowcount > 0

    conn.commit()
    conn.close()

    return changed


def has_ticket_access(
    ticket_id,
    user_id
):

    if has_permission(
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
        LIMIT 1
    """, (
        ticket_id,
        user_id
    ))

    result = cur.fetchone()

    conn.close()

    return result is not None


def get_ticket_staff(ticket_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            ts.user_id,
            s.username,
            s.full_name,
            s.role
        FROM ticket_staff ts
        LEFT JOIN staff s
            ON s.user_id = ts.user_id
        WHERE ts.ticket_id = ?
        ORDER BY ts.added_at ASC
    """, (ticket_id,))

    rows = cur.fetchall()

    conn.close()

    return rows


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
        SELECT *
        FROM messages
        WHERE ticket_id = ?
        ORDER BY id ASC
    """, (ticket_id,))

    rows = cur.fetchall()

    conn.close()

    return rows


# ============================================================
# LOGS
# ============================================================

def save_log(
    ticket_id,
    actor_id,
    action,
    details=""
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO logs
        (
            ticket_id,
            actor_id,
            action,
            details,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        ticket_id,
        actor_id,
        action,
        details,
        now()
    ))

    conn.commit()
    conn.close()


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
            parse_mode="HTML"
        )

    except Exception:

        logger.exception(
            "Erro enviando log."
        )


# ============================================================
# TRANSCRIÇÃO
# ============================================================

def generate_transcript(ticket):

    messages = get_messages(
        ticket["id"]
    )

    lines = []

    lines.append(
        "=========================================="
    )

    lines.append(
        f"TICKET #{ticket['id']:04d}"
    )

    lines.append(
        "=========================================="
    )

    lines.append(
        f"Usuário: {ticket['username'] or ticket['full_name']}"
    )

    lines.append(
        f"ID: {ticket['user_id']}"
    )

    lines.append(
        f"Categoria: {ticket['category']}"
    )

    lines.append(
        f"Prioridade: {ticket['priority']}"
    )

    lines.append(
        f"Status: {ticket['status']}"
    )

    lines.append(
        f"Criado: {ticket['created_at']}"
    )

    lines.append(
        f"Fechado: {ticket['closed_at'] or '-'}"
    )

    lines.append(
        f"Responsável: {ticket['assigned_to'] or '-'}"
    )

    lines.append("")

    lines.append(
        "================ MENSAGENS ================"
    )

    lines.append("")

    for message in messages:

        sender_type = message["sender_type"]
        sender_id = message["sender_id"]
        message_type = message["message_type"]
        content = message["content"] or ""

        lines.append(
            f"[{message['created_at']}] "
            f"{sender_type.upper()} "
            f"ID:{sender_id} "
            f"TYPE:{message_type}"
        )

        lines.append(content)

        lines.append("")

    lines.append(
        "=========================================="
    )

    return "\n".join(lines)


async def send_transcript(
    context,
    ticket
):

    if LOG_CHAT_ID == 0:
        return

    transcript = generate_transcript(
        ticket
    )

    file = io.BytesIO(
        transcript.encode("utf-8")
    )

    file.name = (
        f"ticket-{ticket['id']:04d}.txt"
    )

    try:

        await context.bot.send_document(
            chat_id=LOG_CHAT_ID,
            document=file,
            caption=(
                f"📜 <b>Transcrição</b>\n\n"
                f"🎫 Ticket: "
                f"<code>#{ticket['id']:04d}</code>\n"
                f"👤 Usuário: "
                f"<code>{ticket['user_id']}</code>\n"
                f"📂 Categoria: "
                f"{esc(ticket['category'])}\n"
                f"🚨 Prioridade: "
                f"{esc(ticket['priority'])}"
            ),
            parse_mode="HTML"
        )

    except Exception:

        logger.exception(
            "Erro enviando transcrição."
        )


# ============================================================
# PAINÉIS
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


def ticket_user_panel(
    ticket_id
):

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔒 Fechar Ticket",
                callback_data=f"user_close_{ticket_id}"
            )
        ]
    ])


def staff_ticket_panel(
    ticket_id
):

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎯 Assumir",
                callback_data=f"claim_{ticket_id}"
            ),
            InlineKeyboardButton(
                "🔒 Fechar",
                callback_data=f"close_{ticket_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🚨 Prioridade",
                callback_data=f"priority_{ticket_id}"
            )
        ]
    ])


def priority_panel(
    ticket_id
):

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🟢 Baixa",
                callback_data=f"setprio_{ticket_id}_baixa"
            )
        ],
        [
            InlineKeyboard
