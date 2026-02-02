"""Detection patterns for threat modeling.

This module contains pattern definitions for detecting:
- Frameworks (Next.js, Express, FastAPI, etc.)
- Authentication mechanisms
- Sensitive data fields
- Injection vulnerabilities
- Hardcoded secrets
- Data stores
"""

from typing import Any

# Framework detection patterns
FRAMEWORK_PATTERNS: dict[str, dict[str, Any]] = {
    "nextjs": {
        "indicators": [
            ("next.config.js", None),
            ("next.config.mjs", None),
            ("next.config.ts", None),
            ("app/layout.tsx", None),
            ("app/layout.jsx", None),
            ("pages/_app.tsx", None),
            ("pages/_app.jsx", None),
        ],
        "entry_patterns": {
            "api_routes_app": r"app/api/.*/route\.(ts|js)x?$",
            "api_routes_pages": r"pages/api/.*\.(ts|js)x?$",
            "server_actions": r"['\"]use server['\"]",
            "middleware": r"middleware\.(ts|js)x?$",
        }
    },
    "express": {
        "indicators": [
            (None, r"require\(['\"]express['\"]\)"),
            (None, r"from ['\"]express['\"]"),
            (None, r"express\(\)"),
        ],
        "entry_patterns": {
            "routes": r"app\.(get|post|put|delete|patch|all)\s*\(",
            "middleware": r"app\.use\s*\(",
            "router": r"router\.(get|post|put|delete|patch|all)\s*\(",
        }
    },
    "fastapi": {
        "indicators": [
            (None, r"from fastapi import"),
            (None, r"FastAPI\(\)"),
        ],
        "entry_patterns": {
            "routes": r"@(app|router)\.(get|post|put|delete|patch)\s*\(",
            "websocket": r"@(app|router)\.websocket\s*\(",
        }
    },
    "django": {
        "indicators": [
            ("manage.py", None),
            ("settings.py", r"INSTALLED_APPS"),
            (None, r"from django"),
        ],
        "entry_patterns": {
            "urls": r"path\s*\(|re_path\s*\(|url\s*\(",
            "views": r"def\s+\w+\s*\(\s*request",
        }
    },
    "flask": {
        "indicators": [
            (None, r"from flask import"),
            (None, r"Flask\(__name__\)"),
        ],
        "entry_patterns": {
            "routes": r"@app\.route\s*\(",
            "blueprint": r"@\w+\.route\s*\(",
        }
    },
    "react": {
        "indicators": [
            (None, r"from ['\"]react['\"]"),
            (None, r"import React"),
        ],
        "entry_patterns": {}
    },
    "vue": {
        "indicators": [
            ("nuxt.config.js", None),
            ("nuxt.config.ts", None),
            (None, r"from ['\"]vue['\"]"),
        ],
        "entry_patterns": {}
    },
}


# Authentication mechanism patterns
AUTH_PATTERNS: dict[str, dict[str, Any]] = {
    "nextauth": {
        "pattern": r"NextAuth|getServerSession|useSession|authOptions",
        "assets": ["session tokens", "OAuth credentials", "CSRF tokens"],
        "framework": "nextjs"
    },
    "clerk": {
        "pattern": r"@clerk/nextjs|ClerkProvider|useAuth|useUser|currentUser",
        "assets": ["JWT tokens", "user metadata", "session"],
        "framework": "nextjs"
    },
    "supabase_auth": {
        "pattern": r"createClient.*supabase|supabase\.auth|useSupabaseClient",
        "assets": ["Supabase session", "JWT tokens", "refresh tokens"],
        "framework": "any"
    },
    "passport": {
        "pattern": r"passport\.|PassportStrategy|passport\.authenticate",
        "assets": ["session", "OAuth tokens"],
        "framework": "express"
    },
    "jwt": {
        "pattern": r"jsonwebtoken|jwt\.sign|jwt\.verify|jose|@auth/core",
        "assets": ["JWT tokens", "signing keys"],
        "framework": "any"
    },
    "firebase_auth": {
        "pattern": r"firebase/auth|getAuth\(\)|signInWith|onAuthStateChanged",
        "assets": ["Firebase tokens", "user credentials"],
        "framework": "any"
    },
    "auth0": {
        "pattern": r"@auth0|Auth0Provider|useAuth0|auth0\.com",
        "assets": ["Auth0 tokens", "user profile"],
        "framework": "any"
    },
    "django_auth": {
        "pattern": r"@login_required|@permission_required|authenticate\(|login\(",
        "assets": ["session", "CSRF token"],
        "framework": "django"
    },
    "fastapi_security": {
        "pattern": r"OAuth2PasswordBearer|HTTPBearer|APIKeyHeader|Depends.*security",
        "assets": ["bearer tokens", "API keys"],
        "framework": "fastapi"
    },
}


