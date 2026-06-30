import os
import json
import re
import csv
import math
import time
import hmac
import hashlib
import secrets
import google_auth_oauthlib.flow
from flask import Flask, render_template, request, jsonify, redirect, session, Response, stream_with_context
from flask_cors import CORS
from groq import Groq
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Allow HTTP for local dev; Vercel uses HTTPS so this is harmless there
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

load_dotenv()

app = Flask(__name__, template_folder='../templates')
app.secret_key = os.getenv("FLASK_SECRET_KEY", "quantum-crew-super-secure-token-2026")

# Proper cookie settings for HTTPS (Vercel) while keeping local HTTP working
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True

CORS(app, supports_credentials=True)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Google OAuth Configuration Matrix
CLIENT_CONFIG = {
    "web": {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [
            os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:4245/callback"),
            "http://localhost:4245/callback",
            "http://127.0.0.1:4245/callback",
        ]
    }
}
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

# ── Persistence helpers ───────────────────────────────────────────────────────
_DATA_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'ext_emails.json')

def _load_persisted():
    global EXT_EMAILS, REPORTED_SOC_IDS, TOTAL_AUDITED, SEEN_GMAIL_IDS
    needs_save = False
    try:
        with open(_DATA_FILE, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        EXT_EMAILS       = saved.get('ext_emails', {})
        REPORTED_SOC_IDS = set(saved.get('reported_soc_ids', []))
        SEEN_GMAIL_IDS   = set(saved.get('seen_gmail_ids', []))
        if 'total_audited' in saved:
            TOTAL_AUDITED = saved['total_audited']
        else:
            TOTAL_AUDITED = len(EXT_EMAILS) + len(SEEN_GMAIL_IDS)
            needs_save = True
    except (FileNotFoundError, json.JSONDecodeError):
        needs_save = True
    if needs_save:
        _save_persisted()

def _save_persisted():
    try:
        with open(_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                'ext_emails':      EXT_EMAILS,
                'reported_soc_ids': list(REPORTED_SOC_IDS),
                'seen_gmail_ids':  list(SEEN_GMAIL_IDS),
                'total_audited':   TOTAL_AUDITED,
            }, f)
    except Exception as e:
        print(f"[PERSIST] Save failed: {e}")

# Global tracking framework for reported cases (persisted runtime fallback)
REPORTED_SOC_IDS = set()

# Emails analyzed via the browser extension / agent (keyed by generated ID)
EXT_EMAILS = {}

# Every Gmail message ID ever fetched — so Gmail emails count toward TOTAL_AUDITED
SEEN_GMAIL_IDS: set = set()

# Monotonically increasing count of every email ever seen — never decreases
TOTAL_AUDITED = 0

_load_persisted()

# ── Dataset-informed keyword lists ────────────────────────────────────────────
# Expanded using patterns from:
#   • Phish No More dataset (Enron, CEAS, Nazario, SpamAssassin) — naserabdullahalam/phishing-email-dataset
#   • Phishing Email Data by Type — charlottehall/phishing-email-data-by-type
#   • 190K+ Spam/Ham Email Dataset — meruvulikith/190k-spam-ham-email-dataset-for-classification
#   • Fraud Email Dataset — llabhishekll/fraud-email-dataset

SCAM_KEYWORDS = [
    # Financial coercion (Phish No More / Fraud Email Dataset)
    "paypal", "bank", "wire", "transfer", "western union", "moneygram",
    "bitcoin", "crypto", "wallet", "iban", "routing number", "account number",
    "swift code", "wire funds", "send money",
    # Credential harvesting (Phishing by Type dataset)
    "verify", "confirm", "login", "credentials", "password", "username",
    "authentication", "2fa", "otp", "one-time", "pin", "sign in", "log in",
    "validate", "reactivate", "unlock account",
    # Urgency triggers (SpamAssassin / CEAS datasets)
    "urgent", "immediately", "expire", "suspended", "locked", "disabled",
    "unauthorized", "unusual activity", "action required", "limited time",
    "your account", "act now", "final notice", "last chance", "within 24 hours",
    "within 48 hours", "will be terminated", "access revoked",
    # Prize & lottery scams (Nazario / Nigerian Letter datasets)
    "winner", "prize", "lottery", "jackpot", "reward", "gift card",
    "voucher", "claim your", "you have been selected", "congratulations you",
    "inheritance", "beneficiary", "next of kin", "million dollars",
    # Legal / authority impersonation (Fraud Email Dataset)
    "arrest", "lawsuit", "legal action", "irs", "warrant", "social security",
    "federal", "investigation", "penalty", "fine", "enforcement",
    # Social engineering openers (Enron phishing corpus)
    "dear customer", "dear user", "dear account holder", "dear valued",
    "hello dear", "attention required", "security alert", "verify your identity",
]

SPAM_KEYWORDS = [
    # Promotional bulk mail (190K Spam/Ham dataset)
    "buy", "discount", "free", "sale", "deals", "offer", "promo", "coupon",
    "savings", "percent off", "% off", "bargain", "clearance", "lowest price",
    "best price", "unbeatable", "compare prices", "price drop",
    # Marketing / opt-out language (190K Spam dataset)
    "subscribe", "unsubscribe", "opt-out", "newsletter", "marketing",
    "advertisement", "sponsored", "mailing list", "email list",
    # Clickbait CTA patterns (SpamAssassin corpus)
    "click here", "click now", "act now", "order now", "shop now",
    "while supplies last", "don't miss out", "limited offer", "exclusive deal",
    "special offer", "one time offer", "today only",
    # Health / pharma spam (SpamAssassin corpus)
    "viagra", "cialis", "weight loss", "miracle", "cure", "no prescription",
    "diet pill", "slim down", "fat burner",
    # Financial spam (190K dataset)
    "refinance", "mortgage", "loan", "debt relief", "consolidate",
    "credit score", "no credit check", "pre-approved", "instant approval",
    # Gambling / adult (SpamAssassin corpus)
    "casino", "poker", "jackpot slot", "sports bet", "free spin",
]

DANGEROUS_URL_KEYWORDS = [
    # Authentication harvesting paths (Malicious URLs dataset — sid321axn)
    "verify", "login", "signin", "sign-in", "secure", "auth", "authenticate",
    "account", "validate", "confirm", "webmail", "weblogin",
    # Financial phishing paths (Phishing URLs with Extracted Features — victusadi)
    "paypal", "bank", "wallet", "payment", "billing", "invoice",
    "checkout", "purchase", "transaction", "wire",
    # Action trigger paths (Malicious URL Detection Enhanced 2026 — moutasmtamimi)
    "update", "reset", "claim", "unlock", "restore", "activate",
    "suspend", "reactivate", "renew", "click", "redirect",
    # Generic phishing scaffolding
    "portal", "support", "help", "alert", "notice", "bonus",
    "credentials", "verification", "security-update", "id-confirm",
]

