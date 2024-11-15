import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or os.urandom(32)
socketio = SocketIO(app)

# Database setup
DATABASE = 'chat_app.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def create_tables():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users 
        (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            recipient_id INTEGER,  -- NULL for public server messages
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sender_id) REFERENCES users (id)
            FOREIGN KEY (recipient_id) REFERENCES users (id) 
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tweets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            likes INTEGER DEFAULT 0,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tweet_likes (
            user_id INTEGER NOT NULL,
            tweet_id INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (tweet_id) REFERENCES tweets (id),
            UNIQUE(user_id, tweet_id)
        )
    ''')

    conn.commit()
    conn.close()

create_tables()

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                'INSERT INTO users (username, password) VALUES (?, ?)',
                (username, password)
            )
            conn.commit()
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            # Handle username already exists error
            pass
        finally:
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor()
        user = cursor.execute(
            'SELECT * FROM users WHERE username = ? AND password = ?',
            (username, password)
        ).fetchone()
        conn.close()

        if user:
            session['user_id'] = user['id']
            return redirect(url_for('index'))
        else:
            # Handle invalid credentials
            pass
    return render_template('login.html')

@app.route('/index')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()
    messages = cursor.execute(
        'SELECT users.username, messages.content FROM messages'
        ' JOIN users ON messages.sender_id = users.id'
        ' WHERE recipient_id IS NULL'
    ).fetchall()

    tweets = cursor.execute('''
        SELECT tweets.id, users.username, tweets.content, tweets.likes 
        FROM tweets
        JOIN users ON tweets.user_id = users.id
    ''').fetchall()

    conn.close()

    return render_template('index.html', messages=messages, tweets=tweets)

@socketio.on('message')
def handle_message(data):
    if 'user_id' not in session:
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        'INSERT INTO messages (sender_id, content) VALUES (?, ?)',
        (session['user_id'], data['message'])
    )
    conn.commit()

    sender = cursor.execute(
        'SELECT username FROM users WHERE id = ?', (session['user_id'],)
    ).fetchone()
    conn.close()

    emit(
        'message',
        {'username': sender['username'], 'message': data['message']},
        broadcast=True
    )

@socketio.on('tweet')
def handle_tweet(data):
    if 'user_id' not in session:
        return

    tweet = data.get('tweet')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        'INSERT INTO tweets (user_id, content) VALUES (?, ?)',
        (session['user_id'], tweet)
    )
    conn.commit()

    username = cursor.execute(
        'SELECT username FROM users WHERE id = ?', (session['user_id'],)
    ).fetchone()['username']
    conn.close()

    emit('tweet', {'username': username, 'tweet': tweet}, broadcast=True)

@socketio.on('like_tweet')
def handle_like_tweet(data):
    if 'user_id' not in session:
        return

    tweet_id = data.get('tweet_id')
    if not tweet_id:
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO tweet_likes (user_id, tweet_id) VALUES (?, ?)
        ''', (session['user_id'], tweet_id))

        cursor.execute('''
            UPDATE tweets SET likes = likes + 1 WHERE id = ?
        ''', (tweet_id,))

        conn.commit()

        emit('update_like_count', {'tweet_id': tweet_id, 'likes': get_tweet_likes(tweet_id)}, broadcast=True)
    except sqlite3.IntegrityError:
        pass
    finally:
        conn.close()

def get_tweet_likes(tweet_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    likes = cursor.execute('''
        SELECT COUNT(*) FROM tweet_likes WHERE tweet_id = ?
    ''', (tweet_id,)).fetchone()[0]
    conn.close()
    return likes

if __name__ == '__main__':
    socketio.run(app)