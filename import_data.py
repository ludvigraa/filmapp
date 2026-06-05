import os
from dotenv import load_dotenv
import csv
import re
import psycopg2

# --- Connection ---
load_dotenv()  # read DB credentials from .env file

conn = psycopg2.connect(
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT")
)
cur = conn.cursor()

DATA_DIR = "ml-latest-small"  # folder holding the four CSVs

# Regex to split "Toy Story (1995)" into title="Toy Story", year=1995.
# ^(.+) is greedy so it grabs everything up to the LAST " (dddd)" group,
# which correctly handles titles that themselves contain parentheses.
TITLE_YEAR = re.compile(r"^(.*) \((\d{4})\)$")


def import_genres():
    """Collect the distinct genre vocabulary from movies.csv and insert it.
    Returns a dict mapping genre_name -> genre_id for use in the junction step."""
    genres = set()
    with open(f"{DATA_DIR}/movies.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            for g in row["genres"].split("|"):
                if g != "(no genres listed)":   # skip the sentinel value
                    genres.add(g)

    genre_ids = {}
    for name in sorted(genres):
        cur.execute(
            "INSERT INTO genres (genre_name) VALUES (%s) RETURNING genre_id;",
            (name,),
        )
        genre_ids[name] = cur.fetchone()[0]
    return genre_ids


def import_movies(genre_ids):
    """Insert movies (with regex-extracted year and imdb_id from links.csv),
    then populate the movie_genres junction table."""

    # First load links.csv into a dict: movieId -> imdb_id
    imdb_by_movie = {}
    with open(f"{DATA_DIR}/links.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            imdb_by_movie[row["movieId"]] = row["imdbId"] or None

    with open(f"{DATA_DIR}/movies.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            movie_id = int(row["movieId"])
            raw_title = row["title"]

            match = TITLE_YEAR.match(raw_title)
            if match:
                title = match.group(1)
                year = int(match.group(2))
            else:
                title = raw_title    # no year found; keep whole string
                year = None

            imdb_id = imdb_by_movie.get(row["movieId"])

            cur.execute(
                "INSERT INTO movies (movie_id, title, year, imdb_id) "
                "VALUES (%s, %s, %s, %s);",
                (movie_id, title, year, imdb_id),
            )

            # Junction rows for each genre on this movie
            for g in row["genres"].split("|"):
                if g in genre_ids:   # skips "(no genres listed)" automatically
                    cur.execute(
                        "INSERT INTO movie_genres (movie_id, genre_id) "
                        "VALUES (%s, %s);",
                        (movie_id, genre_ids[g]),
                    )


def import_users():
    """Seed MovieLens users as anonymous accounts (option C).
    User IDs come from the distinct userIds in ratings.csv."""
    user_ids = set()
    with open(f"{DATA_DIR}/ratings.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            user_ids.add(int(row["userId"]))

    for uid in sorted(user_ids):
        cur.execute(
            "INSERT INTO users (user_id, username, is_seeded) "
            "VALUES (%s, %s, TRUE);",
            (uid, f"movielens_user_{uid}"),
        )

    # Advance the SERIAL sequence so real signups get IDs above the seeded range.
    max_id = max(user_ids)
    cur.execute("SELECT setval('users_user_id_seq', %s);", (max_id,))


def import_ratings():
    """Insert all ratings, converting Unix epoch timestamps to TIMESTAMP."""
    with open(f"{DATA_DIR}/ratings.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cur.execute(
                "INSERT INTO ratings (user_id, movie_id, score, rated_at) "
                "VALUES (%s, %s, %s, to_timestamp(%s));",
                (
                    int(row["userId"]),
                    int(row["movieId"]),
                    float(row["rating"]),
                    int(row["timestamp"]),
                ),
            )


def main():
    print("Importing genres...")
    genre_ids = import_genres()
    print(f"  {len(genre_ids)} genres")

    print("Importing movies + movie_genres...")
    import_movies(genre_ids)

    print("Importing seeded users...")
    import_users()

    print("Importing ratings...")
    import_ratings()

    conn.commit()   # nothing is saved until this line
    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        conn.rollback()   # undo everything if any step fails
        print("Error, rolled back:", e)
        raise
    finally:
        cur.close()
        conn.close()