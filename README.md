# FilmApp

A film-tracking web application built for the Databases and Information Systems course at the University of Copenhagen. Users can browse films, search, view detailed film pages with ratings and genres, and (once logged in) rate films on a half-star scale.

Inspired by Letterboxd, backed by the MovieLens small dataset (~100k ratings, ~10k films, 610 seeded users).

## AI use declaration

This project was developed with assistance from Claude (Anthropic) for guidance on architecture, SQL schema design, regex patterns, Flask routing, and code review. All code was reviewed and integrated by the project authors.

## Tech stack

- **Backend:** Python 3.11+, Flask
- **Database:** PostgreSQL
- **Database driver:** psycopg2
- **Templating:** Jinja2 (built into Flask)
- **Password hashing:** Werkzeug
- **Environment management:** python-dotenv

## Features

- Browse recent films on the homepage
- Film detail pages showing title, year, genres, IMDb link, average rating, and rating count
- Full-text search across film titles, using PostgreSQL regex (`~*`) with multi-word positive-lookahead support
- Genre browse with film counts per genre
- User signup, login, and logout with hashed passwords (Werkzeug `scrypt`)
- Rate films on a half-star scale (0.5–5.0), with one rating per user-film pair (enforced by composite primary key)
- Re-rating overwrites the previous rating using PostgreSQL `INSERT ... ON CONFLICT DO UPDATE`

## Setup

### Prerequisites

- Python 3.11 or newer (other versions likely work; not tested)
- PostgreSQL 14 or newer installed locally
- pgAdmin 4 (recommended for running SQL files and verifying data)
- Conda or any Python environment manager

### 1. Clone the repository

```bash
git clone <repo-url>
cd filmapp
```

### 2. Create and activate a Python environment

Using conda:

```bash
conda create -n filmapp python=3.11
conda activate filmapp
```

Or using `venv`:

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy the template and fill in your values:

```bash
# macOS / Linux
cp .env.example .env

# Windows (cmd)
copy .env.example .env
```

Then edit `.env`:

- `DB_PASSWORD` — the password for your local Postgres `postgres` user (set during Postgres installation)
- `FLASK_SECRET_KEY` — generate a random one with:

```bash
  python -c "import secrets; print(secrets.token_hex(32))"
```

The other variables (`DB_NAME`, `DB_USER`, `DB_HOST`, `DB_PORT`) have defaults that work for a standard local Postgres install and should not need changing.

### 5. Create the database

In pgAdmin: right-click **Databases → Create → Database**, name it `filmapp`.

### 6. Create the schema

In pgAdmin, open a Query Tool against the `filmapp` database, open `schema.sql`, and execute it (F5). You should see all eight tables appear in the tree under `filmapp → Schemas → public → Tables`.

### 7. Import the MovieLens data

From the project root, with your environment active:

```bash
python import_data.py
```

This will populate the database with ~9,742 films, 19 genres, 610 seeded users, and 100,836 ratings. Expected runtime: 1–2 minutes.

Verify in pgAdmin:

```sql
SELECT
  (SELECT COUNT(*) FROM genres)        AS genres,
  (SELECT COUNT(*) FROM movies)        AS movies,
  (SELECT COUNT(*) FROM users)         AS users,
  (SELECT COUNT(*) FROM ratings)       AS ratings,
  (SELECT COUNT(*) FROM movie_genres)  AS movie_genres;
```

Expected: 19 genres, 9742 movies, 610 users, 100836 ratings, ~22000 movie_genres.

### 8. Run the app

```bash
python app.py
```

Visit `http://localhost:5000` in your browser.

## Project structure

