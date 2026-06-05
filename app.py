import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, abort, request, redirect, url_for, session, flash
import re
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]

def get_db_connection():
    """Open a fresh connection. Called per request."""
    return psycopg2.connect(
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        port=os.environ["DB_PORT"],
        cursor_factory=RealDictCursor,   # rows come back as dicts, not tuples
    )

def current_user():
    """Return the logged-in user as a dict, or None if not logged in.
    Re-fetches from the database each call to ensure data is current."""
    user_id = session.get("user_id")
    if user_id is None:
        return None

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, username, email FROM users WHERE user_id = %s;",
        (user_id,),
    )
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user

@app.context_processor
def inject_user():
    return {"current_user": current_user()}

@app.route("/")
def index():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT movie_id, title, year
        FROM movies
        WHERE year IS NOT NULL
        ORDER BY year DESC, title
        LIMIT 20;
    """)
    movies = cur.fetchall()
    cur.close()
    conn.close()

    return render_template("index.html", movies=movies)

@app.route("/movies/<int:movie_id>")
def movie_detail(movie_id):
    conn = get_db_connection()
    cur = conn.cursor()

    # Query 1: the movie itself
    cur.execute("""
        SELECT movie_id, title, year, imdb_id
        FROM movies
        WHERE movie_id = %s;
    """, (movie_id,))
    movie = cur.fetchone()

    if movie is None:
        cur.close()
        conn.close()
        abort(404)

    # Query 2: this movie's genres
    cur.execute("""
        SELECT g.genre_name
        FROM genres g
        JOIN movie_genres mg ON mg.genre_id = g.genre_id
        WHERE mg.movie_id = %s
        ORDER BY g.genre_name;
    """, (movie_id,))
    genres = [row["genre_name"] for row in cur.fetchall()]

    # Query 3: rating stats
    cur.execute("""
        SELECT
            ROUND(AVG(score), 2) AS avg_score,
            COUNT(*) AS rating_count
        FROM ratings
        WHERE movie_id = %s;
    """, (movie_id,))
    stats = cur.fetchone()

    # Query 4: Fetch this user's rating if logged in
    user = current_user()
    user_rating = None
    if user is not None:
        cur.execute(
            "SELECT score FROM ratings WHERE user_id = %s AND movie_id = %s;",
            (user["user_id"], movie_id),
        )
        row = cur.fetchone()
        if row is not None:
            user_rating = float(row["score"])
    
    cur.close()
    conn.close()

    return render_template(
        "movie_detail.html",
        movie=movie,
        genres=genres,
        stats=stats,
        user_rating=user_rating,
    )

@app.route("/search")
def search():
    query = request.args.get("q", "").strip()

    if not query:
        # Empty search — just render the form with no results
        return render_template("search.html", query="", results=None)

    # Build a regex pattern that requires all words to appear, any order.
    # re.escape() turns "C++" into "C\+\+" so regex metacharacters are literal.
    words = query.split()
    pattern = "".join(f"(?=.*{re.escape(w)})" for w in words)

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT movie_id, title, year
        FROM movies
        WHERE title ~* %s
        ORDER BY year DESC NULLS LAST, title
        LIMIT 50;
    """, (pattern,))
    results = cur.fetchall()
    cur.close()
    conn.close()

    return render_template("search.html", query=query, results=results)

