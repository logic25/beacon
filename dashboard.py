"""
Enhanced Dashboard v2 routes for Beacon analytics with OAuth protection.
Full-featured dashboard with date ranges, conversations, topics, and insights.
Only authorized users (AUTHORIZED_EMAILS) can access.
"""

from flask import render_template_string, jsonify, request, redirect, url_for, session
from datetime import datetime, timedelta
from analytics import AnalyticsDB
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
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
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
    </style>
</head>
<body>
    <div class="login-container">
        <h1>🎯 Beacon Dashboard</h1>
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
        }
        
        body.dark {
            --bg: #0f172a;
            --card: #1e293b;
            --border: #334155;
            --text: #f1f5f9;
            --text-muted: #cbd5e1;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            transition: background 0.2s, color 0.2s;
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
            font-family: monospace;
            font-weight: bold;
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
            margin-bottom: 4px;
            border-radius: 8px;
            text-decoration: none;
            color: var(--text-muted);
            font-size: 14px;
            font-weight: 500;
            transition: all 0.2s;
        }
        
        .nav-item:hover { background: var(--bg); color: var(--text); }
        .nav-item.active { background: #fef3c7; color: var(--primary); }
        
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
            box-shadow: 0 1px 3px rgba(0,0,0,0.02);
            transition: all 0.2s;
        }
        
        .card:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
            transform: translateY(-2px);
        }
        
        .metric-card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.02);
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
            font-family: 'Courier New', monospace;
            font-size: 32px;
            font-weight: bold;
            margin-bottom: 4px;
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
            font-size: 11px;
            color: var(--text-muted);
            font-weight: 600;
            padding: 12px;
            border-bottom: 1px solid var(--border);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        
        td {
            padding: 12px;
            font-size: 13px;
            border-bottom: 1px solid var(--border);
        }
        
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
            transition: all 0.2s;
        }
        
        .conv-card:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
            border-color: rgba(245, 158, 11, 0.3);
        }
        
        .topic-bar {
            display: flex;
            justify-content: space-between;
            margin-bottom: 12px;
        }
        
        .topic-name { font-size: 13px; font-weight: 500; }
        .topic-count { font-family: monospace; font-size: 12px; color: var(--text-muted); }
        
        .progress-bar {
            height: 8px;
            background: #e2e8f0;
            border-radius: 4px;
            overflow: hidden;
            margin-top: 6px;
            margin-bottom: 16px;
        }
        
        .progress-fill { height: 100%; transition: width 0.3s; }
        
        .rank { font-family: monospace; font-weight: bold; color: var(--primary); }
        
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
    </style>
</head>
<body>
    <aside class="sidebar" id="sidebar">
        <div class="sidebar-header">
            <div class="logo">B</div>
            <span class="sidebar-title">Beacon</span>
        </div>
        <nav class="nav">
            <a href="/analytics" class="nav-item {{ 'active' if active_page == 'analytics' }}">
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
            <a href="/feedback" class="nav-item {{ 'active' if active_page == 'feedback' }}">
                <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                </svg>
                <span class="nav-label">Feedback</span>
            </a>
            <a href="/content" class="nav-item {{ 'active' if active_page == 'content' }}">
                <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                </svg>
                <span class="nav-label">Content Engine</span>
            </a>
            <a href="/roadmap" class="nav-item {{ 'active' if active_page == 'roadmap' }}">
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
<div class="page-header">
    <div class="page-title">📊 Analytics</div>
    <div class="page-subtitle">Beacon bot performance · Auto-refreshes every 30 seconds · {{ user_email }}</div>
</div>

<div class="grid grid-6 mb-6">
    <div class="metric-card">
        <div class="metric-icon" style="background: #fef3c7;">💬</div>
        <div class="metric-value" id="total-questions">-</div>
        <div class="metric-label">Total Questions</div>
        <div class="metric-sublabel">Last 7 days</div>
    </div>
    
    <div class="metric-card">
        <div class="metric-icon" style="background: #dcfce7;">✅</div>
        <div class="metric-value" id="success-rate">-</div>
        <div class="metric-label">Success Rate</div>
        <div class="metric-sublabel" id="answered-count">-</div>
    </div>
    
    <div class="metric-card">
        <div class="metric-icon" style="background: #dbeafe;">👥</div>
        <div class="metric-value" id="active-users">-</div>
        <div class="metric-label">Active Users</div>
        <div class="metric-sublabel">N/A</div>
    </div>
    
    <div class="metric-card">
        <div class="metric-icon" style="background: #fef3c7;">💰</div>
        <div class="metric-value" id="api-cost">$0.00</div>
        <div class="metric-label">Total API Cost</div>
        <div class="metric-sublabel">N/A</div>
    </div>
    
    <div class="metric-card">
        <div class="metric-icon" style="background: #e0e7ff;">⏱️</div>
        <div class="metric-value" id="avg-time">0s</div>
        <div class="metric-label">Avg Response Time</div>
        <div class="metric-sublabel" id="time-range">N/A</div>
    </div>
    
    <div class="metric-card">
        <div class="metric-icon" style="background: #fce7f3;">📝</div>
        <div class="metric-value" id="pending-reviews">0</div>
        <div class="metric-label">Pending Reviews</div>
        <div class="metric-sublabel" id="feedback-count">0 new feedback</div>
    </div>
