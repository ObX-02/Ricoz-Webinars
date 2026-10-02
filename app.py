import os
import re
from functools import wraps
from datetime import datetime

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    abort,
)

from werkzeug.security import generate_password_hash, check_password_hash


# =========================================================
# ENVIRONMENT
# =========================================================

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not configured. Please add it to your .env file."
    )


# =========================================================
# FLASK APP
# =========================================================

app = Flask(__name__)

app.secret_key = os.getenv(
    "SECRET_KEY",
    "ricoz-webinar-development-secret-key"
)


# =========================================================
# DATABASE
# =========================================================

def get_db():
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row
    )


def initialize_database():

    with get_db() as conn:

        with conn.cursor() as cur:

            # -------------------------------------------------
            # USERS
            # -------------------------------------------------

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role VARCHAR(20) NOT NULL DEFAULT 'user',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # -------------------------------------------------
            # WEBINAR CATEGORIES
            # -------------------------------------------------

            cur.execute("""
                CREATE TABLE IF NOT EXISTS webinar_categories (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) UNIQUE NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # -------------------------------------------------
            # WEBINARS
            # -------------------------------------------------

            cur.execute("""
                CREATE TABLE IF NOT EXISTS webinars (
                    id SERIAL PRIMARY KEY,
                    title VARCHAR(255) NOT NULL,
                    slug VARCHAR(255) UNIQUE NOT NULL,
                    description TEXT,
                    category_id INTEGER REFERENCES webinar_categories(id)
                        ON DELETE SET NULL,
                    speaker_name VARCHAR(150),
                    speaker_title VARCHAR(150),
                    speaker_bio TEXT,
                    scheduled_at TIMESTAMP,
                    duration_minutes INTEGER DEFAULT 60,
                    meeting_link TEXT,
                    recording_url TEXT,
                    status VARCHAR(30) DEFAULT 'Upcoming',
                    is_published BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # -------------------------------------------------
            # WEBINAR REGISTRATIONS
            # -------------------------------------------------

            cur.execute("""
                CREATE TABLE IF NOT EXISTS webinar_registrations (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL
                        REFERENCES users(id)
                        ON DELETE CASCADE,
                    webinar_id INTEGER NOT NULL
                        REFERENCES webinars(id)
                        ON DELETE CASCADE,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, webinar_id)
                )
            """)

            # -------------------------------------------------
            # NOTIFICATIONS
            # -------------------------------------------------

            cur.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL
                        REFERENCES users(id)
                        ON DELETE CASCADE,
                    title VARCHAR(255) NOT NULL,
                    message TEXT NOT NULL,
                    is_read BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # -------------------------------------------------
            # DEFAULT CATEGORIES
            # -------------------------------------------------

            categories = [
                (
                    "Product",
                    "Product updates, features, and customer-focused sessions."
                ),
                (
                    "Security",
                    "Cybersecurity, privacy, and digital protection."
                ),
                (
                    "Customer Education",
                    "Practical sessions designed to help customers get more value."
                ),
                (
                    "Technology",
                    "Technology, systems, infrastructure, and innovation."
                ),
            ]

            for name, description in categories:

                cur.execute("""
                    INSERT INTO webinar_categories (name, description)
                    VALUES (%s, %s)
                    ON CONFLICT (name) DO NOTHING
                """, (name, description))

        conn.commit()


# =========================================================
# HELPERS
# =========================================================

def slugify(text):

    text = text.lower().strip()

    text = re.sub(
        r"[^a-z0-9\s-]",
        "",
        text
    )

    text = re.sub(
        r"[\s-]+",
        "-",
        text
    )

    return text.strip("-")


def unique_slug(title, exclude_id=None):

    base_slug = slugify(title)

    if not base_slug:
        base_slug = "webinar"

    slug = base_slug
    counter = 2

    with get_db() as conn:

        with conn.cursor() as cur:

            while True:

                if exclude_id is None:

                    cur.execute("""
                        SELECT id
                        FROM webinars
                        WHERE slug = %s
                    """, (slug,))

                else:

                    cur.execute("""
                        SELECT id
                        FROM webinars
                        WHERE slug = %s
                        AND id != %s
                    """, (slug, exclude_id))

                existing = cur.fetchone()

                if not existing:
                    return slug

                slug = f"{base_slug}-{counter}"
                counter += 1


def current_user():

    user_id = session.get("user_id")

    if not user_id:
        return None

    with get_db() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT id, name, email, role, created_at
                FROM users
                WHERE id = %s
            """, (user_id,))

            return cur.fetchone()


def login_required(view):

    @wraps(view)
    def wrapped_view(*args, **kwargs):

        if not session.get("user_id"):

            flash(
                "Please sign in to continue.",
                "warning"
            )

            return redirect(
                url_for(
                    "login",
                    next=request.path
                )
            )

        return view(*args, **kwargs)

    return wrapped_view


def admin_required(view):

    @wraps(view)
    def wrapped_view(*args, **kwargs):

        user = current_user()

        if not user:

            flash(
                "Please sign in to continue.",
                "warning"
            )

            return redirect(
                url_for("login")
            )

        if user["role"] != "admin":

            abort(403)

        return view(*args, **kwargs)

    return wrapped_view


def parse_datetime(value):

    if not value:
        return None

    formats = [
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
    ]

    for fmt in formats:

        try:
            return datetime.strptime(value, fmt)

        except ValueError:
            continue

    return None


# =========================================================
# TEMPLATE CONTEXT
# =========================================================

@app.context_processor
def inject_globals():

    return {
        "current_user": current_user(),
        "current_year": datetime.now().year,
    }


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    with get_db() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    w.*,
                    c.name AS category_name
                FROM webinars w
                LEFT JOIN webinar_categories c
                    ON w.category_id = c.id
                WHERE w.is_published = TRUE
                ORDER BY w.scheduled_at ASC NULLS LAST
            """)

            webinars = cur.fetchall()

    featured_webinar = webinars[0] if webinars else None

    return render_template(
        "home.html",
        webinars=webinars,
        featured_webinar=featured_webinar
    )


# =========================================================
# WEBINARS
# =========================================================

@app.route("/webinars")
def webinars():

    category = request.args.get(
        "category",
        ""
    ).strip()

    with get_db() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    w.*,
                    c.name AS category_name
                FROM webinars w
                LEFT JOIN webinar_categories c
                    ON w.category_id = c.id
                WHERE w.is_published = TRUE
                AND (
                    %s = ''
                    OR c.name = %s
                )
                ORDER BY w.scheduled_at ASC NULLS LAST
            """, (category, category))

            webinar_list = cur.fetchall()

            cur.execute("""
                SELECT *
                FROM webinar_categories
                ORDER BY name ASC
            """)

            categories = cur.fetchall()

    return render_template(
        "webinars.html",
        webinars=webinar_list,
        categories=categories,
        selected_category=category
    )


# =========================================================
# WEBINAR DETAIL
# =========================================================

@app.route("/webinars/<slug>")
def webinar_detail(slug):

    with get_db() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    w.*,
                    c.name AS category_name,
                    c.description AS category_description
                FROM webinars w
                LEFT JOIN webinar_categories c
                    ON w.category_id = c.id
                WHERE w.slug = %s
            """, (slug,))

            webinar = cur.fetchone()

    if not webinar:
        abort(404)

    return render_template(
        "webinar_detail.html",
        webinar=webinar
    )


