import http.server
import json
import hashlib
import hmac
import base64
import time
import io
import csv
import os
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta , timezone
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone
from dotenv import load_dotenv
 

load_dotenv()
# ── CONFIG ──────────────────────────────────────────────────────────────────
PORT = int(os.getenv("PORT", 8000))
SECRET_KEY = os.getenv("SECRET_KEY")
TOKEN_TTL = 86400
RECRUITER_ACCESS_REQUIRED = "Recruiter access required"
def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT"),
        cursor_factory=RealDictCursor
    )
def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

def _unb64(s):
    pad = (-len(s)) % 4
    return base64.urlsafe_b64decode(s + '=' * pad)

def create_token(user_id, company_id, user_type):
    header  = _b64(json.dumps({"alg":"HS256","typ":"JWT"}).encode())
    payload = _b64(json.dumps({"uid": user_id, "cid": company_id, "utype": user_type, "exp": int(time.time()) + TOKEN_TTL}).encode())
    sig = _b64(hmac.new(SECRET_KEY.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"

def verify_token(token):
    try:
        header, payload, sig = token.split('.')
        expected = _b64(
            hmac.new(
                SECRET_KEY.encode(),
                f"{header}.{payload}".encode(),
                hashlib.sha256
            ).digest()
        )

        if not hmac.compare_digest(sig, expected):
            return None

        data = json.loads(_unb64(payload))

        if data['exp'] < time.time():
            return None

        return data

    except (ValueError, KeyError, json.JSONDecodeError):
        return None

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def get_auth_user(handler):
    auth = handler.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    return verify_token(auth[7:])

def time_ago(dt_val):
    try:
        if isinstance(dt_val, datetime):
            dt = dt_val
        else:
            dt = datetime.fromisoformat(str(dt_val))

        diff = datetime.now(timezone.utc) - dt

        if diff.total_seconds() < 3600:
            return f"{int(diff.total_seconds() // 60)} min ago"

        if diff.days == 0:
            return f"{int(diff.total_seconds() // 3600)} hours ago"

        if diff.days == 1:
            return "Yesterday"

        return dt.strftime('%b %d')

    except  (TypeError,ValueError):
        return str(dt_val)
def fmt_sal(mn, mx):
    if mn and mx: return f"${mn//1000}k–${mx//1000}k"
    return None

class Handler(http.server.BaseHTTPRequestHandler):
    def route_recruiter_interviews(self, qs):
        claims = get_auth_user(self)

        if not claims or claims.get('utype') != 'recruiter':
            return self.send_error_json(RECRUITER_ACCESS_REQUIRED, 403)

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                i.*,
                c.full_name,
                j.title AS role
            FROM interviews i
            LEFT JOIN candidates c
                ON i.candidate_id = c.id
            LEFT JOIN jobs j
                ON i.job_id = j.id
            WHERE i.company_id = %s
            ORDER BY i.interview_date, i.interview_time
        """, (claims['cid'],))

        rows = cur.fetchall()

        cur.close()
        conn.close()

        self.send_json(rows)
    def route_recruiter_interviews_create(self, qs):
        claims = get_auth_user(self)

        if not claims or claims.get('utype') != 'recruiter':
            return self.send_error_json(RECRUITER_ACCESS_REQUIRED, 403)

        body = self.read_body()

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO interviews (
                company_id,
                candidate_id,
                job_id,
                scheduled_by,
                title,
                interview_type,
                interview_date,
                interview_time,
                duration_minutes,
                meeting_link,
                location,
                notes
            )
            VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
            )
            RETURNING id
        """, (
            claims['cid'],
            body.get('candidate_id'),
            body.get('job_id'),
            claims['uid'],
            body.get('title', 'Interview'),
            body.get('interview_type', 'interview'),
            body.get('interview_date'),
            body.get('interview_time'),
            body.get('duration_minutes', 60),
            body.get('meeting_link'),
            body.get('location'),
            body.get('notes')
        ))
        iid = cur.fetchone()['id']

        conn.commit()

        cur.close()
        conn.close()

        self.send_json({
            'id': iid,
            'message': 'Interview scheduled'
        }, 201)
    def route_recruiter_interviews_delete(self, qs):
        claims = get_auth_user(self)

        if not claims or claims.get('utype') != 'recruiter':
            return self.send_error_json (RECRUITER_ACCESS_REQUIRED, 403)

        body = self.read_body()
        interview_id = body.get('id')

        if not interview_id:
            return self.send_error_json('Interview id required', 400)

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            DELETE FROM interviews
            WHERE id = %s
            AND company_id = %s
            RETURNING id
        """, (interview_id, claims['cid']))

        deleted = cur.fetchone()

        conn.commit()

        cur.close()
        conn.close()

        if not deleted:
            return self.send_error_json('Interview not found', 404)

        self.send_json({
            'message': 'Interview deleted'
        })
    def route_seeker_interviews(self, qs):
        claims = get_auth_user(self)

        if not claims:
            return self.send_error_json('Unauthorized', 401)

        uid = claims['uid']

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                i.*,
                c.full_name,
                j.title AS role,
                co.name AS company_name
            FROM interviews i
            JOIN candidates c
                ON i.candidate_id = c.id
            LEFT JOIN jobs j
                ON c.job_id = j.id
            LEFT JOIN companies co
                ON i.company_id = co.id
            WHERE c.user_id = %s
            ORDER BY i.interview_date, i.interview_time
        """, (uid,))

        rows = cur.fetchall()

        cur.close()
        conn.close()

        self.send_json(rows)
    def route_dashboard(self, qs):
        claims = get_auth_user(self)

        if not claims:
            return self.send_error_json('Unauthorized', 401)

        if claims.get('utype') != 'recruiter':
            return self.send_error_json(RECRUITER_ACCESS_REQUIRED, 403)

        cid = claims['cid']
        uid = claims['uid']

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM companies WHERE id = %s",
            (cid,)
        )
        company = cur.fetchone()

        cur.execute(
            "SELECT * FROM users WHERE id = %s",
            (uid,)
        )
        user = cur.fetchone()

        cur.execute("""
            SELECT COUNT(*) AS total_hired
            FROM candidates
            WHERE company_id = %s
            AND stage = 'hired'
        """, (cid,))
        total_hired = cur.fetchone()['total_hired']

        cur.execute("""
            SELECT COUNT(*) AS open_roles
            FROM jobs
            WHERE company_id = %s
            AND status = 'open'
        """, (cid,))
        open_roles = cur.fetchone()['open_roles']

        cur.execute("""
            SELECT AVG(
                EXTRACT(EPOCH FROM (updated_at - applied_at)) / 86400
            ) AS avg_days
            FROM candidates
            WHERE company_id = %s
            AND stage = 'hired'
        """, (cid,))
        avg_row = cur.fetchone()['avg_days']

        cur.execute("""
            SELECT
                c.full_name,
                c.stage,
                c.updated_at,
                j.title AS job_title
            FROM candidates c
            LEFT JOIN jobs j
                ON c.job_id = j.id
            WHERE c.company_id = %s
            AND c.stage IN (
                    'hired',
                    'offer',
                    'interview',
                    'screening'
            )
            ORDER BY c.updated_at DESC
            LIMIT 5
        """, (cid,))
        recent = cur.fetchall()

        cur.execute("""
            SELECT
                j.*,
                COUNT(c.id) AS applicants
            FROM jobs j
            LEFT JOIN candidates c
                ON c.job_id = j.id
            WHERE j.company_id = %s
            AND j.status IN ('open', 'paused')
            GROUP BY j.id
            ORDER BY j.created_at DESC
        """, (cid,))
        jobs = cur.fetchall()

        cur.execute("""
            SELECT *
            FROM activity_log
            WHERE company_id = %s
            ORDER BY created_at DESC
            LIMIT 6
        """, (cid,))
        activity = cur.fetchall()

        cur.close()
        conn.close()

        self.send_json({
            'company': {
                'id': company['id'],
                'name': company['name'],
                'industry': company['industry'],
                'location': company['location'],
                'website': company['website'],
                'founded': company['founded'],
                'employees': company['employees'],
                'logo_emoji': company['logo_emoji'],
                'verified': bool(company['verified'])
            },

            'recruiter': {
                'name': user['full_name'],
                'title': user['title'],
                'role': user['role'],
                'years_exp': user['years_exp'],
                'avatar_emoji': user['avatar_emoji']
            },

            'stats': {
                'total_hired': total_hired,
                'open_roles': open_roles,
                'avg_days_to_hire': round(avg_row or 0)
            },

            'recent_candidates': [
                {
                    'name': r['full_name'],
                    'stage': r['stage'],
                    'job_title': r['job_title'],
                    'date': time_ago(r['updated_at'])
                }
                for r in recent
            ],

            'jobs': [
                {
                    'id': j['id'],
                    'title': j['title'],
                    'department': j['department'],
                    'status': j['status'],
                    'applicants': j['applicants'],
                    'location': j['location'],
                    'job_type': j['job_type'],
                    'salary_min': j['salary_min'],
                    'salary_max': j['salary_max']
                }
                for j in jobs
            ],

            'activity': [
                {
                    'action': a['action'],
                    'detail': a['detail'],
                    'time': time_ago(a['created_at'])
                }
                for a in activity
            ]
        })
    def log_message(self, fmt, *args):
        timestamp = datetime.now().strftime('%H:%M:%S')

        safe_fmt = str(fmt).replace('\n', '\\n').replace('\r', '\\r')
        safe_args = tuple(
            str(arg).replace('\n', '\\n').replace('\r', '\\r')
            for arg in args
        )

        print(f"[{timestamp}] {safe_fmt % safe_args}")
    def send_json(self, data, status=200):
        body = json.dumps(data, default=str).encode("utf-8")

        self.send_response(status)

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )

        self.send_header(
            "X-Content-Type-Options",
            "nosniff"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self._cors()
        self.end_headers()
        self.wfile.write(body)
    def send_error_json(self, msg, status=400):
        self.send_json({'error': msg}, status)

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,PUT,DELETE,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type,Authorization')

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if not length: return {}
        try:   return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
    def dispatch(self, method):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip('/')
        qs     = parse_qs(parsed.query)
        routes = {
            ('POST','/auth/login'):           self.route_login,
            ('POST','/auth/register'):        self.route_register,
            ('GET', '/companies'):            self.route_companies_list,
            ('GET', '/recruiter/dashboard'):  self.route_dashboard,
            ('GET', '/jobs'):                 self.route_jobs_list,
            ('POST','/jobs'):                 self.route_jobs_create,
            ('PUT', '/jobs'):                 self.route_jobs_update,
            ('DELETE','/jobs'):               self.route_jobs_delete,
            ('GET', '/candidates'):           self.route_candidates_list,
            ('POST','/candidates'):           self.route_candidates_create,
            ('PUT', '/candidates'):           self.route_candidates_update,
            ('GET', '/activity'):             self.route_activity,
            ('GET', '/stats/hiring-trend'):   self.route_hiring_trend,
            ('GET', '/export/report'):        self.route_export,
            ('GET', '/company'):              self.route_company_get,
            ('PUT', '/company'):              self.route_company_update,
            ('GET', '/seeker/dashboard'):     self.route_seeker_dashboard,
            ('GET', '/seeker/jobs'):          self.route_seeker_jobs,
            ('POST','/seeker/apply'):         self.route_seeker_apply,
            ('GET', '/seeker/applications'):  self.route_seeker_applications,
            ('GET', '/seeker/profile'):       self.route_seeker_profile,
            ('PUT', '/seeker/profile'):       self.route_seeker_profile_update,
            ('GET',  '/recruiter/interviews'): self.route_recruiter_interviews,
            ('POST', '/recruiter/interviews'): self.route_recruiter_interviews_create,
            ('GET',  '/seeker/interviews'): self.route_seeker_interviews,
            ('DELETE' , '/recruiter/interviews') : self.route_recruiter_interviews_delete,
            ('GET', '/ping'): self.route_ping
        }
        fn = routes.get((method, path))
        if fn: fn(qs)
        else:  self.send_error_json('Not found', 404)

    def do_GET(self):    self.dispatch('GET')
    def do_POST(self):   self.dispatch('POST')
    def do_PUT(self):    self.dispatch('PUT')
    def do_DELETE(self): self.dispatch('DELETE')

    # ── AUTH ──────────────────────────────────────────────────────────────
    def route_ping(self, qs):
        self.send_json({"status": "ok"})
    def route_login(self, qs):
        body      = self.read_body()
        email     = body.get('email','').strip().lower()
        pw        = body.get('password','')
        user_type = body.get('user_type','recruiter')
        if not email or not pw:
            return self.send_error_json('Email and password required')
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE EMAIL = %s",(email,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row or row['password_hash'] != hash_pw(pw):
            return self.send_error_json('Invalid email or password', 401)
        if row['user_type'] != user_type:
            other = 'job seeker' if user_type == 'recruiter' else 'recruiter'
            return self.send_error_json(f"This account is registered as a {other}. Please select the correct account type.", 403)

        token = create_token(row['id'], row['company_id'], row['user_type'])
        self.send_json({'access_token': token, 'user': {
            'id': row['id'], 'name': row['full_name'], 'email': row['email'],
            'user_type': row['user_type'], 'role': row['role'],
            'title': row['title'], 'company_id': row['company_id'],
        }})

    def route_register(self, qs):
        body = self.read_body()

        email = body.get('email', '').strip().lower()
        pw = body.get('password', '')
        name = body.get('full_name', '').strip()
        user_type = body.get('user_type', 'recruiter')

        if not email or not pw or not name:
            return self.send_error_json('Name, email and password are required')

        if len(pw) < 6:
            return self.send_error_json('Password must be at least 6 characters')

        conn = get_db()
        cur = conn.cursor()

        try:

            if user_type == 'recruiter':

                role = 'admin'
                title = body.get('title', 'Recruiter')
                avatar = '👩‍💼'

                existing_cid = body.get('company_id')
                company_name = (body.get('company_name') or '').strip()

                if existing_cid:

                    cur.execute(
                        "SELECT id FROM companies WHERE id = %s",
                        (existing_cid,)
                    )

                    row = cur.fetchone()

                    if not row:
                        cur.close()
                        conn.close()
                        return self.send_error_json(
                            'Selected company not found',
                            404
                        )

                    cid = existing_cid

                elif company_name:

                    cur.execute("""
                        INSERT INTO companies (
                            name,
                            industry,
                            location,
                            website,
                            founded,
                            employees,
                            logo_emoji,
                            verified
                        )
                        VALUES (
                            %s,%s,%s,%s,%s,%s,%s,FALSE
                        )
                        RETURNING id
                    """, (
                        company_name,
                        body.get('company_industry', ''),
                        body.get('company_location', ''),
                        body.get('company_website', ''),
                        body.get('company_founded') or None,
                        body.get('company_employees') or None,
                        body.get('company_logo', '🏢')
                    ))

                    cid = cur.fetchone()['id']

                else:
                    cur.close()
                    conn.close()

                    return self.send_error_json(
                        'Please enter your company name to create an account',
                        400
                    )

            else:

                cid = None
                role = 'job_seeker'
                title = body.get('title', '')
                avatar = '🧑‍💻'

            cur.execute("""
                INSERT INTO users (
                    company_id,
                    email,
                    password_hash,
                    full_name,
                    title,
                    user_type,
                    role,
                    avatar_emoji
                )
                VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s
                )
                RETURNING id
            """, (
                cid,
                email,
                hash_pw(pw),
                name,
                title,
                user_type,
                role,
                avatar
            ))

            uid = cur.fetchone()['id']

            if user_type == 'job_seeker':

                cur.execute("""
                    INSERT INTO job_seeker_profiles (
                        user_id,
                        location
                    )
                    VALUES (
                        %s,%s
                    )
                    ON CONFLICT (user_id)
                    DO NOTHING
                """, (
                    uid,
                    body.get('location', '')
                ))

            conn.commit()

            token = create_token(
                uid,
                cid,
                user_type
            )

            self.send_json({
                'access_token': token,
                'user_type': user_type,
                'company_id': cid,
                'message': 'Registered successfully'
            }, 201)

        except psycopg2.IntegrityError:

            conn.rollback()

            self.send_error_json(
                'An account with this email already exists',
                409
            )

        finally:

            cur.close()
            conn.close()
    def route_companies_list(self, qs):
        """Public endpoint — list all companies so recruiters can search & join one."""

        conn = get_db()
        cur = conn.cursor()

        from urllib.parse import urlparse, parse_qs as _pqs

        raw_qs = _pqs(urlparse(self.path).query)
        search = raw_qs.get('q', [''])[0].lower()

        if search:
            cur.execute("""
                SELECT
                    id,
                    name,
                    industry,
                    location,
                    website,
                    employees,
                    logo_emoji,
                    verified
                FROM companies
                WHERE LOWER(name) LIKE %s
                ORDER BY name
            """, (
                f'%{search}%',
            ))

            rows = cur.fetchall()

        else:
            cur.execute("""
                SELECT
                    id,
                    name,
                    industry,
                    location,
                    website,
                    employees,
                    logo_emoji,
                    verified
                FROM companies
                ORDER BY name
            """)

            rows = cur.fetchall()

        cur.close()
        conn.close()

        self.send_json(rows)
    # ── RECRUITER DASHBOARD ───────────────────────────────────────────────
     

    # ── JOBS ────────────────────────────────────────────────────────────
    def route_jobs_list(self, qs):
        claims = get_auth_user(self)

        if not claims:
            return self.send_error_json('Unauthorized', 401)

        conn = get_db()
        cur = conn.cursor()

        if claims.get('utype') == 'recruiter':

            cur.execute("""
                SELECT
                    j.*,
                    COUNT(c.id) AS applicants,
                    co.name AS company_name
                FROM jobs j
                LEFT JOIN candidates c
                    ON c.job_id = j.id
                LEFT JOIN companies co
                    ON j.company_id = co.id
                WHERE j.company_id = %s
                GROUP BY j.id, co.name
                ORDER BY j.created_at DESC
            """, (
                claims['cid'],
            ))

            jobs = cur.fetchall()

        else:
            search = qs.get('q', [''])[0].lower()

            if search:
                cur.execute("""
                    SELECT
                        j.*,
                        0 AS applicants,
                        co.name AS company_name
                    FROM jobs j
                    JOIN companies co
                        ON j.company_id = co.id
                    WHERE j.status = 'open'
                    AND (
                            LOWER(j.title) LIKE %s
                        OR LOWER(co.name) LIKE %s
                        OR LOWER(j.location) LIKE %s
                    )
                    ORDER BY j.created_at DESC
                """, (
                    f'%{search}%',
                    f'%{search}%',
                    f'%{search}%'
                ))

                jobs = cur.fetchall()

            else:
                cur.execute("""
                    SELECT
                        j.*,
                        0 AS applicants,
                        co.name AS company_name
                    FROM jobs j
                    JOIN companies co
                        ON j.company_id = co.id
                    WHERE j.status = 'open'
                    ORDER BY j.created_at DESC
                """)

                jobs = cur.fetchall()

        cur.close()
        conn.close()

        self.send_json(jobs)

    def route_jobs_create(self, qs):
        claims = get_auth_user(self)

        if not claims or claims.get('utype') != 'recruiter':
            return self.send_error_json(RECRUITER_ACCESS_REQUIRED, 403)

        body = self.read_body()

        if not body.get('title'):
            return self.send_error_json('Job title is required')

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO jobs (
                company_id,
                created_by,
                title,
                department,
                location,
                job_type,
                salary_min,
                salary_max,
                description,
                requirements,
                status
            )
            VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
            )
            RETURNING id
        """, (
            claims['cid'],
            claims['uid'],
            body.get('title'),
            body.get('department', ''),
            body.get('location', ''),
            body.get('job_type', 'Full-time'),
            body.get('salary_min'),
            body.get('salary_max'),
            body.get('description', ''),
            body.get('requirements', ''),
            'open'
        ))

        jid = cur.fetchone()['id']

        cur.execute("""
            INSERT INTO activity_log (
                company_id,
                user_id,
                action,
                entity_type,
                entity_id,
                detail
            )
            VALUES (
                %s,%s,
                'job_posted',
                'job',
                %s,
                %s
            )
        """, (
            claims['cid'],
            claims['uid'],
            jid,
            f"New job posted: {body.get('title')}"
        ))

        conn.commit()

        cur.close()
        conn.close()

        self.send_json({
            'id': jid,
            'message': 'Job created'
        }, 201)

    def route_jobs_update(self, qs):
        claims = get_auth_user(self)

        if not claims or claims.get('utype') != 'recruiter':
            return self.send_error_json (RECRUITER_ACCESS_REQUIRED, 403)

        body = self.read_body()
        jid = body.get('id')

        if not jid:
            return self.send_error_json('Missing job id')

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            UPDATE jobs
            SET
                title = COALESCE(%s, title),
                department = COALESCE(%s, department),
                location = COALESCE(%s, location),
                status = COALESCE(%s, status),
                salary_min = COALESCE(%s, salary_min),
                salary_max = COALESCE(%s, salary_max),
                description = COALESCE(%s, description),
                requirements = COALESCE(%s, requirements),
                updated_at = NOW()
            WHERE id = %s
            AND company_id = %s
        """, (
            body.get('title'),
            body.get('department'),
            body.get('location'),
            body.get('status'),
            body.get('salary_min'),
            body.get('salary_max'),
            body.get('description'),
            body.get('requirements'),
            jid,
            claims['cid']
        ))

        conn.commit()

        cur.close()
        conn.close()

        self.send_json({
            'message': 'Updated'
        })
    def route_jobs_delete(self, qs):
        claims = get_auth_user(self)

        if not claims or claims.get('utype') != 'recruiter':
            return self.send_error_json( RECRUITER_ACCESS_REQUIRED, 403)

        jid = qs.get('id', [None])[0]

        if not jid:
            return self.send_error_json('Missing id')

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            UPDATE jobs
            SET status = 'closed'
            WHERE id = %s
            AND company_id = %s
        """, (
            jid,
            claims['cid']
        ))

        conn.commit()

        cur.close()
        conn.close()

        self.send_json({
            'message': 'Job closed'
        })
    # ── CANDIDATES ──────────────────────────────────────────────────────
    def route_candidates_list(self, qs):
        claims = get_auth_user(self)

        if not claims or claims.get('utype') != 'recruiter':
            return self.send_error_json (RECRUITER_ACCESS_REQUIRED, 403)

        job_id = qs.get('job_id', [None])[0]

        conn = get_db()
        cur = conn.cursor()

        if job_id:
            cur.execute("""
                SELECT
                    c.*,
                    j.title AS job_title
                FROM candidates c
                LEFT JOIN jobs j
                    ON c.job_id = j.id
                WHERE c.company_id = %s
                AND c.job_id = %s
                ORDER BY c.applied_at DESC
            """, (
                claims['cid'],
                job_id
            ))
        else:
            cur.execute("""
                SELECT
                    c.*,
                    j.title AS job_title
                FROM candidates c
                LEFT JOIN jobs j
                    ON c.job_id = j.id
                WHERE c.company_id = %s
                ORDER BY c.applied_at DESC
            """, (
                claims['cid'],
            ))

        rows = cur.fetchall()

        cur.close()
        conn.close()

        self.send_json(rows)

    def route_candidates_create(self, qs):
        claims = get_auth_user(self)

        if not claims or claims.get('utype') != 'recruiter':
            return self.send_error_json (RECRUITER_ACCESS_REQUIRED, 403)

        body = self.read_body()

        if not body.get('full_name') or not body.get('job_id'):
            return self.send_error_json('full_name and job_id required')

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO candidates (
                company_id,
                job_id,
                full_name,
                email,
                phone,
                notes,
                stage
            )
            VALUES (
                %s,%s,%s,%s,%s,%s,'applied'
            )
            RETURNING id
        """, (
            claims['cid'],
            body['job_id'],
            body['full_name'],
            body.get('email', ''),
            body.get('phone', ''),
            body.get('notes', '')
        ))

        cid2 = cur.fetchone()['id']

        cur.execute("""
            INSERT INTO activity_log (
                company_id,
                user_id,
                action,
                entity_type,
                entity_id,
                detail
            )
            VALUES (
                %s,%s,
                'new_application',
                'candidate',
                %s,
                %s
            )
        """, (
            claims['cid'],
            claims['uid'],
            cid2,
            f"{body['full_name']} applied"
        ))

        conn.commit()

        cur.close()
        conn.close()

        self.send_json({
            'id': cid2,
            'message': 'Candidate added'
        }, 201)

    def route_candidates_update(self, qs):
        claims = get_auth_user(self)
        print(claims)
        if not claims or claims.get('utype') != 'recruiter':
            return self.send_error_json(RECRUITER_ACCESS_REQUIRED, 403)

        body = self.read_body()
        cid2 = body.get('id')

        if not cid2:
            return self.send_error_json('Missing candidate id')

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            UPDATE candidates
            SET
                stage = COALESCE(%s, stage),
                notes = COALESCE(%s, notes),
                updated_at = NOW()
            WHERE id = %s
            AND company_id = %s
        """, (
            body.get('stage'),
            body.get('notes'),
            cid2,
            claims['cid']
        ))

        if body.get('stage'):
            cur.execute(
                "SELECT full_name FROM candidates WHERE id = %s",
                (cid2,)
            )

            nr = cur.fetchone()
            nm = nr['full_name'] if nr else 'Candidate'
            print("Before Activity Log")
            print("CLAIMS:", claims)
            print("CID:", claims.get('cid'))
            print("UID:", claims.get('uid'))
            cur.execute("""
                INSERT INTO activity_log (
                    company_id,
                    user_id,
                    action,
                    entity_type,
                    entity_id,
                    detail
                )
                VALUES (
                    %s,%s,
                    'stage_changed',
                    'candidate',
                    %s,
                    %s
                )
            """, (
                claims['cid'],
                claims['uid'],
                cid2,
                f"{nm} moved to {body['stage']}"
            ))
        print("AFTER ACRTIVITY LOG")

        conn.commit()

        cur.close()
        conn.close()

        self.send_json({
            'message': 'Updated'
        })

    # ── ACTIVITY ────────────────────────────────────────────────────────
    def route_activity(self, qs):
        claims = get_auth_user(self)

        if not claims:
            return self.send_error_json('Unauthorized', 401)

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT *
            FROM activity_log
            WHERE company_id = %s
            ORDER BY created_at DESC
            LIMIT 20
        """, (
            claims['cid'],
        ))

        rows = cur.fetchall()

        cur.close()
        conn.close()

        self.send_json([
            {
                'action': r['action'],
                'detail': r['detail'],
                'time': time_ago(r['created_at'])
            }
            for r in rows
        ])
    # ── HIRING TREND ─────────────────────────────────────────────────────
    def route_hiring_trend(self, qs):
        claims = get_auth_user(self)

        if not claims:
            return self.send_error_json('Unauthorized', 401)

        period = qs.get('period', ['1Y'])[0]
        months = {'6M': 6, '1Y': 12, '2Y': 24}.get(period, 12)

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                TO_CHAR(updated_at, 'YYYY-MM') AS month,
                COUNT(*) AS applications,
                COUNT(*) FILTER (WHERE stage = 'hired') AS hired
            FROM candidates
            WHERE company_id = %s
            AND updated_at >= NOW() - (%s * INTERVAL '1 month')
            GROUP BY month
            ORDER BY month
            """, (
            claims['cid'],
            months
            ))

        
        rows = cur.fetchall()

        apps_map = {}
        hired_map = {}

        for r in rows:
            apps_map[r['month']] = r['applications']
            hired_map[r['month']] = r['hired']

        labels = []
        data = []
        applications = []

        now = datetime.now(timezone.utc)

        for i in range(months - 1, -1, -1):
            d = now.replace(day=1) - timedelta(days=i * 28)

            labels.append(
                d.strftime('%b')
                if months <= 12
                else d.strftime("%b '%y")
            )

            month_key = d.strftime('%Y-%m')

            data.append(
                hired_map.get(month_key, 0)
            )

            applications.append(
                apps_map.get(month_key, 0)
            )

        self.send_json({
            'labels': labels,
            'data': data,
            'applications' : applications
        })

    # ── EXPORT ──────────────────────────────────────────────────────────
    def route_export(self, qs):
        claims = get_auth_user(self)

        if not claims or claims.get('utype') != 'recruiter':
            return self.send_error_json(RECRUITER_ACCESS_REQUIRED, 403)

        cid = claims['cid']

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM companies WHERE id = %s",
            (cid,)
        )
        company = cur.fetchone()

        cur.execute("""
            SELECT
                j.*,
                COUNT(c.id) AS applicants
            FROM jobs j
            LEFT JOIN candidates c
                ON c.job_id = j.id
            WHERE j.company_id = %s
            GROUP BY j.id
        """, (cid,))
        jobs = cur.fetchall()

        cur.execute("""
            SELECT
                c.*,
                j.title AS job_title
            FROM candidates c
            LEFT JOIN jobs j
                ON c.job_id = j.id
            WHERE c.company_id = %s
            ORDER BY c.applied_at DESC
        """, (cid,))
        cands = cur.fetchall()

        cur.execute("""
            SELECT COUNT(*) AS total_hired
            FROM candidates
            WHERE company_id = %s
            AND stage = 'hired'
        """, (cid,))
        total_hired = cur.fetchone()['total_hired']

        cur.execute("""
            SELECT COUNT(*) AS open_roles
            FROM jobs
            WHERE company_id = %s
            AND status = 'open'
        """, (cid,))
        open_roles = cur.fetchone()['open_roles']

        cur.close()
        conn.close()

        stats = {
            'total_hired': total_hired,
            'open_roles': open_roles
        }

        out = io.StringIO()
        w = csv.writer(out)

        w.writerow(['=== TALENTBRIDGE HIRING REPORT ==='])
        w.writerow([
            f'Company: {company["name"]}',
            f'Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}'
        ])

        w.writerow([])

        w.writerow(['SUMMARY'])
        w.writerow(['Total Hired', stats['total_hired']])
        w.writerow(['Open Roles', stats['open_roles']])

        w.writerow([])

        w.writerow(['OPEN POSITIONS'])
        w.writerow([
            'Title',
            'Department',
            'Location',
            'Status',
            'Applicants',
            'Salary Range'
        ])

        for j in jobs:
            sal = (
                f"${j['salary_min']:,}–${j['salary_max']:,}"
                if j['salary_min']
                else 'N/A'
            )

            w.writerow([
                j['title'],
                j['department'],
                j['location'],
                j['status'],
                j['applicants'],
                sal
            ])

        w.writerow([])
        w.writerow(['ALL CANDIDATES'])
        w.writerow(['Name', 'Email', 'Job', 'Stage', 'Applied'])

        for c in cands:
            applied = (
                c['applied_at'].strftime('%Y-%m-%d')
                if c['applied_at']
                else ''
            )

            w.writerow([
                c['full_name'],
                c['email'],
                c['job_title'],
                c['stage'],
                applied
            ])

        csv_bytes = out.getvalue().encode('utf-8-sig')

        filename = (
            f"talentbridge_report_"
            f"{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
        )

        self.send_response(200)
        self.send_header(
            'Content-Type',
            'text/csv; charset=utf-8'
        )
        self.send_header(
            'Content-Disposition',
            f'attachment; filename="{filename}"'
        )
        self.send_header(
            'Content-Length',
            len(csv_bytes)
        )

        self._cors()
        self.end_headers()
        self.wfile.write(csv_bytes)
    # ── COMPANY ──────────────────────────────────────────────────────────
    def route_company_get(self, qs):
        claims = get_auth_user(self)

        if not claims:
            return self.send_error_json('Unauthorized', 401)

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM companies WHERE id = %s",
            (claims['cid'],)
        )

        c = cur.fetchone()

        cur.close()
        conn.close()

        self.send_json(c if c else {})

    def route_company_update(self, qs):
        claims = get_auth_user(self)

        if not claims or claims.get('utype') != 'recruiter':
            return self.send_error_json(RECRUITER_ACCESS_REQUIRED, 403)

        body = self.read_body()

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            UPDATE companies
            SET
                name = COALESCE(%s, name),
                industry = COALESCE(%s, industry),
                location = COALESCE(%s, location),
                website = COALESCE(%s, website),
                employees = COALESCE(%s, employees),
                founded = COALESCE(%s, founded)
            WHERE id = %s
        """, (
            body.get('name'),
            body.get('industry'),
            body.get('location'),
            body.get('website'),
            body.get('employees'),
            body.get('founded'),
            claims['cid']
        ))

        conn.commit()

        cur.close()
        conn.close()

        self.send_json({
            'message': 'Company updated'
        })
         

    # ── JOB SEEKER ───────────────────────────────────────────────────────
    def route_seeker_dashboard(self, qs):
        
        claims = get_auth_user(self)
        print("seeker claims:",claims)
        if not claims:
                return self.send_error_json('Unauthorized', 401)

        if claims.get('utype') != 'job_seeker':
            return self.send_error_json('Job seeker access required', 403)

        uid = claims['uid']

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM users WHERE id = %s",
            (uid,)
        )
        user = cur.fetchone()
        print("USER FROM DB:", user)
 

        cur.execute(
            "SELECT * FROM job_seeker_profiles WHERE user_id = %s",
            (uid,)
        )
        profile = cur.fetchone()
        print("PROFILE FROM DB:", profile)

        cur.execute("""
            SELECT
                c.*,
                j.title AS job_title,
                j.location AS job_location,
                j.job_type,
                j.salary_min,
                j.salary_max,
                co.name AS company_name,
                co.logo_emoji
            FROM candidates c
            LEFT JOIN jobs j ON c.job_id = j.id
            LEFT JOIN companies co ON j.company_id = co.id
            WHERE c.user_id = %s
            OR c.email = %s
            ORDER BY c.applied_at DESC
        """, (
            uid,
            user['email'] if user else ''
        ))
        applications = cur.fetchall()

        cur.execute("""
            SELECT
                j.*,
                co.name AS company_name,
                co.logo_emoji
            FROM jobs j
            JOIN companies co
                ON j.company_id = co.id
            WHERE j.status = 'open'
            ORDER BY j.created_at DESC
            LIMIT 10
        """)
        open_jobs = cur.fetchall()

        cur.close()
        conn.close()

        applied_ids = [a['job_id'] for a in applications]

        self.send_json({
            'user': {
                'name': user['full_name'],
                'email': user['email'],
                'title': user['title'],
                'avatar': user['avatar_emoji']
            } if user else {},

            'profile': profile if profile else {},

            'stats': {
                'total_applications': len(applications),
                'in_progress': len([
                    a for a in applications
                    if a['stage'] not in ('hired', 'rejected')
                ]),
                'interviews': len([
                    a for a in applications
                    if a['stage'] == 'interview'
                ]),
                'offers': len([
                    a for a in applications
                    if a['stage'] == 'offer'
                ])
            },

            'applications': [
                {
                    'id': a['id'],
                    'job_title': a['job_title'],
                    'company_name': a['company_name'],
                    'company_logo': a['logo_emoji'],
                    'stage': a['stage'],
                    'applied_at': time_ago(a['applied_at']),
                    'location': a['job_location'],
                    'salary': fmt_sal(a['salary_min'], a['salary_max'])
                }
                for a in applications
            ],

            'recommended_jobs': [
                {
                    'id': j['id'],
                    'title': j['title'],
                    'company_name': j['company_name'],
                    'company_logo': j['logo_emoji'],
                    'location': j['location'],
                    'job_type': j['job_type'],
                    'salary': fmt_sal(j['salary_min'], j['salary_max']),
                    'department': j['department'],
                    'already_applied': j['id'] in applied_ids
                }
                for j in open_jobs
            ]
    })
    def route_seeker_jobs(self, qs):
        claims = get_auth_user(self)
        if not claims:
            return self.send_error_json('Unauthorized', 401)

        search = qs.get('q', [''])[0].lower()
        location = qs.get('location', [''])[0].lower()
        job_type = qs.get('type', [''])[0]

        conn = get_db()
        cur = conn.cursor()

        query = """
            SELECT
                j.*,
                co.name AS company_name,
                co.logo_emoji,
                co.industry
            FROM jobs j
            JOIN companies co
                ON j.company_id = co.id
            WHERE j.status = 'open'
        """

        params = []

        if search:
            query += """
                AND (
                    LOWER(j.title) LIKE %s
                    OR LOWER(j.department) LIKE %s
                    OR LOWER(co.name) LIKE %s
                )
            """
            params.extend([
                f'%{search}%',
                f'%{search}%',
                f'%{search}%'
            ])

        if location:
            query += " AND LOWER(j.location) LIKE %s"
            params.append(f'%{location}%')

        if job_type:
            query += " AND j.job_type = %s"
            params.append(job_type)

        query += " ORDER BY j.created_at DESC"

        cur.execute(query, tuple(params))
        jobs = cur.fetchall()

        cur.close()
        conn.close()

        self.send_json([
            {
                'id': j['id'],
                'title': j['title'],
                'company_name': j['company_name'],
                'company_logo': j['logo_emoji'],
                'industry': j['industry'],
                'location': j['location'],
                'job_type': j['job_type'],
                'department': j['department'],
                'salary': fmt_sal(j['salary_min'], j['salary_max']),
                'description': j['description'],
                'requirements': j['requirements'],
                'created_at': time_ago(j['created_at'])
            }
            for j in jobs
        ])
    def route_seeker_apply(self, qs):
        claims = get_auth_user(self)
        if not claims:
            return self.send_error_json('Unauthorized', 401)

        if claims.get('utype') != 'job_seeker':
            return self.send_error_json('Job seeker access required', 403)

        body = self.read_body()
        job_id = body.get('job_id')

        if not job_id:
            return self.send_error_json('job_id required')

        uid = claims['uid']

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM users WHERE id = %s",
            (uid,)
        )
        user = cur.fetchone()

        if not user:
            cur.close()
            conn.close()
            return self.send_error_json('User not found', 404)

        cur.execute("""
            SELECT id
            FROM candidates
            WHERE job_id = %s
            AND (user_id = %s OR email = %s)
        """, (
            job_id,
            uid,
            user['email']
        ))

        existing = cur.fetchone()

        if existing:
            cur.close()
            conn.close()
            return self.send_error_json('You have already applied for this job', 409)

        cur.execute("""
            SELECT
                j.*,
                co.id AS coid
            FROM jobs j
            JOIN companies co
                ON j.company_id = co.id
            WHERE j.id = %s
        """, (job_id,))

        job = cur.fetchone()

        if not job or job['status'] != 'open':
            cur.close()
            conn.close()
            return self.send_error_json('Job not found or no longer open', 404)

        cur.execute("""
            INSERT INTO candidates (
                company_id,
                job_id,
                user_id,
                full_name,
                email,
                phone,
                notes,
                stage
            )
            VALUES (
                %s,%s,%s,%s,%s,%s,%s,'applied'
            )
            RETURNING id
        """, (
            job['coid'],
            job_id,
            uid,
            user['full_name'],
            user['email'],
            body.get('phone', ''),
            body.get('cover_note', '')
        ))

        app_row = cur.fetchone()
        app_id = app_row['id']

        cur.execute("""
            INSERT INTO activity_log (
                company_id,
                user_id,
                action,
                entity_type,
                entity_id,
                detail
            )
            VALUES (
                %s,%s,'new_application','candidate',%s,%s
            )
        """, (
            job['coid'],
            uid,
            app_id,
            f"{user['full_name']} applied for {job['title']}"
        ))

        conn.commit()

        cur.close()
        conn.close()

        self.send_json({
            'id': app_id,
            'message': 'Application submitted successfully!'
        }, 201)

    def route_seeker_applications(self, qs):
        claims = get_auth_user(self)
        if not claims:
            return self.send_error_json('Unauthorized', 401)

        if claims.get('utype') != 'job_seeker':
            return self.send_error_json('Job seeker access required', 403)

        uid = claims['uid']
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT email FROM users WHERE id = %s",
            (uid,)
            )
        user = cur.fetchone()
        cur.execute("""
                    SELECT
                    c.*,
                    j.title AS job_title,
                    j.location AS job_location,
                    j.job_type,
                    j.salary_min,
                    j.salary_max,
                    co.name AS company_name,
                    co.logo_emoji
                    FROM candidates c
                    LEFT JOIN jobs j ON c.job_id = j.id
                    LEFT JOIN companies co ON j.company_id = co.id
                    WHERE c.user_id = %s
                    OR c.email = %s
                    ORDER BY c.applied_at DESC
                    """, (
                        uid,
                        user['email'] if user else ''
                        ))
        rows = cur.fetchall()

        cur.close()
        conn.close()
   
        self.send_json([
            {
                'id': r['id'],
                'job_title': r['job_title'],
                'company_name': r['company_name'],
                'company_logo': r['logo_emoji'],
                'stage': r['stage'],
                'applied_at': r['applied_at'],
                'location': r['job_location'],
                'job_type': r['job_type'],
                'salary': fmt_sal(r['salary_min'], r['salary_max'])
            }
        for r in rows
    ])
    def route_seeker_profile(self, qs):
        claims = get_auth_user(self)

        if not claims:
            return self.send_error_json('Unauthorized', 401)

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM users WHERE id = %s",
            (claims['uid'],)
        )
        user = cur.fetchone()

        cur.execute(
            """
            SELECT *
            FROM job_seeker_profiles
            WHERE user_id = %s
            """,
            (claims['uid'],)
        )
        profile = cur.fetchone()

        cur.close()
        conn.close()

        self.send_json({
            'user': user,
            'profile': profile
        })
   
    def route_seeker_profile_update(self, qs):
        claims = get_auth_user(self)
        if not claims:
            return self.send_error_json('Unauthorized', 401)
    

        body = self.read_body()
        print("PROFILE UPDATE BODY", body)
        conn = get_db()
        cur = conn.cursor()
        open_to_work = body.get('open_to_work', True)

        if isinstance(open_to_work, int):
            open_to_work = bool(open_to_work)
        cur.execute("""
                    UPDATE users
                    SET
                    full_name = COALESCE(%s, full_name),
                    title = COALESCE(%s, title)
                    WHERE id = %s
                    """, (
                        body.get('full_name'),
                        body.get('title'),
                        claims['uid']
                        ))

        cur.execute("""
                    INSERT INTO job_seeker_profiles (
                    user_id,
                    headline,
                    bio,
                    skills,
                    location,
                    linkedin_url,
                    github_url,
                    portfolio_url,
                    experience_years,
                    open_to_work,
                    updated_at
                    )
                    VALUES (
                            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW()
                                )
                    ON CONFLICT (user_id)
                    DO UPDATE SET
                    headline = COALESCE(EXCLUDED.headline, job_seeker_profiles.headline),
                    bio = COALESCE(EXCLUDED.bio, job_seeker_profiles.bio),
                    skills = COALESCE(EXCLUDED.skills, job_seeker_profiles.skills),
                    location = COALESCE(EXCLUDED.location, job_seeker_profiles.location),
                    linkedin_url = COALESCE(EXCLUDED.linkedin_url, job_seeker_profiles.linkedin_url),
                    github_url = COALESCE(EXCLUDED.github_url, job_seeker_profiles.github_url),
                    portfolio_url = COALESCE(EXCLUDED.portfolio_url, job_seeker_profiles.portfolio_url),
                    experience_years = COALESCE(EXCLUDED.experience_years, job_seeker_profiles.experience_years),
                    open_to_work = COALESCE(EXCLUDED.open_to_work, job_seeker_profiles.open_to_work),
                    updated_at = NOW()
                    """, (
                        claims['uid'],
                        body.get('headline'),
                        body.get('bio'),
                        body.get('skills'),
                        body.get('location'),
                        body.get('linkedin_url'),
                        body.get('github_url'),
                        body.get('portfolio_url'),
                        body.get('experience_years'),
                        open_to_work
                        ))
        conn.commit()
        cur.close()
        conn.close()

        return self.send_json({
            'message': 'Profile updated'
        })
    @staticmethod
    def fetch_one(query, params=None):
        conn = get_db()
        cur = conn.cursor()

        cur.execute(query, params or ())
        row = cur.fetchone()

        cur.close()
        conn.close()
        return row
    @staticmethod
    def fetch_all(query, params=None):
        conn = get_db()
        cur = conn.cursor()
        cur.execute(query, params or ())
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows
    @staticmethod
    def execute_query(query, params=None):
        conn = get_db()
        cur = conn.cursor()
        cur.execute(query, params or ())
        conn.commit()
        cur.close()
        conn.close()

if __name__ == '__main__':
    
    server = http.server.ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    print(f"""
╔══════════════════════════════════════════════╗
║   TalentBridge Backend — Running ✓           ║
║   http://localhost:{PORT}                        ║
║                                              ║
║   Recruiter:  sarah@novatech.io / password   ║
║   Job Seeker: alex@jobseeker.com / password  ║
╚══════════════════════════════════════════════╝
""")
    server.serve_forever()