# Sensitive data field patterns
SENSITIVE_DATA_PATTERNS: dict[str, dict[str, Any]] = {
    "pii": {
        "patterns": [
            r"(email|e_mail|user_email)",
            r"(phone|phone_number|mobile|telephone)",
            r"(ssn|social_security|social_security_number)",
            r"(date_of_birth|dob|birth_date|birthday)",
            r"(address|street_address|home_address|mailing_address)",
            r"(first_name|last_name|full_name|user_name)",
            r"(passport|passport_number)",
            r"(driver_license|drivers_license)",
            r"(national_id|id_number)",
        ],
        "requirements": ["encryption", "access logging", "retention policy", "GDPR compliance"]
    },
    "financial": {
        "patterns": [
            r"(credit_card|card_number|cc_number)",
            r"(cvv|cvc|security_code)",
            r"(bank_account|account_number|routing_number)",
            r"(payment|stripe|paypal).*(?:key|secret|token)",
            r"(billing|invoice).*(?:amount|total)",
        ],
        "requirements": ["PCI-DSS compliance", "tokenization", "audit trail", "encryption"]
    },
    "health": {
        "patterns": [
            r"(diagnosis|medical_record|health_record)",
            r"(prescription|medication|treatment)",
            r"(patient|health_)(?:id|data|info)",
            r"(insurance|hipaa)",
        ],
        "requirements": ["HIPAA compliance", "encryption", "access controls", "audit logging"]
    },
    "authentication": {
        "patterns": [
            r"(password|passwd|pwd)(?!.*hash)",
            r"(api_key|apikey|api_secret)",
            r"(secret_key|private_key|signing_key)",
            r"(token|auth_token|access_token|refresh_token)",
            r"(bearer|authorization).*(?:header|token)",
        ],
        "requirements": ["secure storage", "rotation policy", "never log", "encryption"]
    },
}


# Injection vulnerability patterns
INJECTION_PATTERNS: dict[str, dict[str, Any]] = {
    "sql_injection": {
        "patterns": [
            r"execute\s*\(.*\+",
            r"execute\s*\(.*\$\{",
            r"execute\s*\(.*%s.*%",
            r"query\s*\(.*\+",
            r"query\s*\(.*\$\{",
            r"\.raw\s*\(",
            r"cursor\.execute\s*\(.*f['\"]",
            r"cursor\.execute\s*\(.*%",
        ],
        "severity": "critical",
        "cwe": "CWE-89",
        "recommendation": "Use parameterized queries or ORM"
    },
    "command_injection": {
        "patterns": [
            r"exec\s*\(.*\+",
            r"exec\s*\(.*\$\{",
            r"spawn\s*\(.*\+",
            r"execSync\s*\(.*\+",
            r"child_process",
            r"subprocess\.(?:run|call|Popen)\s*\(.*shell\s*=\s*True",
            r"os\.system\s*\(",
            r"os\.popen\s*\(",
        ],
        "severity": "critical",
        "cwe": "CWE-78",
        "recommendation": "Avoid shell execution or use strict input validation"
    },
    "xss": {
        "patterns": [
            r"innerHTML\s*=",
            r"dangerouslySetInnerHTML",
            r"document\.write\s*\(",
            r"\|safe\b",
            r"mark_safe\s*\(",
            r"Markup\s*\(",
            r"v-html\s*=",
        ],
        "severity": "high",
        "cwe": "CWE-79",
        "recommendation": "Use framework's built-in escaping, avoid raw HTML rendering"
    },
    "path_traversal": {
        "patterns": [
            r"readFile\s*\(.*\+",
            r"readFileSync\s*\(.*\+",
            r"open\s*\(.*\+.*['\"]r",
            r"path\.join\s*\(.*req\.",
            r"fs\..*\(.*req\.",
        ],
        "severity": "high",
        "cwe": "CWE-22",
        "recommendation": "Validate and sanitize file paths, use allowlists"
    },
    "ssrf": {
        "patterns": [
            r"fetch\s*\(.*req\.",
            r"axios\s*\(.*req\.",
            r"http\.get\s*\(.*req\.",
            r"requests\.get\s*\(.*request\.",
            r"urllib\.request\.urlopen\s*\(",
        ],
        "severity": "high",
        "cwe": "CWE-918",
        "recommendation": "Validate URLs against allowlist, block internal IPs"
    },
    "code_injection": {
        "patterns": [
            r"eval\s*\(",
            r"Function\s*\(",
            r"vm\.runIn",
            r"new\s+Function\s*\(",
            r"exec\s*\(.*compile",
        ],
        "severity": "critical",
        "cwe": "CWE-94",
        "recommendation": "Avoid dynamic code evaluation entirely"
    },
}