# =========================================================
# REGISTER FOR WEBINAR
# =========================================================

@app.route(
    "/webinars/<slug>/register",
    methods=["POST"]
)
@login_required
def register_webinar(slug):

    user = current_user()

    with get_db() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT id, title
                FROM webinars
                WHERE slug = %s
                AND is_published = TRUE
            """, (slug,))

            webinar = cur.fetchone()

            if not webinar:
                abort(404)

            cur.execute("""
                SELECT id
                FROM webinar_registrations
                WHERE user_id = %s
                AND webinar_id = %s
            """, (
                user["id"],
                webinar["id"]
            ))

            existing = cur.fetchone()

            if existing:

                flash(
                    "You are already registered for this webinar.",
                    "info"
                )

            else:

                cur.execute("""
                    INSERT INTO webinar_registrations
                    (
                        user_id,
                        webinar_id
                    )
                    VALUES (%s, %s)
                """, (
                    user["id"],
                    webinar["id"]
                ))

                cur.execute("""
                    INSERT INTO notifications
                    (
                        user_id,
                        title,
                        message
                    )
                    VALUES (%s, %s, %s)
                """, (
                    user["id"],
                    "Webinar Registration Confirmed",
                    f"You are registered for '{webinar['title']}'."
                ))

                flash(
                    "You are successfully registered for the webinar.",
                    "success"
                )

        conn.commit()

    return redirect(
        url_for(
            "webinar_detail",
            slug=slug
        )
    )


# =========================================================
# MY WEBINARS
# =========================================================

@app.route("/my-webinars")
@login_required
def my_webinars():

    user = current_user()

    with get_db() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    w.*,
                    c.name AS category_name,
                    wr.registered_at
                FROM webinar_registrations wr
                JOIN webinars w
                    ON wr.webinar_id = w.id
                LEFT JOIN webinar_categories c
                    ON w.category_id = c.id
                WHERE wr.user_id = %s
                ORDER BY w.scheduled_at ASC NULLS LAST
            """, (user["id"],))

            registrations = cur.fetchall()

    return render_template(
        "my_webinars.html",
        webinars=registrations
    )


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        if not email or not password:

            flash(
                "Please enter your email and password.",
                "warning"
            )

            return render_template("login.html")

        with get_db() as conn:

            with conn.cursor() as cur:

                cur.execute("""
                    SELECT *
                    FROM users
                    WHERE email = %s
                """, (email,))

                user = cur.fetchone()

        if not user or not check_password_hash(
            user["password_hash"],
            password
        ):

            flash(
                "Invalid email or password.",
                "danger"
            )

            return render_template("login.html")

        session.clear()

        session["user_id"] = user["id"]

        next_url = request.args.get("next")

        if next_url and next_url.startswith("/"):

            return redirect(next_url)

        if user["role"] == "admin":

            return redirect(
                url_for("admin")
            )

        return redirect(
            url_for("home")
        )

    return render_template("login.html")