# Suspicious TLDs sourced from Malicious URL Detection Dataset (Enhanced 2026)
SUSPICIOUS_TLDS = {
    ".xyz", ".top", ".tk", ".ml", ".ga", ".cf", ".gq", ".pw",
    ".click", ".link", ".work", ".party", ".date", ".faith",
    ".stream", ".download", ".accountant", ".loan", ".men",
}

# URL shortener domains sourced from Malicious URLs dataset (sid321axn)
URL_SHORTENERS = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "tiny.cc",
    "is.gd", "buff.ly", "adf.ly", "short.io", "rebrand.ly", "cutt.ly",
}

# ── Dataset-informed brand list ────────────────────────────────────────────────
# Expanded using brand impersonation patterns from:
#   • Fraud Email Dataset — llabhishekll/fraud-email-dataset
#   • Phishing & Benign Email Dataset — cyberprince/phishing-and-benign-email-dataset-short-version
MONITORED_BRANDS = [
    # Original brands
    "paypal", "meta", "google", "netflix", "amazon", "apple", "security",
    # Financial institutions (Fraud Email Dataset)
    "chase", "wellsfargo", "citibank", "bankofamerica", "barclays",
    "hsbc", "americanexpress", "amex", "capitalone",
    # Big Tech (Phishing by Type dataset)
    "microsoft", "outlook", "office365", "onedrive", "azure",
    "dropbox", "adobe", "zoom", "docusign",
    # Social / Messaging
    "facebook", "instagram", "twitter", "linkedin", "whatsapp",
    "discord", "telegram", "snapchat",
    # E-commerce / Delivery
    "ebay", "walmart", "fedex", "dhl", "ups", "usps",
    # Entertainment / Subscriptions
    "spotify", "hulu", "disney", "youtube",
    # Crypto / Finance platforms
    "coinbase", "binance", "kraken", "venmo", "cashapp", "zelle",
    # Government impersonation (Fraud Email Dataset)
    "irs", "socialsecurity", "dmv", "medicare",
    # Gaming
    "steam", "playstation", "xbox", "blizzard",
]

# Domains whose emails should not be flagged as threats (unless spoofing is detected)
TRUSTED_DOMAINS = {
    "google.com", "accounts.google.com", "googlemail.com", "mail.google.com",
    "yahoo.com", "ymail.com",
    "github.com",
    "apple.com", "icloud.com",
    "microsoft.com", "outlook.com", "hotmail.com", "live.com",
    "amazon.com", "aws.amazon.com",
    "linkedin.com",
    "twitter.com", "x.com",
    "instagram.com", "facebook.com",
    "spotify.com", "netflix.com",
    "dropbox.com", "zoom.us",
    "slack.com", "notion.so",
    "stripe.com", "cloudflare.com",
    "paypal.com",
}

# ── URL Intelligence (dataset-backed blacklist / whitelist) ───────────────────
_URL_INTEL_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'url_datasets', 'url_intelligence.json')
URL_BLACKLIST_DOMAINS: set = set()
URL_BLACKLIST_URLS: set = set()
URL_SAFELIST_DOMAINS: set = set()

def _load_url_intelligence():
    global URL_BLACKLIST_DOMAINS, URL_BLACKLIST_URLS, URL_SAFELIST_DOMAINS
    try:
        with open(_URL_INTEL_FILE, 'r', encoding='utf-8') as f:
            intel = json.load(f)
        URL_BLACKLIST_DOMAINS = set(intel.get('malicious_domains', []))
        URL_BLACKLIST_URLS    = set(intel.get('malicious_urls', []))
        URL_SAFELIST_DOMAINS  = set(intel.get('safe_domains', []))
        print(f"[URL-INTEL] Loaded {len(URL_BLACKLIST_DOMAINS)} bad domains, "
              f"{len(URL_BLACKLIST_URLS)} bad URLs, {len(URL_SAFELIST_DOMAINS)} safe domains")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[URL-INTEL] Could not load url_intelligence.json: {e}")

_load_url_intelligence()


def _dataset_dir() -> str:
    """Returns path to the datasets/ folder next to this file."""
    return os.path.join(os.path.dirname(__file__), '..', 'datasets')


def load_dataset_keywords():
    """
    If the user has downloaded Kaggle CSVs into datasets/, load extra keywords
    from them and merge into the runtime keyword lists.

    Expected files (place in datasets/ folder):
      • phishing_emails.csv     — Phish No More dataset (col: Email Text)
      • spam_ham.csv            — 190K Spam/Ham dataset (cols: text, label)
      • malicious_urls.csv      — Malicious URLs dataset (cols: url, type)

    Kaggle sources:
      kaggle.com/datasets/naserabdullahalam/phishing-email-dataset
      kaggle.com/datasets/meruvulikith/190k-spam-ham-email-dataset-for-classification
      kaggle.com/datasets/sid321axn/malicious-urls-dataset
    """
    global SCAM_KEYWORDS, SPAM_KEYWORDS, DANGEROUS_URL_KEYWORDS
    datasets_path = _dataset_dir()

    # phishing_email.csv — cols: text_combined, label (1=phishing, 0=safe)
    phishing_csv = os.path.join(datasets_path, 'phishing_email.csv')
    if os.path.exists(phishing_csv):
        extra = set()
        try:
            with open(phishing_csv, newline='', encoding='utf-8', errors='ignore') as f:
                reader = csv.DictReader(f)
                for i, row in enumerate(reader):
                    if i > 5000:
                        break
                    if row.get('label', '').strip() == '1':
                        text = row.get('text_combined', '').lower()
                        for word in re.findall(r'\b[a-z]{4,}\b', text):
                            extra.add(word)
            SCAM_KEYWORDS = list(set(SCAM_KEYWORDS) | extra)
            print(f"[DATASET] Loaded {len(extra)} extra scam tokens from phishing_email.csv")
        except Exception as e:
            print(f"[DATASET] Could not load phishing_email.csv: {e}")

    # spam_Emails_data.csv — cols: label, text
    # Some rows contain very large email bodies so we skip them gracefully
    spam_csv = os.path.join(datasets_path, 'spam_Emails_data.csv')
    if os.path.exists(spam_csv):
        extra_spam = set()
        loaded = 0
        try:
            with open(spam_csv, encoding='utf-8', errors='ignore') as f:
                header = f.readline().strip().split(',')
                try:
                    label_idx = header.index('label')
                    text_idx = header.index('text')
                except ValueError:
                    label_idx, text_idx = 0, 1
                for i, raw_line in enumerate(f):
                    if loaded >= 5000:
                        break
                    try:
                        parts = raw_line.split(',', max(label_idx, text_idx) + 1)
                        if len(parts) <= max(label_idx, text_idx):
                            continue
                        label = parts[label_idx].strip().lower()
                        if 'spam' in label:
                            text = parts[text_idx].lower()
                            for word in re.findall(r'\b[a-z]{4,}\b', text):
                                extra_spam.add(word)
                            loaded += 1
                    except Exception:
                        continue
            SPAM_KEYWORDS = list(set(SPAM_KEYWORDS) | extra_spam)
            print(f"[DATASET] Loaded {len(extra_spam)} extra spam tokens from spam_Emails_data.csv")
        except Exception as e:
            print(f"[DATASET] Could not load spam_Emails_data.csv: {e}")

    # malicious_phish.csv — cols: url, type
    urls_csv = os.path.join(datasets_path, 'malicious_phish.csv')
    if os.path.exists(urls_csv):
        extra_url_keywords = set()
        try:
            with open(urls_csv, newline='', encoding='utf-8', errors='ignore') as f:
                reader = csv.DictReader(f)
                for i, row in enumerate(reader):
                    if i > 10000:
                        break
                    url_type = row.get('type', '').strip().lower()
                    url = row.get('url', '').lower()
                    if url_type in ('phishing', 'malware'):
                        for segment in re.split(r'[/\-_=&?.]', url):
                            if len(segment) > 3 and segment.isalpha():
                                extra_url_keywords.add(segment)
            DANGEROUS_URL_KEYWORDS = list(set(DANGEROUS_URL_KEYWORDS) | extra_url_keywords)
            print(f"[DATASET] Loaded {len(extra_url_keywords)} extra URL keywords from malicious_phish.csv")
        except Exception as e:
            print(f"[DATASET] Could not load malicious_phish.csv: {e}")