@app.route("/genres")
def genres_list():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT g.genre_id, g.genre_name, COUNT(mg.movie_id) AS movie_count
        FROM genres g
        LEFT JOIN movie_genres mg ON mg.genre_id = g.genre_id
        GROUP BY g.genre_id, g.genre_name
        ORDER BY g.genre_name;
    """)
    genres = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("genres_list.html", genres=genres)


@app.route("/genres/<int:genre_id>")
def genre_detail(genre_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT genre_id, genre_name FROM genres WHERE genre_id = %s;", (genre_id,))
    genre = cur.fetchone()

    if genre is None:
        cur.close()
        conn.close()
        abort(404)

    cur.execute("""
        SELECT m.movie_id, m.title, m.year
        FROM movies m
        JOIN movie_genres mg ON mg.movie_id = m.movie_id
        WHERE mg.genre_id = %s
        ORDER BY m.year DESC NULLS LAST, m.title
        LIMIT 100;
    """, (genre_id,))
    movies = cur.fetchall()

    cur.close()
    conn.close()
    return render_template("genre_detail.html", genre=genre, movies=movies)

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        return render_template("signup.html")

    # POST handling
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    # Server-side validation
    if len(username) < 3 or len(username) > 50:
        flash("Username must be 3–50 characters.", "error")
        return redirect(url_for("signup"))
    if "@" not in email or len(email) > 255:
        flash("Please provide a valid email.", "error")
        return redirect(url_for("signup"))
    if len(password) < 8:
        flash("Password must be at least 8 characters.", "error")
        return redirect(url_for("signup"))

    conn = get_db_connection()
    cur = conn.cursor()

    # Check uniqueness explicitly so we can give a friendly message
    cur.execute("SELECT 1 FROM users WHERE username = %s OR email = %s;", (username, email))
    if cur.fetchone() is not None:
        cur.close()
        conn.close()
        flash("That username or email is already taken.", "error")
        return redirect(url_for("signup"))

    password_hash = generate_password_hash(password)

    cur.execute("""
        INSERT INTO users (username, email, password_hash, is_seeded)
        VALUES (%s, %s, %s, FALSE)
        RETURNING user_id;
    """, (username, email, password_hash))
    new_user_id = cur.fetchone()["user_id"]
    conn.commit()
    cur.close()
    conn.close()

    # Log them in automatically after signup
    session["user_id"] = new_user_id
    session["username"] = username

    flash(f"Welcome to FilmApp, {username}!", "success")
    return redirect(url_for("index"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    identifier = request.form.get("identifier", "").strip()
    password = request.form.get("password", "")

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, username, password_hash
        FROM users
        WHERE (username = %s OR email = %s)
          AND password_hash IS NOT NULL;
    """, (identifier, identifier.lower()))
    user = cur.fetchone()
    cur.close()
    conn.close()

    if user is None or not check_password_hash(user["password_hash"], password):
        flash("Incorrect username/email or password.", "error")
        return redirect(url_for("login"))

    session["user_id"] = user["user_id"]
    session["username"] = user["username"]

    flash(f"Welcome back, {user['username']}!", "success")
    return redirect(url_for("index"))

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("index"))

@app.route("/movies/<int:movie_id>/rate", methods=["POST"])
def rate_movie(movie_id):
    user = current_user()
    if user is None:
        flash("Please log in to rate.", "error")
        return redirect(url_for("login"))

    try:
        score = float(request.form.get("score", ""))
    except ValueError:
        flash("Invalid rating.", "error")
        return redirect(url_for("movie_detail", movie_id=movie_id))

    if score < 0.5 or score > 5.0 or (score * 2) != int(score * 2):
        flash("Rating must be between 0.5 and 5.0 in half-star steps.", "error")
        return redirect(url_for("movie_detail", movie_id=movie_id))

    conn = get_db_connection()
    cur = conn.cursor()

    # Confirm the movie exists (defensive — prevents creating ratings for invalid IDs)
    cur.execute("SELECT 1 FROM movies WHERE movie_id = %s;", (movie_id,))
    if cur.fetchone() is None:
        cur.close()
        conn.close()
        abort(404)

    cur.execute("""
        INSERT INTO ratings (user_id, movie_id, score, rated_at)
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (user_id, movie_id)
        DO UPDATE SET score = EXCLUDED.score, rated_at = EXCLUDED.rated_at;
    """, (user["user_id"], movie_id, score))
    conn.commit()
    cur.close()
    conn.close()

    flash(f"Rated {score} / 5", "success")
    return redirect(url_for("movie_detail", movie_id=movie_id))

if __name__ == "__main__":
    app.run(debug=True)