# =========================================================
# REGISTER
# =========================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        if not name or not email or not password:

            flash(
                "Please complete all required fields.",
                "warning"
            )

            return render_template("register.html")

        if password != confirm_password:

            flash(
                "Passwords do not match.",
                "warning"
            )

            return render_template("register.html")

        if len(password) < 8:

            flash(
                "Password must be at least 8 characters.",
                "warning"
            )

            return render_template("register.html")

        password_hash = generate_password_hash(
            password
        )

        try:

            with get_db() as conn:

                with conn.cursor() as cur:

                    cur.execute("""
                        INSERT INTO users
                        (
                            name,
                            email,
                            password_hash
                        )
                        VALUES (%s, %s, %s)
                        RETURNING id
                    """, (
                        name,
                        email,
                        password_hash
                    ))

                    user = cur.fetchone()

                conn.commit()

        except psycopg.errors.UniqueViolation:

            flash(
                "An account with this email already exists.",
                "danger"
            )

            return render_template("register.html")

        session.clear()

        session["user_id"] = user["id"]

        flash(
            "Your account has been created successfully.",
            "success"
        )

        return redirect(
            url_for("home")
        )

    return render_template("register.html")


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    flash(
        "You have been signed out.",
        "success"
    )

    return redirect(
        url_for("home")
    )


# =========================================================
# ADMIN DASHBOARD
# =========================================================