# Freeze the curated list before dataset augmentation adds noisy common words
_CURATED_SCAM_KEYWORDS = list(SCAM_KEYWORDS)

load_dataset_keywords()


def detect_spoofing(sender_str: str) -> bool:
    """
    Detects brand impersonation in sender strings.
    Brand list expanded from Fraud Email Dataset and Phishing & Benign Email Dataset (Kaggle).
    """
    sender_lower = sender_str.lower()
    email_match = re.search(r'<([^>]+)>', sender_str)
    if email_match:
        display_part = sender_lower.split('<')[0]
        actual_email_domain = email_match.group(1).lower().split('@')[-1]
        for brand in MONITORED_BRANDS:
            if brand in display_part and brand not in actual_email_domain:
                return True
    else:
        if "@" in sender_lower:
            local_part, domain_part = sender_lower.split("@", 1)
            for brand in MONITORED_BRANDS:
                if brand in local_part and brand not in domain_part:
                    return True
    return False


def is_trusted_sender(sender_str: str) -> bool:
    """Returns True if the sender's actual email domain is in TRUSTED_DOMAINS."""
    email_match = re.search(r'<([^>]+)>', sender_str)
    if email_match:
        domain = email_match.group(1).lower().split('@')[-1].strip()
    elif '@' in sender_str:
        domain = sender_str.lower().split('@')[-1].strip()
    else:
        return False
    return domain in TRUSTED_DOMAINS or any(domain.endswith('.' + td) for td in TRUSTED_DOMAINS)


def url_lexical_risk(url: str) -> int:
    """
    Scores a single URL using lexical features derived from:
      • Phishing URLs Dataset with Extracted Features (victusadi/phishing-urls-dataset-with-extracted-features)
      • Malicious URL Detection Dataset Enhanced 2026 (moutasmtamimi)
    Returns a risk score 0–100.
    """
    score = 0
    url_lower = url.lower()

    reasons = []

    # Dataset-backed exact URL blacklist check (URLhaus + OpenPhish)
    clean_url_check = url.rstrip('/')
    if clean_url_check in URL_BLACKLIST_URLS:
        return 100, ["Confirmed malicious URL (URLhaus/OpenPhish database match)"]

    # Domain-level checks against trusted providers and dataset-backed lists
    url_domain = None
    try:
        domain_match = re.search(r'https?://([^/]+)', url_lower)
        if domain_match:
            url_domain = domain_match.group(1)
            # Curated TRUSTED_DOMAINS → always safe
            if url_domain in TRUSTED_DOMAINS or any(url_domain.endswith('.' + td) for td in TRUSTED_DOMAINS):
                return 0, []
            # Dataset blacklist: known malicious domain
            if url_domain in URL_BLACKLIST_DOMAINS:
                return 90, [f"Domain flagged in threat database (URLhaus/OpenPhish): {url_domain}"]
            # Dataset safelist: Tranco top-10k verified safe domain
            if url_domain in URL_SAFELIST_DOMAINS:
                return 0, []
    except Exception:
        pass

    if len(url) > 100:
        score += 20
        reasons.append("Unusually long URL (>100 chars)")
    elif len(url) > 75:
        score += 10
        reasons.append("Long URL (>75 chars)")

    if re.search(r'https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', url):
        score += 30
        reasons.append("Raw IP address used instead of domain name")

    if '@' in url:
        score += 25
        reasons.append("@ symbol in URL (browser misdirection trick)")

    try:
        domain = re.search(r'https?://([^/]+)', url_lower)
        if domain and any(short in domain.group(1) for short in URL_SHORTENERS):
            score += 20
            reasons.append(f"URL shortener detected: {domain.group(1)}")
    except Exception:
        pass

    matched_tld = next((tld for tld in SUSPICIOUS_TLDS if url_lower.endswith(tld) or (tld + '/') in url_lower), None)
    if matched_tld:
        score += 20
        reasons.append(f"Suspicious TLD: {matched_tld}")

    try:
        domain_part = re.search(r'https?://([^/]+)', url_lower)
        if domain_part and domain_part.group(1).count('-') >= 3:
            score += 15
            reasons.append("Excessive hyphens in domain (typosquatting)")
    except Exception:
        pass

    if '//' in url[8:]:
        score += 15
        reasons.append("Double-slash open redirect pattern")

    url_path_only = re.sub(r'^https?://', '', url_lower)
    matched_kw = next((k for k in DANGEROUS_URL_KEYWORDS if k in url_path_only), None)
    if matched_kw:
        score += 15
        reasons.append(f'Suspicious path keyword: "{matched_kw}"')

    if url_lower.startswith('http://') and any(k in url_lower for k in ['login', 'verify', 'pay', 'bank', 'secure']):
        score += 15
        reasons.append("Unencrypted HTTP on sensitive path")

    try:
        domain_part = re.search(r'https?://([^/]+)', url_lower)
        if domain_part and domain_part.group(1).count('.') > 3:
            score += 10
            reasons.append("Excessive subdomains (domain camouflage)")
    except Exception:
        pass

    try:
        path = re.sub(r'https?://[^/]+', '', url_lower)
        if path:
            freq = {c: path.count(c) / len(path) for c in set(path)}
            entropy = -sum(p * math.log2(p) for p in freq.values())
            if entropy > 4.5:
                score += 10
                reasons.append(f"High path entropy ({entropy:.1f}) — likely obfuscated")
    except Exception:
        pass

    final = min(score, 100)
    # HTTPS means the connection is encrypted — cap below the "Dangerous" threshold
    if url_lower.startswith('https://'):
        final = min(final, 35)
        if final < score:
            reasons.append("HTTPS detected — encrypted connection (capped below Dangerous)")
    return final, reasons


