import http.server
import json
import sqlite3
import hashlib
import hmac
import base64
import time
import io
import csv
import os
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta

# ── CONFIG ──────────────────────────────────────────────────────────────────
PORT       = 8000
DB_PATH    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "talentbridge.db")
SECRET_KEY = "talentbridge-super-secret-2025"
TOKEN_TTL  = 86400

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS companies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    industry    TEXT,
    location    TEXT,
    website     TEXT,
    founded     INTEGER,
    employees   INTEGER,
    logo_emoji  TEXT DEFAULT '🏢',
    verified    INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id    INTEGER REFERENCES companies(id),
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name     TEXT,
    title         TEXT,
    user_type     TEXT DEFAULT 'recruiter',
    role          TEXT DEFAULT 'recruiter',
    years_exp     INTEGER DEFAULT 0,
    avatar_emoji  TEXT DEFAULT '👤',
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS job_seeker_profiles (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER UNIQUE REFERENCES users(id),
    headline       TEXT,
    bio            TEXT,
    skills         TEXT,
    location       TEXT,
    resume_url     TEXT,
    linkedin_url   TEXT,
    github_url     TEXT,
    portfolio_url  TEXT,
    experience_years INTEGER DEFAULT 0,
    open_to_work   INTEGER DEFAULT 1,
    created_at     TEXT DEFAULT (datetime('now')),
    updated_at     TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id   INTEGER REFERENCES companies(id),
    created_by   INTEGER REFERENCES users(id),
    title        TEXT NOT NULL,
    department   TEXT,
    location     TEXT,
    job_type     TEXT DEFAULT 'Full-time',
    salary_min   INTEGER,
    salary_max   INTEGER,
    description  TEXT,
    requirements TEXT,
    status       TEXT DEFAULT 'open',
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS candidates (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id   INTEGER REFERENCES companies(id),
    job_id       INTEGER REFERENCES jobs(id),
    user_id      INTEGER REFERENCES users(id),
    full_name    TEXT NOT NULL,
    email        TEXT,
    phone        TEXT,
    resume_url   TEXT,
    stage        TEXT DEFAULT 'applied',
    notes        TEXT,
    applied_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS activity_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER REFERENCES companies(id),
    user_id     INTEGER REFERENCES users(id),
    action      TEXT NOT NULL,
    entity_type TEXT,
    entity_id   INTEGER,
    detail      TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
"""

SEED_SQL = """
INSERT OR IGNORE INTO companies (id, name, industry, location, website, founded, employees, logo_emoji, verified)
VALUES (1, 'NovaTech Solutions', 'Technology & SaaS', 'San Francisco, CA', 'novatech.io', 2015, 1200, '⚡', 1);

INSERT OR IGNORE INTO users (id, company_id, email, password_hash, full_name, title, user_type, role, years_exp, avatar_emoji)
VALUES
  (1, 1, 'sarah@novatech.io',
   '5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8',
   'Sarah Johnson', 'Head of Talent Acquisition', 'recruiter', 'admin', 3, '👩\u200d💼'),
  (2, NULL, 'alex@jobseeker.com',
   '5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8',
   'Alex Rivera', 'Full Stack Developer', 'job_seeker', 'job_seeker', 4, '🧑\u200d💻');

INSERT OR IGNORE INTO job_seeker_profiles (id, user_id, headline, bio, skills, location, experience_years, open_to_work)
VALUES (1, 2,
  'Full Stack Developer · React & Node.js',
  'Passionate developer with 4 years building scalable web applications.',
  'React,Node.js,TypeScript,PostgreSQL,AWS,Docker',
  'New York, NY', 4, 1);

INSERT OR IGNORE INTO jobs (id, company_id, created_by, title, department, location, job_type, salary_min, salary_max, description, requirements, status)
VALUES
(1,1,1,'Staff ML Engineer','AI / Engineering','San Francisco, CA','Full-time',180000,240000,'Lead ML infrastructure and model deployment.','5+ yrs ML, Python, PyTorch','open'),
(2,1,1,'VP of Marketing','Marketing','Remote','Full-time',200000,280000,'Own the full marketing function.','8+ yrs B2B SaaS marketing','open'),
(3,1,1,'iOS Developer','Mobile Engineering','San Francisco, CA','Full-time',140000,180000,'Build native iOS features.','3+ yrs Swift, SwiftUI','open'),
(4,1,1,'UX Researcher','Design','Hybrid','Full-time',110000,145000,'Mixed-methods research at scale.','3+ yrs UX research','open'),
(5,1,1,'Finance Analyst','Finance','San Francisco, CA','Full-time',90000,120000,'FP&A and reporting.','2+ yrs finance','paused');

INSERT OR IGNORE INTO candidates (id, company_id, job_id, user_id, full_name, email, stage, applied_at)
VALUES
(1,1,3,NULL,'Marcus Chen','marcus.chen@email.com','hired',datetime('now','-8 days')),
(2,1,4,NULL,'Priya Sharma','priya.sharma@email.com','hired',datetime('now','-12 days')),
(3,1,1,NULL,'James Okafor','james.okafor@email.com','offer',datetime('now','-15 days')),
(4,1,1,NULL,'Yuki Tanaka','yuki.tanaka@email.com','interview',datetime('now','-18 days')),
(5,1,1,NULL,'Arun Patel','arun.patel@email.com','hired',datetime('now','-23 days')),
(6,1,2,NULL,'Linda Torres','linda.torres@email.com','applied',datetime('now','-2 days')),
(7,1,2,NULL,'David Kim','david.kim@email.com','applied',datetime('now','-3 days')),
(8,1,1,NULL,'Fatima Al-Hassan','fatima@email.com','screening',datetime('now','-5 days')),
(9,1,3,NULL,'Ryan O''Brien','ryan@email.com','applied',datetime('now','-1 days')),
(10,1,4,2,'Alex Rivera','alex@jobseeker.com','interview',datetime('now','-7 days'));

INSERT OR IGNORE INTO activity_log (id, company_id, user_id, action, entity_type, entity_id, detail, created_at)
VALUES
(1,1,1,'accepted_offer','candidate',1,'Marcus Chen accepted offer for Frontend Engineer',datetime('now','-2 hours')),
(2,1,1,'new_applications','job',1,'3 new applications received for Staff ML Engineer',datetime('now','-4 hours')),
(3,1,1,'interview_scheduled','candidate',4,'Interview scheduled with Yuki Tanaka — Feb 19, 10am',datetime('now','-1 day')),
(4,1,1,'offer_sent','candidate',3,'Offer letter sent to James Okafor for DevOps role',datetime('now','-1 day')),
(5,1,1,'job_posted','job',2,'VP of Marketing listing went live — 21 views so far',datetime('now','-6 days')),
(6,1,1,'background_check','candidate',2,'Priya Sharma completed background check',datetime('now','-7 days'));
"""

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.executescript(SEED_SQL)
    conn.commit()
    conn.close()
    print(f"[DB] Initialized at {DB_PATH}")

def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

def _unb64(s):
    pad = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + '=' * pad)

def create_token(user_id, company_id, user_type):
    header  = _b64(json.dumps({"alg":"HS256","typ":"JWT"}).encode())
    payload = _b64(json.dumps({"uid": user_id, "cid": company_id, "utype": user_type, "exp": int(time.time()) + TOKEN_TTL}).encode())
    sig = _b64(hmac.new(SECRET_KEY.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"

def verify_token(token):
    try:
        header, payload, sig = token.split('.')
        expected = _b64(hmac.new(SECRET_KEY.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(_unb64(payload))
        if data['exp'] < time.time():
            return None
        return data
    except:
        return None

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def get_auth_user(handler):
    auth = handler.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    return verify_token(auth[7:])

def time_ago(dt_str):
    try:
        dt   = datetime.fromisoformat(dt_str)
        diff = datetime.utcnow() - dt
        if diff.total_seconds() < 3600: return f"{int(diff.total_seconds()//60)} min ago"
        if diff.days == 0:              return f"{int(diff.total_seconds()//3600)} hours ago"
        if diff.days == 1:              return "Yesterday"
        return dt.strftime('%b %d')
    except:
        return dt_str

def fmt_sal(mn, mx):
    if mn and mx: return f"${mn//1000}k–${mx//1000}k"
    return None

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {fmt % args}")

    def send_json(self, data, status=200):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
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
        except: return {}

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
        }
        fn = routes.get((method, path))
        if fn: fn(qs)
        else:  self.send_error_json('Not found', 404)

    def do_GET(self):    self.dispatch('GET')
    def do_POST(self):   self.dispatch('POST')
    def do_PUT(self):    self.dispatch('PUT')
    def do_DELETE(self): self.dispatch('DELETE')

    # ── AUTH ──────────────────────────────────────────────────────────────
    def route_login(self, qs):
        body      = self.read_body()
        email     = body.get('email','').strip().lower()
        pw        = body.get('password','')
        user_type = body.get('user_type','recruiter')
        if not email or not pw:
            return self.send_error_json('Email and password required')
        conn = get_db()
        row  = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
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
        body      = self.read_body()
        email     = body.get('email','').strip().lower()
        pw        = body.get('password','')
        name      = body.get('full_name','').strip()
        user_type = body.get('user_type','recruiter')
        if not email or not pw or not name:
            return self.send_error_json('Name, email and password are required')
        if len(pw) < 6:
            return self.send_error_json('Password must be at least 6 characters')
        conn = get_db()
        try:
            if user_type == 'recruiter':
                role   = 'admin'
                title  = body.get('title', 'Recruiter')
                avatar = '\U0001f469\u200d\U0001f4bc'

                # Option A: join existing company by ID
                existing_cid = body.get('company_id')
                # Option B: create a brand-new company
                company_name = (body.get('company_name') or '').strip()

                if existing_cid:
                    row = conn.execute("SELECT id FROM companies WHERE id=?", (existing_cid,)).fetchone()
                    if not row:
                        conn.close()
                        return self.send_error_json('Selected company not found', 404)
                    cid = existing_cid
                elif company_name:
                    conn.execute(
                        """INSERT INTO companies (name,industry,location,website,founded,employees,logo_emoji,verified)
                           VALUES (?,?,?,?,?,?,?,0)""",
                        (company_name,
                         body.get('company_industry',''),
                         body.get('company_location',''),
                         body.get('company_website',''),
                         body.get('company_founded') or None,
                         body.get('company_employees') or None,
                         body.get('company_logo','\U0001f3e2'))
                    )
                    conn.commit()
                    cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                else:
                    conn.close()
                    return self.send_error_json('Please enter your company name to create an account', 400)
            else:
                cid, role, title, avatar = None, 'job_seeker', body.get('title',''), '\U0001f9d1\u200d\U0001f4bb'

            conn.execute(
                "INSERT INTO users (company_id,email,password_hash,full_name,title,user_type,role,avatar_emoji) VALUES (?,?,?,?,?,?,?,?)",
                (cid, email, hash_pw(pw), name, title, user_type, role, avatar)
            )
            conn.commit()
            uid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            if user_type == 'job_seeker':
                conn.execute("INSERT OR IGNORE INTO job_seeker_profiles (user_id,location) VALUES (?,?)",
                             (uid, body.get('location','')))
                conn.commit()

            token = create_token(uid, cid, user_type)
            self.send_json({
                'access_token': token,
                'user_type': user_type,
                'company_id': cid,
                'message': 'Registered successfully'
            }, 201)
        except sqlite3.IntegrityError:
            self.send_error_json('An account with this email already exists', 409)
        finally:
            conn.close()

    def route_companies_list(self, qs):
        """Public endpoint — list all companies so recruiters can search & join one."""
        conn = get_db()
        search = ''
        # parse raw query string since qs may be empty
        from urllib.parse import urlparse, parse_qs as _pqs
        raw_qs = _pqs(urlparse(self.path).query)
        search = raw_qs.get('q',[''])[0].lower()
        if search:
            rows = conn.execute(
                "SELECT id,name,industry,location,website,employees,logo_emoji,verified FROM companies WHERE LOWER(name) LIKE ? ORDER BY name",
                (f'%{search}%',)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id,name,industry,location,website,employees,logo_emoji,verified FROM companies ORDER BY name"
            ).fetchall()
        conn.close()
        self.send_json([dict(r) for r in rows])
    # ── RECRUITER DASHBOARD ───────────────────────────────────────────────
    def route_dashboard(self, qs):
        claims = get_auth_user(self)
        if not claims: return self.send_error_json('Unauthorized', 401)
        if claims.get('utype') != 'recruiter': return self.send_error_json('Recruiter access required', 403)
        cid, uid = claims['cid'], claims['uid']
        conn = get_db()
        company = conn.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
        user    = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        total_hired = conn.execute("SELECT COUNT(*) FROM candidates WHERE company_id=? AND stage='hired'", (cid,)).fetchone()[0]
        open_roles  = conn.execute("SELECT COUNT(*) FROM jobs WHERE company_id=? AND status='open'", (cid,)).fetchone()[0]
        avg_row     = conn.execute("SELECT AVG(julianday(updated_at)-julianday(applied_at)) FROM candidates WHERE company_id=? AND stage='hired'", (cid,)).fetchone()[0]
        recent  = conn.execute("SELECT c.full_name,c.stage,c.updated_at,j.title AS job_title FROM candidates c LEFT JOIN jobs j ON c.job_id=j.id WHERE c.company_id=? AND c.stage IN ('hired','offer','interview','screening') ORDER BY c.updated_at DESC LIMIT 5", (cid,)).fetchall()
        jobs    = conn.execute("SELECT j.*,COUNT(c.id) as applicants FROM jobs j LEFT JOIN candidates c ON c.job_id=j.id WHERE j.company_id=? AND j.status IN ('open','paused') GROUP BY j.id ORDER BY j.created_at DESC", (cid,)).fetchall()
        activity= conn.execute("SELECT * FROM activity_log WHERE company_id=? ORDER BY created_at DESC LIMIT 6", (cid,)).fetchall()
        conn.close()
        self.send_json({
            'company': {'id':company['id'],'name':company['name'],'industry':company['industry'],'location':company['location'],'website':company['website'],'founded':company['founded'],'employees':company['employees'],'logo_emoji':company['logo_emoji'],'verified':bool(company['verified'])},
            'recruiter': {'name':user['full_name'],'title':user['title'],'role':user['role'],'years_exp':user['years_exp'],'avatar_emoji':user['avatar_emoji']},
            'stats': {'total_hired':total_hired,'open_roles':open_roles,'avg_days_to_hire':round(avg_row or 0)},
            'recent_candidates': [{'name':r['full_name'],'stage':r['stage'],'job_title':r['job_title'],'date':time_ago(r['updated_at'])} for r in recent],
            'jobs': [{'id':j['id'],'title':j['title'],'department':j['department'],'status':j['status'],'applicants':j['applicants'],'location':j['location'],'job_type':j['job_type'],'salary_min':j['salary_min'],'salary_max':j['salary_max']} for j in jobs],
            'activity': [{'action':a['action'],'detail':a['detail'],'time':time_ago(a['created_at'])} for a in activity]
        })

    # ── JOBS ────────────────────────────────────────────────────────────
    def route_jobs_list(self, qs):
        claims = get_auth_user(self)
        if not claims: return self.send_error_json('Unauthorized', 401)
        conn = get_db()
        if claims.get('utype') == 'recruiter':
            jobs = conn.execute("SELECT j.*,COUNT(c.id) as applicants,co.name as company_name FROM jobs j LEFT JOIN candidates c ON c.job_id=j.id LEFT JOIN companies co ON j.company_id=co.id WHERE j.company_id=? GROUP BY j.id ORDER BY j.created_at DESC", (claims['cid'],)).fetchall()
        else:
            search = qs.get('q',[''])[0].lower()
            if search:
                jobs = conn.execute("SELECT j.*,0 as applicants,co.name as company_name FROM jobs j JOIN companies co ON j.company_id=co.id WHERE j.status='open' AND (LOWER(j.title) LIKE ? OR LOWER(co.name) LIKE ? OR LOWER(j.location) LIKE ?) ORDER BY j.created_at DESC", (f'%{search}%',f'%{search}%',f'%{search}%')).fetchall()
            else:
                jobs = conn.execute("SELECT j.*,0 as applicants,co.name as company_name FROM jobs j JOIN companies co ON j.company_id=co.id WHERE j.status='open' ORDER BY j.created_at DESC").fetchall()
        conn.close()
        self.send_json([dict(j) for j in jobs])

    def route_jobs_create(self, qs):
        claims = get_auth_user(self)
        if not claims or claims.get('utype') != 'recruiter': return self.send_error_json('Recruiter access required', 403)
        body = self.read_body()
        if not body.get('title'): return self.send_error_json('Job title is required')
        conn = get_db()
        conn.execute("INSERT INTO jobs (company_id,created_by,title,department,location,job_type,salary_min,salary_max,description,requirements,status) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (claims['cid'],claims['uid'],body.get('title'),body.get('department',''),body.get('location',''),body.get('job_type','Full-time'),body.get('salary_min'),body.get('salary_max'),body.get('description',''),body.get('requirements',''),'open'))
        jid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO activity_log (company_id,user_id,action,entity_type,entity_id,detail) VALUES (?,?,'job_posted','job',?,?)", (claims['cid'],claims['uid'],jid,f"New job posted: {body.get('title')}"))
        conn.commit(); conn.close()
        self.send_json({'id':jid,'message':'Job created'}, 201)

    def route_jobs_update(self, qs):
        claims = get_auth_user(self)
        if not claims or claims.get('utype') != 'recruiter': return self.send_error_json('Recruiter access required', 403)
        body = self.read_body()
        jid  = body.get('id')
        if not jid: return self.send_error_json('Missing job id')
        conn = get_db()
        conn.execute("UPDATE jobs SET title=COALESCE(?,title),department=COALESCE(?,department),location=COALESCE(?,location),status=COALESCE(?,status),salary_min=COALESCE(?,salary_min),salary_max=COALESCE(?,salary_max),description=COALESCE(?,description),requirements=COALESCE(?,requirements),updated_at=datetime('now') WHERE id=? AND company_id=?", (body.get('title'),body.get('department'),body.get('location'),body.get('status'),body.get('salary_min'),body.get('salary_max'),body.get('description'),body.get('requirements'),jid,claims['cid']))
        conn.commit(); conn.close()
        self.send_json({'message':'Updated'})

    def route_jobs_delete(self, qs):
        claims = get_auth_user(self)
        if not claims or claims.get('utype') != 'recruiter': return self.send_error_json('Recruiter access required', 403)
        jid = qs.get('id',[None])[0]
        if not jid: return self.send_error_json('Missing id')
        conn = get_db()
        conn.execute("UPDATE jobs SET status='closed' WHERE id=? AND company_id=?", (jid,claims['cid']))
        conn.commit(); conn.close()
        self.send_json({'message':'Job closed'})

    # ── CANDIDATES ──────────────────────────────────────────────────────
    def route_candidates_list(self, qs):
        claims = get_auth_user(self)
        if not claims or claims.get('utype') != 'recruiter': return self.send_error_json('Recruiter access required', 403)
        job_id = qs.get('job_id',[None])[0]
        conn   = get_db()
        if job_id:
            rows = conn.execute("SELECT c.*,j.title as job_title FROM candidates c LEFT JOIN jobs j ON c.job_id=j.id WHERE c.company_id=? AND c.job_id=? ORDER BY c.applied_at DESC", (claims['cid'],job_id)).fetchall()
        else:
            rows = conn.execute("SELECT c.*,j.title as job_title FROM candidates c LEFT JOIN jobs j ON c.job_id=j.id WHERE c.company_id=? ORDER BY c.applied_at DESC", (claims['cid'],)).fetchall()
        conn.close()
        self.send_json([dict(r) for r in rows])

    def route_candidates_create(self, qs):
        claims = get_auth_user(self)
        if not claims or claims.get('utype') != 'recruiter': return self.send_error_json('Recruiter access required', 403)
        body = self.read_body()
        if not body.get('full_name') or not body.get('job_id'): return self.send_error_json('full_name and job_id required')
        conn = get_db()
        conn.execute("INSERT INTO candidates (company_id,job_id,full_name,email,phone,notes,stage) VALUES (?,?,?,?,?,?,'applied')", (claims['cid'],body['job_id'],body['full_name'],body.get('email',''),body.get('phone',''),body.get('notes','')))
        cid2 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO activity_log (company_id,user_id,action,entity_type,entity_id,detail) VALUES (?,?,'new_application','candidate',?,?)", (claims['cid'],claims['uid'],cid2,f"{body['full_name']} applied"))
        conn.commit(); conn.close()
        self.send_json({'id':cid2,'message':'Candidate added'}, 201)

    def route_candidates_update(self, qs):
        claims = get_auth_user(self)
        if not claims or claims.get('utype') != 'recruiter': return self.send_error_json('Recruiter access required', 403)
        body  = self.read_body()
        cid2  = body.get('id')
        if not cid2: return self.send_error_json('Missing candidate id')
        conn  = get_db()
        conn.execute("UPDATE candidates SET stage=COALESCE(?,stage),notes=COALESCE(?,notes),updated_at=datetime('now') WHERE id=? AND company_id=?", (body.get('stage'),body.get('notes'),cid2,claims['cid']))
        if body.get('stage'):
            nr = conn.execute("SELECT full_name FROM candidates WHERE id=?", (cid2,)).fetchone()
            nm = nr['full_name'] if nr else 'Candidate'
            conn.execute("INSERT INTO activity_log (company_id,user_id,action,entity_type,entity_id,detail) VALUES (?,?,'stage_changed','candidate',?,?)", (claims['cid'],claims['uid'],cid2,f"{nm} moved to {body['stage']}"))
        conn.commit(); conn.close()
        self.send_json({'message':'Updated'})

    # ── ACTIVITY ────────────────────────────────────────────────────────
    def route_activity(self, qs):
        claims = get_auth_user(self)
        if not claims: return self.send_error_json('Unauthorized', 401)
        conn = get_db()
        rows = conn.execute("SELECT * FROM activity_log WHERE company_id=? ORDER BY created_at DESC LIMIT 20", (claims['cid'],)).fetchall()
        conn.close()
        self.send_json([{'action':r['action'],'detail':r['detail'],'time':time_ago(r['created_at'])} for r in rows])

    # ── HIRING TREND ─────────────────────────────────────────────────────
    def route_hiring_trend(self, qs):
        claims = get_auth_user(self)
        if not claims: return self.send_error_json('Unauthorized', 401)
        period = qs.get('period',['1Y'])[0]
        months = {'6M':6,'1Y':12,'2Y':24}.get(period,12)
        conn   = get_db()
        rows   = conn.execute("SELECT strftime('%Y-%m',updated_at) as month,COUNT(*) as count FROM candidates WHERE company_id=? AND stage='hired' AND updated_at>=datetime('now',? || ' months') GROUP BY month ORDER BY month ASC", (claims['cid'],f'-{months}')).fetchall()
        conn.close()
        result = {r['month']:r['count'] for r in rows}
        labels, data = [], []
        now = datetime.utcnow()
        for i in range(months-1,-1,-1):
            d = now.replace(day=1) - timedelta(days=i*28)
            labels.append(d.strftime('%b' if months<=12 else "%b '%y"))
            data.append(result.get(d.strftime('%Y-%m'),0))
        self.send_json({'labels':labels,'data':data})

    # ── EXPORT ──────────────────────────────────────────────────────────
    def route_export(self, qs):
        claims = get_auth_user(self)
        if not claims or claims.get('utype') != 'recruiter': return self.send_error_json('Recruiter access required', 403)
        cid  = claims['cid']
        conn = get_db()
        company = conn.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
        jobs    = conn.execute("SELECT j.*,COUNT(c.id) as applicants FROM jobs j LEFT JOIN candidates c ON c.job_id=j.id WHERE j.company_id=? GROUP BY j.id", (cid,)).fetchall()
        cands   = conn.execute("SELECT c.*,j.title as job_title FROM candidates c LEFT JOIN jobs j ON c.job_id=j.id WHERE c.company_id=? ORDER BY c.applied_at DESC", (cid,)).fetchall()
        stats   = {'total_hired':conn.execute("SELECT COUNT(*) FROM candidates WHERE company_id=? AND stage='hired'",(cid,)).fetchone()[0],'open_roles':conn.execute("SELECT COUNT(*) FROM jobs WHERE company_id=? AND status='open'",(cid,)).fetchone()[0]}
        conn.close()
        out = io.StringIO()
        w   = csv.writer(out)
        w.writerow(['=== TALENTBRIDGE HIRING REPORT ==='])
        w.writerow([f'Company: {company["name"]}',f'Generated: {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}'])
        w.writerow([])
        w.writerow(['SUMMARY']); w.writerow(['Total Hired',stats['total_hired']]); w.writerow(['Open Roles',stats['open_roles']]); w.writerow([])
        w.writerow(['OPEN POSITIONS']); w.writerow(['Title','Department','Location','Status','Applicants','Salary Range'])
        for j in jobs:
            sal = f"${j['salary_min']:,}–${j['salary_max']:,}" if j['salary_min'] else 'N/A'
            w.writerow([j['title'],j['department'],j['location'],j['status'],j['applicants'],sal])
        w.writerow([]); w.writerow(['ALL CANDIDATES']); w.writerow(['Name','Email','Job','Stage','Applied'])
        for c in cands:
            w.writerow([c['full_name'],c['email'],c['job_title'],c['stage'],c['applied_at'][:10]])
        csv_bytes = out.getvalue().encode('utf-8-sig')
        filename  = f"talentbridge_report_{datetime.utcnow().strftime('%Y%m%d')}.csv"
        self.send_response(200)
        self.send_header('Content-Type','text/csv; charset=utf-8')
        self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        self.send_header('Content-Length',len(csv_bytes))
        self._cors(); self.end_headers(); self.wfile.write(csv_bytes)

    # ── COMPANY ──────────────────────────────────────────────────────────
    def route_company_get(self, qs):
        claims = get_auth_user(self)
        if not claims: return self.send_error_json('Unauthorized', 401)
        conn = get_db()
        c = conn.execute("SELECT * FROM companies WHERE id=?", (claims['cid'],)).fetchone()
        conn.close()
        self.send_json(dict(c) if c else {})

    def route_company_update(self, qs):
        claims = get_auth_user(self)
        if not claims or claims.get('utype') != 'recruiter': return self.send_error_json('Recruiter access required', 403)
        body = self.read_body()
        conn = get_db()
        conn.execute("UPDATE companies SET name=COALESCE(?,name),industry=COALESCE(?,industry),location=COALESCE(?,location),website=COALESCE(?,website),employees=COALESCE(?,employees),founded=COALESCE(?,founded) WHERE id=?", (body.get('name'),body.get('industry'),body.get('location'),body.get('website'),body.get('employees'),body.get('founded'),claims['cid']))
        conn.commit(); conn.close()
        self.send_json({'message':'Company updated'})

    # ── JOB SEEKER ───────────────────────────────────────────────────────
    def route_seeker_dashboard(self, qs):
        claims = get_auth_user(self)
        if not claims: return self.send_error_json('Unauthorized', 401)
        if claims.get('utype') != 'job_seeker': return self.send_error_json('Job seeker access required', 403)
        uid  = claims['uid']
        conn = get_db()
        user    = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        profile = conn.execute("SELECT * FROM job_seeker_profiles WHERE user_id=?", (uid,)).fetchone()
        applications = conn.execute("SELECT c.*,j.title as job_title,j.location as job_location,j.job_type,j.salary_min,j.salary_max,co.name as company_name,co.logo_emoji FROM candidates c LEFT JOIN jobs j ON c.job_id=j.id LEFT JOIN companies co ON j.company_id=co.id WHERE c.user_id=? OR c.email=? ORDER BY c.applied_at DESC", (uid,user['email'] if user else '')).fetchall()
        open_jobs   = conn.execute("SELECT j.*,co.name as company_name,co.logo_emoji FROM jobs j JOIN companies co ON j.company_id=co.id WHERE j.status='open' ORDER BY j.created_at DESC LIMIT 10").fetchall()
        conn.close()
        applied_ids = [a['job_id'] for a in applications]
        self.send_json({
            'user':    {'name':user['full_name'],'email':user['email'],'title':user['title'],'avatar':user['avatar_emoji']} if user else {},
            'profile': dict(profile) if profile else {},
            'stats':   {'total_applications':len(applications),'in_progress':len([a for a in applications if a['stage'] not in ('hired','rejected')]),'interviews':len([a for a in applications if a['stage']=='interview']),'offers':len([a for a in applications if a['stage']=='offer'])},
            'applications': [{'id':a['id'],'job_title':a['job_title'],'company_name':a['company_name'],'company_logo':a['logo_emoji'],'stage':a['stage'],'applied_at':time_ago(a['applied_at']),'location':a['job_location'],'salary':fmt_sal(a['salary_min'],a['salary_max'])} for a in applications],
            'recommended_jobs': [{'id':j['id'],'title':j['title'],'company_name':j['company_name'],'company_logo':j['logo_emoji'],'location':j['location'],'job_type':j['job_type'],'salary':fmt_sal(j['salary_min'],j['salary_max']),'department':j['department'],'already_applied':j['id'] in applied_ids} for j in open_jobs]
        })

    def route_seeker_jobs(self, qs):
        claims = get_auth_user(self)
        if not claims: return self.send_error_json('Unauthorized', 401)
        search   = qs.get('q',[''])[0].lower()
        location = qs.get('location',[''])[0].lower()
        job_type = qs.get('type',[''])[0]
        conn     = get_db()
        query    = "SELECT j.*,co.name as company_name,co.logo_emoji,co.industry FROM jobs j JOIN companies co ON j.company_id=co.id WHERE j.status='open'"
        params   = []
        if search:   query += " AND (LOWER(j.title) LIKE ? OR LOWER(j.department) LIKE ? OR LOWER(co.name) LIKE ?)"; params += [f'%{search}%',f'%{search}%',f'%{search}%']
        if location: query += " AND LOWER(j.location) LIKE ?"; params.append(f'%{location}%')
        if job_type: query += " AND j.job_type=?"; params.append(job_type)
        query += " ORDER BY j.created_at DESC"
        jobs   = conn.execute(query,params).fetchall()
        conn.close()
        self.send_json([{'id':j['id'],'title':j['title'],'company_name':j['company_name'],'company_logo':j['logo_emoji'],'industry':j['industry'],'location':j['location'],'job_type':j['job_type'],'department':j['department'],'salary':fmt_sal(j['salary_min'],j['salary_max']),'description':j['description'],'requirements':j['requirements'],'created_at':time_ago(j['created_at'])} for j in jobs])

    def route_seeker_apply(self, qs):
        claims = get_auth_user(self)
        if not claims: return self.send_error_json('Unauthorized', 401)
        if claims.get('utype') != 'job_seeker': return self.send_error_json('Job seeker access required', 403)
        body   = self.read_body()
        job_id = body.get('job_id')
        if not job_id: return self.send_error_json('job_id required')
        uid  = claims['uid']
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not user: conn.close(); return self.send_error_json('User not found', 404)
        existing = conn.execute("SELECT id FROM candidates WHERE job_id=? AND (user_id=? OR email=?)", (job_id,uid,user['email'])).fetchone()
        if existing: conn.close(); return self.send_error_json('You have already applied for this job', 409)
        job = conn.execute("SELECT j.*,co.id as coid FROM jobs j JOIN companies co ON j.company_id=co.id WHERE j.id=?", (job_id,)).fetchone()
        if not job or job['status'] != 'open': conn.close(); return self.send_error_json('Job not found or no longer open', 404)
        conn.execute("INSERT INTO candidates (company_id,job_id,user_id,full_name,email,phone,notes,stage) VALUES (?,?,?,?,?,?,?,'applied')", (job['coid'],job_id,uid,user['full_name'],user['email'],body.get('phone',''),body.get('cover_note','')))
        app_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO activity_log (company_id,user_id,action,entity_type,entity_id,detail) VALUES (?,?,'new_application','candidate',?,?)", (job['coid'],uid,app_id,f"{user['full_name']} applied for {job['title']}"))
        conn.commit(); conn.close()
        self.send_json({'id':app_id,'message':'Application submitted successfully!'}, 201)

    def route_seeker_applications(self, qs):
        claims = get_auth_user(self)
        if not claims: return self.send_error_json('Unauthorized', 401)
        if claims.get('utype') != 'job_seeker': return self.send_error_json('Job seeker access required', 403)
        uid  = claims['uid']
        conn = get_db()
        user = conn.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone()
        rows = conn.execute("SELECT c.*,j.title as job_title,j.location as job_location,j.job_type,j.salary_min,j.salary_max,co.name as company_name,co.logo_emoji FROM candidates c LEFT JOIN jobs j ON c.job_id=j.id LEFT JOIN companies co ON j.company_id=co.id WHERE c.user_id=? OR c.email=? ORDER BY c.applied_at DESC", (uid,user['email'] if user else '')).fetchall()
        conn.close()
        self.send_json([{'id':r['id'],'job_title':r['job_title'],'company_name':r['company_name'],'company_logo':r['logo_emoji'],'stage':r['stage'],'applied_at':r['applied_at'],'location':r['job_location'],'job_type':r['job_type'],'salary':fmt_sal(r['salary_min'],r['salary_max'])} for r in rows])

    def route_seeker_profile(self, qs):
        claims = get_auth_user(self)
        if not claims: return self.send_error_json('Unauthorized', 401)
        conn = get_db()
        user    = conn.execute("SELECT * FROM users WHERE id=?", (claims['uid'],)).fetchone()
        profile = conn.execute("SELECT * FROM job_seeker_profiles WHERE user_id=?", (claims['uid'],)).fetchone()
        conn.close()
        self.send_json({'user':dict(user) if user else {},'profile':dict(profile) if profile else {}})

    def route_seeker_profile_update(self, qs):
        claims = get_auth_user(self)
        if not claims: return self.send_error_json('Unauthorized', 401)
        body = self.read_body()
        conn = get_db()
        if body.get('full_name') or body.get('title'):
            conn.execute("UPDATE users SET full_name=COALESCE(?,full_name),title=COALESCE(?,title) WHERE id=?", (body.get('full_name'),body.get('title'),claims['uid']))
        conn.execute("INSERT INTO job_seeker_profiles (user_id,headline,bio,skills,location,linkedin_url,github_url,portfolio_url,experience_years,open_to_work,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now')) ON CONFLICT(user_id) DO UPDATE SET headline=COALESCE(excluded.headline,headline),bio=COALESCE(excluded.bio,bio),skills=COALESCE(excluded.skills,skills),location=COALESCE(excluded.location,location),linkedin_url=COALESCE(excluded.linkedin_url,linkedin_url),github_url=COALESCE(excluded.github_url,github_url),portfolio_url=COALESCE(excluded.portfolio_url,portfolio_url),experience_years=COALESCE(excluded.experience_years,experience_years),open_to_work=COALESCE(excluded.open_to_work,open_to_work),updated_at=datetime('now')", (claims['uid'],body.get('headline'),body.get('bio'),body.get('skills'),body.get('location'),body.get('linkedin_url'),body.get('github_url'),body.get('portfolio_url'),body.get('experience_years'),body.get('open_to_work',1)))
        conn.commit(); conn.close()
        self.send_json({'message':'Profile updated'})

if __name__ == '__main__':
    init_db()
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
