from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import os
import sqlite3
import json
import requests
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import tempfile
import re
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['ALLOWED_EXTENSIONS'] = {'sql'}

# Ollama API configuration (local)
OLLAMA_API_URL = os.environ.get('OLLAMA_API_URL', 'http://localhost:11434/api/chat')
# Default model - using llama3.2:3b for lower memory requirements (~2GB)
# For full models (requires 4.6GB+), use: 'llama3', 'llama3:latest'
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'llama3.2:3b')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# Database file for user authentication
DATABASE = 'users.db'

# User Database Functions
def init_db():
    """Initialize the user database"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def get_user_db():
    """Get database connection for users"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# Authentication Decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def convert_mysql_to_sqlite(schema_content):
    """Convert MySQL syntax to SQLite-compatible syntax"""
    # Remove backticks first (before other processing)
    schema_content = schema_content.replace('`', '')
    
    # Remove comment lines
    lines = schema_content.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        # Skip comment lines and empty lines
        if stripped.startswith('--') or not stripped or (stripped.startswith('/*') and stripped.endswith('*/')):
            continue
        cleaned_lines.append(stripped)
    
    # Join all lines into single string (SQL statements can be multi-line)
    schema_content = ' '.join(cleaned_lines)
    
    # Find and process CREATE TABLE statements
    # SQLite requires AUTOINCREMENT to be used with INTEGER PRIMARY KEY, not INTEGER NOT NULL AUTOINCREMENT
    def fix_auto_increment_in_table(create_stmt):
        """Fix AUTO_INCREMENT columns that are also PRIMARY KEY and remove MySQL-specific syntax"""
        # Remove MySQL-specific syntax that comes after the closing parenthesis
        # Find the last closing parenthesis and remove everything after it that matches MySQL syntax
        last_paren = create_stmt.rfind(')')
        if last_paren != -1:
            table_def = create_stmt[:last_paren + 1]
            remainder = create_stmt[last_paren + 1:]
            # Remove MySQL-specific syntax from remainder
            remainder = re.sub(r'\s*ENGINE\s*=\s*\w+', '', remainder, flags=re.IGNORECASE)
            remainder = re.sub(r'\s*DEFAULT\s+CHARSET\s*=\s*\w+', '', remainder, flags=re.IGNORECASE)
            remainder = re.sub(r'\s*CHARACTER\s+SET\s+\w+', '', remainder, flags=re.IGNORECASE)
            remainder = re.sub(r'\s*AUTO_INCREMENT\s*=\s*\d+', '', remainder, flags=re.IGNORECASE)
            remainder = re.sub(r'\s*COLLATE\s+\w+', '', remainder, flags=re.IGNORECASE)
            create_stmt = table_def + remainder
        
        # Find column with AUTO_INCREMENT
        # Pattern to match: column_name int(11) NOT NULL AUTO_INCREMENT or similar
        autoinc_col_pattern = r'(\w+)\s+(?:int\(\d+\)|int\b|INTEGER)\s+(?:NOT\s+NULL\s+)?AUTO_INCREMENT'
        match = re.search(autoinc_col_pattern, create_stmt, re.IGNORECASE)
        
        if match:
            col_name = match.group(1)
            # Check if there's a PRIMARY KEY constraint for this column
            pk_constraint_pattern = r'PRIMARY\s+KEY\s*\(\s*' + re.escape(col_name) + r'\s*\)'
            
            if re.search(pk_constraint_pattern, create_stmt, re.IGNORECASE):
                # Replace the column definition to use INTEGER PRIMARY KEY AUTOINCREMENT
                # Match: col_name int(...) NOT NULL AUTO_INCREMENT (with variations)
                col_def_to_replace = r'\b' + re.escape(col_name) + r'\s+(?:int\(\d+\)|int\b|INTEGER)\s+(?:NOT\s+NULL\s+)?AUTO_INCREMENT'
                create_stmt = re.sub(col_def_to_replace, 
                                    col_name + ' INTEGER PRIMARY KEY AUTOINCREMENT', 
                                    create_stmt, flags=re.IGNORECASE)
                
                # Remove the separate PRIMARY KEY constraint
                create_stmt = re.sub(pk_constraint_pattern + r'\s*,?\s*', '', create_stmt, flags=re.IGNORECASE)
        
        return create_stmt
    
    # Split by semicolons to process each statement separately
    # This is simpler and more reliable than trying to match nested parentheses
    parts = schema_content.split(';')
    processed_parts = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Check if this is a CREATE TABLE statement
        if re.match(r'CREATE\s+TABLE', part, re.IGNORECASE):
            part = fix_auto_increment_in_table(part)
        processed_parts.append(part)
    
    schema_content = '; '.join(processed_parts)
    
    # Convert INT(n) to INTEGER for all remaining columns
    schema_content = re.sub(r'\bint\(\d+\)', 'INTEGER', schema_content, flags=re.IGNORECASE)
    schema_content = re.sub(r'\bint\b(?!EGER)', 'INTEGER', schema_content, flags=re.IGNORECASE)
    
    # Remove any remaining AUTO_INCREMENT (SQLite only supports AUTOINCREMENT with PRIMARY KEY)
    schema_content = re.sub(r'\s+AUTO_INCREMENT\b', '', schema_content, flags=re.IGNORECASE)
    
    # Remove MySQL-specific syntax
    schema_content = re.sub(r'\s*ENGINE\s*=\s*\w+', '', schema_content, flags=re.IGNORECASE)
    schema_content = re.sub(r'\s*CHARACTER\s+SET\s+\w+', '', schema_content, flags=re.IGNORECASE)
    schema_content = re.sub(r'\s*COLLATE\s+\w+', '', schema_content, flags=re.IGNORECASE)
    schema_content = re.sub(r'\s*DEFAULT\s+CHARSET\s*=\s*\w+', '', schema_content, flags=re.IGNORECASE)
    schema_content = re.sub(r'\bUNSIGNED\b', '', schema_content, flags=re.IGNORECASE)
    schema_content = re.sub(r'\s*AUTO_INCREMENT\s*=\s*\d+\s*', ' ', schema_content, flags=re.IGNORECASE)
    
    # Clean up multiple spaces and commas
    schema_content = re.sub(r',\s*,', ',', schema_content)  # double commas
    schema_content = re.sub(r',\s*\)', ')', schema_content)  # trailing comma
    schema_content = re.sub(r'\s+', ' ', schema_content)  # multiple spaces
    
    # Ensure semicolons separate statements properly
    schema_content = re.sub(r'\s*;\s*', ';', schema_content)
    
    return schema_content