def calculate_risk_index(category: str, spoofed: bool, links: list) -> int:
    """
    Risk scoring model informed by feature weights in:
      • Phishing URLs Dataset with Extracted Features (victusadi — Kaggle)
      • Phishing Email Data by Type (charlottehall — Kaggle)
    Combines email category, brand spoofing, and per-URL lexical risk scores.
    """
    score = 10
    if category == "Scam Alert":
        score += 45
    elif category == "Spam":
        score += 20
    elif category == "High Priority":
        score += 5

    if spoofed:
        score += 25

    # Use URL lexical risk scores instead of binary dangerous/not-dangerous
    for link in links:
        url_risk = link.get("url_risk_score", 0)
        if url_risk >= 40:
            score += 15
        elif url_risk >= 20:
            score += 7

    result = min(score, 100)
    if category == "Safe":
        result = min(result, 15)
    elif category == "Important":
        result = min(result, 35)
    return result


def calculate_analytics(emails):
    """Computes operational security metrics across real active inbox parameters."""
    total = len(emails)
    counts = {
        "scams": sum(1 for e in emails if e.get("initial_category") == "Scam Alert"),
        "spams": sum(1 for e in emails if e.get("initial_category") == "Spam"),
        "spoofed": sum(1 for e in emails if e.get("spoofing_detected")),
        "soc_cases": sum(1 for e in emails if e.get("soc_reported"))
    }
    counts["total"] = total
    counts["percentage"] = round((counts["scams"] / total) * 100) if total > 0 else 0
    return counts


def parse_and_sandbox_links(body_text):
    """
    Extracts URLs and scores them using lexical analysis.
    Scoring model derived from:
      • Phishing URLs Dataset with Extracted Features (victusadi — Kaggle)
      • Malicious URL Detection Dataset Enhanced 2026 (moutasmtamimi — Kaggle)
    """
    found_urls = re.findall(r'https?://[^\s<>"\')\]\n\r]+', body_text)
    results = []
    for url in found_urls:
        clean_url = url.rstrip(".,;:")
        risk, reasons = url_lexical_risk(clean_url)
        if risk >= 40:
            status = "Dangerous / Blacklisted Match"
        elif risk >= 20:
            status = "Suspicious / Unverified"
        else:
            status = "External Link / Unverified Clear"
        domain_m = re.search(r'https?://([^/]+)', clean_url.lower())
        domain = domain_m.group(1) if domain_m else clean_url
        results.append({
            "url": clean_url,
            "domain": domain,
            "safety_status": status,
            "url_risk_score": risk,
            "risk_reasons": reasons
        })
    return results


def fallback_categorize(body: str) -> str:
    """Keyword-based fallback categorizer. Requires 3+ curated scam keyword hits to reduce false positives."""
    lower = body.lower()
    scam_hits = sum(1 for k in _CURATED_SCAM_KEYWORDS if k in lower)
    if scam_hits >= 3:
        return "Scam Alert"
    if any(k in lower for k in SPAM_KEYWORDS):
        return "Spam"
    if scam_hits == 0:
        return "Safe"
    return "Important"


def generate_threat_reasoning(body: str, spoofed: bool, links: list, category: str,
                              sender: str = '', subject: str = '', use_groq: bool = True) -> str:
    """Generate specific, contextual reasoning for why an email was flagged as Spam or Scam Alert.
    Tries Groq first for email-specific analysis; falls back to signal-based points."""
    if category not in ('Spam', 'Scam Alert'):
        return ''

    # ── Groq: email-specific contextual reasoning ──────────────────────────────
    if use_groq and groq_client and body:
        label = 'spam' if category == 'Spam' else 'a scam/phishing attempt'
        signal_notes = []
        if spoofed:
            signal_notes.append('the sender domain does not match the display name')
        bad_urls = [l['domain'] for l in links if l.get('url_risk_score', 0) >= 40]
        if bad_urls:
            signal_notes.append(f'links to known malicious domain(s): {", ".join(bad_urls[:2])}')
        sus_urls = [l['domain'] for l in links if 20 <= l.get('url_risk_score', 0) < 40]
        if sus_urls and not bad_urls:
            signal_notes.append('links to unverified domains')
        signal_str = ('; also: ' + '; '.join(signal_notes)) if signal_notes else ''

        prompt = (
            f'This email from "{sender}" with subject "{subject}" was classified as {label}{signal_str}. '
            f'In exactly 2 concise sentences, explain specifically why — referencing actual phrases or '
            f'patterns found in the content below. Be direct and factual. '
            f'Do not give advice, ask questions, or use bullet points.\n\n'
            f'Email content: {body[:900]}'
        )
        try:
            completion = groq_client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant",
                max_tokens=120,
                temperature=0.2,
            )
            result = completion.choices[0].message.content.strip()
            if result and len(result) > 20:
                return result
        except Exception:
            pass

    # ── Signal-based fallback ──────────────────────────────────────────────────
    reasons = []
    lower = body.lower()

    if spoofed:
        reasons.append("The sender's display name doesn't match the actual sending domain — a classic brand impersonation pattern.")

    bad_urls  = [l for l in links if l.get('url_risk_score', 0) >= 40]
    sus_urls  = [l for l in links if 20 <= l.get('url_risk_score', 0) < 40]
    if bad_urls:
        domains = list(dict.fromkeys(l['domain'] for l in bad_urls))[:2]
        reasons.append(f"Links to known malicious domain(s): {', '.join(domains)}.")
    elif sus_urls:
        reasons.append("Contains links to unverified or suspicious domains.")

    if any(k in lower for k in ['verify your account', 'confirm your', 'update your password', 'sign in to', 'log in to']):
        reasons.append("Requests account verification or credential confirmation — a common phishing tactic.")
    if any(k in lower for k in ["you've won", 'congratulations', 'selected', 'prize', 'gift card']):
        reasons.append("Uses unsolicited prize or reward language to manufacture urgency.")
    if any(k in lower for k in ['click here', 'act now', 'limited time', 'expires soon', 'hurry']):
        reasons.append("Uses high-pressure time-limited language typical of spam campaigns.")
    if any(k in lower for k in ['bitcoin', 'crypto', 'investment', 'guaranteed return', 'wire transfer']):
        reasons.append("References financial schemes, cryptocurrency, or wire transfers.")
    if any(k in lower for k in ['unsubscribe', 'opt out', 'opt-out', 'mailing list']) and category == 'Spam':
        reasons.append("Bulk email characteristics detected — contains unsubscribe/opt-out language typical of mass marketing sends.")
    if any(k in lower for k in ['take your project', 'go live', 'get started', 'explore features', 'tips and tricks', 'welcome to', 'start using', 'new features', 'your subscription']) and category == 'Spam':
        reasons.append("Promotional onboarding or product marketing content sent to a broad audience without direct user request.")

    if not reasons:
        reasons.append("Multiple content signals indicate unsolicited or potentially deceptive email content.")

    return ' '.join(reasons[:3])