</div>

<div class="section">
    <h2>💬 Recent Conversations (Last 10)</h2>
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

<div class="grid grid-2">
    <div class="section">
        <h2>📊 Questions by Topic</h2>
        <div id="topics-breakdown"></div>
    </div>
    
    <div class="section">
        <h2>⚡ Slash Command Usage</h2>
        <div id="slash-commands"></div>
    </div>
</div>

<script>
async function loadDashboardData() {
    try {
        const response = await fetch('/api/dashboard?days=7');
        const data = await response.json();
        
        document.getElementById('total-questions').textContent = data.total_questions || 0;
        document.getElementById('success-rate').textContent = data.success_rate ? data.success_rate + '%' : '0%';
        document.getElementById('answered-count').textContent = (data.answered || 0) + ' answered';
        document.getElementById('active-users').textContent = data.active_users || 0;
        document.getElementById('api-cost').textContent = '$' + (data.total_cost_usd || '0.00');
        document.getElementById('avg-time').textContent = data.response_time && data.response_time.avg_ms ? (data.response_time.avg_ms / 1000).toFixed(1) + 's' : '0s';
        document.getElementById('pending-reviews').textContent = data.pending_suggestions || 0;
        document.getElementById('feedback-count').textContent = (data.new_feedback || 0) + ' new feedback';
        
        const tbody = document.querySelector('#conversations-table tbody');
        tbody.innerHTML = '';
        (data.conversations || []).slice(0, 10).forEach(conv => {
            const row = tbody.insertRow();
            row.innerHTML = `
                <td><strong>${conv.question || 'N/A'}</strong></td>
                <td>${conv.user_name || 'Unknown'}</td>
                <td><span class="badge">${conv.topic || 'General'}</span></td>
                <td style="color: var(--text-muted); font-size: 12px;">${conv.timestamp || ''}</td>
                <td><span class="badge ${conv.answered ? 'badge-success' : 'badge-danger'}">${conv.answered ? '✓ Answered' : '✗ Failed'}</span></td>
            `;
        });
        
        const topicsDiv = document.getElementById('topics-breakdown');
        topicsDiv.innerHTML = '';
        const totalQ = data.total_questions || 1;
        (data.topics || []).forEach(t => {
            const pct = Math.round((t.count / totalQ) * 100);
            topicsDiv.innerHTML += `
                <div style="margin-bottom: 16px;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                        <span style="font-size: 13px; font-weight: 500;">${t.topic}</span>
                        <span style="font-family: monospace; font-size: 12px; color: var(--text-muted);">${t.count} (${pct}%)</span>
                    </div>
                    <div style="height: 8px; background: var(--border); border-radius: 4px; overflow: hidden;">
                        <div style="height: 100%; width: ${pct}%; background: var(--primary);"></div>
                    </div>
                </div>
            `;
        });
        
        const slashDiv = document.getElementById('slash-commands');
        slashDiv.innerHTML = '';
        (data.command_usage || []).forEach(cmd => {
            const pct = Math.round((cmd.count / totalQ) * 100);
            slashDiv.innerHTML += `
                <div style="margin-bottom: 16px;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                        <span style="font-size: 13px; font-weight: 500;">/${cmd.command}</span>
                        <span style="font-family: monospace; font-size: 12px; color: var(--text-muted);">${cmd.count} (${pct}%)</span>
                    </div>
                    <div style="height: 8px; background: var(--border); border-radius: 4px; overflow: hidden;">
                        <div style="height: 100%; width: ${pct}%; background: var(--primary);"></div>
                    </div>
                </div>
            `;
        });
    } catch (error) {
        console.error('Failed to load dashboard data:', error);
    }
}

loadDashboardData();
setInterval(loadDashboardData, 30000);
</script>
{% endblock %}''')




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
        
        # Hardcode redirect URI to fix the redirect_uri_mismatch error
        redirect_uri = "https://web-production-44b7c.up.railway.app/auth/callback"
        auth_url = (
            f"https://accounts.google.com/o/oauth2/v2/auth?"
            f"client_id={GOOGLE_CLIENT_ID}&"
            f"redirect_uri={redirect_uri}&"
            f"response_type=code&"
            f"scope=openid email profile&"
            f"access_type=offline"
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
            redirect_uri = "https://web-production-44b7c.up.railway.app/auth/callback"
            
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
        return render_template_string(DASHBOARD_V2_HTML, user_email=user_email)
    
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
        
        return jsonify({
            **stats,
            "conversations": conversations,
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