```
filmapp/
├── ml-latest-small/         # MovieLens CSVs (movies, ratings, links, tags)
├── templates/               # Jinja2 templates
│   ├── base.html            # Base template with nav, footer, flash messages
│   ├── index.html           # Homepage (recent films)
│   ├── movie_detail.html    # Film detail page with rating form
│   ├── search.html          # Search results
│   ├── genres_list.html     # Genre index
│   ├── genre_detail.html    # Films in a genre
│   ├── signup.html          # Signup form
│   └── login.html           # Login form
├── app.py                   # Flask application (routes + queries)
├── import_data.py           # One-time data import from CSVs
├── schema.sql               # Database schema (DROP + CREATE)
├── requirements.txt         # Python dependencies
├── .env.example             # Template for environment variables
├── .gitignore               # Excludes .env, __pycache__, etc.
└── README.md
```

## Database design

### Entity-Relationship diagram

![E/R diagram](Movie_ER_Diagram.drawio(1).png)

Four entities (`users`, `movies`, `genres`, `watchlists`) with relationships expressed as junction tables for many-to-many associations (`ratings`, `reviews`, `movie_genres`, `watchlist_movies`) and as foreign keys for one-to-many (`watchlists.user_id`).

Composite primary keys on the junction tables enforce uniqueness invariants:
- `(user_id, movie_id)` on `ratings` and `reviews` — one rating, one review per user-film pair
- `(movie_id, genre_id)` on `movie_genres` — no duplicate genre tagging
- `(watchlist_id, movie_id)` on `watchlist_movies` — a film can't be added to the same list twice

### Notable schema decisions

- **MovieLens user IDs are preserved.** Seeded users occupy `user_id` 1–610; the `SERIAL` sequence is advanced via `setval()` after import so real signups get IDs from 611 onward. The `is_seeded` boolean flag distinguishes the two.
- **Email and password_hash are nullable** to accommodate seeded users (who have neither). Real signups always supply both, enforced in the Flask signup route.
- **Rating scores use `NUMERIC(2,1)`** to match MovieLens half-star precision (0.5–5.0). A `CHECK` constraint enforces the valid range.
- **Timestamps use `TIMESTAMP`.** MovieLens Unix epoch values are converted via PostgreSQL's `to_timestamp()` during import.
- **Year is nullable on `movies`** to handle the small number of titles where the regex extraction returned no year (mostly TV series with year ranges like `(2006–2007)`).

## Regex usage

The project uses regular expressions in two distinct places, both real and load-bearing:

1. **Year extraction during import** (in `import_data.py`): the pattern `^(.*) \((\d{4})\)$` extracts the year from titles formatted as `"Toy Story (1995)"`. Titles failing the match are imported with `year = NULL` and the original title preserved. Trailing whitespace is stripped before matching to handle CSV quirks.

2. **Search with multi-word lookahead** (in `app.py`'s `/search` route): user input is split on whitespace, each word is escaped with `re.escape()`, and combined into a positive-lookahead chain like `(?=.*star)(?=.*wars)` — requiring all words to appear in the title in any order. This is matched against `movies.title` using PostgreSQL's case-insensitive regex operator `~*`.

## Development workflow

### Iterating on the schema

Schema changes are made by editing `schema.sql` and re-running it in pgAdmin. The `DROP TABLE IF EXISTS ... CASCADE` statements at the top wipe existing tables, so a fresh schema requires re-running the import:

1. Edit `schema.sql` in VS Code
2. Re-run it in pgAdmin (F5)
3. Re-run `python import_data.py` to repopulate

This destructive workflow is fine while data is purely seeded. Once real user data exists, switch to `ALTER TABLE` migrations.

### Adding new routes

Each feature follows the same pattern:
1. Add a route to `app.py`
2. Use `get_db_connection()` to get a connection, run queries with `cur.execute(...)`, close connection
3. Render a template in `templates/`, extending `base.html`

### Restarting Flask

`debug=True` in `app.py` auto-reloads on file changes, but syntax errors crash the reload. Restart manually with `python app.py` if changes don't take effect.

## Course

NDAB18004U — Databases and Information Systems  
Department of Computer Science, University of Copenhagen
