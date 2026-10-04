#!/usr/bin/env python3
"""
╔════════════════════════════════════════════════════════════════╗
║     🛡️ TELEGRAM REPORT BOT PRO MAX 🛡️                      ║
║     👨‍💻 Developed by: Bobby Maharaj                          ║
║     🔥 Version: 3.0.0 Premium                                 ║
╚════════════════════════════════════════════════════════════════╝
"""

import os
import logging
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
import threading
from flask import Flask, jsonify

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, CallbackQueryHandler, 
    MessageHandler, Filters, ConversationHandler, CallbackContext
)

# ═════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═════════════════════════════════════════════════════════════════

BOT_TOKEN = os.getenv('BOT_TOKEN', '').strip()

def _parse_admin_ids(value):
    ids = []
    for raw in value.split(','):
        raw = raw.strip()
        if raw:
            try:
                ids.append(int(raw))
            except ValueError:
                logging.warning('Ignoring invalid ADMIN_IDS value: %r', raw)
    return ids

ADMIN_IDS = _parse_admin_ids(os.getenv('ADMIN_IDS', ''))
try:
    SUPER_ADMIN = int(os.getenv('SUPER_ADMIN', '0'))
except ValueError:
    SUPER_ADMIN = 0

BOT_NAME = "Report Bot Pro"
VERSION = "3.0.0 Premium"
DEVELOPER = "Bobby Maharaj"
DEV_USERNAME = "@bobbymaharaj"
DEV_CHANNEL = "https://t.me/bobbymaharaj"

REPORT_COOLDOWN = 30
MAX_DAILY_REPORTS = 80
MAX_REPORTS_PER_CHANNEL = 50
DB_PATH = os.getenv('DB_PATH', 'bot_data.db')
PORT = int(os.getenv('PORT', '10000'))
THEME = "🟣"
DIVIDER = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

EMOJI = {
    'bot': '🤖', 'user': '👤', 'admin': '👑', 'report': '📝',
    'success': '✅', 'error': '❌', 'warning': '⚠️', 'info': 'ℹ️',
    'stats': '📊', 'time': '⏰', 'channel': '📢', 'ban': '🚫',
    'unban': '🔓', 'star': '⭐', 'fire': '🔥', 'rocket': '🚀',
    'shield': '🛡️', 'check': '✓', 'cross': '✗'
}

BANNER = f"""
╔══════════════════════════════════════════════════════════════╗
║           {THEME} REPORT BOT PRO MAX {THEME}                 ║
║              ✨ Ultimate Reporting System ✨                  ║
║           👨‍💻 By: {DEVELOPER}                      ║
║           🔥 Version: {VERSION}                         ║
╚══════════════════════════════════════════════════════════════╝"""

SELECTING_CHANNEL, SELECTING_REASON, SELECTING_PRIORITY, ADDING_DESCRIPTION, CONFIRMING = range(5)

# Lightweight HTTP endpoint required by Render Web Services.
app = Flask(__name__)

@app.get('/')
def root_health():
    return jsonify({'status': 'ok', 'service': BOT_NAME, 'version': VERSION})

@app.get('/health')
def health():
    return jsonify({'status': 'healthy'})

def start_health_server():
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)


# ═════════════════════════════════════════════════════════════════
# DATABASE FUNCTIONS
# ═════════════════════════════════════════════════════════════════

def init_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT,
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_banned INTEGER DEFAULT 0,
            ban_reason TEXT, reports_count INTEGER DEFAULT 0, last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_id INTEGER, target_channel TEXT,
            reason TEXT, description TEXT, priority INTEGER DEFAULT 1, status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, processed_at TIMESTAMP,
            processed_by INTEGER, admin_notes TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, report_count INTEGER DEFAULT 0,
            first_reported TIMESTAMP DEFAULT CURRENT_TIMESTAMP, last_reported TIMESTAMP, is_verified_bad INTEGER DEFAULT 0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rate_limits (
            user_id INTEGER, command TEXT, last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, command)
        )
    ''')
    
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def register_user(user_id, username, first_name, last_name):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (id, username, first_name, last_name, last_activity)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name,
            last_name = excluded.last_name,
            last_activity = CURRENT_TIMESTAMP
    ''', (user_id, username, first_name, last_name))
    conn.commit()
    conn.close()

