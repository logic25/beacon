"""
Enhanced Dashboard v2 routes for Beacon analytics with OAuth protection.
Full-featured dashboard with date ranges, conversations, topics, and insights.
Only authorized users (AUTHORIZED_EMAILS) can access.
"""

from flask import render_template_string, jsonify, request, redirect, url_for, session
from datetime import datetime, timedelta
from analytics.analytics import AnalyticsDB
import os
from functools import wraps

# Google OAuth imports
try:
    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests
    import requests
    OAUTH_AVAILABLE = True
except ImportError:
    OAUTH_AVAILABLE = False

# OAuth Configuration
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
AUTHORIZED_EMAILS = os.getenv("AUTHORIZED_EMAILS", "").split(",")
OAUTH_ENABLED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and OAUTH_AVAILABLE)


# Login page HTML
LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Beacon Dashboard - Login</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            -webkit-font-smoothing: antialiased;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            padding: 20px;
        }
        .login-container {
            background: white;
            padding: 60px 50px;
            border-radius: 12px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            text-align: center;
            max-width: 450px;
            width: 100%;
        }
        h1 {
            color: #2c3e50;
            margin-bottom: 10px;
            font-size: 32px;
        }
        .subtitle {
            color: #7f8c8d;
            margin-bottom: 40px;
            font-size: 14px;
        }
        .google-btn {
            display: inline-flex;
            align-items: center;
            background: white;
            border: 1px solid #dadce0;
            border-radius: 4px;
            padding: 12px 24px;
            font-size: 14px;
            font-weight: 500;
            color: #3c4043;
            cursor: pointer;
            transition: all 0.2s;
            text-decoration: none;
        }
        .google-btn:hover {
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            border-color: #d2d2d2;
        }
        .google-icon {
            width: 18px;
            height: 18px;
            margin-right: 12px;
        }
        .error {
            background: #fee;
            color: #c33;
            padding: 12px;
            border-radius: 4px;
            margin-bottom: 20px;
            font-size: 14px;
        }
        .info {
            background: #e8f4f8;
            color: #0c5460;
            padding: 15px;
            border-radius: 4px;
            margin-top: 30px;
            font-size: 13px;
            line-height: 1.6;
        }
    
        .trend {
            font-size: 11px;
            font-weight: 600;
            padding: 2px 6px;
            border-radius: 4px;
            margin-right: 6px;
            display: inline-block;
        }
        .trend-up {
            color: #059669;
            background: #d1fae5;
        }
        .trend-down {
            color: #dc2626;
            background: #fee2e2;
        }
    
        .btn-approve {
            background: #dcfce7;
            color: #059669;
            border: 1px solid #86efac;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-approve:hover { background: #bbf7d0; }
        
        .btn-reject {
            background: #fee2e2;
            color: #dc2626;
            border: 1px solid #fca5a5;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-reject:hover { background: #fecaca; }


        /* Modal Styles */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.5);
            backdrop-filter: blur(4px);
        }
        
        .modal-content {
            background: var(--card);
            margin: 80px auto;
            padding: 32px;
            border-radius: 16px;
            max-width: 600px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.2);
            position: relative;
        }
        
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
        }
        
        .modal-title {
            font-size: 18px;
            font-weight: 600;
        }
        
        .modal-close {
            background: none;
            border: none;
            font-size: 24px;
            cursor: pointer;
            color: var(--text-muted);
            padding: 0;
            width: 32px;
            height: 32px;
        }
        
        .modal-user-info {
            font-size: 13px;
            color: var(--text-muted);
            margin-bottom: 24px;
        }
        
        .modal-section {
            margin-bottom: 24px;
        }
        
        .modal-section-label {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            margin-bottom: 12px;
        }
        
        .label-wrong {
            background: #fee2e2;
            color: #dc2626;
        }
        
        .label-correct {
            background: #dcfce7;
            color: #059669;
        }
        
        .modal-text {
            background: var(--bg);
            padding: 16px;
            border-radius: 8px;
            font-size: 14px;
            line-height: 1.6;
            border: 1px solid var(--border);
        }
        
        .modal-textarea {
            width: 100%;
            min-height: 120px;
            padding: 16px;
            border: 1px solid var(--border);
            border-radius: 8px;
            font-size: 14px;
            font-family: inherit;
            resize: vertical;
            background: var(--bg);
        }
        
        .modal-actions {
            display: flex;
            gap: 12px;
            justify-content: flex-end;
            margin-top: 24px;
        }
        
        .btn-cancel {
            background: white;
            color: var(--text);
            border: 1px solid var(--border);
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
        }
        
        .btn-reject-modal {
            background: white;
            color: #dc2626;
            border: 1px solid #fca5a5;
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
        }
        
        .btn-approve-modal {
            background: #f59e0b;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
        }
        .btn-approve-modal:hover {
            background: #d97706;
        }

    </style>
</head>
<body>
    <div class="login-container">
        <h1>Beacon Dashboard</h1>
        <div class="subtitle">Analytics & Monitoring</div>
        
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        
        <a href="{{ auth_url }}" class="google-btn">
            <svg class="google-icon" viewBox="0 0 24 24">
                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
            </svg>
            Sign in with Google
        </a>
        
        <div class="info">
            <strong>Authorized Access Only</strong><br>
            Only Green Light Expediting team members can access this dashboard.
        </div>
    </div>