def get_db_connection(schema_content):
    """Create an in-memory SQLite database from schema content"""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    
    # Convert MySQL syntax to SQLite-compatible syntax
    schema_content = convert_mysql_to_sqlite(schema_content)
    
    # Execute schema SQL
    try:
        # Split by semicolons and execute each statement
        statements = [s.strip() for s in schema_content.split(';') if s.strip()]
        for statement in statements:
            if statement:
                # Skip comments and empty statements
                if statement.strip().startswith('--') or statement.strip().startswith('/*'):
                    continue
                # Skip non-SQL lines (like -- comments)
                if statement.strip() and not statement.strip().startswith('--'):
                    try:
                        conn.execute(statement)
                    except sqlite3.OperationalError as e:
                        # If it's a table already exists error, that's okay (IF NOT EXISTS)
                        if 'already exists' not in str(e).lower():
                            raise
        conn.commit()
    except Exception as e:
        conn.close()
        raise Exception(f"Error executing schema: {str(e)}. Statement that failed: {statement[:100] if 'statement' in locals() else 'unknown'}")
    
    return conn

def generate_sql_with_ai(natural_language_query, schema_content, model=None):
    """Generate SQL query using Ollama API (local)"""
    # Use provided model or default to OLLAMA_MODEL
    if model is None:
        model = OLLAMA_MODEL
    
    # Verify model is available (optional check)
    try:
        check_url = OLLAMA_API_URL.replace('/api/chat', '/api/tags')
        check_response = requests.get(check_url, timeout=5)
        if check_response.status_code == 200:
            available_models = check_response.json().get('models', [])
            model_names = [m.get('name', '') for m in available_models]
            # Check if exact model name or base model name exists
            model_base = model.split(':')[0]
            # Also check for 'latest' tag variations
            model_variants = [model, model_base, f"{model_base}:latest"]
            if not any(m in model_names or any(avail.startswith(m.split(':')[0]) for avail in model_names) for m in model_variants):
                available_list = ', '.join(set([m.split(':')[0] for m in model_names]))
                raise Exception(f"Model '{model}' not found. Available models: {available_list}. Please run: ollama pull {model}")
    except requests.exceptions.RequestException:
        # If we can't check, continue anyway - might be a network issue
        pass
    
    # Limit schema size to prevent extremely long prompts that slow down generation
    max_schema_length = 2000  # characters
    if len(schema_content) > max_schema_length:
        schema_content_truncated = schema_content[:max_schema_length] + "\n... (schema truncated)"
    else:
        schema_content_truncated = schema_content
    
    # Very concise prompt for faster generation
    prompt = f"""Schema:
{schema_content_truncated}

Query: {natural_language_query}

SQL:"""

    headers = {
        'Content-Type': 'application/json'
    }
    
    payload = {
        'model': model,
        'messages': [
            {
                'role': 'system',
                'content': 'You are an expert SQL query generator. Generate only SQL queries without explanations.'
            },
            {
                'role': 'user',
                'content': prompt
            }
        ],
        'stream': False,
        'options': {
            'temperature': 0.1,  # Lower temperature for faster, more deterministic outputs
            'num_predict': 500   # Limit response length to speed up generation
        }
    }
    
    try:
        # Try /api/chat endpoint first (newer Ollama versions)
        # Increased timeout for slower systems - local models can take longer
        response = requests.post(OLLAMA_API_URL, headers=headers, json=payload, timeout=300)
        
        # If /api/chat fails, try /api/generate as fallback (older Ollama versions)
        if response.status_code == 500 or response.status_code == 404:
            # Try the /api/generate endpoint with simpler format
            generate_url = OLLAMA_API_URL.replace('/api/chat', '/api/generate')
            generate_payload = {
                'model': model,
                'prompt': f"{payload['messages'][0]['content']}\n\n{payload['messages'][1]['content']}",
                'stream': False,
                'options': {
                    'temperature': 0.1,
                    'num_predict': 300
                }
            }
            response = requests.post(generate_url, headers=headers, json=generate_payload, timeout=300)
        
        # Get more details about the error if request failed
        if response.status_code != 200:
            error_detail = ""
            try:
                error_data = response.json()
                error_detail = f" - {error_data}"
                # Check for model not found errors
                if 'error' in error_data and ('not found' in error_data['error'].lower() or response.status_code == 404):
                    error_msg = error_data['error']
                    raise Exception(f"Model not found: {error_msg}. Available models: Run 'ollama list' to see installed models. To install a smaller model, try: 'ollama pull llama3.2:3b' or 'ollama pull mistral:7b'")
                # Check for memory-related errors
                elif 'error' in error_data and 'memory' in error_data['error'].lower():
                    error_msg = error_data['error']
                    raise Exception(f"Insufficient memory: {error_msg}. Try using a smaller model. Run 'ollama pull llama3.2:3b' (requires ~2GB) or 'ollama pull mistral:7b' (requires ~4GB) to download smaller versions.")
            except Exception as e:
                if "Model not found" in str(e) or "Insufficient memory" in str(e):
                    raise e
                error_detail = f" - {error_data if 'error_data' in locals() else response.text[:200]}"
            if not error_detail:
                error_detail = f" - {response.text[:200]}"
            raise Exception(f"Ollama API returned status {response.status_code}{error_detail}")
        
        response.raise_for_status()
        data = response.json()
        
        # Ollama /api/chat response format: {"message": {"content": "..."}}
        if 'message' in data and 'content' in data['message']:
            generated_sql = data['message']['content'].strip()
        # Ollama /api/generate response format: {"response": "..."}
        elif 'response' in data:
            generated_sql = data['response'].strip()
        else:
            raise Exception(f"No SQL generated from API response. Response: {data}")
        
        # Clean up SQL - remove markdown code blocks if present
        generated_sql = re.sub(r'```sql\n?', '', generated_sql)
        generated_sql = re.sub(r'```\n?', '', generated_sql)
        generated_sql = generated_sql.strip()
        return generated_sql
    except requests.exceptions.ConnectionError as e:
        raise Exception("Cannot connect to Ollama. Please make sure Ollama is running on your machine. Start it with: ollama serve")
    except requests.exceptions.RequestException as e:
        raise Exception(f"API request failed: {str(e)}")
    except Exception as e:
        raise Exception(f"Error generating SQL: {str(e)}")