def is_user_banned(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT is_banned FROM users WHERE id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result and result['is_banned'] == 1

def ban_user(user_id, reason):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_banned = 1, ban_reason = ? WHERE id = ?', (reason, user_id))
    conn.commit()
    conn.close()

def unban_user(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_banned = 0, ban_reason = NULL WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()

def get_daily_reports_count(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM reports WHERE reporter_id = ? AND DATE(created_at) = DATE("now")', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0

def get_recent_reports_for_channel(channel, user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM reports WHERE target_channel = ? AND reporter_id = ? AND created_at > datetime("now", "-7 days")',
                   (channel, user_id))
    results = cursor.fetchall()
    conn.close()
    return results

def create_report(reporter_id, target_channel, reason, description="", priority=1):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO reports (reporter_id, target_channel, reason, description, priority) VALUES (?, ?, ?, ?, ?)',
                   (reporter_id, target_channel, reason, description, priority))
    report_id = cursor.lastrowid
    cursor.execute('INSERT INTO channels (username, last_reported, report_count) VALUES (?, CURRENT_TIMESTAMP, 1) ON CONFLICT(username) DO UPDATE SET last_reported = CURRENT_TIMESTAMP, report_count = report_count + 1',
                   (target_channel,))
    cursor.execute('UPDATE users SET reports_count = reports_count + 1 WHERE id = ?', (reporter_id,))
    conn.commit()
    conn.close()
    return report_id

def get_user_stats(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    cursor.execute('SELECT COUNT(*) as total, SUM(CASE WHEN status = "completed" THEN 1 ELSE 0 END) as completed, SUM(CASE WHEN status = "pending" THEN 1 ELSE 0 END) as pending, SUM(CASE WHEN status = "rejected" THEN 1 ELSE 0 END) as rejected FROM reports WHERE reporter_id = ?', (user_id,))
    reports = cursor.fetchone()
    conn.close()
    return {'user': dict(user) if user else {}, 'total_reports': reports['total'] or 0, 'completed': reports['completed'] or 0,
            'pending': reports['pending'] or 0, 'rejected': reports['rejected'] or 0}

def get_admin_stats():
    conn = get_db()
    cursor = conn.cursor()
    stats = {}
    cursor.execute('SELECT COUNT(*) FROM users')
    stats['total_users'] = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM users WHERE is_banned = 1')
    stats['banned_users'] = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM reports')
    stats['total_reports'] = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM reports WHERE status = "pending"')
    stats['pending_reports'] = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM reports WHERE status = "completed"')
    stats['completed_reports'] = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM channels')
    stats['total_channels'] = cursor.fetchone()[0]
    conn.close()
    return stats

def get_all_users():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT id, username, first_name FROM users WHERE is_banned = 0')
    results = cursor.fetchall()
    conn.close()
    return [dict(row) for row in results]

def update_report_status(report_id, status, admin_id=None, notes=None):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE reports SET status = ?, processed_at = CURRENT_TIMESTAMP, processed_by = ?, admin_notes = ? WHERE id = ?',
                   (status, admin_id, notes, report_id))
    conn.commit()
    conn.close()

def check_rate_limit(user_id, command, cooldown):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT last_used FROM rate_limits WHERE user_id = ? AND command = ?', (user_id, command))
    result = cursor.fetchone()
    if result:
        last_used = datetime.fromisoformat(result['last_used'])
        elapsed = (datetime.now() - last_used).total_seconds()
        if elapsed < cooldown:
            remaining = int(cooldown - elapsed)
            conn.close()
            return False, remaining
    cursor.execute('INSERT OR REPLACE INTO rate_limits (user_id, command, last_used) VALUES (?, ?, CURRENT_TIMESTAMP)',
                   (user_id, command))
    conn.commit()
    conn.close()
    return True, 0
    # ═════════════════════════════════════════════════════════════════
# KEYBOARDS
# ═════════════════════════════════════════════════════════════════

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{EMOJI['report']} Report Channel", callback_data='start_report'),
         InlineKeyboardButton(f"{EMOJI['stats']} My Stats", callback_data='my_stats')],
        [InlineKeyboardButton(f"{EMOJI['info']} Check Status", callback_data='check_status'),
         InlineKeyboardButton(f"{EMOJI['shield']} Help", callback_data='show_help')],
        [InlineKeyboardButton(f"👨‍💻 {DEVELOPER}", url=f"https://t.me/{DEV_USERNAME[1:]}"),
         InlineKeyboardButton(f"📢 Channel", url=DEV_CHANNEL)]
    ])