def _backfill_reasoning():
    """Populate threat_reasoning for any Spam/Scam Alert email stored before the field existed."""
    changed = 0
    for email in EXT_EMAILS.values():
        if email.get('initial_category') not in ('Spam', 'Scam Alert'):
            continue
        if email.get('threat_reasoning'):
            continue
        reasoning = generate_threat_reasoning(
            body=email.get('body', ''),
            spoofed=email.get('spoofing_detected', False),
            links=email.get('links', []),
            category=email['initial_category'],
            sender=email.get('sender', ''),
            subject=email.get('subject', ''),
            use_groq=False,  # keyword-only at startup — no Groq delay
        )
        if reasoning:
            email['threat_reasoning'] = reasoning
            changed += 1
    if changed:
        print(f"[BACKFILL] Populated threat_reasoning for {changed} existing email(s).")
        _save_persisted()

_backfill_reasoning()


def build_learned_context() -> str:
    """Summarise threat patterns from the last 100 audited emails to sharpen Groq's categorisation."""
    recent = list(EXT_EMAILS.values())[-100:]
    if not recent:
        return ''
    scams   = [e for e in recent if e.get('initial_category') == 'Scam Alert']
    spoofed = [e for e in recent if e.get('spoofing_detected')]
    threat_domains: set = set()
    for e in scams + spoofed:
        m = re.search(r'@([^\s>]+)', e.get('sender', ''))
        if m:
            threat_domains.add(m.group(1).lower())
    parts = []
    if threat_domains:
        parts.append(f"Threat domains seen in this inbox: {', '.join(list(threat_domains)[:8])}.")
    if len(scams) >= 3:
        parts.append(f"{len(scams)} scam emails detected recently — be conservative.")
    if len(spoofed) >= 2:
        parts.append(f"{len(spoofed)} brand-impersonation attempts observed.")
    return ' '.join(parts)


def calculate_confidence(category: str, spoofed: bool, links: list,
                         groq_used: bool, fallback_cat: str) -> dict:
    """Estimate how confident we are in the classification based on signal agreement."""
    score = 50
    # Groq + fallback agreement
    if groq_used:
        score += 25 if category == fallback_cat else -10
    else:
        score -= 10  # only fallback used
    # Spoofing signal alignment
    if spoofed:
        score += 20 if category in ('Scam Alert', 'Spam') else -10
    # URL risk alignment
    bad_urls = sum(1 for l in links if l.get('url_risk_score', 0) >= 40)
    sus_urls  = sum(1 for l in links if 20 <= l.get('url_risk_score', 0) < 40)
    if bad_urls:
        score += 15 if category in ('Scam Alert', 'Spam') else -8
    elif sus_urls:
        score += 8
    elif links:
        score += 10 if category == 'Safe' else 0
    score = max(10, min(98, score))
    label = 'High' if score >= 78 else 'Medium' if score >= 52 else 'Low'
    return {'score': score, 'label': label}


def find_rescan_candidates(sender: str, category: str) -> list:
    """If a new scam arrives from a domain we previously called Safe, flag those old IDs."""
    if category != 'Scam Alert':
        return []
    m = re.search(r'@([^\s>]+)', sender)
    if not m:
        return []
    threat_domain = m.group(1).lower()
    candidates = []
    for eid, email in EXT_EMAILS.items():
        if email.get('initial_category') != 'Safe':
            continue
        em = re.search(r'@([^\s>]+)', email.get('sender', ''))
        if em and em.group(1).lower() == threat_domain:
            candidates.append(eid)
        if len(candidates) >= 5:
            break
    return candidates


def groq_categorize(body: str, learned_context: str = '') -> str | None:
    """Calls Groq to categorize email, optionally enriched with inbox threat history."""
    if not groq_client or not body:
        return None
    ctx = f' Context from prior scans: {learned_context}' if learned_context else ''
    prompt = (
        "Categorize this email into exactly one of: "
        "'High Priority', 'Important', 'Safe', 'Spam', 'Scam Alert'. "
        "Safe = clearly benign. Important = legitimate but noteworthy. "
        "High Priority = urgent legitimate. Spam = unsolicited promo. "
        f"Scam Alert = phishing/fraud/malicious.{ctx} "
        f"Email: {body[:1200]}. Reply with ONLY the category name."
    )
    try:
        completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            max_tokens=10,
            temperature=0.0
        )
        decision = completion.choices[0].message.content.strip().strip("'\"")
        return decision if decision in ("High Priority", "Important", "Safe", "Spam", "Scam Alert") else None
    except Exception:
        return None


def groq_json_call(prompt: str) -> dict | None:
    """Generic Groq call expecting a JSON response. Returns parsed dict or None."""
    if not groq_client:
        return None
    try:
        completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            max_tokens=512,
            temperature=0.0
        )
        raw = completion.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw).rstrip("`").strip()
        return json.loads(raw)
    except Exception:
        return None


def get_email_body(payload):
    """Recursively processes multi-part structures to extract safe plain text segments, with HTML fallback tracking."""
    import base64
    if 'parts' in payload:
        # Step A: Attempt to prioritize clean raw plain text data packets
        for part in payload['parts']:
            if part.get('mimeType') == 'text/plain' and 'data' in part.get('body', {}):
                try:
                    return base64.urlsafe_b64decode(part['body']['data'].encode('ASCII')).decode('utf-8', errors='ignore')
                except Exception:
                    pass
        # Step B: Fall back onto text/html parsing matrices if plain text strings are empty
        for part in payload['parts']:
            if part.get('mimeType') == 'text/html' and 'data' in part.get('body', {}):
                try:
                    html_content = base64.urlsafe_b64decode(part['body']['data'].encode('ASCII')).decode('utf-8', errors='ignore')
                    return re.sub('<[^<]+?>', '', html_content)
                except Exception:
                    pass
            elif 'parts' in part:
                body = get_email_body(part)
                if body:
                    return body
    else:
        body_obj = payload.get('body', {})
        if 'data' in body_obj:
            try:
                content = base64.urlsafe_b64decode(body_obj['data'].encode('ASCII')).decode('utf-8', errors='ignore')
                if payload.get('mimeType') == 'text/html':
                    return re.sub('<[^<]+?>', '', content)
                return content
            except Exception:
                pass
    return ""