# Authentication Routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.json
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        if not username or not password:
            return jsonify({'success': False, 'error': 'Username and password are required'}), 400
        
        conn = get_user_db()
        user = conn.execute('SELECT * FROM users WHERE username = ? OR email = ?', (username, username)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            return jsonify({'success': True, 'message': 'Login successful'})
        else:
            return jsonify({'success': False, 'error': 'Invalid username or password'}), 401
    
    # If already logged in, redirect to home
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        data = request.json
        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '').strip()
        confirm_password = data.get('confirm_password', '').strip()
        
        # Validation
        if not username or not email or not password:
            return jsonify({'success': False, 'error': 'All fields are required'}), 400
        
        if password != confirm_password:
            return jsonify({'success': False, 'error': 'Passwords do not match'}), 400
        
        if len(password) < 6:
            return jsonify({'success': False, 'error': 'Password must be at least 6 characters long'}), 400
        
        # Email validation
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            return jsonify({'success': False, 'error': 'Invalid email format'}), 400
        
        conn = get_user_db()
        try:
            # Check if username or email already exists
            existing_user = conn.execute('SELECT * FROM users WHERE username = ? OR email = ?', (username, email)).fetchone()
            if existing_user:
                conn.close()
                return jsonify({'success': False, 'error': 'Username or email already exists'}), 400
            
            # Create new user
            password_hash = generate_password_hash(password)
            cursor = conn.cursor()
            cursor.execute('INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)',
                        (username, email, password_hash))
            conn.commit()
            user_id = cursor.lastrowid
            conn.close()
            
            # Auto-login the user after successful signup
            session['user_id'] = user_id
            session['username'] = username
            
            return jsonify({'success': True, 'message': 'Account created successfully'})
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({'success': False, 'error': 'Username or email already exists'}), 400
        except Exception as e:
            conn.close()
            return jsonify({'success': False, 'error': 'An error occurred. Please try again.'}), 500
    
    # If already logged in, redirect to home
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('welcome'))