def reasons_keyboard():
    reasons = [('🗑️ Spam', 'spam'), ('💰 Scam', 'scam'), ('🔞 Adult', 'adult'), ('🔪 Violence', 'violence'),
               ('⚖️ Illegal', 'illegal'), ('©️ Copyright', 'copyright'), ('🤬 Hate', 'hate'), ('🎣 Phishing', 'phishing'), ('❓ Other', 'other')]
    buttons = [[InlineKeyboardButton(text, callback_data=f'reason_{code}')] for text, code in reasons]
    buttons.append([InlineKeyboardButton(f"{EMOJI['cross']} Cancel", callback_data='cancel_report')])
    return InlineKeyboardMarkup(buttons)

def priority_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Low", callback_data='priority_1'), InlineKeyboardButton("🟡 Medium", callback_data='priority_2')],
        [InlineKeyboardButton("🟠 High", callback_data='priority_3'), InlineKeyboardButton("🔴 Critical", callback_data='priority_4')],
        [InlineKeyboardButton("⬅️ Back", callback_data='back_to_reasons')]
    ])

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Users", callback_data='admin_users'), InlineKeyboardButton("📝 Reports", callback_data='admin_reports')],
        [InlineKeyboardButton("📊 Statistics", callback_data='admin_stats'), InlineKeyboardButton("📢 Broadcast", callback_data='admin_broadcast')]
    ])

# ═════════════════════════════════════════════════════════════════
# USER HANDLERS
# ═════════════════════════════════════════════════════════════════

def start(update: Update, context: CallbackContext):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name, user.last_name)
    
    if is_user_banned(user.id):
        text = f"{EMOJI['ban']} **ACCESS DENIED**\n\nYour account has been banned.\nContact: {DEV_USERNAME}"
        if update.callback_query:
            update.callback_query.edit_message_text(text, parse_mode='Markdown')
        else:
            update.message.reply_text(text, parse_mode='Markdown')
        return
    
    welcome_text = f"""
{BANNER}

{DIVIDER}

👋 **Welcome, {user.first_name}!**

{EMOJI['shield']} **The Ultimate Reporting System**

{EMOJI['info']} **Features:**
• Report malicious channels
• Track report status
• View detailed statistics
• Admin panel (for admins)

{DIVIDER}

{EMOJI['star']} **Get Started:**
Use the buttons below!

{DIVIDER}

{EMOJI['rocket']} **Developed by:** {DEVELOPER}
{EMOJI['fire']} **Version:** {VERSION}
    """
    if update.callback_query:
        update.callback_query.answer()
        update.callback_query.edit_message_text(welcome_text, reply_markup=main_menu_keyboard(), parse_mode='Markdown')
    else:
        update.message.reply_text(welcome_text, reply_markup=main_menu_keyboard(), parse_mode='Markdown')

def help_command(update: Update, context: CallbackContext):
    help_text = f"""
{EMOJI['info']} **COMPLETE HELP GUIDE**

{DIVIDER}

📚 **Commands:**
• `/start` - Start the bot
• `/report` - Report a channel
• `/status` - Check your reports
• `/stats` - Your statistics
• `/help` - Show this help
• `/admin` - Admin panel (admins only)

{DIVIDER}

🎯 **How to Report:**
1️⃣ Click "Report Channel" or use /report
2️⃣ Enter channel username (@channel)
3️⃣ Select reason category
4️⃣ Set priority level
5️⃣ Add description (optional)
6️⃣ Confirm submission

{DIVIDER}

⚠️ **Rules:**
• Max {MAX_DAILY_REPORTS} reports per day
• No duplicate reporting
• Only report actual violations

{DIVIDER}

👨‍💻 **Developer:** {DEVELOPER}
📢 **Channel:** {DEV_CHANNEL}
    """
    if update.callback_query:
        update.callback_query.answer()
        update.callback_query.edit_message_text(help_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 Back to Menu', callback_data='main_menu')]]))
    else:
        update.message.reply_text(help_text, parse_mode='Markdown')

def report_start(update: Update, context: CallbackContext):
    user = update.effective_user
    if is_user_banned(user.id):
        text = f"{EMOJI['ban']} **ACCESS DENIED**\n\nYour account has been banned."
        if update.callback_query:
            update.callback_query.answer()
            update.callback_query.edit_message_text(text, parse_mode='Markdown')
        else:
            update.message.reply_text(text, parse_mode='Markdown')
        return ConversationHandler.END
    daily_count = get_daily_reports_count(user.id)
    
    if daily_count >= MAX_DAILY_REPORTS:
        update.message.reply_text(f"{EMOJI['warning']} **Daily Limit Reached!**\n\nUsed: {daily_count}/{MAX_DAILY_REPORTS}\nPlease try again tomorrow.", parse_mode='Markdown')
        return ConversationHandler.END
    
    report_text = f"""
{EMOJI['report']} **NEW REPORT WIZARD**

{DIVIDER}

**Step 1/4:** Channel Information

Please send me the channel username:
• Format: `@channelusername`
• Or: `channelusername`

{EMOJI['info']} **Daily Reports:** {daily_count}/{MAX_DAILY_REPORTS}

{DIVIDER}

{EMOJI['warning']} **Note:** False reports may result in ban!
    """
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(f"{EMOJI['cross']} Cancel", callback_data='cancel_report')]])
    if update.callback_query:
        update.callback_query.answer()
        update.callback_query.edit_message_text(report_text, reply_markup=keyboard, parse_mode='Markdown')
    else:
        update.message.reply_text(report_text, reply_markup=keyboard, parse_mode='Markdown')
    return SELECTING_CHANNEL

def process_channel(update: Update, context: CallbackContext):
    channel_input = update.message.text.strip()
    channel = channel_input.replace('@', '').replace('https://t.me/', '').split('/')[0]
    
    if len(channel) < 5 or not channel.replace('_', '').isalnum():
        update.message.reply_text(f"{EMOJI['error']} **Invalid Channel**\n\nPlease enter a valid username.", parse_mode='Markdown')
        return SELECTING_CHANNEL
    
    existing = get_recent_reports_for_channel(channel, update.effective_user.id)
    if len(existing) >= MAX_REPORTS_PER_CHANNEL:
        update.message.reply_text(f"{EMOJI['warning']} **Already Reported**\n\nYou've reported this channel {len(existing)} times recently.", parse_mode='Markdown')
        return ConversationHandler.END
    
    context.user_data['report_channel'] = channel
    update.message.reply_text(f"""
{EMOJI['report']} **Step 2/4:** Select Reason

{DIVIDER}

Channel: `@{channel}`

Select a reason:
        """, reply_markup=reasons_keyboard(), parse_mode='Markdown')
    return SELECTING_REASON

def process_reason_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    reason = query.data.replace('reason_', '')
    context.user_data['report_reason'] = reason
    
    query.edit_message_text(f"""
{EMOJI['report']} **Step 3/4:** Set Priority

{DIVIDER}

Channel: `@{context.user_data['report_channel']}`
Reason: {reason.upper()}

Select priority level:
        """, reply_markup=priority_keyboard(), parse_mode='Markdown')
    return SELECTING_PRIORITY

def process_priority_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    priority = int(query.data.replace('priority_', ''))
    context.user_data['report_priority'] = priority
    priority_text = {1: "🟢 Low", 2: "🟡 Medium", 3: "🟠 High", 4: "🔴 Critical"}
    
    query.edit_message_text(f"""
{EMOJI['report']} **Step 4/4:** Add Description (Optional)

{DIVIDER}

📋 **Report Summary:**
• Channel: `@{context.user_data['report_channel']}`
• Reason: {context.user_data['report_reason'].upper()}
• Priority: {priority_text.get(priority)}

Send additional details or click Skip:
        """, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ Skip", callback_data='skip_description'),
             InlineKeyboardButton("❌ Cancel", callback_data='cancel_report')]
        ]), parse_mode='Markdown')
    return ADDING_DESCRIPTION