def fetch_gmail_emails(page_token=None):
    """Builds access credentials and queries live Gmail message matrices seamlessly supporting token pagination."""
    if 'credentials' not in session:
        return [], None
    try:
        creds_dict = session['credentials']
        credentials = Credentials(
            token=creds_dict['token'],
            refresh_token=creds_dict.get('refresh_token'),
            token_uri=creds_dict['token_uri'],
            client_id=creds_dict['client_id'],
            client_secret=creds_dict['client_secret'],
            scopes=creds_dict['scopes']
        )
        service = build('gmail', 'v1', credentials=credentials)
        
        # Inject pageToken query parameter into the active request context map
        results = service.users().messages().list(userId='me', maxResults=10, pageToken=page_token).execute()
        messages = results.get('messages', [])
        next_page_token = results.get('nextPageToken', None)
        
        emails_list = []
        for msg in messages:
            msg_data = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
            payload = msg_data.get('payload', {})
            headers = payload.get('headers', [])
            
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '(No Subject)')
            sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown Sender')
            date_str = next((h['value'] for h in headers if h['name'].lower() == 'date'), 'Unknown Date')
            
            body = get_email_body(payload)
            if not body or body.strip() == "":
                body = msg_data.get('snippet', '')

            spoofed = detect_spoofing(sender)
            trusted = is_trusted_sender(sender)
            if trusted and not spoofed:
                category = "Safe"
            else:
                category = groq_categorize(body) or fallback_categorize(body)
            links = parse_and_sandbox_links(body)
            risk_score = calculate_risk_index(category, spoofed, links)
            
            soc_reported = msg['id'] in REPORTED_SOC_IDS
            
            emails_list.append({
                "id": msg['id'],
                "sender": sender,
                "subject": subject,
                "date": date_str,
                "body": body,
                "initial_category": category,
                "spoofing_detected": spoofed,
                "risk_score": risk_score,
                "soc_reported": soc_reported,
                "links": links
            })

        # Track every Gmail message ID so they count toward TOTAL_AUDITED
        new_gmail = [e['id'] for e in emails_list if e['id'] not in SEEN_GMAIL_IDS]
        if new_gmail:
            SEEN_GMAIL_IDS.update(new_gmail)
            TOTAL_AUDITED += len(new_gmail)
            _save_persisted()

        return emails_list, next_page_token
    except Exception:
        return [], None


@app.route('/api/agent-run')
def agent_run():
    """SSE endpoint: autonomously reads Gmail emails and streams analysis results."""
    import hashlib

    count_param = request.args.get('count', '10').strip().lower()

    if 'credentials' not in session:
        def no_auth():
            yield f"data: {json.dumps({'error': 'not_authenticated'})}\n\n"
        return Response(no_auth(), mimetype='text/event-stream')

    # Snapshot session credentials before entering generator (session unavailable inside)
    creds_dict = dict(session['credentials'])

    max_count = None if count_param == 'all' else max(1, int(count_param)) if count_param.isdigit() else 10

    def generate():
        try:
            credentials = Credentials(
                token=creds_dict['token'],
                refresh_token=creds_dict.get('refresh_token'),
                token_uri=creds_dict['token_uri'],
                client_id=creds_dict['client_id'],
                client_secret=creds_dict['client_secret'],
                scopes=creds_dict['scopes']
            )
            service = build('gmail', 'v1', credentials=credentials)

            # Collect message IDs (paginate if "all")
            all_messages = []
            page_token = None
            fetch_size = min(max_count or 500, 500)
            while True:
                # labelIds=INBOX + default ordering = newest first
                kwargs = {'userId': 'me', 'maxResults': fetch_size, 'labelIds': ['INBOX']}
                if page_token:
                    kwargs['pageToken'] = page_token
                results = service.users().messages().list(**kwargs).execute()
                all_messages.extend(results.get('messages', []))
                if max_count and len(all_messages) >= max_count:
                    all_messages = all_messages[:max_count]
                    break
                page_token = results.get('nextPageToken')
                if not page_token:
                    break

            total = len(all_messages)
            yield f"data: {json.dumps({'status': 'started', 'total': total})}\n\n"

            processed = spoofed_count = soc_count = 0

            for msg in all_messages:
                try:
                    msg_data = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
                    payload = msg_data.get('payload', {})
                    hdrs = payload.get('headers', [])

                    subject  = next((h['value'] for h in hdrs if h['name'].lower() == 'subject'), '(No Subject)')
                    sender   = next((h['value'] for h in hdrs if h['name'].lower() == 'from'), 'Unknown')
                    date_str = next((h['value'] for h in hdrs if h['name'].lower() == 'date'), '')
                    body     = get_email_body(payload) or msg_data.get('snippet', '')

                    spoofed = detect_spoofing(sender)
                    trusted = is_trusted_sender(sender)
                    category = "Safe" if (trusted and not spoofed) else (groq_categorize(body) or fallback_categorize(body))
                    links = parse_and_sandbox_links(body)
                    risk  = calculate_risk_index(category, spoofed, links)

                    email_id = hashlib.md5((sender + subject + body[:64]).encode()).hexdigest()[:12]
                    is_soc = risk >= 75 or spoofed

                    if spoofed:
                        spoofed_count += 1
                    if is_soc:
                        soc_count += 1
                        REPORTED_SOC_IDS.add(email_id)

                    email_data = {
                        "id": email_id, "sender": sender, "subject": subject,
                        "body": body, "date": date_str,
                        "initial_category": category, "spoofing_detected": spoofed,
                        "risk_score": risk, "soc_reported": is_soc,
                        "links": links, "from_agent": True,
                        "threat_reasoning": generate_threat_reasoning(body, spoofed, links, category, sender, subject),
                    }
                    is_new_email = email_id not in EXT_EMAILS
                    EXT_EMAILS[email_id] = email_data
                    if is_new_email:
                        TOTAL_AUDITED += 1
                    processed += 1

                    yield f"data: {json.dumps({'status': 'progress', 'email': email_data, 'processed': processed, 'total': total, 'spoofed': spoofed_count, 'soc': soc_count, 'is_new': is_new_email, 'total_audited': TOTAL_AUDITED})}\n\n"

                except Exception as e:
                    print(f"[AGENT] skip {msg['id']}: {e}")
                    processed += 1
                    yield f"data: {json.dumps({'status': 'skip', 'processed': processed, 'total': total})}\n\n"

            _save_persisted()
            yield f"data: {json.dumps({'status': 'done', 'processed': processed, 'spoofed': spoofed_count, 'soc': soc_count})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    origin = request.headers.get('Origin', '*')
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Access-Control-Allow-Origin': origin,
            'Access-Control-Allow-Credentials': 'true',
        }
    )


