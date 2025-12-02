from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from functools import wraps
import secrets
import hashlib
import sqlite3
import logging
from datetime import datetime
import os

app = Flask(__name__)
# Gerar chave secreta segura - Use variável de ambiente em produção
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('moderation.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Chave de API para Roblox - Use variável de ambiente em produção
API_KEY = os.environ.get('ROBLOX_API_KEY', 'sua_chave_api_secreta_aqui')

# Banco de dados SQLite
DB_NAME = 'moderation.db'

# ==================== DATABASE SETUP ====================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Tabela de administradores
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabela de players ativos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS active_players (
            user_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabela de comandos pendentes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            reason TEXT,
            moderator TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed INTEGER DEFAULT 0
        )
    ''')
    
    # Tabela de bans permanentes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            reason TEXT,
            banned_by TEXT,
            banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabela de logs de ações
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS action_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            moderator TEXT,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    
    # Criar usuários padrão (apenas se não existirem)
    cursor.execute("SELECT COUNT(*) FROM admins")
    if cursor.fetchone()[0] == 0:
        default_users = [
            ("gui", "gui1909"),
            ("tavoxx", "script99")
        ]
        for username, password in default_users:
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            cursor.execute("INSERT INTO admins (username, password_hash) VALUES (?, ?)", 
                         (username, password_hash))
            logger.info(f"Usuário padrão criado: {username}")
        conn.commit()
    
    conn.close()
    logger.info("Database inicializado com sucesso")

# ==================== HELPER FUNCTIONS ====================
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_api_key():
    """Verifica se a requisição tem a chave de API válida"""
    auth_header = request.headers.get('X-API-Key')
    return auth_header == API_KEY

def log_action(user_id, action, moderator, details=""):
    """Registra ações no banco de dados"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO action_logs (user_id, action, moderator, details) VALUES (?, ?, ?, ?)",
            (user_id, action, moderator, details)
        )
        conn.commit()
        conn.close()
        logger.info(f"Ação registrada: {action} por {moderator} em UserID {user_id}")
    except Exception as e:
        logger.error(f"Erro ao registrar ação: {e}")

# ==================== DECORATORS ====================
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'logged_in' not in session or not session['logged_in']:
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return wrapper

def api_key_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not verify_api_key():
            logger.warning(f"Tentativa de acesso não autorizado à API de {request.remote_addr}")
            return jsonify({"status": "error", "message": "Não autorizado"}), 401
        return f(*args, **kwargs)
    return wrapper

# ==================== LOGIN/LOGOUT ROUTES ====================
@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        if not username or not password:
            return render_template('login.html', error="Preencha todos os campos.")
        
        password_hash = hash_password(password)
        
        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT username FROM admins WHERE username = ? AND password_hash = ?",
                (username, password_hash)
            )
            user = cursor.fetchone()
            conn.close()
            
            if user:
                session['logged_in'] = True
                session['username'] = username
                logger.info(f"Login bem-sucedido: {username}")
                return redirect(url_for('dashboard_page'))
            else:
                logger.warning(f"Tentativa de login falhou para: {username}")
                return render_template('login.html', error="Usuário ou senha inválidos.")
        except Exception as e:
            logger.error(f"Erro no login: {e}")
            return render_template('login.html', error="Erro no servidor.")
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    username = session.get('username', 'Unknown')
    session.clear()
    logger.info(f"Logout: {username}")
    return redirect(url_for('login_page'))

# ==================== API ROUTES (ROBLOX) ====================
@app.route('/api/moderacao/updatePlayers', methods=['POST'])
@api_key_required
def update_players():
    try:
        player_list = request.get_json()
        
        if not isinstance(player_list, list):
            return jsonify({"status": "error", "message": "Formato inválido"}), 400
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Limpar players antigos (opcional - manter histórico)
        cursor.execute("DELETE FROM active_players")
        
        # Inserir players atuais
        for player in player_list:
            if 'UserId' in player and 'Name' in player:
                cursor.execute(
                    "INSERT OR REPLACE INTO active_players (user_id, name, last_seen) VALUES (?, ?, ?)",
                    (player['UserId'], player['Name'], datetime.now())
                )
        
        conn.commit()
        conn.close()
        
        logger.info(f"Lista de players atualizada: {len(player_list)} jogadores")
        return jsonify({"status": "success", "count": len(player_list)})
        
    except Exception as e:
        logger.error(f"Erro ao atualizar players: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/moderacao/pendingCommands', methods=['GET'])
@api_key_required
def get_pending_commands():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, user_id, action, reason, moderator 
            FROM pending_commands 
            WHERE processed = 0
            ORDER BY created_at ASC
        """)
        
        commands = []
        command_ids = []
        
        for row in cursor.fetchall():
            cmd_id, user_id, action, reason, moderator = row
            commands.append({
                "UserId": user_id,
                "Action": action,
                "Reason": reason or f"{action} por {moderator}"
            })
            command_ids.append(cmd_id)
        
        # Marcar como processados
        if command_ids:
            cursor.execute(
                f"UPDATE pending_commands SET processed = 1 WHERE id IN ({','.join('?' * len(command_ids))})",
                command_ids
            )
        
        conn.commit()
        conn.close()
        
        logger.info(f"Comandos pendentes enviados: {len(commands)}")
        return jsonify(commands)
        
    except Exception as e:
        logger.error(f"Erro ao buscar comandos: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/moderacao/checkBan/<int:user_id>', methods=['GET'])
@api_key_required
def check_ban(user_id):
    """Endpoint para verificar se um usuário está banido"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT reason, banned_by FROM bans WHERE user_id = ?", (user_id,))
        ban = cursor.fetchone()
        conn.close()
        
        if ban:
            return jsonify({
                "banned": True,
                "reason": ban[0],
                "banned_by": ban[1]
            })
        return jsonify({"banned": False})
        
    except Exception as e:
        logger.error(f"Erro ao verificar ban: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400

# ==================== DASHBOARD ROUTES ====================
@app.route('/')
@login_required
def dashboard_page():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute("SELECT user_id, name, last_seen FROM active_players ORDER BY name")
        players = [{"UserId": row[0], "Name": row[1], "LastSeen": row[2]} for row in cursor.fetchall()]
        
        cursor.execute("""
            SELECT user_id, action, moderator, details, timestamp 
            FROM action_logs 
            ORDER BY timestamp DESC 
            LIMIT 50
        """)
        recent_logs = cursor.fetchall()
        
        conn.close()
        
        return render_template(
            'dashboard.html', 
            players=players, 
            username=session['username'],
            recent_logs=recent_logs
        )
    except Exception as e:
        logger.error(f"Erro ao carregar dashboard: {e}")
        return f"Erro ao carregar dashboard: {e}", 500

@app.route('/api/moderacao/executeAction', methods=['POST'])
@login_required
def execute_action():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        action = data.get('action')
        reason = data.get('reason', '')
        
        if not user_id or action not in ["Kick", "Ban"]:
            return jsonify({"status": "error", "message": "Dados inválidos"}), 400
        
        moderator = session.get('username', 'Unknown')
        user_id = int(user_id)
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Adicionar comando pendente
        cursor.execute(
            "INSERT INTO pending_commands (user_id, action, reason, moderator) VALUES (?, ?, ?, ?)",
            (user_id, action, reason, moderator)
        )
        
        # Se for ban, adicionar à tabela de bans
        if action == "Ban":
            cursor.execute(
                "INSERT OR REPLACE INTO bans (user_id, reason, banned_by) VALUES (?, ?, ?)",
                (user_id, reason, moderator)
            )
        
        conn.commit()
        conn.close()
        
        # Registrar ação
        log_action(user_id, action, moderator, reason)
        
        logger.info(f"{moderator} executou {action} em UserID {user_id}")
        return jsonify({
            "status": "success", 
            "message": f"Comando {action} agendado para o UserID {user_id}"
        })
        
    except Exception as e:
        logger.error(f"Erro ao executar ação: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/bans')
@login_required
def bans_page():
    """Página para gerenciar bans"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT user_id, username, reason, banned_by, banned_at 
            FROM bans 
            ORDER BY banned_at DESC
        """)
        bans = cursor.fetchall()
        conn.close()
        
        return render_template('bans.html', bans=bans, username=session['username'])
    except Exception as e:
        logger.error(f"Erro ao carregar bans: {e}")
        return f"Erro: {e}", 500

@app.route('/api/moderacao/unban', methods=['POST'])
@login_required
def unban_user():
    """Remove ban de um usuário"""
    try:
        data = request.get_json()
        user_id = int(data.get('user_id'))
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM bans WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        
        moderator = session.get('username', 'Unknown')
        log_action(user_id, "Unban", moderator, "Ban removido")
        
        logger.info(f"{moderator} removeu ban de UserID {user_id}")
        return jsonify({"status": "success", "message": f"Ban removido do UserID {user_id}"})
        
    except Exception as e:
        logger.error(f"Erro ao remover ban: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400

# ==================== STARTUP ====================
if __name__ == '__main__':
    init_db()
    logger.info("Sistema de moderação iniciado")
    print("\n" + "="*50)
    print("🔐 SISTEMA DE MODERAÇÃO INICIADO")
    print("="*50)
    print(f"📝 Chave API: {API_KEY}")
    print(f"🔑 Secret Key: {app.secret_key[:20]}...")
    print("⚠️  ATENÇÃO: Altere as chaves de API em produção!")
    print("="*50 + "\n")
    
    # Modo debug apenas em desenvolvimento
    app.run(host='127.0.0.1', port=5000, debug=True)