@app.route('/')
def welcome():
    # If already logged in, redirect to home
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('welcome.html')

@app.route('/home')
@login_required
def index():
    return render_template('index.html')

@app.route('/about')
@login_required
def about():
    return render_template('about.html')

@app.route('/developers')
@login_required
def developers():
    return render_template('developers.html')

@app.route('/contact')
@login_required
def contact():
    return render_template('contact.html')

@app.route('/api/generate-sql', methods=['POST'])
def generate_sql():
    try:
        data = request.json
        natural_language_query = data.get('query', '').strip()
        schema_content = data.get('schema', '').strip()
        model = data.get('model', OLLAMA_MODEL)
        
        if not natural_language_query:
            return jsonify({'error': 'Natural language query is required'}), 400
        
        if not schema_content:
            return jsonify({'error': 'Schema content is required'}), 400
        
        # Generate SQL using AI
        generated_sql = generate_sql_with_ai(natural_language_query, schema_content, model)
        
        return jsonify({
            'success': True,
            'sql': generated_sql
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/execute-sql', methods=['POST'])
def execute_sql():
    try:
        data = request.json
        sql_query = data.get('sql', '').strip()
        schema_content = data.get('schema', '').strip()
        
        if not sql_query:
            return jsonify({'error': 'SQL query is required'}), 400
        
        if not schema_content:
            return jsonify({'error': 'Schema content is required'}), 400
        
        # Create database connection
        conn = get_db_connection(schema_content)
        cursor = conn.cursor()
        
        # Execute query
        cursor.execute(sql_query)
        
        # Fetch results
        if sql_query.strip().upper().startswith('SELECT'):
            rows = cursor.fetchall()
            columns = [description[0] for description in cursor.description]
            results = [dict(zip(columns, row)) for row in rows]
        else:
            conn.commit()
            results = {'message': 'Query executed successfully', 'rows_affected': cursor.rowcount}
            columns = []
        
        conn.close()
        
        return jsonify({
            'success': True,
            'columns': columns,
            'results': results
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/contact', methods=['POST'])
def contact_submit():
    try:
        data = request.json
        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        subject = data.get('subject', '').strip()
        message = data.get('message', '').strip()
        
        # Validation
        if not name:
            return jsonify({'error': 'Name is required'}), 400
        if not email:
            return jsonify({'error': 'Email is required'}), 400
        if not message:
            return jsonify({'error': 'Message is required'}), 400
        
        # Email validation
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            return jsonify({'error': 'Invalid email format'}), 400
        
        # In a real application, you would send an email here
        # For now, we'll just return success
        print(f"Contact form submission: {name} ({email}) - {subject}: {message}")
        
        return jsonify({
            'success': True,
            'message': 'Thank you for your message! We will get back to you soon.'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Initialize database on startup
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)