# ── Platform presence tracking (extension pings when active on a webmail) ────
# Stores {platform: last_ping_timestamp}. Platform is "active" within 35 s.
ACTIVE_PLATFORMS: dict = {}

@app.route('/api/set-platform', methods=['POST'])
def set_platform():
    platform = (request.json or {}).get('platform', '')
    if platform in ('gmail', 'yahoo', 'outlook'):
        ACTIVE_PLATFORMS[platform] = time.time()
    return jsonify({'ok': True})

@app.route('/api/platform-status', methods=['GET'])
def platform_status():
    now = time.time()
    return jsonify({p: (now - ACTIVE_PLATFORMS.get(p, 0)) < 35
                    for p in ('gmail', 'yahoo', 'outlook')})


@app.route('/api/network-info', methods=['GET'])
def network_info():
    import socket as _socket
    try:
        lan_ip = _socket.gethostbyname(_socket.gethostname())
    except Exception:
        lan_ip = '127.0.0.1'
    return jsonify({
        'lan_ip': lan_ip,
        'mobile_url': f'http://{lan_ip}:4245',
    })


@app.route('/landing')
def landing():
    return render_template('landing.html')


@app.route('/')
def index():
    if 'credentials' not in session:
        # View-only mode: show extension-scanned emails without requiring Gmail login
        ext_list = list(EXT_EMAILS.values())
        if ext_list:
            analytics = calculate_analytics(ext_list)
            analytics['total'] = TOTAL_AUDITED
            return render_template('index.html', logged_in=False, emails=ext_list,
                                   next_token=None, analytics=analytics)
        return render_template('landing.html')

    current_token = request.args.get('pageToken', None)
    emails, next_token = fetch_gmail_emails(page_token=current_token)

    # TOTAL_AUDITED already counts every Gmail + extension + agent email ever seen
    all_analyzed = list(EXT_EMAILS.values()) + [e for e in emails if e['id'] not in EXT_EMAILS]
    analytics = calculate_analytics(all_analyzed)
    analytics['total'] = TOTAL_AUDITED   # monotonic — never goes down

    return render_template('index.html', logged_in=True, emails=emails, next_token=next_token, analytics=analytics)


def _build_redirect_uri() -> str:
    """Build OAuth callback URI dynamically so it works from any host (localhost or LAN IP)."""
    env_uri = os.getenv("GOOGLE_REDIRECT_URI")
    if env_uri:
        return env_uri
    return request.url_root.rstrip('/') + '/callback'

def _make_state() -> str:
    """Create a stateless CSRF state token signed with the app secret key.
    Works on serverless (Vercel) where session cookies may not survive the OAuth round-trip."""
    nonce = secrets.token_urlsafe(16)
    sig = hmac.new(app.secret_key.encode(), nonce.encode(), hashlib.sha256).hexdigest()[:24]
    return f"{nonce}.{sig}"

def _verify_state(token: str) -> bool:
    """Verify an HMAC-signed state token without needing session storage."""
    try:
        nonce, sig = token.rsplit('.', 1)
        expected = hmac.new(app.secret_key.encode(), nonce.encode(), hashlib.sha256).hexdigest()[:24]
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False

@app.route('/login')
def login():
    """Initializes Google OAuth pipeline variables and options."""
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        CLIENT_CONFIG,
        scopes=SCOPES
    )
    flow.redirect_uri = _build_redirect_uri()
    state = _make_state()
    authorization_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        state=state,
    )
    session['state'] = state  # best-effort; may not survive serverless
    return redirect(authorization_url)


@app.route('/callback')
def callback():
    """Transforms verification properties into runtime auth tokens securely."""
    incoming_state = request.args.get('state', '')
    session_state  = session.get('state')

    # Accept if session state matches OR if the HMAC signature on the incoming state is valid
    # (the HMAC check handles Vercel serverless where the session cookie is lost mid-flight)
    state_ok = (session_state and session_state == incoming_state) or _verify_state(incoming_state)

    if not state_ok:
        print(f"[DEBUG] State invalid — session: {repr(session_state)}, incoming: {repr(incoming_state)}")
        session.clear()
        return redirect('/login')
        
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        CLIENT_CONFIG,
        scopes=SCOPES,
        state=incoming_state
    )
    flow.redirect_uri = _build_redirect_uri()

    authorization_response = request.url
    # Only upgrade http→https for public/external hosts, not LAN IPs or localhost
    _host = request.host.split(':')[0]
    _is_local = _host in ('localhost', '127.0.0.1') or _host.startswith('192.168.') or _host.startswith('10.') or _host.startswith('172.')
    if authorization_response.startswith('http://') and not _is_local:
        authorization_response = authorization_response.replace('http://', 'https://')
        
    # Checkpoint B: Protect the token exchange from throwing raw exceptions during live debugging restarts
    try:
        flow.fetch_token(authorization_response=authorization_response)
    except Exception as e:
        print(f"[DEBUG] Token exchange failed: {e}")
        session.clear()
        return redirect('/login')
        
    credentials = flow.credentials
    
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    return redirect('/')


@app.route('/logout')
def logout():
    """Clears localized cookie metrics configuration parameters safely."""
    session.clear()
    return redirect('/')


@app.route('/api/feed-state', methods=['GET'])
def stream_feed_state():
    if 'credentials' not in session:
        return jsonify({"emails": [], "next_token": None, "analytics": {"total": 0, "spoofed": 0, "soc_cases": 0, "percentage": 0}})
    
    requested_token = request.args.get('pageToken', None)
    emails, next_token = fetch_gmail_emails(page_token=requested_token)
    analytics = calculate_analytics(emails)
    return jsonify({"emails": emails, "next_token": next_token, "analytics": analytics})


import re as _re

def _is_fallback(sender: str, subject: str) -> bool:
    """True when the extension couldn't extract real data from the inbox row."""
    _s = sender.strip().lower()
    _sub = subject.strip().lower()
    sender_empty = _s in ('(unknown)', '') or bool(_re.match(r'^\(yahoo-sender-\d+\)$', _s))
    subject_empty = _sub in ('(no subject)', '') or bool(_re.match(r'^\(yahoo-subject-\d+\)$', _sub))
    return sender_empty and subject_empty