@app.route("/admin")
@admin_required
def admin():

    with get_db() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    w.*,
                    c.name AS category_name
                FROM webinars w
                LEFT JOIN webinar_categories c
                    ON w.category_id = c.id
                ORDER BY w.created_at DESC
            """)

            webinar_list = cur.fetchall()

            cur.execute("""
                SELECT COUNT(*) AS count
                FROM webinar_registrations
            """)

            registration_count = cur.fetchone()["count"]

            cur.execute("""
                SELECT COUNT(*) AS count
                FROM webinars
                WHERE status = 'Upcoming'
            """)

            upcoming_count = cur.fetchone()["count"]

            cur.execute("""
                SELECT COUNT(*) AS count
                FROM webinars
                WHERE status = 'Completed'
            """)

            completed_count = cur.fetchone()["count"]

    return render_template(
        "admin.html",
        webinars=webinar_list,
        registration_count=registration_count,
        upcoming_count=upcoming_count,
        completed_count=completed_count
    )


# =========================================================
# CREATE WEBINAR
# =========================================================

@app.route(
    "/admin/webinars/create",
    methods=["GET", "POST"]
)
@admin_required
def create_webinar():

    with get_db() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT *
                FROM webinar_categories
                ORDER BY name ASC
            """)

            categories = cur.fetchall()

    if request.method == "POST":

        title = request.form.get(
            "title",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        category_id = request.form.get(
            "category_id"
        )

        speaker_name = request.form.get(
            "speaker_name",
            ""
        ).strip()

        speaker_title = request.form.get(
            "speaker_title",
            ""
        ).strip()

        speaker_bio = request.form.get(
            "speaker_bio",
            ""
        ).strip()

        scheduled_at_raw = request.form.get(
            "scheduled_at",
            ""
        ).strip()

        duration_raw = request.form.get(
            "duration_minutes",
            "60"
        ).strip()

        meeting_link = request.form.get(
            "meeting_link",
            ""
        ).strip()

        recording_url = request.form.get(
            "recording_url",
            ""
        ).strip()

        status = request.form.get(
            "status",
            "Upcoming"
        ).strip()

        is_published = (
            request.form.get("is_published")
            == "on"
        )

        if not title:

            flash(
                "Webinar title is required.",
                "danger"
            )

            return render_template(
                "admin_webinar_form.html",
                categories=categories,
                webinar=None,
                edit_mode=False
            )

        scheduled_at = parse_datetime(
            scheduled_at_raw
        )

        if scheduled_at_raw and not scheduled_at:

            flash(
                "Please enter a valid date and time.",
                "danger"
            )

            return render_template(
                "admin_webinar_form.html",
                categories=categories,
                webinar=None,
                edit_mode=False
            )

        try:

            duration_minutes = int(
                duration_raw or 60
            )

        except ValueError:

            flash(
                "Duration must be a valid number.",
                "danger"
            )

            return render_template(
                "admin_webinar_form.html",
                categories=categories,
                webinar=None,
                edit_mode=False
            )

        if duration_minutes <= 0:

            flash(
                "Duration must be greater than zero.",
                "danger"
            )

            return render_template(
                "admin_webinar_form.html",
                categories=categories,
                webinar=None,
                edit_mode=False
            )

        slug = unique_slug(title)

        with get_db() as conn:

            with conn.cursor() as cur:

                cur.execute("""
                    INSERT INTO webinars
                    (
                        title,
                        slug,
                        description,
                        category_id,
                        speaker_name,
                        speaker_title,
                        speaker_bio,
                        scheduled_at,
                        duration_minutes,
                        meeting_link,
                        recording_url,
                        status,
                        is_published
                    )
                    VALUES
                    (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s
                    )
                """, (
                    title,
                    slug,
                    description,
                    int(category_id) if category_id else None,
                    speaker_name,
                    speaker_title,
                    speaker_bio,
                    scheduled_at,
                    duration_minutes,
                    meeting_link,
                    recording_url,
                    status,
                    is_published
                ))

            conn.commit()

        flash(
            "Webinar created successfully.",
            "success"
        )

        return redirect(
            url_for("admin")
        )

    return render_template(
        "admin_webinar_form.html",
        categories=categories,
        webinar=None,
        edit_mode=False
    )


# =========================================================
# EDIT WEBINAR
# =========================================================

@app.route(
    "/admin/webinars/<int:webinar_id>/edit",
    methods=["GET", "POST"]
)
@admin_required
def edit_webinar(webinar_id):

    with get_db() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT *
                FROM webinars
                WHERE id = %s
            """, (webinar_id,))

            webinar = cur.fetchone()

            if not webinar:
                abort(404)

            cur.execute("""
                SELECT *
                FROM webinar_categories
                ORDER BY name ASC
            """)

            categories = cur.fetchall()

    if request.method == "POST":

        title = request.form.get(
            "title",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        category_id = request.form.get(
            "category_id"
        )

        speaker_name = request.form.get(
            "speaker_name",
            ""
        ).strip()

        speaker_title = request.form.get(
            "speaker_title",
            ""
        ).strip()

        speaker_bio = request.form.get(
            "speaker_bio",
            ""
        ).strip()

        scheduled_at_raw = request.form.get(
            "scheduled_at",
            ""
        ).strip()

        duration_raw = request.form.get(
            "duration_minutes",
            "60"
        ).strip()

        meeting_link = request.form.get(
            "meeting_link",
            ""
        ).strip()

        recording_url = request.form.get(
            "recording_url",
            ""
        ).strip()

        status = request.form.get(
            "status",
            "Upcoming"
        ).strip()

        is_published = (
            request.form.get("is_published")
            == "on"
        )

        if not title:

            flash(
                "Webinar title is required.",
                "danger"
            )

            return render_template(
                "admin_webinar_form.html",
                categories=categories,
                webinar=webinar,
                edit_mode=True
            )

        scheduled_at = parse_datetime(
            scheduled_at_raw
        )

        if scheduled_at_raw and not scheduled_at:

            flash(
                "Please enter a valid date and time.",
                "danger"
            )

            return render_template(
                "admin_webinar_form.html",
                categories=categories,
                webinar=webinar,
                edit_mode=True
            )

        try:

            duration_minutes = int(
                duration_raw or 60
            )

        except ValueError:

            flash(
                "Duration must be a valid number.",
                "danger"
            )

            return render_template(
                "admin_webinar_form.html",
                categories=categories,
                webinar=webinar,
                edit_mode=True
            )

        if duration_minutes <= 0:

            flash(
                "Duration must be greater than zero.",
                "danger"
            )

            return render_template(
                "admin_webinar_form.html",
                categories=categories,
                webinar=webinar,
                edit_mode=True
            )

        slug = unique_slug(
            title,
            exclude_id=webinar_id
        )

        with get_db() as conn:

            with conn.cursor() as cur:

                cur.execute("""
                    UPDATE webinars
                    SET
                        title = %s,
                        slug = %s,
                        description = %s,
                        category_id = %s,
                        speaker_name = %s,
                        speaker_title = %s,
                        speaker_bio = %s,
                        scheduled_at = %s,
                        duration_minutes = %s,
                        meeting_link = %s,
                        recording_url = %s,
                        status = %s,
                        is_published = %s
                    WHERE id = %s
                """, (
                    title,
                    slug,
                    description,
                    int(category_id) if category_id else None,
                    speaker_name,
                    speaker_title,
                    speaker_bio,
                    scheduled_at,
                    duration_minutes,
                    meeting_link,
                    recording_url,
                    status,
                    is_published,
                    webinar_id
                ))

            conn.commit()

        flash(
            "Webinar updated successfully.",
            "success"
        )

        return redirect(
            url_for("admin")
        )

    return render_template(
        "admin_webinar_form.html",
        categories=categories,
        webinar=webinar,
        edit_mode=True
    )


# =========================================================
# DELETE WEBINAR
# =========================================================

@app.route(
    "/admin/webinars/<int:webinar_id>/delete",
    methods=["POST"]
)
@admin_required
def delete_webinar(webinar_id):

    with get_db() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT id, title
                FROM webinars
                WHERE id = %s
            """, (webinar_id,))

            webinar = cur.fetchone()

            if not webinar:

                flash(
                    "Webinar not found.",
                    "danger"
                )

                return redirect(
                    url_for("admin")
                )

            cur.execute("""
                DELETE FROM webinars
                WHERE id = %s
            """, (webinar_id,))

        conn.commit()

    flash(
        f"'{webinar['title']}' was deleted successfully.",
        "success"
    )

    return redirect(
        url_for("admin")
    )