</body>
</html>
"""

# Dashboard HTML template
BASE_TEMPLATE = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Beacon - {{ page_title }}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        :root {
            --bg: #f8fafc;
            --card: #ffffff;
            --border: #e2e8f0;
            --text: #0f172a;
            --text-muted: #64748b;
            --primary: #f59e0b;
            --success: #22c55e;
            --danger: #ef4444;
            --sidebar-width: 240px;
            --sidebar-collapsed: 72px;
            --shadow-card: 0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.06);
            --shadow-card-hover: 0 10px 25px -5px rgba(0,0,0,0.08), 0 4px 10px -5px rgba(0,0,0,0.04);
        }

        body.dark {
            --bg: #0f172a;
            --card: #1e293b;
            --border: #334155;
            --text: #f1f5f9;
            --text-muted: #cbd5e1;
        }

        body {
            font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg);
            color: var(--text);
            transition: background 0.2s, color 0.2s;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }
        
        .sidebar {
            position: fixed;
            left: 0;
            top: 0;
            bottom: 0;
            width: var(--sidebar-width);
            background: var(--card);
            border-right: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            transition: width 0.2s;
            z-index: 100;
        }
        
        .sidebar.collapsed { width: var(--sidebar-collapsed); }
        
        .sidebar-header {
            height: 64px;
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 0 16px;
            border-bottom: 1px solid var(--border);
        }
        
        .logo {
            width: 32px;
            height: 32px;
            border-radius: 8px;
            background: linear-gradient(135deg, #f59e0b, #d97706);
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: bold;
            flex-shrink: 0;
        }
        
        .sidebar-title {
            font-family: 'JetBrains Mono', monospace;
            font-weight: 600;
            font-size: 15px;
            white-space: nowrap;
            overflow: hidden;
            transition: opacity 0.2s, width 0.2s;
        }
        
        .sidebar.collapsed .sidebar-title { opacity: 0; width: 0; }
        
        .nav { padding: 12px; flex: 1; }
        
        .nav-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 12px;
            margin-bottom: 2px;
            border-radius: 8px;
            text-decoration: none;
            color: var(--text-muted);
            font-size: 13.5px;
            font-weight: 500;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            letter-spacing: -0.01em;
        }

        .nav-item:hover { background: var(--bg); color: var(--text); }
        .nav-item.active { background: #fef3c7; color: var(--primary); font-weight: 600; }
        
        .nav-icon { width: 16px; height: 16px; flex-shrink: 0; }
        
        .nav-label {
            white-space: nowrap;
            overflow: hidden;
            transition: opacity 0.2s;
        }
        
        .sidebar.collapsed .nav-label { opacity: 0; width: 0; }
        
        .sidebar-footer {
            padding: 12px;
            border-top: 1px solid var(--border);
        }
        
        .footer-btn {
            width: 100%;
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 12px;
            margin-bottom: 4px;
            border-radius: 8px;
            border: none;
            background: transparent;
            color: var(--text-muted);
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .footer-btn:hover { background: var(--bg); color: var(--text); }
        
        .main {
            margin-left: var(--sidebar-width);
            padding: 32px 24px;
            max-width: 1400px;
            transition: margin-left 0.2s;
        }
        
        .sidebar.collapsed ~ .main { margin-left: var(--sidebar-collapsed); }
        
        .page-header { margin-bottom: 32px; }
        
        .page-title {
            font-family: 'JetBrains Mono', monospace;
            font-size: 24px;
            font-weight: 700;
            margin-bottom: 4px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .page-icon { width: 24px; height: 24px; color: var(--primary); }
        .page-subtitle { font-size: 14px; color: var(--text-muted); }
        
        .card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
            box-shadow: var(--shadow-card);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .card:hover {
            box-shadow: var(--shadow-card-hover);
            transform: translateY(-2px);
        }

        .metric-card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            box-shadow: var(--shadow-card);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .metric-card:hover {
            box-shadow: var(--shadow-card-hover);
            transform: translateY(-1px);
        }
        
        .metric-icon {
            width: 40px;
            height: 40px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
            margin-bottom: 12px;
        }
        
        .metric-value {
            font-family: 'JetBrains Mono', monospace;
            font-size: 32px;
            font-weight: 700;
            margin-bottom: 4px;
            letter-spacing: -0.02em;
        }
        
        .metric-label { font-size: 14px; color: var(--text); margin-bottom: 2px; }
        .metric-sublabel { font-size: 11px; color: var(--text-muted); }
        .trend-up { color: var(--success); font-size: 11px; font-weight: 600; }
        
        .tabs {
            display: flex;
            gap: 8px;
            margin-bottom: 24px;
            border-bottom: 1px solid var(--border);
        }
        
        .tab {
            padding: 12px 16px;
            background: none;
            border: none;
            border-bottom: 2px solid transparent;
            color: var(--text-muted);
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .tab.active { color: var(--primary); border-bottom-color: var(--primary); }
        
        .badge {
            padding: 4px 12px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
            display: inline-block;
        }
        
        .badge-success { background: #dcfce7; color: var(--success); }
        .badge-danger { background: #fee2e2; color: var(--danger); }
        .badge-warning { background: #fef3c7; color: var(--primary); }
        .badge-info { background: #dbeafe; color: #3b82f6; }
        
        .btn {
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            border: none;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .btn-success { background: var(--success); color: white; }
        .btn-success:hover { background: #16a34a; }
        .btn-danger { background: var(--danger); color: white; }
        .btn-danger:hover { background: #dc2626; }
        
        table { width: 100%; border-collapse: collapse; }
        
        th {
            text-align: left;
            font-family: 'JetBrains Mono', monospace;
            font-size: 10.5px;
            color: var(--text-muted);
            font-weight: 500;
            padding: 12px;
            border-bottom: 1px solid var(--border);
            text-transform: uppercase;
            letter-spacing: 0.06em;
        }

        td {
            padding: 12px;
            font-size: 13px;
            border-bottom: 1px solid var(--border);
            line-height: 1.5;
        }

        tr { transition: background 0.15s ease; }
        tr:hover { background: var(--bg); }
        
        .grid { display: grid; gap: 16px; }
        .grid-2 { grid-template-columns: repeat(2, 1fr); }
        .grid-4 { grid-template-columns: repeat(4, 1fr); }
        .grid-6 { grid-template-columns: repeat(6, 1fr); }
        .grid-5-2 { grid-template-columns: 3fr 2fr; }
        
        .mb-6 { margin-bottom: 24px; }
        
        .conv-card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 12px;
            cursor: pointer;
            box-shadow: var(--shadow-card);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .conv-card:hover {
            box-shadow: var(--shadow-card-hover);
            border-color: rgba(245, 158, 11, 0.3);
            transform: translateY(-1px);
        }
        
        .topic-bar {
            display: flex;
            justify-content: space-between;
            margin-bottom: 12px;
        }
        
        .topic-name { font-size: 13px; font-weight: 500; }
        .topic-count { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-muted); }
        
        .progress-bar {
            height: 8px;
            background: #e2e8f0;
            border-radius: 4px;
            overflow: hidden;
            margin-top: 6px;
            margin-bottom: 16px;
        }
        
        .progress-fill { height: 100%; transition: width 0.3s; }

        .insight-card {
            border-radius: 12px;
            border: 1px solid;
            padding: 16px;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            cursor: default;
        }
        .insight-card:hover { box-shadow: var(--shadow-card-hover); }
        .insight-warning { border-color: rgba(245, 158, 11, 0.3); background: rgba(245, 158, 11, 0.05); }
        .insight-success { border-color: rgba(34, 197, 94, 0.3); background: rgba(34, 197, 94, 0.05); }
        .insight-info { border-color: rgba(59, 130, 246, 0.3); background: rgba(59, 130, 246, 0.05); }
        .insight-title { font-size: 13px; font-weight: 600; color: var(--text); margin-bottom: 4px; }
        .insight-desc { font-size: 12px; color: var(--text-muted); line-height: 1.5; }
        .insight-icon { width: 16px; height: 16px; flex-shrink: 0; margin-top: 2px; }

        .section-label {
            font-family: 'JetBrains Mono', monospace;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--text-muted);
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 12px;
        }
        
        .rank { font-family: 'JetBrains Mono', monospace; font-weight: 600; color: var(--primary); }
        
        /* Tab content visibility */
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        
        /* Animations */
        @keyframes fadeInUp {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .card, .conv-card, .metric-card {
            animation: fadeInUp 0.5s ease-out;
        }
        
        .metric-card:nth-child(1) { animation-delay: 0s; }
        .metric-card:nth-child(2) { animation-delay: 0.1s; }
        .metric-card:nth-child(3) { animation-delay: 0.2s; }
        .metric-card:nth-child(4) { animation-delay: 0.3s; }
        .metric-card:nth-child(5) { animation-delay: 0.4s; }
        .metric-card:nth-child(6) { animation-delay: 0.5s; }
    
        .trend {
            font-size: 11px;
            font-weight: 600;
            padding: 2px 6px;
            border-radius: 4px;
            margin-right: 6px;
            display: inline-block;
        }
        .trend-up {
            color: #059669;
            background: #d1fae5;
        }
        .trend-down {
            color: #dc2626;
            background: #fee2e2;
        }
    
        .btn-approve {
            background: #dcfce7;
            color: #059669;
            border: 1px solid #86efac;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-approve:hover { background: #bbf7d0; }
        
        .btn-reject {
            background: #fee2e2;
            color: #dc2626;
            border: 1px solid #fca5a5;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-reject:hover { background: #fecaca; }


        /* Modal Styles */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.5);
            backdrop-filter: blur(4px);
        }
        
        .modal-content {
            background: var(--card);
            margin: 80px auto;
            padding: 32px;
            border-radius: 16px;
            max-width: 600px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.2);
            position: relative;
        }
        
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
        }
        
        .modal-title {
            font-size: 18px;
            font-weight: 600;
        }
        
        .modal-close {
            background: none;
            border: none;
            font-size: 24px;
            cursor: pointer;
            color: var(--text-muted);
            padding: 0;
            width: 32px;
            height: 32px;
        }
        
        .modal-user-info {
            font-size: 13px;
            color: var(--text-muted);
            margin-bottom: 24px;
        }
        
        .modal-section {
            margin-bottom: 24px;
        }
        
        .modal-section-label {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            margin-bottom: 12px;
        }
        
        .label-wrong {
            background: #fee2e2;
            color: #dc2626;
        }
        
        .label-correct {
            background: #dcfce7;
            color: #059669;
        }
        
        .modal-text {
            background: var(--bg);
            padding: 16px;
            border-radius: 8px;
            font-size: 14px;
            line-height: 1.6;
            border: 1px solid var(--border);
        }
        
        .modal-textarea {
            width: 100%;
            min-height: 120px;
            padding: 16px;
            border: 1px solid var(--border);
            border-radius: 8px;
            font-size: 14px;
            font-family: inherit;
            resize: vertical;
            background: var(--bg);
        }
        
        .modal-actions {
            display: flex;
            gap: 12px;
            justify-content: flex-end;
            margin-top: 24px;
        }
        
        .btn-cancel {
            background: white;
            color: var(--text);
            border: 1px solid var(--border);
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
        }
        
        .btn-reject-modal {
            background: white;
            color: #dc2626;
            border: 1px solid #fca5a5;
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
        }
        
        .btn-approve-modal {
            background: #f59e0b;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
        }
        .btn-approve-modal:hover {
            background: #d97706;
        }

    </style>
</head>
<body>
    <aside class="sidebar" id="sidebar">
        <div class="sidebar-header">
            <div class="logo">B</div>
            <span class="sidebar-title">Beacon</span>
        </div>
        <nav class="nav">
            <a href="/dashboard" class="nav-item {{ 'active' if active_page == 'analytics' }}">
                <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
                <span class="nav-label">Analytics</span>
            </a>
            <a href="/conversations" class="nav-item {{ 'active' if active_page == 'conversations' }}">
                <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
                <span class="nav-label">Conversations</span>
            </a>
            <a href="/feedback-page" class="nav-item {{ 'active' if active_page == 'feedback' }}">
                <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                </svg>
                <span class="nav-label">Feedback</span>
            </a>
            <a href="/content-intelligence" class="nav-item {{ 'active' if active_page == 'content' }}">
                <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                </svg>
                <span class="nav-label">Content Engine</span>
            </a>
            <a href="/roadmap-page" class="nav-item {{ 'active' if active_page == 'roadmap' }}">
                <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
                </svg>
                <span class="nav-label">Roadmap</span>
            </a>
        </nav>
        
        <div class="sidebar-footer">
            <button class="footer-btn" onclick="toggleDarkMode()">
                <svg class="nav-icon" id="theme-icon-light" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                </svg>
                <svg class="nav-icon" id="theme-icon-dark" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="display:none;">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
                </svg>
                <span class="nav-label" id="theme-label">Dark Mode</span>
            </button>
            
            <button class="footer-btn" onclick="toggleSidebar()">
                <svg class="nav-icon" id="collapse-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
                </svg>
            </button>
        </div>
    </aside>
    
    <main class="main">
        {% block content %}{% endblock %}
    </main>
    
    
    <!-- Feedback Review Modal -->
    <div id="feedback-modal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <div class="modal-title">Review Suggestion</div>
                <button class="modal-close" onclick="closeFeedbackModal()">×</button>
            </div>
            
            <div class="modal-user-info" id="modal-user-info"></div>
            
            <div class="modal-section">
                <div class="modal-section-label label-wrong">BEACON GAVE THIS WRONG ANSWER</div>
                <div class="modal-text" id="modal-wrong-answer"></div>
            </div>
            
            <div class="modal-section">
                <div class="modal-section-label label-correct">EDIT CORRECT ANSWER</div>
                <textarea class="modal-textarea" id="modal-correct-answer"></textarea>
            </div>
            
            <div class="modal-actions">
                <button class="btn-cancel" onclick="closeFeedbackModal()">Cancel</button>
                <button class="btn-reject-modal" onclick="rejectFromModal()">Reject</button>
                <button class="btn-approve-modal" onclick="approveFromModal()">Edit & Approve</button>
            </div>
        </div>
    </div>

<script>
        function toggleSidebar() {
            const sidebar = document.getElementById('sidebar');
            sidebar.classList.toggle('collapsed');
            
            const icon = document.getElementById('collapse-icon');
            const path = icon.querySelector('path');
            
            if (sidebar.classList.contains('collapsed')) {
                path.setAttribute('d', 'M9 5l7 7-7 7');
            } else {
                path.setAttribute('d', 'M15 19l-7-7 7-7');
            }
        }
        
        function toggleDarkMode() {
            document.body.classList.toggle('dark');
            const isDark = document.body.classList.contains('dark');
            
            document.getElementById('theme-icon-light').style.display = isDark ? 'none' : 'block';
            document.getElementById('theme-icon-dark').style.display = isDark ? 'block' : 'none';
            document.getElementById('theme-label').textContent = isDark ? 'Light Mode' : 'Dark Mode';
            
            localStorage.setItem('darkMode', isDark);
        }
        
        if (localStorage.getItem('darkMode') === 'true') {
            toggleDarkMode();
        }
        
        function showTab(tabName) {
            // Hide all tab contents
            document.querySelectorAll('.tab-content').forEach(el => {
                el.classList.remove('active');
            });
            
            // Remove active from all tab buttons
            document.querySelectorAll('.tab').forEach(btn => {
                btn.classList.remove('active');
            });
            
            // Show selected tab content
            const selectedContent = document.getElementById(tabName + '-tab');
            if (selectedContent) {
                selectedContent.classList.add('active');
            }
            
            // Mark clicked tab as active
            event.target.classList.add('active');
        }
        
        {% block extra_js %}{% endblock %}
    </script>
</body>
</html>'''

DASHBOARD_V2_HTML = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''{% block content %}
<div class="page-header" style="display: flex; justify-content: space-between; align-items: flex-start;">
    <div>
        <div class="page-title">
            <svg width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" style="color: var(--primary);"><path stroke-linecap="round" stroke-linejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z"/></svg>
            Analytics
        </div>
        <div class="page-subtitle">Beacon bot performance &middot; Auto-refreshes every 30 seconds</div>
    </div>
    <div style="display: flex; gap: 8px; align-items: center;">
        <select id="date-range" style="padding: 8px 14px; border: 1px solid var(--border); border-radius: 8px; background: var(--card); font-size: 13px; font-family: 'Inter', sans-serif; cursor: pointer; color: var(--text);">
            <option value="7">Last 7 Days</option>
            <option value="30">Last 30 Days</option>
            <option value="90">Last 90 Days</option>
            <option value="this_month">This Month</option>
            <option value="last_month">Last Month</option>
            <option value="this_year">This Year</option>
            <option value="all">All Time</option>
        </select>
        <button onclick="window.location.reload()" class="btn" style="background: var(--card); color: var(--text); border: 1px solid var(--border); display: flex; align-items: center; gap: 6px; font-family: 'Inter', sans-serif;">
            <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
            Refresh
        </button>
    </div>
</div>

<!-- AI Insights Section -->
<div class="mb-6" id="insights-section">
    <div class="section-label">
        <svg width="16" height="16" fill="none" stroke="var(--primary)" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z"/></svg>
        AI Insights
    </div>
    <div class="grid" style="grid-template-columns: repeat(3, 1fr);" id="insights-grid">
        <!-- Populated by JS -->
    </div>
</div>

<div class="grid mb-6" style="grid-template-columns: repeat(3, 1fr);">
    <div class="metric-card">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
            <div class="metric-icon" style="background: linear-gradient(135deg, #fef3c7, #fde68a);">
                <svg width="20" height="20" fill="none" stroke="#d97706" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/></svg>
            </div>
            <span id="total-questions-trend" class="trend-up"></span>
        </div>
        <div class="metric-value" id="total-questions">-</div>
        <div class="metric-label">Total Questions</div>
    </div>

    <div class="metric-card">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
            <div class="metric-icon" style="background: linear-gradient(135deg, #dcfce7, #bbf7d0);">
                <svg width="20" height="20" fill="none" stroke="#16a34a" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
            </div>
        </div>
        <div class="metric-value" id="success-rate">-</div>
        <div class="metric-label">Success Rate</div>
        <div class="metric-sublabel" id="answered-count">-</div>
    </div>

    <div class="metric-card">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
            <div class="metric-icon" style="background: linear-gradient(135deg, #dbeafe, #bfdbfe);">
                <svg width="20" height="20" fill="none" stroke="#2563eb" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z"/></svg>
            </div>
        </div>
        <div class="metric-value" id="active-users">-</div>
        <div class="metric-label">Active Users</div>
    </div>
</div>

<div class="grid mb-6" style="grid-template-columns: repeat(3, 1fr);">
    <div class="metric-card">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
            <div class="metric-icon" style="background: linear-gradient(135deg, #fef3c7, #fde68a);">
                <svg width="20" height="20" fill="none" stroke="#d97706" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6v12m-3-2.818l.879.659c1.171.879 3.07.879 4.242 0 1.172-.879 1.172-2.303 0-3.182C13.536 12.219 12.768 12 12 12c-.725 0-1.45-.22-2.003-.659-1.106-.879-1.106-2.303 0-3.182s2.9-.879 4.006 0l.415.33M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
            </div>
        </div>
        <div class="metric-value" id="api-cost">$0.00</div>
        <div class="metric-label">API Cost</div>
    </div>

    <div class="metric-card">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
            <div class="metric-icon" style="background: linear-gradient(135deg, #e0e7ff, #c7d2fe);">
                <svg width="20" height="20" fill="none" stroke="#4f46e5" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
            </div>
        </div>
        <div class="metric-value" id="avg-time">0s</div>
        <div class="metric-label">Avg Response Time</div>
        <div class="metric-sublabel" id="time-range"></div>
    </div>

    <div class="metric-card">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
            <div class="metric-icon" style="background: linear-gradient(135deg, #fce7f3, #fbcfe8);">
                <svg width="20" height="20" fill="none" stroke="#db2777" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M11.35 3.836c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m8.9-4.414c.376.023.75.05 1.124.08 1.131.094 1.976 1.057 1.976 2.192V16.5A2.25 2.25 0 0118 18.75h-2.25m-7.5-10.5H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V18.75m-7.5-10.5h6.375c.621 0 1.125.504 1.125 1.125v9.375m-8.25-3l1.5 1.5 3-3.75"/></svg>
            </div>
        </div>
        <div class="metric-value" id="pending-reviews">0</div>
        <div class="metric-label">Pending Reviews</div>
        <div class="metric-sublabel" id="feedback-count">0 new</div>
    </div>
</div>

<div class="card mb-6">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
        <div>
            <h3 style="font-family: 'JetBrains Mono', monospace; font-size: 15px; font-weight: 600;">Recent Conversations</h3>
            <p style="font-size: 12px; color: var(--text-muted); margin-top: 2px;">Last 10 questions asked to Beacon</p>
        </div>
    </div>
    <table id="conversations-table">
        <thead>
            <tr>
                <th>Question</th>
                <th>User</th>
                <th>Topic</th>
                <th>When</th>
                <th>Status</th>
            </tr>
        </thead>
        <tbody></tbody>
    </table>
</div>

<!-- Usage Chart -->
<div class="grid mb-6" style="grid-template-columns: 3fr 2fr;">
    <div class="card">
        <h3 style="font-family: 'JetBrains Mono', monospace; font-size: 14px; font-weight: 600; margin-bottom: 2px;">Daily Usage</h3>
        <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 24px;">Questions asked over the selected period</p>
        <div style="height: 256px; position: relative;">
            <canvas id="usage-chart"></canvas>
        </div>
    </div>
    <div class="card">
        <h3 style="font-family: 'JetBrains Mono', monospace; font-size: 14px; font-weight: 600; margin-bottom: 2px;">Questions by Topic</h3>
        <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 24px;">Distribution across knowledge areas</p>
        <div id="topics-breakdown"></div>
    </div>
</div>

<!-- Bottom Row -->
<div class="grid grid-2">
    <div class="card">
        <h3 style="font-family: 'JetBrains Mono', monospace; font-size: 14px; font-weight: 600; margin-bottom: 2px;">Slash Command Usage</h3>
        <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 24px;">Commands used by team members</p>
        <div id="slash-commands"></div>
    </div>
    <div class="card">
        <h3 style="font-family: 'JetBrains Mono', monospace; font-size: 14px; font-weight: 600; margin-bottom: 2px;">Top Users</h3>
        <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 24px;">Most active team members</p>
        <div id="top-users"></div>
    </div>
</div>

<script>
let usageChart = null;
const topicColors = ['#f59e0b', '#3b82f6', '#22c55e', '#8b5cf6', '#ef4444', '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1'];

function calculateTrend(current, previous) {
    if (!previous || previous === 0) return '';
    const change = ((current - previous) / previous) * 100;
    const arrow = change >= 0 ? '↑' : '↓';
    const className = change >= 0 ? 'trend-up' : 'trend-down';
    return `<span class="trend ${className}">${arrow}${Math.abs(change).toFixed(1)}%</span>`;
}

function generateInsights(data) {
    const insights = [];
    const successRate = data.success_rate || 0;
    const totalQ = data.total_questions || 0;
    const pending = data.pending_suggestions || 0;

    if (successRate >= 90) {
        insights.push({ type: 'success', icon: 'trending-up', title: `${successRate}% success rate`, desc: 'Beacon is performing well across all topics this period.' });
    } else if (successRate < 75 && successRate > 0) {
        insights.push({ type: 'warning', icon: 'alert', title: `Success rate at ${successRate}%`, desc: 'Consider reviewing failed queries and updating knowledge base articles.' });
    }

    if (pending > 0) {
        insights.push({ type: 'warning', icon: 'clipboard', title: `${pending} corrections pending`, desc: 'Team members submitted corrections that need your review.' });
    }

    const topics = data.topics || [];
    if (topics.length > 0) {
        const top = topics[0];
        insights.push({ type: 'info', icon: 'trending-up', title: `"${top.topic}" is most asked`, desc: `${top.count} questions on this topic — make sure KB coverage is thorough.` });
    }

    if (totalQ === 0) {
        insights.push({ type: 'info', icon: 'info', title: 'No questions yet', desc: "Beacon has not received any questions in this period." });
    }

    const grid = document.getElementById('insights-grid');
    grid.innerHTML = '';

    const iconSvgs = {
        'trending-up': '<svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M2.25 18L9 11.25l4.306 4.307a11.95 11.95 0 015.814-5.519l2.74-1.22m0 0l-5.94-2.28m5.94 2.28l-2.28 5.941"/></svg>',
        'alert': '<svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/></svg>',
        'clipboard': '<svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M11.35 3.836c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m8.9-4.414c.376.023.75.05 1.124.08 1.131.094 1.976 1.057 1.976 2.192V16.5A2.25 2.25 0 0118 18.75h-2.25m-7.5-10.5H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V18.75m-7.5-10.5h6.375c.621 0 1.125.504 1.125 1.125v9.375m-8.25-3l1.5 1.5 3-3.75"/></svg>',
        'info': '<svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z"/></svg>'
    };

    const colorMap = { warning: '#f59e0b', success: '#22c55e', info: '#3b82f6' };

    insights.forEach(ins => {
        const color = colorMap[ins.type] || '#3b82f6';
        grid.innerHTML += `
            <div class="insight-card insight-${ins.type}">
                <div style="display: flex; gap: 12px; align-items: flex-start;">
                    <div class="insight-icon" style="color: ${color};">${iconSvgs[ins.icon] || iconSvgs['info']}</div>
                    <div style="flex: 1; min-width: 0;">
                        <div class="insight-title">${ins.title}</div>
                        <div class="insight-desc">${ins.desc}</div>
                    </div>
                </div>
            </div>
        `;
    });

    // Hide section if no insights
    document.getElementById('insights-section').style.display = insights.length ? 'block' : 'none';
}

function renderUsageChart(dailyUsage, conversations) {
    const ctx = document.getElementById('usage-chart');
    if (!ctx) return;

    // Use server-computed daily_usage if available, else fall back to conversations
    const dailyCounts = {};
    if (dailyUsage && dailyUsage.length > 0) {
        dailyUsage.forEach(d => { dailyCounts[d.date] = d.count; });
    } else {
        (conversations || []).forEach(c => {
            if (!c.timestamp) return;
            const date = c.timestamp.includes('T') ? c.timestamp.split('T')[0] : c.timestamp.split(' ')[0];
            dailyCounts[date] = (dailyCounts[date] || 0) + 1;
        });
    }

    // Fill last 14 days
    const labels = [];
    const dataPoints = [];
    for (let i = 13; i >= 0; i--) {
        const d = new Date();
        d.setDate(d.getDate() - i);
        const key = d.toISOString().split('T')[0];
        const label = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        labels.push(label);
        dataPoints.push(dailyCounts[key] || 0);
    }

    if (usageChart) usageChart.destroy();

    usageChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: 'Questions',
                data: dataPoints,
                borderColor: '#f59e0b',
                backgroundColor: 'rgba(245, 158, 11, 0.1)',
                fill: true,
                tension: 0.4,
                borderWidth: 2,
                pointRadius: 0,
                pointHoverRadius: 5,
                pointHoverBackgroundColor: '#f59e0b'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#fff',
                    titleColor: '#0f172a',
                    bodyColor: '#64748b',
                    borderColor: '#e2e8f0',
                    borderWidth: 1,
                    padding: 12,
                    cornerRadius: 8,
                    titleFont: { family: 'Inter', size: 13, weight: '600' },
                    bodyFont: { family: 'Inter', size: 12 },
                    boxShadow: '0 4px 12px rgba(0,0,0,0.08)'
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { font: { family: 'Inter', size: 11 }, color: '#94a3b8' },
                    border: { display: false }
                },
                y: {
                    grid: { color: '#e2e8f0', drawBorder: false },
                    ticks: { font: { family: 'Inter', size: 11 }, color: '#94a3b8', stepSize: 1 },
                    border: { display: false },
                    beginAtZero: true
                }
            },
            interaction: { intersect: false, mode: 'index' }
        }
    });
}

async function loadDashboardData() {
    try {
        const days = document.getElementById('date-range')?.value || 7;
        const response = await fetch(`/api/dashboard?days=${days}`);
        const data = await response.json();

        // Generate AI Insights
        generateInsights(data);

        document.getElementById('total-questions').textContent = data.total_questions || 0;
        document.getElementById('success-rate').textContent = data.success_rate ? data.success_rate + '%' : '0%';
        document.getElementById('answered-count').textContent = (data.answered || 0) + ' answered';
        document.getElementById('active-users').textContent = data.active_users || 0;
        document.getElementById('api-cost').textContent = '$' + (data.total_cost_usd || '0.00');
        document.getElementById('avg-time').textContent = data.response_time && data.response_time.avg_ms ? (data.response_time.avg_ms / 1000).toFixed(1) + 's' : '0s';
        document.getElementById('pending-reviews').textContent = data.pending_suggestions || 0;
        document.getElementById('feedback-count').textContent = (data.new_feedback || 0) + ' new feedback';

        // Render usage chart (prefer server-computed daily_usage)
        renderUsageChart(data.daily_usage, data.conversations);

        const tbody = document.querySelector('#conversations-table tbody');
        tbody.innerHTML = '';
        (data.conversations || []).slice(0, 10).forEach(conv => {
            const row = tbody.insertRow();
            row.innerHTML = `
                <td><strong>${conv.question || 'N/A'}</strong></td>
                <td>${conv.user_name || 'Unknown'}</td>
                <td><span class="badge badge-warning">${conv.topic || 'General'}</span></td>
                <td style="color: var(--text-muted); font-size: 12px;">${conv.timestamp || ''}</td>
                <td><span class="badge ${conv.answered ? 'badge-success' : 'badge-danger'}">${conv.answered ? 'Answered' : 'Failed'}</span></td>
            `;
        });

        const topicsDiv = document.getElementById('topics-breakdown');
        topicsDiv.innerHTML = '';
        const totalQ = data.total_questions || 1;
        (data.topics || []).forEach((t, i) => {
            const pct = Math.round((t.count / totalQ) * 100);
            const color = topicColors[i % topicColors.length];
            topicsDiv.innerHTML += `
                <div style="margin-bottom: 12px;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                        <span style="font-size: 13px; font-weight: 500;">${t.topic}</span>
                        <span style="font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-muted);">${t.count} <span style="opacity: 0.5;">(${pct}%)</span></span>
                    </div>
                    <div style="height: 8px; background: var(--bg); border-radius: 4px; overflow: hidden;">
                        <div style="height: 100%; width: ${pct}%; background: ${color}; border-radius: 4px; transition: width 0.6s ease;"></div>
                    </div>
                </div>
            `;
        });

        const slashDiv = document.getElementById('slash-commands');
        slashDiv.innerHTML = '';
        (data.command_usage || []).forEach((cmd, i) => {
            const pct = Math.round((cmd.count / totalQ) * 100);
            const color = topicColors[(i + 3) % topicColors.length];
            slashDiv.innerHTML += `
                <div style="margin-bottom: 12px;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                        <span style="font-size: 13px; font-weight: 500; font-family: 'JetBrains Mono', monospace;">/${cmd.command}</span>
                        <span style="font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-muted);">${cmd.count} <span style="opacity: 0.5;">(${pct}%)</span></span>
                    </div>
                    <div style="height: 8px; background: var(--bg); border-radius: 4px; overflow: hidden;">
                        <div style="height: 100%; width: ${pct}%; background: ${color}; border-radius: 4px; transition: width 0.6s ease;"></div>
                    </div>
                </div>
            `;
        });

        // Top users
        const usersDiv = document.getElementById('top-users');
        if (usersDiv) {
            usersDiv.innerHTML = '';
            const userCounts = {};
            (data.conversations || []).forEach(c => {
                const name = c.user_name || 'Unknown';
                userCounts[name] = (userCounts[name] || 0) + 1;
            });
            const sorted = Object.entries(userCounts).sort((a, b) => b[1] - a[1]).slice(0, 5);
            const maxU = sorted.length > 0 ? sorted[0][1] : 1;
            sorted.forEach(([name, count], i) => {
                const pct = Math.round((count / maxU) * 100);
                usersDiv.innerHTML += `
                    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 12px;">
                        <div style="width: 28px; height: 28px; border-radius: 50%; background: linear-gradient(135deg, ${topicColors[i % topicColors.length]}44, ${topicColors[i % topicColors.length]}22); display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 600; color: ${topicColors[i % topicColors.length]}; flex-shrink: 0;">${name.charAt(0).toUpperCase()}</div>
                        <div style="flex: 1; min-width: 0;">
                            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                                <span style="font-size: 13px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${name}</span>
                                <span style="font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-muted);">${count}</span>
                            </div>
                            <div style="height: 4px; background: var(--bg); border-radius: 2px; overflow: hidden;">
                                <div style="height: 100%; width: ${pct}%; background: ${topicColors[i % topicColors.length]}; border-radius: 2px;"></div>
                            </div>
                        </div>
                    </div>
                `;
            });
            if (sorted.length === 0) {
                usersDiv.innerHTML = '<div style="text-align: center; padding: 20px; color: var(--text-muted); font-size: 13px;">No user data yet</div>';
            }
        }
    } catch (error) {
        console.error('Failed to load dashboard data:', error);
    }
}

loadDashboardData();
setInterval(loadDashboardData, 30000);

// Listen for date range changes
document.getElementById('date-range')?.addEventListener('change', loadDashboardData);
</script>
{% endblock %}''')

CONVERSATIONS_PAGE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''{% block content %}
<div class="page-header">
    <div class="page-title">
        <svg width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" style="color: var(--primary);"><path stroke-linecap="round" stroke-linejoin="round" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155"/></svg>
        Conversations
    </div>
    <div class="page-subtitle">Browse all questions answered by Beacon</div>
</div>

<div class="section">
    <table>
        <thead>
            <tr>
                <th>Question</th>
                <th>User</th>
                <th>Topic</th>
                <th>When</th>
                <th>Response Time</th>
                <th>Status</th>
            </tr>
        </thead>
        <tbody>
            {% for conv in conversations %}
            <tr>
                <td><strong>{{ conv.question }}</strong></td>
                <td>{{ conv.user_name }}</td>
                <td><span class="badge badge-warning">{{ conv.topic or 'General' }}</span></td>
                <td style="color: var(--text-muted); font-size: 12px;">{{ conv.timestamp }}</td>
                <td style="font-family: monospace;">{{ "%.1f"|format(conv.response_time_ms / 1000) }}s</td>
                <td><span class="badge badge-success">✓ Answered</span></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}''')

# Feedback page with tabs

FEEDBACK_PAGE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''{% block content %}
<div class="page-header">
    <div class="page-title">
        <svg width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" style="color: var(--primary);"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
        Feedback & Corrections
    </div>
    <div class="page-subtitle">Review team suggestions and correction history</div>
</div>

<div class="tabs mb-6">
    <button class="tab active" onclick="showTab('pending')">Pending Review <span style="background: #fef3c7; color: #f59e0b; padding: 2px 8px; border-radius: 12px; font-size: 10px; font-weight: 600; margin-left: 4px;">{{ suggestions|length }}</span></button>
    <button class="tab" onclick="showTab('approved')">Approved History</button>
    <button class="tab" onclick="showTab('digests')">Weekly Digests</button>
</div>

<!-- Pending Review Tab -->
<div id="pending-tab" class="tab-content active">
    <div class="section">
        {% if suggestions|length > 0 %}
        <table>
            <thead>
                <tr>
                    <th>USER</th>
                    <th>WHEN</th>
                    <th>WRONG ANSWER</th>
                    <th>CORRECT ANSWER</th>
                    <th>ACTIONS</th>
                </tr>
            </thead>
            <tbody>
                {% for s in suggestions %}
                <tr style="cursor: pointer;" onclick="openFeedbackModal({{ s.id }}, {{ s.user_name|tojson }}, {{ s.timestamp|tojson }}, {{ s.wrong_answer|tojson }}, {{ s.correct_answer|tojson }})">
                    <td><strong>{{ s.user_name }}</strong></td>
                    <td style="color: var(--text-muted); font-size: 12px;">{{ s.timestamp }}</td>
                    <td style="font-size: 13px;">
                        <span class="badge badge-danger" style="font-size: 11px; margin-bottom: 4px;">Wrong</span>
                        <div style="color: var(--text-muted);">{{ s.wrong_answer[:100] }}{% if s.wrong_answer|length > 100 %}...{% endif %}</div>
                    </td>
                    <td style="font-size: 13px;">
                        <span class="badge badge-success" style="font-size: 11px; margin-bottom: 4px;">Correct</span>
                        <div style="color: var(--text-muted);">{{ s.correct_answer[:100] }}{% if s.correct_answer|length > 100 %}...{% endif %}</div>
                    </td>
                    <td>
                        <button class="btn-approve" style="margin-right: 8px;" onclick="event.stopPropagation(); approveSuggestion({{ s.id }})">✓ Approve</button>
                        <button class="btn-reject" onclick="event.stopPropagation(); rejectSuggestion({{ s.id }})">✗ Reject</button>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <div style="text-align: center; padding: 60px 20px; color: var(--text-muted);">
            <svg width="48" height="48" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="margin: 0 auto 16px;">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <div style="font-size: 16px; font-weight: 600; margin-bottom: 8px;">No pending suggestions</div>
            <div style="font-size: 14px;">Team corrections will appear here</div>
        </div>
        {% endif %}
    </div>
</div>

<!-- Approved History Tab -->
<div id="approved-tab" class="tab-content">
    <div class="section">
        {% if approved_suggestions|length > 0 %}
        <table>
            <thead>
                <tr>
                    <th>USER</th>
                    <th>APPROVED BY</th>
                    <th>WHEN</th>
                    <th>CORRECTION</th>
                </tr>
            </thead>
            <tbody>
                {% for s in approved_suggestions %}
                <tr>
                    <td><strong>{{ s.user_name }}</strong></td>
                    <td>{{ s.reviewed_by }}</td>
                    <td>{{ s.reviewed_at }}</td>
                    <td>
                        <div style="margin-bottom: 8px;"><span style="color: var(--danger);">✗</span> {{ s.wrong_answer[:100] }}...</div>
                        <div><span style="color: var(--success);">✓</span> {{ s.correct_answer[:100] }}...</div>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <div style="text-align: center; padding: 60px 20px; color: var(--text-muted);">
            <div style="font-size: 16px; font-weight: 600; margin-bottom: 8px;">No approved corrections yet</div>
        </div>
        {% endif %}
    </div>
</div>

<!-- Weekly Digests Tab -->
<div id="digests-tab" class="tab-content">
    <div class="section">
        <div style="text-align: center; padding: 60px 20px; color: var(--text-muted);">
            <div style="font-size: 16px; font-weight: 600; margin-bottom: 8px;">Weekly digest emails</div>
            <div style="font-size: 14px;">Coming soon</div>
        </div>
    </div>
</div>

<script>

let currentFeedbackId = null;

function openFeedbackModal(id, userName, timestamp, wrongAnswer, correctAnswer) {
    currentFeedbackId = id;
    document.getElementById('modal-user-info').textContent = `${userName} · ${timestamp}`;
    document.getElementById('modal-wrong-answer').textContent = wrongAnswer;
    document.getElementById('modal-correct-answer').value = correctAnswer;
    document.getElementById('feedback-modal').style.display = 'block';
}

function closeFeedbackModal() {
    document.getElementById('feedback-modal').style.display = 'none';
    currentFeedbackId = null;
}

async function approveFromModal() {
    if (!currentFeedbackId) return;
    
    const editedAnswer = document.getElementById('modal-correct-answer').value;
    
    try {
        const response = await fetch(`/api/suggestions/${currentFeedbackId}/approve`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({correct_answer: editedAnswer})
        });
        
        if (response.ok) {
            closeFeedbackModal();
            location.reload();
        } else {
            alert('Error approving suggestion');
        }
    } catch (error) {
        alert('Error: ' + error.message);
    }
}

async function rejectFromModal() {
    if (!currentFeedbackId || !confirm('Reject this suggestion?')) return;
    
    try {
        const response = await fetch(`/api/suggestions/${currentFeedbackId}/reject`, {
            method: 'POST'
        });
        
        if (response.ok) {
            closeFeedbackModal();
            location.reload();
        } else {
            alert('Error rejecting suggestion');
        }
    } catch (error) {
        alert('Error: ' + error.message);
    }
}

// Close modal when clicking outside
window.onclick = function(event) {
    const modal = document.getElementById('feedback-modal');
    if (event.target === modal) {
        closeFeedbackModal();
    }
}


async function approveSuggestion(id) {
    if (!confirm('Approve this correction?')) return;
    try {
        const response = await fetch(`/api/suggestions/${id}/approve`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: id})
        });
        if (response.ok) {
            location.reload();
        }
    } catch (error) {
        alert('Error approving suggestion');
    }
}

async function rejectSuggestion(id) {
    if (!confirm('Reject this correction?')) return;
    try {
        const response = await fetch(`/api/suggestions/${id}/reject`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: id})
        });
        if (response.ok) {
            location.reload();
        }
    } catch (error) {
        alert('Error rejecting suggestion');
    }
}

function showTab(tabName) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(btn => btn.classList.remove('active'));
    document.getElementById(tabName + '-tab').classList.add('active');
    event.target.classList.add('active');
}
</script>
{% endblock %}''')

# Roadmap page with status summary cards

ROADMAP_PAGE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''{% block content %}
<div class="page-header" style="display: flex; justify-content: space-between; align-items: flex-start;">
    <div>
        <div class="page-title"><svg width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" style="color: var(--primary);"><path stroke-linecap="round" stroke-linejoin="round" d="M9 6.75V15m6-6v8.25m.503 3.498l4.875-2.437c.381-.19.622-.58.622-1.006V4.82c0-.836-.88-1.38-1.628-1.006l-3.869 1.934c-.317.159-.69.159-1.006 0L9.503 3.252a1.125 1.125 0 00-1.006 0L3.622 5.689C3.24 5.88 3 6.27 3 6.695V19.18c0 .836.88 1.38 1.628 1.006l3.869-1.934c.317-.159.69-.159 1.006 0l4.994 2.497c.317.158.69.158 1.006 0z"/></svg> Roadmap</div>
        <div class="page-subtitle">Track feature requests and development progress</div>
    </div>
    <button class="btn btn-primary" onclick="openNewItemModal()" style="white-space: nowrap;">+ New Item</button>
</div>

<!-- New Roadmap Item Modal -->
<div id="new-item-modal" class="modal" style="display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); z-index: 999; display: none; align-items: center; justify-content: center;">
    <div style="background: var(--card); border-radius: 12px; padding: 32px; max-width: 500px; width: 90%; margin: auto; position: relative; top: 50%; transform: translateY(-50%);">
        <h3 style="font-size: 18px; font-weight: 600; margin-bottom: 20px;">New Roadmap Item</h3>
        <div style="margin-bottom: 16px;">
            <label style="display: block; font-size: 13px; font-weight: 500; margin-bottom: 6px; color: var(--text-muted);">Title *</label>
            <input id="ri-title" type="text" placeholder="e.g. Add multi-language support" style="width: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; font-size: 14px; background: var(--bg); color: var(--text);">
        </div>
        <div style="display: flex; gap: 12px; margin-bottom: 16px;">
            <div style="flex: 1;">
                <label style="display: block; font-size: 13px; font-weight: 500; margin-bottom: 6px; color: var(--text-muted);">Priority</label>
                <select id="ri-priority" style="width: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; font-size: 14px; background: var(--bg); color: var(--text);">
                    <option value="low">Low</option>
                    <option value="medium" selected>Medium</option>
                    <option value="high">High</option>
                </select>
            </div>
            <div style="flex: 1;">
                <label style="display: block; font-size: 13px; font-weight: 500; margin-bottom: 6px; color: var(--text-muted);">Status</label>
                <select id="ri-status" style="width: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; font-size: 14px; background: var(--bg); color: var(--text);">
                    <option value="backlog" selected>Backlog</option>
                    <option value="planned">Planned</option>
                    <option value="in-progress">In Progress</option>
                    <option value="shipped">Shipped</option>
                </select>
            </div>
        </div>
        <div style="margin-bottom: 16px;">
            <label style="display: block; font-size: 13px; font-weight: 500; margin-bottom: 6px; color: var(--text-muted);">Target Quarter</label>
            <input id="ri-quarter" type="text" placeholder="e.g. Q2 2026" style="width: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; font-size: 14px; background: var(--bg); color: var(--text);">
        </div>
        <div style="margin-bottom: 20px;">
            <label style="display: block; font-size: 13px; font-weight: 500; margin-bottom: 6px; color: var(--text-muted);">Notes</label>
            <textarea id="ri-notes" rows="3" placeholder="Optional details..." style="width: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; font-size: 14px; background: var(--bg); color: var(--text); resize: vertical;"></textarea>
        </div>
        <div style="display: flex; justify-content: flex-end; gap: 8px;">
            <button class="btn btn-outline" onclick="closeNewItemModal()">Cancel</button>
            <button class="btn btn-primary" onclick="createRoadmapItem()">Create Item</button>
        </div>
    </div>
</div>

<div class="grid grid-4 mb-6">
    <div class="card" style="text-align: center;">
        <div style="font-family: 'JetBrains Mono', monospace; font-size: 48px; font-weight: bold; margin-bottom: 8px; color: var(--text);">{{ roadmap.by_status.get('shipped', 0) }}</div>
        <div style="font-size: 13px; color: var(--text-muted); display: flex; align-items: center; justify-content: center; gap: 6px;"><svg width="14" height="14" fill="none" stroke="#22c55e" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg> Shipped</div>
    </div>
    <div class="card" style="text-align: center;">
        <div style="font-family: 'JetBrains Mono', monospace; font-size: 48px; font-weight: bold; margin-bottom: 8px; color: var(--text);">{{ roadmap.by_status.get('in-progress', 0) }}</div>
        <div style="font-size: 13px; color: var(--text-muted); display: flex; align-items: center; justify-content: center; gap: 6px;"><svg width="14" height="14" fill="none" stroke="#f59e0b" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z"/></svg> In Progress</div>
    </div>
    <div class="card" style="text-align: center;">
        <div style="font-family: 'JetBrains Mono', monospace; font-size: 48px; font-weight: bold; margin-bottom: 8px; color: var(--text);">{{ roadmap.by_status.get('planned', 0) }}</div>
        <div style="font-size: 13px; color: var(--text-muted); display: flex; align-items: center; justify-content: center; gap: 6px;"><svg width="14" height="14" fill="none" stroke="#3b82f6" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5"/></svg> Planned</div>
    </div>
    <div class="card" style="text-align: center;">
        <div style="font-family: 'JetBrains Mono', monospace; font-size: 48px; font-weight: bold; margin-bottom: 8px; color: var(--text);">{{ roadmap.by_status.get('backlog', 0) }}</div>
        <div style="font-size: 13px; color: var(--text-muted); display: flex; align-items: center; justify-content: center; gap: 6px;"><svg width="14" height="14" fill="none" stroke="#94a3b8" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M3.75 12h16.5m-16.5 3.75h16.5M3.75 19.5h16.5M5.625 4.5h12.75a1.875 1.875 0 010 3.75H5.625a1.875 1.875 0 010-3.75z"/></svg> Backlog</div>
    </div>
</div>

{% if roadmap.items_by_status %}
<div class="grid grid-2">
    {% for status, items in roadmap.items_by_status.items() %}
        {% for item in items %}
        <div class="card" style="cursor: pointer;">
            <div style="margin-bottom: 8px;">
                {% if status == 'shipped' %}
                <span class="badge badge-success">Shipped</span>
                {% elif status == 'in-progress' %}
                <span class="badge badge-warning">In Progress</span>
                {% elif status == 'planned' %}
                <span class="badge" style="background: #dbeafe; color: #3b82f6;">Planned</span>
                {% else %}
                <span class="badge" style="background: #f3f4f6; color: #6b7280;">{{ status|title }}</span>
                {% endif %}
                {% if item.priority %}
                <span class="badge {{ 'badge-danger' if item.priority == 'high' else 'badge-warning' }}" style="margin-left: 4px;">
                    {{ item.priority|title }} Priority
                </span>
                {% endif %}
            </div>
            <h3 style="font-size: 14px; font-weight: 600;">{{ item.feedback_text }}</h3>
            <p style="font-size: 13px; color: var(--text-muted); margin-top: 4px;">
                Requested by {{ item.user_name }}
                {% if item.target_quarter %} · Target: {{ item.target_quarter }}{% endif %}
            </p>
        </div>
        {% endfor %}
    {% endfor %}
</div>
{% else %}
<div class="section" style="text-align: center; padding: 60px 20px; color: var(--text-muted);">
    <svg width="48" height="48" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="margin: 0 auto 16px;">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
    </svg>
    <div style="font-size: 16px; font-weight: 600; margin-bottom: 8px;">No roadmap items yet</div>
    <div style="font-size: 14px;">Feature requests will appear here</div>
</div>
{% endif %}

<script>
// Roadmap page scripts

function openNewItemModal() {
    document.getElementById('new-item-modal').style.display = 'block';
}

function closeNewItemModal() {
    document.getElementById('new-item-modal').style.display = 'none';
}

async function createRoadmapItem() {
    const title = document.getElementById('ri-title').value.trim();
    if (!title) { alert('Title is required'); return; }

    const btn = event.target;
    btn.disabled = true;
    btn.textContent = 'Creating...';

    try {
        const resp = await fetch('/api/roadmap/create', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                title: title,
                priority: document.getElementById('ri-priority').value,
                roadmap_status: document.getElementById('ri-status').value,
                target_quarter: document.getElementById('ri-quarter').value || null,
                notes: document.getElementById('ri-notes').value || null,
            })
        });
        const data = await resp.json();
        if (data.status === 'ok') {
            window.location.reload();
        } else {
            alert('Error: ' + data.message);
        }
    } catch (error) {
        alert('Error: ' + error.message);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Create Item';
    }
}

// Close modal on background click
document.getElementById('new-item-modal')?.addEventListener('click', function(e) {
    if (e.target === this) closeNewItemModal();
});

</script>
{% endblock %}
''')

# Login page
LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Beacon Analytics - Login</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            -webkit-font-smoothing: antialiased;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        .login-card {
            background: white;
            padding: 48px;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            text-align: center;
            max-width: 400px;
        }
        .logo {
            width: 64px;
            height: 64px;
            margin: 0 auto 24px;
            background: linear-gradient(135deg, #f59e0b, #d97706);
            border-radius: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 32px;
            font-weight: bold;
        }
        h1 { color: #2c3e50; margin-bottom: 8px; font-size: 28px; }
        .subtitle { color: #7f8c8d; margin-bottom: 32px; font-size: 14px; }
        .google-btn {
            display: inline-flex;
            align-items: center;
            gap: 12px;
            padding: 12px 24px;
            background: white;
            border: 2px solid #e8ecef;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
            text-decoration: none;
            color: #2c3e50;
        }
        .google-btn:hover { border-color: #3498db; transform: translateY(-2px); }
        .error { color: #e74c3c; margin-top: 20px; padding: 12px; background: #fee; border-radius: 4px; }
    
        .trend {
            font-size: 11px;
            font-weight: 600;
            padding: 2px 6px;
            border-radius: 4px;
            margin-right: 6px;
            display: inline-block;
        }
        .trend-up {
            color: #059669;
            background: #d1fae5;
        }
        .trend-down {
            color: #dc2626;
            background: #fee2e2;
        }
    
        .btn-approve {
            background: #dcfce7;
            color: #059669;
            border: 1px solid #86efac;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-approve:hover { background: #bbf7d0; }
        
        .btn-reject {
            background: #fee2e2;
            color: #dc2626;
            border: 1px solid #fca5a5;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-reject:hover { background: #fecaca; }


        /* Modal Styles */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.5);
            backdrop-filter: blur(4px);
        }
        
        .modal-content {
            background: var(--card);
            margin: 80px auto;
            padding: 32px;
            border-radius: 16px;
            max-width: 600px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.2);
            position: relative;
        }
        
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
        }
        
        .modal-title {
            font-size: 18px;
            font-weight: 600;
        }
        
        .modal-close {
            background: none;
            border: none;
            font-size: 24px;
            cursor: pointer;
            color: var(--text-muted);
            padding: 0;
            width: 32px;
            height: 32px;
        }
        
        .modal-user-info {
            font-size: 13px;
            color: var(--text-muted);
            margin-bottom: 24px;
        }
        
        .modal-section {
            margin-bottom: 24px;
        }
        
        .modal-section-label {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            margin-bottom: 12px;
        }
        
        .label-wrong {
            background: #fee2e2;
            color: #dc2626;
        }
        
        .label-correct {
            background: #dcfce7;
            color: #059669;
        }
        
        .modal-text {
            background: var(--bg);
            padding: 16px;
            border-radius: 8px;
            font-size: 14px;
            line-height: 1.6;
            border: 1px solid var(--border);
        }
        
        .modal-textarea {
            width: 100%;
            min-height: 120px;
            padding: 16px;
            border: 1px solid var(--border);
            border-radius: 8px;
            font-size: 14px;
            font-family: inherit;
            resize: vertical;
            background: var(--bg);
        }
        
        .modal-actions {
            display: flex;
            gap: 12px;
            justify-content: flex-end;
            margin-top: 24px;
        }
        
        .btn-cancel {
            background: white;
            color: var(--text);
            border: 1px solid var(--border);
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
        }
        
        .btn-reject-modal {
            background: white;
            color: #dc2626;
            border: 1px solid #fca5a5;
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
        }
        
        .btn-approve-modal {
            background: #f59e0b;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
        }
        .btn-approve-modal:hover {
            background: #d97706;
        }

    </style>
</head>
<body>
    <div class="login-card">
        <div class="logo">B</div>
        <h1>Beacon Analytics</h1>
        <p class="subtitle">Sign in to access the dashboard</p>
        
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        
        <a href="{{ auth_url }}" class="google-btn">
            <svg width="20" height="20" viewBox="0 0 24 24">
                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
            </svg>
            Sign in with Google
        </a>
    </div>
</body>
</html>
"""