def process_description(update: Update, context: CallbackContext):
    context.user_data['report_description'] = update.message.text
    return show_confirmation(update, context)

def skip_description(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    context.user_data['report_description'] = ""
    return show_confirmation_callback(update, context)

def show_confirmation(update: Update, context: CallbackContext):
    return show_confirmation_callback(update, context)

def show_confirmation_callback(update: Update, context: CallbackContext):
    priority_text = {1: "🟢 Low", 2: "🟡 Medium", 3: "🟠 High", 4: "🔴 Critical"}
    text = f"""
{EMOJI['report']} **CONFIRM REPORT**

{DIVIDER}

📋 **Report Details:**
• Channel: `@{context.user_data['report_channel']}`
• Reason: {context.user_data['report_reason'].upper()}
• Priority: {priority_text.get(context.user_data['report_priority'])}
• Description: {context.user_data.get('report_description', 'None')}

{DIVIDER}

{EMOJI['warning']} **Confirm submission?**
    """
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{EMOJI['success']} Confirm", callback_data='confirm_report'),
         InlineKeyboardButton(f"{EMOJI['cross']} Cancel", callback_data='cancel_report')]
    ])
    
    if update.callback_query:
        update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
    else:
        update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')
    return CONFIRMING

def confirm_report(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user = update.effective_user
    if is_user_banned(user.id):
        query.edit_message_text(f"{EMOJI['ban']} **ACCESS DENIED**", parse_mode='Markdown')
        context.user_data.clear()
        return ConversationHandler.END
    if get_daily_reports_count(user.id) >= MAX_DAILY_REPORTS:
        query.edit_message_text(f"{EMOJI['warning']} **Daily Limit Reached**", parse_mode='Markdown')
        context.user_data.clear()
        return ConversationHandler.END

    report_id = create_report(
        reporter_id=user.id,
        target_channel=context.user_data['report_channel'],
        reason=context.user_data['report_reason'],
        description=context.user_data.get('report_description', ''),
        priority=context.user_data['report_priority']
    )
    
    success_text = f"""
{EMOJI['success']} **REPORT SUBMITTED!**

{DIVIDER}

🆔 **Report ID:** `{report_id}`
📢 **Channel:** `@{context.user_data['report_channel']}`
📊 **Status:** Pending Review

{DIVIDER}

{EMOJI['star']} Thank you for helping keep Telegram safe!

{EMOJI['rocket']} **Developed by:** {DEVELOPER}
    """
    query.edit_message_text(success_text, parse_mode='Markdown')
    context.user_data.clear()
    return ConversationHandler.END

def cancel_report(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text(f"{EMOJI['cross']} **Report Cancelled**\n\nUse /report to start again.", parse_mode='Markdown')
    context.user_data.clear()
    return ConversationHandler.END

def my_stats(update: Update, context: CallbackContext):
    user = update.effective_user
    stats = get_user_stats(user.id)
    reputation = min(100, (stats['completed'] * 10) + (stats['user'].get('reports_count', 0) * 2))
    
    stats_text = f"""
{EMOJI['stats']} **MY STATISTICS**

{DIVIDER}

{EMOJI['user']} **Profile:**
• Name: {user.first_name}
• ID: `{user.id}`
• Reports: {stats['user'].get('reports_count', 0)}

{EMOJI['report']} **Report Stats:**
• Total: {stats['total_reports']}
• ✅ Approved: {stats['completed']}
• ⏳ Pending: {stats['pending']}
• ❌ Rejected: {stats['rejected']}

{EMOJI['star']} **Reputation:** {reputation}/100

{DIVIDER}

{EMOJI['fire']} Keep reporting responsibly!
    """
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]])
    if update.callback_query:
        update.callback_query.answer()
        update.callback_query.edit_message_text(stats_text, reply_markup=keyboard, parse_mode='Markdown')
    else:
        update.message.reply_text(stats_text, reply_markup=keyboard, parse_mode='Markdown')

def check_status(update: Update, context: CallbackContext):
    user = update.effective_user
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT id, target_channel, reason, status, created_at FROM reports WHERE reporter_id = ? ORDER BY created_at DESC LIMIT 5', (user.id,))
    reports = cursor.fetchall()
    conn.close()
    
    if not reports:
        text = f"{EMOJI['info']} No reports found. Use /report to create one."
        if update.callback_query:
            update.callback_query.answer()
            update.callback_query.edit_message_text(text, parse_mode='Markdown')
        else:
            update.message.reply_text(text, parse_mode='Markdown')
        return
    
    status_text = f"{EMOJI['info']} **YOUR RECENT REPORTS**\n\n{DIVIDER}\n\n"
    status_emoji = {'pending': '⏳', 'processing': '🔄', 'completed': '✅', 'rejected': '❌'}
    
    for report in reports:
        status_text += f"""
🆔 `{report[0]}` | {status_emoji.get(report[3], '❓')} {report[3].upper()}
📢 {report[1]}
📝 {report[2]}
📅 {report[4][:10]}

{DIVIDER}
"""
    if update.callback_query:
        update.callback_query.answer()
        update.callback_query.edit_message_text(status_text, parse_mode='Markdown')
    else:
        update.message.reply_text(status_text, parse_mode='Markdown')
    # ═════════════════════════════════════════════════════════════════
# ADMIN HANDLERS
# ═════════════════════════════════════════════════════════════════

def is_admin(user_id):
    return user_id in ADMIN_IDS or (SUPER_ADMIN and user_id == SUPER_ADMIN)

def admin_users_view(update: Update, context: CallbackContext):
    query = update.callback_query
    if not is_admin(update.effective_user.id):
        query.answer('Access denied.', show_alert=True)
        return
    users = get_all_users()
    if not users:
        text = '👥 **Users**\n\nNo active users found.'
    else:
        rows = []
        for u in users[:30]:
            name = (u['first_name'] or 'User').replace('*', '')
            username = f"@{u['username']}" if u['username'] else 'no username'
            rows.append(f"• `{u['id']}` — {name} ({username})")
        text = f"👥 **Users ({len(users)})**\n\n" + '\n'.join(rows)
        if len(users) > 30:
            text += '\n\n_Showing first 30 users._'
    query.answer()
    query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 Admin Panel', callback_data='admin_home')]]))

def admin_reports_view(update: Update, context: CallbackContext):
    query = update.callback_query
    if not is_admin(update.effective_user.id):
        query.answer('Access denied.', show_alert=True)
        return
    conn = get_db()
    rows = conn.execute("SELECT id, reporter_id, target_channel, reason, priority, created_at FROM reports WHERE status = 'pending' ORDER BY priority DESC, created_at ASC LIMIT 10").fetchall()
    conn.close()
    if not rows:
        text = '📝 **Pending Reports**\n\nNo pending reports.'
        keyboard = [[InlineKeyboardButton('🔙 Admin Panel', callback_data='admin_home')]]
    else:
        text = '📝 **Pending Reports**\n\n'
        keyboard = []
        for r in rows:
            text += f"`#{r['id']}` @{r['target_channel']} — {r['reason']} — P{r['priority']}\n"
            keyboard.append([
                InlineKeyboardButton(f'✅ Approve #{r["id"]}', callback_data=f'approve_{r["id"]}'),
                InlineKeyboardButton(f'❌ Reject #{r["id"]}', callback_data=f'reject_{r["id"]}')
            ])
        keyboard.append([InlineKeyboardButton('🔙 Admin Panel', callback_data='admin_home')])
    query.answer()
    query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

def admin_panel(update: Update, context: CallbackContext):
    user = update.effective_user
    if not is_admin(user.id):
        update.message.reply_text(f"{EMOJI['error']} **Access Denied!**\nAdmin privileges required.", parse_mode='Markdown')
        return
    
    stats = get_admin_stats()
    admin_text = f"""
{EMOJI['admin']} **ADMIN CONTROL PANEL**

{DIVIDER}

📊 **System Overview:**
• Total Users: `{stats['total_users']}`
• Banned: `{stats['banned_users']}`

📝 **Reports:**
• Total: `{stats['total_reports']}`
• Pending: `{stats['pending_reports']}`
• Completed: `{stats['completed_reports']}`

📢 **Channels:**
• Tracked: `{stats['total_channels']}`

{DIVIDER}

Welcome, Boss! 👑
    """
    update.message.reply_text(admin_text, reply_markup=admin_keyboard(), parse_mode='Markdown')

def broadcast_command(update: Update, context: CallbackContext):
    user = update.effective_user
    if not is_admin(user.id):
        return
    
    if not context.args:
        update.message.reply_text("Usage: /broadcast <message>")
        return
    
    message = ' '.join(context.args)
    users = get_all_users()
    sent = 0
    failed = 0
    
    status_msg = update.message.reply_text(f"📢 Broadcasting to {len(users)} users...")
    
    for user_data in users:
        try:
            personalized = message.replace('{name}', user_data['first_name'] or 'User')
            context.bot.send_message(
                chat_id=user_data['id'],
                text=f"{BANNER}\n\n{DIVIDER}\n\n📢 **ANNOUNCEMENT**\n\n{personalized}\n\n{DIVIDER}\n\n{EMOJI['bot']} {BOT_NAME}",
                parse_mode='Markdown'
            )
            sent += 1
        except:
            failed += 1
    
    status_msg.edit_text(f"✅ Broadcast Complete!\n\n📤 Sent: {sent}\n❌ Failed: {failed}\n📊 Success: {sent/(sent+failed)*100:.1f}%")

def ban_command(update: Update, context: CallbackContext):
    user = update.effective_user
    if not is_admin(user.id):
        return
    
    if not context.args:
        update.message.reply_text("Usage: /ban <user_id> [reason]")
        return
    
    user_id = int(context.args[0])
    reason = ' '.join(context.args[1:]) if len(context.args) > 1 else "No reason"
    ban_user(user_id, reason)
    update.message.reply_text(f"{EMOJI['ban']} **User Banned**\n\nUser ID: `{user_id}`\nReason: {reason}", parse_mode='Markdown')

def unban_command(update: Update, context: CallbackContext):
    user = update.effective_user
    if not is_admin(user.id):
        return
    
    if not context.args:
        update.message.reply_text("Usage: /unban <user_id>")
        return
    
    user_id = int(context.args[0])
    unban_user(user_id)
    update.message.reply_text(f"{EMOJI['unban']} **User Unbanned**\n\nUser ID: `{user_id}`", parse_mode='Markdown')

# ═════════════════════════════════════════════════════════════════
# CALLBACK HANDLER
# ═════════════════════════════════════════════════════════════════