# =========================================================
# PUBLISH / UNPUBLISH WEBINAR
# =========================================================

@app.route(
    "/admin/webinars/<int:webinar_id>/toggle-publish",
    methods=["POST"]
)
@admin_required
def toggle_publish(webinar_id):

    with get_db() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT id, title, is_published
                FROM webinars
                WHERE id = %s
            """, (webinar_id,))

            webinar = cur.fetchone()

            if not webinar:

                flash(
                    "Webinar not found.",
                    "danger"
                )

                return redirect(
                    url_for("admin")
                )

            new_status = not webinar["is_published"]

            cur.execute("""
                UPDATE webinars
                SET is_published = %s
                WHERE id = %s
            """, (
                new_status,
                webinar_id
            ))

        conn.commit()

    if new_status:

        flash(
            f"'{webinar['title']}' has been published.",
            "success"
        )

    else:

        flash(
            f"'{webinar['title']}' has been unpublished.",
            "info"
        )

    return redirect(
        url_for("admin")
    )


# =========================================================
# PRIVACY
# =========================================================

@app.route("/privacy")
def privacy():

    return render_template(
        "privacy.html"
    )


# =========================================================
# TERMS
# =========================================================

@app.route("/terms")
def terms():

    return render_template(
        "terms.html"
    )


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/health")
def health():

    try:

        with get_db() as conn:

            with conn.cursor() as cur:

                cur.execute("SELECT 1")

                cur.fetchone()

        return {
            "status": "healthy",
            "database": "connected"
        }

    except Exception:

        return {
            "status": "unhealthy",
            "database": "disconnected"
        }, 500

@app.route("/status")
def status():
    return render_template("status.html")
# =========================================================
# ERROR HANDLERS
# =========================================================

@app.errorhandler(403)
def forbidden(error):

    return render_template(
        "404.html"
    ), 403


@app.errorhandler(404)
def page_not_found(error):

    return render_template(
        "404.html"
    ), 404


@app.errorhandler(500)
def internal_server_error(error):

    return render_template(
        "500.html"
    ), 500


# =========================================================
# START APPLICATION
# =========================================================

if __name__ == "__main__":

    initialize_database()

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )