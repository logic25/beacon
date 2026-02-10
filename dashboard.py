"""
Enhanced Dashboard v2 routes for Beacon analytics with OAuth protection.
Updated with Lovable styling, sidebar navigation, and logout button.
"""

import json
import os
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional

from flask import (Flask, jsonify, redirect, render_template_string, request,
                   session, url_for)

# Google OAuth imports
try:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token
    GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    GOOGLE_AUTH_AVAILABLE = False

from analytics import AnalyticsDB, Interaction

# OAuth Configuration
GOOGLE_OAUTH_CLIENT_ID = os.getenv('GOOGLE_OAUTH_CLIENT_ID')
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv('GOOGLE_OAUTH_CLIENT_SECRET')

# Check if OAuth is properly configured
OAUTH_CONFIGURED = bool(
    GOOGLE_OAUTH_CLIENT_ID and 
    GOOGLE_OAUTH_CLIENT_SECRET and 
    GOOGLE_AUTH_AVAILABLE
)

# ============================================================================
# LOVABLE STYLED TEMPLATES - BASE WITH SIDEBAR
# ============================================================================

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
            transition: background 0.2s;
        }
        
        /* Sidebar */
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
            transition: opacity 0.2s;
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
        
        .nav-label { white-space: nowrap; overflow: hidden; transition: opacity 0.2s; }
        .sidebar.collapsed .nav-label { opacity: 0; width: 0; }
        
        .sidebar-footer { padding: 12px; border-top: 1px solid var(--border); }
        
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
            text-decoration: none;
        }
        
        .footer-btn:hover { background: var(--bg); color: var(--text); }
        .footer-btn.logout { color: var(--danger); }
        .footer-btn.logout:hover { background: #fee2e2; }
        
        /* Main content */
        .main { margin-left: var(--sidebar-width); padding: 32px 24px; max-width: 1400px; transition: margin-left 0.2s; }
        .sidebar.collapsed ~ .main { margin-left: var(--sidebar-collapsed); }
        
        .page-header { margin-bottom: 32px; }
        .page-title { font-size: 24px; font-weight: 700; margin-bottom: 4px; display: flex; align-items: center; gap: 10px; }
        .page-subtitle { font-size: 14px; color: var(--text-muted); }
        
        .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.02); transition: all 0.2s; }
        .card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.05); transform: translateY(-2px); }
        
        .metric-card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.02); }
        .metric-icon { width: 40px; height: 40px; border-radius: 8px; display: flex; align-items: center; justify-content: center; margin-bottom: 12px; }
        .metric-value { font-family: 'Courier New', monospace; font-size: 32px; font-weight: bold; margin-bottom: 4px; }
        .metric-label { font-size: 14px; color: var(--text); margin-bottom: 2px; }
        .metric-sublabel { font-size: 11px; color: var(--text-muted); }
        .trend-up { color: var(--success); font-size: 11px; font-weight: 600; }
        
        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; font-size: 11px; color: var(--text-muted); font-weight: 600; padding: 12px; border-bottom: 1px solid var(--border); text-transform: uppercase; }
        td { padding: 12px; font-size: 13px; border-bottom: 1px solid var(--border); }
        tr:hover { background: var(--bg); }
        
        .badge { padding: 4px 12px; border-radius: 6px; font-size: 11px; font-weight: 600; display: inline-block; }
        .badge-success { background: #dcfce7; color: var(--success); }
        .badge-danger { background: #fee2e2; color: var(--danger); }
        .badge-warning { background: #fef3c7; color: var(--primary); }
        
        .btn { padding: 8px 16px; border-radius: 8px; font-size: 13px; font-weight: 600; border: none; cursor: pointer; transition: all 0.2s; }
        .btn-success { background: var(--success); color: white; }
        .btn-success:hover { background: #16a34a; }
        .btn-danger { background: var(--danger); color: white; }
        .btn-danger:hover { background: #dc2626; }
        
        .grid { display: grid; gap: 16px; }
        .grid-6 { grid-template-columns: repeat(6, 1fr); }
        .grid-2 { grid-template-columns: repeat(2, 1fr); }
        .mb-6 { margin-bottom: 24px; }
        
        .section { background: var(--card); padding: 28px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); border: 1px solid var(--border); margin-bottom: 24px; }
        .section h2 { font-size: 18px; margin-bottom: 20px; color: var(--text); }
        
        @keyframes fadeInUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
        .metric-card { animation: fadeInUp 0.5s ease-out; }
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
                <span class="nav-label">Collapse</span>
            </button>
            
            <a href="/logout" class="footer-btn logout">
                <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                </svg>
                <span class="nav-label">Logout</span>
            </a>
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
        
        {% block extra_js %}{% endblock %}
    </script>
</body>
</html>'''

# Main analytics dashboard - using your existing data structure
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
        <div class="metric-icon" style="background: #fef3c7;">💵</div>
        <div class="metric-value" id="api-cost">-</div>
        <div class="metric-label">Total API Cost</div>
        <div class="metric-sublabel">N/A</div>
    </div>
    
    <div class="metric-card">
        <div class="metric-icon" style="background: #e0e7ff;">⏱️</div>
        <div class="metric-value" id="avg-time">-</div>
        <div class="metric-label">Avg Response Time</div>
        <div class="metric-sublabel" id="time-range">-</div>
    </div>
    
    <div class="metric-card">
        <div class="metric-icon" style="background: #fee2e2;">📝</div>
        <div class="metric-value" id="pending-reviews">-</div>
        <div class="metric-label">Pending Reviews</div>
        <div class="metric-sublabel" id="feedback-count">-</div>
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

{% block extra_js %}
<script>
// Auto-refresh data every 30 seconds
async function loadDashboardData() {
    try {
        const response = await fetch('/api/dashboard?days=7');
        const data = await response.json();
        
        // Update metrics
        document.getElementById('total-questions').textContent = data.total_questions || 0;
        document.getElementById('success-rate').textContent = data.success_rate ? data.success_rate + '%' : '0%';
        document.getElementById('answered-count').textContent = data.answered_count + ' answered';
        document.getElementById('active-users').textContent = data.active_users || 0;
        document.getElementById('api-cost').textContent = '$' + (data.api_cost || '0.00');
        document.getElementById('avg-time').textContent = data.avg_response_time ? data.avg_response_time.toFixed(1) + 's' : '0s';
        document.getElementById('time-range').textContent = data.time_range || 'N/A';
        document.getElementById('pending-reviews').textContent = data.pending_reviews || 0;
        document.getElementById('feedback-count').textContent = data.feedback_count || 'No feedback';
        
        // Update conversations table
        const tbody = document.querySelector('#conversations-table tbody');
        tbody.innerHTML = '';
        (data.conversations || []).slice(0, 10).forEach(conv => {
            const row = tbody.insertRow();
            row.innerHTML = `
                <td><strong>${conv.question}</strong></td>
                <td>${conv.user}</td>
                <td><span class="badge badge-warning">${conv.topic || 'General'}</span></td>
                <td style="color: var(--text-muted); font-size: 12px;">${conv.when}</td>
                <td><span class="badge ${conv.answered ? 'badge-success' : 'badge-danger'}">${conv.answered ? '✓ Answered' : '✗ Failed'}</span></td>
            `;
        });
        
        // Update topics
        const topicsDiv = document.getElementById('topics-breakdown');
        topicsDiv.innerHTML = '';
        Object.entries(data.topics || {}).forEach(([topic, count]) => {
            const pct = data.total_questions ? Math.round((count / data.total_questions) * 100) : 0;
            topicsDiv.innerHTML += `
                <div style="margin-bottom: 16px;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                        <span style="font-size: 13px; font-weight: 500;">${topic}</span>
                        <span style="font-family: monospace; font-size: 12px; color: var(--text-muted);">${count} (${pct}%)</span>
                    </div>
                    <div style="height: 8px; background: #e2e8f0; border-radius: 4px; overflow: hidden;">
                        <div style="height: 100%; width: ${pct}%; background: var(--primary);"></div>
                    </div>
                </div>
            `;
        });
        
        // Update slash commands
        const slashDiv = document.getElementById('slash-commands');
        slashDiv.innerHTML = '';
        Object.entries(data.slash_commands || {}).forEach(([cmd, count]) => {
            const maxCount = Math.max(...Object.values(data.slash_commands || {1: 1}));
            const pct = Math.round((count / maxCount) * 100);
            slashDiv.innerHTML += `
                <div style="margin-bottom: 16px;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                        <span style="font-family: monospace; font-size: 13px; font-weight: 500;">${cmd}</span>
                        <span style="font-family: monospace; font-size: 12px; color: var(--text-muted);">${count} uses</span>
                    </div>
                    <div style="height: 8px; background: #e2e8f0; border-radius: 4px; overflow: hidden;">
                        <div style="height: 100%; width: ${pct}%; background: var(--primary);"></div>
                    </div>
                </div>
            `;
        });
        
    } catch (error) {
        console.error('Failed to load dashboard data:', error);
    }
}

// Load immediately and then every 30 seconds
loadDashboardData();
setInterval(loadDashboardData, 30000);
</script>
{% endblock %}
{% endblock %}''')

# Conversations page (NEW)
CONVERSATIONS_PAGE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''{% block content %}
<div class="page-header">
    <div class="page-title">💬 Conversations</div>
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
                <td><span class="badge {{ 'badge-success' if conv.answered else 'badge-danger' }}">{{ '✓ Answered' if conv.answered else '✗ Failed' }}</span></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}''')

# Feedback page (NEW)
FEEDBACK_PAGE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''{% block content %}
<div class="page-header">
    <div class="page-title">✅ Feedback & Corrections</div>
    <div class="page-subtitle">Review team suggestions and correction history</div>
</div>

<div class="section">
    <h2>Suggestions Queue ({{ suggestions|length }} pending)</h2>
    <table>
        <thead>
            <tr>
                <th>User</th>
                <th>When</th>
                <th>Wrong Answer</th>
                <th>Correct Answer</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody>
            {% for s in suggestions %}
            <tr>
                <td><strong>{{ s.user_name }}</strong></td>
                <td style="color: var(--text-muted); font-size: 12px;">{{ s.timestamp }}</td>
                <td style="color: var(--danger); font-size: 13px;">❌ {{ s.wrong_answer }}</td>
                <td style="color: var(--success); font-size: 13px;">✅ {{ s.correct_answer }}</td>
                <td>
                    <button class="btn btn-success" style="margin-right: 8px; font-size: 11px; padding: 6px 12px;" onclick="approveSuggestion({{ s.id }})">Approve</button>
                    <button class="btn btn-danger" style="font-size: 11px; padding: 6px 12px;" onclick="rejectSuggestion({{ s.id }})">Reject</button>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>

{% block extra_js %}
<script>
async function approveSuggestion(id) {
    if (!confirm('Approve this correction?')) return;
    try {
        const response = await fetch('/approve-suggestion', {
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
        const response = await fetch('/reject-suggestion', {
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
</script>
{% endblock %}''')

# Roadmap page (NEW)
ROADMAP_PAGE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''{% block content %}
<div class="page-header">
    <div class="page-title">🗺️ Product Roadmap</div>
    <div class="page-subtitle">Track feature requests and development progress</div>
</div>

<div class="grid grid-2">
    {% for item in roadmap.items %}
    <div class="card" style="cursor: pointer;">
        <div style="margin-bottom: 8px;">
            <span class="badge {{ 'badge-success' if item.status == 'shipped' else ('badge-warning' if item.status == 'in_progress' else 'badge-info') }}">
                {{ item.status.replace('_', ' ').title() }}
            </span>
        </div>
        <h3 style="font-size: 14px; font-weight: 600;">{{ item.idea }}</h3>
        <p style="font-size: 13px; color: var(--text-muted); margin-top: 4px;">
            Requested by {{ item.requested_by }}
            {% if item.notes %} · {{ item.notes }}{% endif %}
        </p>
    </div>
    {% endfor %}
</div>
{% endblock %}''')

# Login page
LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Beacon Analytics - Login</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
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


def add_dashboard_routes(app, analytics_db: AnalyticsDB):
    """Add OAuth-protected dashboard routes to Flask app."""
    
    @app.route("/login")
    def login():
        """Login page with Google OAuth."""
        if not OAUTH_CONFIGURED:
            return "OAuth not configured. Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET environment variables."
        
        # Build OAuth authorization URL
        from urllib.parse import urlencode
        
        params = {
            'client_id': GOOGLE_OAUTH_CLIENT_ID,
            'redirect_uri': url_for('oauth_callback', _external=True),
            'response_type': 'code',
            'scope': 'openid email profile',
            'access_type': 'offline',
            'prompt': 'select_account'
        }
        auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
        return render_template_string(LOGIN_HTML, auth_url=auth_url, error=None)
    
    @app.route("/oauth/callback")
    def oauth_callback():
        """Handle Google OAuth callback."""
        if not OAUTH_CONFIGURED:
            return "OAuth not configured"
        
        code = request.args.get('code')
        if not code:
            return render_template_string(LOGIN_HTML,
                error="No authorization code received",
                auth_url=url_for('login'))
        
        try:
            # Exchange code for tokens
            import requests as req
            token_url = "https://oauth2.googleapis.com/token"
            data = {
                'code': code,
                'client_id': GOOGLE_OAUTH_CLIENT_ID,
                'client_secret': GOOGLE_OAUTH_CLIENT_SECRET,
                'redirect_uri': url_for('oauth_callback', _external=True),
                'grant_type': 'authorization_code'
            }
            
            token_response = req.post(token_url, data=data)
            tokens = token_response.json()
            
            if 'error' in tokens:
                raise Exception(tokens.get('error_description', tokens['error']))
            
            # Verify ID token and extract user info
            id_info = id_token.verify_oauth2_token(
                tokens['id_token'],
                google_requests.Request(),
                GOOGLE_OAUTH_CLIENT_ID
            )
            
            # Store user info in session
            session['user_email'] = id_info.get('email')
            session['user_name'] = id_info.get('name')
            session['user_picture'] = id_info.get('picture')
            
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
        return render_template_string(DASHBOARD_V2_HTML, 
            user_email=user_email,
            active_page='analytics',
            page_title='Analytics')
    
    @app.route("/api/dashboard")
    @require_auth
    def api_dashboard():
        """Dashboard data API (OAuth protected)."""
        days = request.args.get('days', 7, type=int)
        
        # Get stats from analytics_db
        stats = analytics_db.get_stats(days=days)
        
        # Get recent conversations
        conversations = []
        recent = analytics_db.get_recent_conversations(limit=10)
        for conv in recent:
            conversations.append({
                'question': conv.question,
                'user': conv.user_name,
                'topic': conv.topic,
                'when': conv.timestamp,
                'answered': conv.answered
            })
        
        # Get topics
        topics = {}
        for conv in recent:
            topic = conv.topic or 'General'
            topics[topic] = topics.get(topic, 0) + 1
        
        # Get slash commands
        slash_commands = analytics_db.get_slash_commands() or {}
        
        return jsonify({
            'total_questions': stats.get('total_questions', 0),
            'success_rate': stats.get('success_rate', 0),
            'answered_count': stats.get('answered_count', 0),
            'active_users': stats.get('active_users', 0),
            'api_cost': stats.get('api_cost', '0.00'),
            'avg_response_time': stats.get('avg_response_time', 0),
            'time_range': stats.get('time_range', 'N/A'),
            'pending_reviews': len(analytics_db.get_pending_suggestions()),
            'feedback_count': f"{len(analytics_db.get_suggestions(status='pending'))} new feedback",
            'conversations': conversations,
            'topics': topics,
            'slash_commands': slash_commands
        })
    
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
        return render_template_string(FEEDBACK_PAGE,
            active_page='feedback',
            page_title='Feedback',
            suggestions=suggestions)
    
    @app.route("/roadmap-page")
    @require_auth
    def roadmap_page():
        """Roadmap page."""
        roadmap = analytics_db.get_roadmap_summary()
        return render_template_string(ROADMAP_PAGE,
            active_page='roadmap',
            page_title='Roadmap',
            roadmap=roadmap_items)
    
    @app.route("/approve-suggestion", methods=["POST"])
    @require_auth
    def approve_suggestion():
        """Approve a suggestion (OAuth protected)."""
        data = request.get_json()
        suggestion_id = data.get('id')
        if suggestion_id:
            analytics_db.update_suggestion_status(suggestion_id, 'approved')
        return jsonify({'status': 'success'})
    
    @app.route("/reject-suggestion", methods=["POST"])
    @require_auth
    def reject_suggestion():
        """Reject a suggestion (OAuth protected)."""
        data = request.get_json()
        suggestion_id = data.get('id')
        if suggestion_id:
            analytics_db.update_suggestion_status(suggestion_id, 'rejected')
        return jsonify({'status': 'success'})