def handle_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    
    if data == 'main_menu':
        start(update, context)
    elif data == 'start_report':
        return report_start(update, context)
    elif data == 'my_stats':
        my_stats(update, context)
    elif data == 'check_status':
        check_status(update, context)
    elif data == 'show_help':
        help_command(update, context)
    elif data.startswith('reason_'):
        return process_reason_callback(update, context)
    elif data.startswith('priority_'):
        return process_priority_callback(update, context)
    elif data == 'skip_description':
        return skip_description(update, context)
    elif data == 'confirm_report':
        return confirm_report(update, context)
    elif data == 'cancel_report':
        return cancel_report(update, context)
    elif data == 'admin_home':
        if not is_admin(update.effective_user.id):
            query.answer('Access denied.', show_alert=True)
            return
        query.answer()
        stats = get_admin_stats()
        query.edit_message_text(
            f"{EMOJI['admin']} **ADMIN CONTROL PANEL**\n\nUsers: `{stats['total_users']}`\nBanned: `{stats['banned_users']}`\nReports: `{stats['total_reports']}`\nPending: `{stats['pending_reports']}`\nCompleted: `{stats['completed_reports']}`\nChannels: `{stats['total_channels']}`",
            reply_markup=admin_keyboard(), parse_mode='Markdown')
    elif data == 'admin_users':
        admin_users_view(update, context)
    elif data == 'admin_reports':
        admin_reports_view(update, context)
    elif data == 'admin_broadcast':
        if not is_admin(update.effective_user.id):
            query.answer('Access denied.', show_alert=True)
            return
        query.answer()
        query.edit_message_text('📢 **Broadcast**\n\nUse `/broadcast your message` from the bot chat.', parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 Admin Panel', callback_data='admin_home')]]))
    elif data == 'admin_stats':
        if not is_admin(update.effective_user.id):
            query.answer('Access denied.', show_alert=True)
            return
        query.answer()
        stats = get_admin_stats()
        query.edit_message_text(f"📊 **Statistics**\n\nUsers: {stats['total_users']}\nReports: {stats['total_reports']}\nPending: {stats['pending_reports']}", parse_mode='Markdown')
    elif data.startswith('approve_') or data.startswith('reject_'):
        if not is_admin(update.effective_user.id):
            query.answer('Access denied.', show_alert=True)
            return
        query.answer()
        action, raw_id = data.split('_', 1)
        report_id = int(raw_id)
        status = 'completed' if action == 'approve' else 'rejected'
        update_report_status(report_id, status, update.effective_user.id)
        label = 'approved' if status == 'completed' else 'rejected'
        query.edit_message_text(f"{'✅' if status == 'completed' else '❌'} Report #{report_id} {label}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('📝 Pending Reports', callback_data='admin_reports'), InlineKeyboardButton('🔙 Admin Panel', callback_data='admin_home')]]))

# ═════════════════════════════════════════════════════════════════
# ERROR HANDLER
# ═════════════════════════════════════════════════════════════════

def error_handler(update, context):
    logging.error(f"Update {update} caused error {context.error}")
    if update and update.effective_message:
        update.effective_message.reply_text(f"{EMOJI['error']} **An error occurred!**\n\nPlease try again later or contact {DEV_USERNAME}", parse_mode='Markdown')

# ═════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════

def main():
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
    if not BOT_TOKEN:
        raise RuntimeError('BOT_TOKEN is required. Set it in Render Environment Variables.')
    init_database()

    # Render Web Services require an HTTP listener. The bot polling loop runs
    # alongside a lightweight health server.
    threading.Thread(target=start_health_server, daemon=True).start()

    updater = Updater(BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    
    report_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('report', report_start), CallbackQueryHandler(report_start, pattern='^start_report$')],
        states={
            SELECTING_CHANNEL: [
                MessageHandler(Filters.text & ~Filters.command, process_channel),
                CallbackQueryHandler(cancel_report, pattern='^cancel_report$')
            ],
            SELECTING_REASON: [
                CallbackQueryHandler(process_reason_callback, pattern='^reason_'),
                CallbackQueryHandler(cancel_report, pattern='^cancel_report$')
            ],
            SELECTING_PRIORITY: [
                CallbackQueryHandler(process_priority_callback, pattern='^priority_'),
            ],
            ADDING_DESCRIPTION: [
                MessageHandler(Filters.text & ~Filters.command, process_description),
                CallbackQueryHandler(skip_description, pattern='^skip_description$'),
                CallbackQueryHandler(cancel_report, pattern='^cancel_report$')
            ],
            CONFIRMING: [
                CallbackQueryHandler(confirm_report, pattern='^confirm_report$'),
                CallbackQueryHandler(cancel_report, pattern='^cancel_report$')
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel_report)],
    )
    
    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CommandHandler('help', help_command))
    dispatcher.add_handler(CommandHandler('stats', my_stats))
    dispatcher.add_handler(CommandHandler('status', check_status))
    dispatcher.add_handler(report_conv_handler)
    dispatcher.add_handler(CommandHandler('admin', admin_panel))
    dispatcher.add_handler(CommandHandler('broadcast', broadcast_command))
    dispatcher.add_handler(CommandHandler('ban', ban_command))
    dispatcher.add_handler(CommandHandler('unban', unban_command))
    dispatcher.add_handler(CallbackQueryHandler(handle_callback))
    dispatcher.add_error_handler(error_handler)
    
    print(f"""
    ╔══════════════════════════════════════╗
    ║     BOT STARTED SUCCESSFULLY!       ║
    ║                                      ║
    ║  Developer: {DEVELOPER}    ║
    ║  Version: {VERSION}            ║
    ╚══════════════════════════════════════╝
    """)
    
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()