# Secret detection patterns
SECRET_PATTERNS: dict[str, dict[str, Any]] = {
    "hardcoded_secret": {
        "pattern": r"(api[_-]?key|secret|password|token|credential)\s*[=:]\s*['\"][^'\"]{8,}['\"]",
        "severity": "critical",
        "recommendation": "Use environment variables or secret management"
    },
    "aws_key": {
        "pattern": r"AKIA[0-9A-Z]{16}",
        "severity": "critical",
        "recommendation": "Rotate AWS credentials immediately"
    },
    "private_key": {
        "pattern": r"-----BEGIN\s+(RSA|DSA|EC|OPENSSH)?\s*PRIVATE KEY-----",
        "severity": "critical",
        "recommendation": "Remove private keys from code, use secret management"
    },
    "jwt_secret": {
        "pattern": r"jwt[_-]?secret\s*[=:]\s*['\"][^'\"]+['\"]",
        "severity": "critical",
        "recommendation": "Store JWT secrets in environment variables"
    },
    "database_url": {
        "pattern": r"(postgres|mysql|mongodb)://[^'\"\s]+:[^@'\"\s]+@",
        "severity": "high",
        "recommendation": "Use environment variables for database credentials"
    },
}


# Data store detection patterns
DATASTORE_PATTERNS: dict[str, dict[str, Any]] = {
    "postgresql": {
        "patterns": [r"pg\.|postgres|psycopg|PrismaClient.*postgres", r"postgresql://"],
        "type": "database",
    },
    "mysql": {
        "patterns": [r"mysql\.|mysql2|pymysql", r"mysql://"],
        "type": "database",
    },
    "mongodb": {
        "patterns": [r"mongoose|MongoClient|mongodb\+srv://"],
        "type": "database",
    },
    "redis": {
        "patterns": [r"redis\.|ioredis|createClient.*redis"],
        "type": "cache",
    },
    "sqlite": {
        "patterns": [r"sqlite3|better-sqlite3|\.sqlite"],
        "type": "database",
    },
    "s3": {
        "patterns": [r"@aws-sdk/client-s3|s3\.putObject|s3\.getObject|boto3.*s3"],
        "type": "external_storage",
    },
    "prisma": {
        "patterns": [r"PrismaClient|@prisma/client"],
        "type": "database",
    },
    "drizzle": {
        "patterns": [r"drizzle-orm|drizzle\("],
        "type": "database",
    },
    "supabase": {
        "patterns": [r"@supabase/supabase-js|createClient.*supabase"],
        "type": "database",
    },
}


# Directories to skip during scanning
SKIP_DIRECTORIES = [
    'node_modules', '.git', 'venv', '__pycache__',
    '.next', 'dist', 'build', '.venv', 'env'
]


# File extensions to scan
SOURCE_EXTENSIONS = ('.ts', '.tsx', '.js', '.jsx', '.py', '.go')


__all__ = [
    "FRAMEWORK_PATTERNS",
    "AUTH_PATTERNS",
    "SENSITIVE_DATA_PATTERNS",
    "INJECTION_PATTERNS",
    "SECRET_PATTERNS",
    "DATASTORE_PATTERNS",
    "SKIP_DIRECTORIES",
    "SOURCE_EXTENSIONS",
]