# ============================================================================
# AUTH DECORATOR AND ROUTES
# ============================================================================

def require_auth(f):
    """Decorator to require authentication for routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not OAUTH_CONFIGURED:
            # If OAuth not configured, allow access (development mode)
            return f(*args, **kwargs)
        
        if 'user_email' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function







def require_auth(f):
    """Decorator to require authentication for routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not OAUTH_ENABLED:
            # If OAuth not configured, allow access (development mode)
            return f(*args, **kwargs)
        
        if 'user_email' not in session:
            return redirect(url_for('login'))
        
        # Check if user is authorized
        user_email = session['user_email']
        if user_email not in AUTHORIZED_EMAILS:
            return render_template_string(LOGIN_HTML, 
                error=f"Access denied. {user_email} is not authorized.",
                auth_url=url_for('login'))
        
        return f(*args, **kwargs)
    return decorated_function


def add_dashboard_routes(app, analytics_db: AnalyticsDB):
    """Add OAuth-protected dashboard routes to Flask app."""
    
    @app.route("/login")
    def login():
        """Login page with Google OAuth."""
        if not OAUTH_ENABLED:
            return "OAuth not configured. Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET environment variables."
        
        # Build redirect URI from RAILWAY_PUBLIC_DOMAIN or request host
        public_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", request.host)
        scheme = "https" if "railway" in public_domain or "up.railway.app" in public_domain else request.scheme
        redirect_uri = f"{scheme}://{public_domain}/auth/callback"
        auth_url = (
            f"https://accounts.google.com/o/oauth2/v2/auth?"
            f"client_id={GOOGLE_CLIENT_ID}&"
            f"redirect_uri={redirect_uri}&"
            f"response_type=code&"
            f"scope=openid email profile&"
            f"access_type=offline&"
            f"prompt=select_account"
        )
        
        return render_template_string(LOGIN_HTML, auth_url=auth_url, error=None)
    
    @app.route("/auth/callback")
    def auth_callback():
        """Handle Google OAuth callback."""
        if not OAUTH_ENABLED:
            return "OAuth not configured"
        
        code = request.args.get('code')
        if not code:
            return redirect(url_for('login'))
        
        try:
            # Exchange code for token
            token_url = "https://oauth2.googleapis.com/token"
            public_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", request.host)
            scheme = "https" if "railway" in public_domain or "up.railway.app" in public_domain else request.scheme
            redirect_uri = f"{scheme}://{public_domain}/auth/callback"
            
            token_data = {
                'code': code,
                'client_id': GOOGLE_CLIENT_ID,
                'client_secret': GOOGLE_CLIENT_SECRET,
                'redirect_uri': redirect_uri,
                'grant_type': 'authorization_code'
            }
            
            token_response = requests.post(token_url, data=token_data)
            token_json = token_response.json()
            
            if 'id_token' not in token_json:
                return render_template_string(LOGIN_HTML, 
                    error="Authentication failed. Please try again.",
                    auth_url=url_for('login'))
            
            # Verify ID token
            idinfo = id_token.verify_oauth2_token(
                token_json['id_token'],
                google_requests.Request(),
                GOOGLE_CLIENT_ID
            )
            
            # Store user info in session
            user_email = idinfo['email']
            session['user_email'] = user_email
            session['user_name'] = idinfo.get('name', user_email)
            
            # Check if authorized
            if user_email not in AUTHORIZED_EMAILS:
                return render_template_string(LOGIN_HTML,
                    error=f"Access denied. {user_email} is not authorized to access this dashboard.",
                    auth_url=url_for('login'))
            
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            return render_template_string(LOGIN_HTML,
                error=f"Authentication error: {str(e)}",
                auth_url=url_for('login'))
    
    @app.route("/logout")
    def logout():
        """Logout and clear session."""
        session.clear()
        return redirect(url_for('login'))
    
    @app.route("/dashboard")
    @require_auth
    def dashboard():
        """Main dashboard page (OAuth protected)."""
        user_email = session.get('user_email', 'Unknown')
        return render_template_string(DASHBOARD_V2_HTML, user_email=user_email, active_page='analytics', page_title='Analytics')
    

    @app.route("/conversations")
    @require_auth
    def conversations():
        """Conversations page."""
        convs = analytics_db.get_recent_conversations(limit=100)
        return render_template_string(CONVERSATIONS_PAGE,
            active_page='conversations',
            page_title='Conversations',
            conversations=convs)
    
    @app.route("/feedback-page")
    @require_auth
    def feedback_page():
        """Feedback page."""
        suggestions = analytics_db.get_pending_suggestions()
        approved_suggestions = analytics_db.get_approved_corrections(limit=50)
        return render_template_string(FEEDBACK_PAGE,
            active_page='feedback',
            page_title='Feedback',
            suggestions=suggestions,
            approved_suggestions=approved_suggestions)
    
    @app.route("/roadmap-page")
    @require_auth
    def roadmap_page():
        """Roadmap page."""
        try:
            roadmap = analytics_db.get_roadmap_summary()
            if roadmap is None:
                roadmap = {"by_status": {}, "items": []}
        except Exception as e:
            logger.error(f"Error getting roadmap: {e}")
            roadmap = {"by_status": {}, "items": []}
        return render_template_string(ROADMAP_PAGE,
            active_page='roadmap',
            page_title='Roadmap',
            roadmap=roadmap)
    
    @app.route("/api/dashboard")
    @require_auth
    def api_dashboard():
        """Dashboard data API (OAuth protected)."""
        days = request.args.get('days', type=int)
        start_date = request.args.get('start')
        end_date = request.args.get('end')
        
        stats = analytics_db.get_stats(
            start_date=start_date,
            end_date=end_date,
            days=days
        )
        
        # Get question clusters for better grouping
        try:
            question_clusters = analytics_db.get_question_clusters(threshold=0.85)
        except Exception as e:
            logger.warning(f"Question clustering failed: {e}")
            question_clusters = []

        
        conversations = analytics_db.get_recent_conversations(limit=20)
        suggestions = analytics_db.get_pending_suggestions()
        feedback = analytics_db.get_feedback(limit=100)  # Get all feedback for roadmap
        roadmap_summary = analytics_db.get_roadmap_summary()
        approved_corrections = analytics_db.get_approved_corrections(limit=50)
        
        # Compute command_usage from conversations
        # The edge function stores 'command' field on interactions but
        # getRecentConversations may not include it yet. Also check question
        # text for slash commands as a fallback.
        command_counts = {}
        for conv in conversations:
            c = conv if isinstance(conv, dict) else vars(conv) if hasattr(conv, '__dict__') else {}
            cmd = c.get("command")
            if not cmd:
                # Fallback: detect slash commands from question text
                q = c.get("question", "")
                if q.startswith("/"):
                    cmd = q.split()[0]  # e.g. "/help" or "/correct"
            if cmd:
                command_counts[cmd] = command_counts.get(cmd, 0) + 1
        command_usage = [
            {"command": cmd, "count": cnt}
            for cmd, cnt in sorted(command_counts.items(), key=lambda x: -x[1])
        ]

        # Filter "COMMAND" from topics breakdown (slash commands pollute it)
        if "topics" in stats:
            stats["topics"] = [t for t in stats["topics"] if t.get("topic") != "COMMAND"]

        return jsonify({
            **stats,
            "conversations": conversations,
            "command_usage": command_usage,
            "suggestions": suggestions,
            "question_clusters": question_clusters,
            "feedback": feedback,
            "roadmap_summary": roadmap_summary,
            "approved_corrections": approved_corrections
        })
    
    @app.route("/api/suggestions/<int:suggestion_id>/approve", methods=["POST"])
    @require_auth
    def api_approve_suggestion(suggestion_id):
        """Approve a suggestion (OAuth protected)."""
        try:
            reviewed_by = session.get('user_email', 'unknown')
            correction_data = analytics_db.approve_suggestion(
                suggestion_id,
                reviewed_by=reviewed_by
            )
            return jsonify({"status": "ok", "message": "Suggestion approved"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 400
    
    @app.route("/api/suggestions/<int:suggestion_id>/reject", methods=["POST"])
    @require_auth
    def api_reject_suggestion(suggestion_id):
        """Reject a suggestion (OAuth protected)."""
        try:
            reviewed_by = session.get('user_email', 'unknown')
            analytics_db.reject_suggestion(
                suggestion_id,
                reviewed_by=reviewed_by
            )
            return jsonify({"status": "ok", "message": "Suggestion rejected"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 400
    
    @app.route("/api/roadmap/<int:feedback_id>", methods=["POST"])
    @require_auth
    def api_update_roadmap(feedback_id):
        """Update roadmap status for a feedback item (OAuth protected)."""
        try:
            data = request.get_json()

            updated = analytics_db.update_feedback_roadmap(
                feedback_id,
                roadmap_status=data.get('roadmap_status'),
                priority=data.get('priority'),
                target_quarter=data.get('target_quarter'),
                notes=data.get('notes')
            )

            if updated:
                return jsonify({"status": "ok", "message": "Roadmap updated"})
            else:
                return jsonify({"status": "error", "message": "Feedback item not found"}), 404
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 400

    @app.route("/api/roadmap/create", methods=["POST"])
    @require_auth
    def api_create_roadmap_item():
        """Create a standalone roadmap item (OAuth protected)."""
        try:
            data = request.get_json()
            title = (data.get("title") or "").strip()
            if not title:
                return jsonify({"status": "error", "message": "Title is required"}), 400

            created_by = session.get("user_email", "admin")
            item_id = analytics_db.create_roadmap_item(
                title=title,
                priority=data.get("priority", "medium"),
                roadmap_status=data.get("roadmap_status", "backlog"),
                target_quarter=data.get("target_quarter"),
                notes=data.get("notes"),
                created_by=created_by,
            )

            return jsonify({"status": "ok", "id": item_id, "message": "Roadmap item created"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 400