@app.route('/api/analyze-ext', methods=['POST'])
def analyze_ext():
    """Called by the browser extension to analyze an email open in the webmail client."""
    import hashlib
    data = request.json or {}
    sender = str(data.get('sender', ''))
    subject = str(data.get('subject', ''))
    body = str(data.get('body', ''))

    if _is_fallback(sender, subject):
        return jsonify({"skipped": True, "reason": "no_data"})

    spoofed  = detect_spoofing(sender)
    trusted  = is_trusted_sender(sender)
    fallback_cat = fallback_categorize(body)
    learned_ctx  = build_learned_context()

    if trusted and not spoofed:
        category  = "Safe"
        groq_used = False
    else:
        groq_result = groq_categorize(body, learned_ctx)
        groq_used   = groq_result is not None
        category    = groq_result or fallback_cat

    links      = parse_and_sandbox_links(body)
    risk       = calculate_risk_index(category, spoofed, links)
    confidence = calculate_confidence(category, spoofed, links, groq_used, fallback_cat)
    rescan     = find_rescan_candidates(sender, category)
    reasoning  = generate_threat_reasoning(body, spoofed, links, category, sender, subject)
    email_id   = hashlib.md5((sender + subject + body[:64]).encode()).hexdigest()[:12]

    email_data = {
        "id": email_id,
        "sender": sender,
        "subject": subject,
        "body": body,
        "date": "",
        "initial_category": category,
        "spoofing_detected": spoofed,
        "risk_score": risk,
        "soc_reported": email_id in REPORTED_SOC_IDS,
        "links": links,
        "from_extension": True,
        "threat_reasoning": reasoning,
    }
    global TOTAL_AUDITED
    is_new = email_id not in EXT_EMAILS
    EXT_EMAILS[email_id] = email_data
    if is_new:
        TOTAL_AUDITED += 1

    # Cap the sandbox at 250 emails — evict the oldest entry when exceeded
    evicted_id = None
    while len(EXT_EMAILS) > 250:
        evicted_id = next(iter(EXT_EMAILS))
        del EXT_EMAILS[evicted_id]

    _save_persisted()

    return jsonify({
        **email_data,
        "assigned_category": category,
        "total_audited":     TOTAL_AUDITED,
        "is_new":            is_new,
        "evicted_id":        evicted_id,
        "confidence":        confidence,
        "rescan_candidates": rescan,
    })


@app.route('/api/ext-emails', methods=['GET'])
def get_ext_emails():
    """Returns all emails analyzed via the browser extension."""
    return jsonify({"emails": list(EXT_EMAILS.values())})


@app.route('/api/report-soc/<email_id>', methods=['POST'])
def report_to_soc(email_id):
    """Documents incident and escalates telemetry properties to the Enterprise SOC layer."""
    REPORTED_SOC_IDS.add(email_id)
    _save_persisted()
    return jsonify({"status": "success", "message": f"Payload {email_id} successfully dispatched to SOC."})


@app.route('/analyze/<email_id>', methods=['POST'])
def analyze_email(email_id):
    """Generates a threat report for an email."""
    data = request.json or {}
    sender = str(data.get('sender', ''))
    subject = str(data.get('subject', ''))
    body = str(data.get('body', ''))

    lower = body.lower()
    if "paypal" in lower or "bank" in lower or "wire" in lower:
        fallback = {
            "threat_type": "Financial Wire Scam",
            "educational_report": (
                "The request demands immediate financial verification or wire parameters. "
                "Legitimate payment vendors will never ask for credentials via direct text paths."
            ),
            "indicators": ["Financial coercion hook", "Impersonated payment vendor gateway"]
        }
    elif "login" in lower or "verify" in lower or "portal" in lower:
        fallback = {
            "threat_type": "Phishing Link Attack",
            "educational_report": (
                "This payload utilizes artificial redirect URLs to harvest credentials. "
                "Inspect link structures carefully to confirm mismatch anomalies before clicking."
            ),
            "indicators": ["Deceptive link redirection setup", "Psychological action-inducing threat"]
        }
    else:
        fallback = {
            "threat_type": "Suspicious Threat Signature",
            "educational_report": (
                "This message possesses active psychological hooks. Avoid sharing security credentials, "
                "private identity details, or authorization profiles."
            ),
            "indicators": ["Urgent actionable demands", "Generic unrecognized email domain routing"]
        }

    prompt = f"""
You are an elite cybersecurity educator analyzing a suspicious email threat.
Sender: {sender}
Subject: {subject}
Body: {body}

Provide a JSON response with exactly three keys:
1. "threat_type": One of: 'Phishing Link Attack', 'Financial Wire Scam', 'Brand Impersonation', 'Malicious Attachment Trap'.
2. "educational_report": 2-3 sentences explaining indicators of compromise and how to protect oneself.
3. "indicators": A JSON list of 2-3 brief warning point strings.

Return ONLY raw valid JSON. No markdown.
"""
    report = groq_json_call(prompt) or fallback
    return jsonify({"status": "success", "report": report})


@app.route('/api/quiz/<email_id>', methods=['POST'])
def generate_quiz(email_id):
    """Generates a multiple-choice quiz question from email content."""
    data = request.json or {}
    body = str(data.get('body', ''))

    fallback = {
        "question": "What is the primary indicator of compromise present within this email?",
        "options": [
            "The urgent warning tone demanding quick, unverified action",
            "The presence of external, blacklisted redirect hyperlinks",
            "The generic greeting and unmatched email domain",
            "All of the above"
        ],
        "correct_index": 3,
        "explanation": (
            "Scam campaigns typically integrate multiple psychological and structural warning flags "
            "simultaneously to maximize impact."
        )
    }

    prompt = f"""
Based on this suspicious email, generate a multiple choice question to test a student's ability to spot this type of cybersecurity scam.
Body: {body}

Provide a JSON response with exactly four keys:
1. "question": A clear educational multiple choice question focused on red flags in this email.
2. "options": An array of exactly 4 distinct answer strings.
3. "correct_index": Zero-based integer index of the correct answer.
4. "explanation": One sentence explaining why that answer is correct.

Return ONLY raw valid JSON. No markdown.
"""
    quiz = groq_json_call(prompt) or fallback
    return jsonify({"status": "success", "quiz": quiz})


if __name__ == '__main__':
    import socket
    try:
        lan_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        lan_ip = '127.0.0.1'
    print(f"\n{'='*52}")
    print(f"  GuardMail AI  —  server running")
    print(f"  Local:   http://127.0.0.1:4245")
    print(f"  Mobile:  http://{lan_ip}:4245")
    print(f"{'='*52}\n")
    app.run(host='0.0.0.0', port=4245, debug=True)