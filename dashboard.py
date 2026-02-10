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
DASHBOARD_V2_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Beacon Analytics Dashboard v2</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            background: #f9fafb;
            padding: 20px;
        }
        .container { max-width: 1600px; margin: 0 auto; }
        .header-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }
        .user-info {
            display: flex;
            align-items: center;
            gap: 15px;
        }
        .user-email {
            font-size: 14px;
            color: #7f8c8d;
        }
        .logout-btn {
            padding: 8px 16px;
            background: #e74c3c;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            text-decoration: none;
        }
        .logout-btn:hover {
            background: #c0392b;
        }
        h1 { color: #2c3e50; margin-bottom: 10px; font-size: 32px; }
        .subtitle { color: #7f8c8d; margin-bottom: 20px; font-size: 14px; }
        
        /* Date Range Controls */
        .date-controls {
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
        }
        .date-preset {
            padding: 8px 16px;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            background: white;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
        }
        .date-preset:hover { background: #f8f9fa; }
        .date-preset.active {
            background: #3498db;
            color: white;
            border-color: #3498db;
        }
        
        .metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .metric-card {
            background: white;
            padding: 24px;
            border-radius: 12px;
            box-shadow: 0 1px 2px rgba(0,0,0,0.04);
            border: 1px solid #e8ecef;
            transition: all 0.2s ease;
        }
        .metric-card:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        }
        .metric-value {
            font-size: 36px;
            font-weight: bold;
            color: #3498db;
            margin-bottom: 5px;
        }
        .metric-label {
            color: #7f8c8d;
            font-size: 14px;
        }
        .metric-sublabel {
            color: #95a5a6;
            font-size: 12px;
            margin-top: 4px;
        }
        
        .section {
            background: white;
            padding: 28px;
            border-radius: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
            border: 1px solid #e8ecef;
            margin-bottom: 20px;
        }
        .section-title {
            font-size: 18px;
            color: #1f2937;
            margin-bottom: 20px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th {
            text-align: left;
            padding: 14px 16px;
            background: #f9fafb;
            color: #374151;
            font-weight: 600;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 1px solid #e5e7eb;
        }
        td {
            padding: 14px 16px;
            border-bottom: 1px solid #f3f4f6;
            color: #1f2937;
        }
        tr:hover { 
            background: #f9fafb;
        }
        tr:last-child td {
            border-bottom: none;
        }
        
        .badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 600;
        }
        .badge-pending { background: #fff3cd; color: #856404; }
        .badge-success { background: #d4edda; color: #155724; }
        .badge-danger { background: #f8d7da; color: #721c24; }
        .badge-info { background: #d1ecf1; color: #0c5460; }
        
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            transition: opacity 0.2s;
        }
        .btn:hover { opacity: 0.9; }
        .btn-approve { background: #28a745; color: white; }
        .btn-reject { background: #dc3545; color: white; }
        .btn-view { background: #17a2b8; color: white; }
        
        .refresh-btn {
            background: #3498db;
            color: white;
            padding: 10px 20px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
        }
        
        .success-rate {
            font-size: 36px;
            font-weight: bold;
        }
        .success-rate.high { color: #28a745; }
        .success-rate.medium { color: #ffc107; }
        .success-rate.low { color: #dc3545; }
        
        /* Modal for conversations */
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.5);
            z-index: 1000;
        }
        .modal.active {
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .modal-content {
            background: white;
            padding: 30px;
            border-radius: 8px;
            max-width: 900px;
            max-height: 90vh;
            overflow-y: auto;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
            position: relative;
        }
        .modal-close {
            position: absolute;
            top: 15px;
            right: 20px;
            cursor: pointer;
            font-size: 28px;
            color: #95a5a6;
        }
        .modal-close:hover { color: #2c3e50; }
        
        .conversation-item {
            background: white;
            padding: 20px;
            border-radius: 12px;
            margin-bottom: 12px;
            cursor: pointer;
            border: 1px solid #e8ecef;
            box-shadow: 0 1px 2px rgba(0,0,0,0.04);
            transition: all 0.2s ease;
        }
        .conversation-item:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
            border-color: #d0d7de;
            transform: translateY(-1px);
        }
        .conversation-question {
            font-weight: 600;
            color: #1f2937;
            margin-bottom: 8px;
            font-size: 15px;
            line-height: 1.5;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }
        .conversation-response-preview {
            color: #6b7280;
            font-size: 14px;
            line-height: 1.6;
            margin-bottom: 10px;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }
        .conversation-meta {
            font-size: 12px;
            color: #9ca3af;
            display: flex;
            gap: 15px;
            align-items: center;
        }
        .conversation-meta-badge {
            display: inline-flex;
            align-items: center;
            padding: 4px 10px;
            background: #f3f4f6;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 500;
            color: #4b5563;
        }
        
        .response-box {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 6px;
            margin: 15px 0;
            line-height: 1.6;
        }
        
        .sources-list {
            margin-top: 15px;
            padding-left: 20px;
        }
        .sources-list li {
            margin: 5px 0;
            color: #555;
        }
        
        .topic-pill {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 12px;
            margin-right: 5px;
        }
        .topic-zoning { background: #e3f2fd; color: #1565c0; }
        .topic-dob { background: #fff3e0; color: #e65100; }
        .topic-dhcr { background: #f3e5f5; color: #6a1b9a; }
        .topic-violations { background: #ffebee; color: #c62828; }
        .topic-general { background: #f5f5f5; color: #616161; }
        
        .grid-2 {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        
        @media (max-width: 768px) {
            .grid-2 { grid-template-columns: 1fr; }
            .metrics { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header-bar">
            <h1>🎯 Beacon Analytics Dashboard</h1>
            <div class="user-info">
                <span class="user-email">{{ user_email }}</span>
                <a href="/logout" class="logout-btn">Logout</a>
            </div>
        </div>
        <div class="subtitle">Enhanced tracking • Auto-refreshes every 30 seconds</div>
        
        <button class="refresh-btn" onclick="loadData()">🔄 Refresh Now</button>
        
        <!-- Date Range Picker -->
        <div class="date-controls">
            <strong>Date Range:</strong>
            <button class="date-preset active" onclick="setRange(7)">Last 7 Days</button>
            <button class="date-preset" onclick="setRange(30)">Last 30 Days</button>
            <button class="date-preset" onclick="setRange('thismonth')">This Month</button>
            <button class="date-preset" onclick="setRange('lastmonth')">Last Month</button>
            <button class="date-preset" onclick="setRange('thisyear')">This Year</button>
            <button class="date-preset" onclick="setRange('all')">All Time</button>
        </div>
        
        <!-- Key Metrics -->
        <div class="metrics">
            <div class="metric-card">
                <div class="metric-value" id="total-questions">-</div>
                <div class="metric-label">Total Questions</div>
                <div class="metric-sublabel" id="date-range-display">Last 7 days</div>
            </div>
            <div class="metric-card">
                <div class="metric-value" id="success-rate">-</div>
                <div class="metric-label">Success Rate</div>
                <div class="metric-sublabel"><span id="answered-count">-</span> answered</div>
            </div>
            <div class="metric-card">
                <div class="metric-value" id="active-users">-</div>
                <div class="metric-label">Active Users</div>
            </div>
            <div class="metric-card">
                <div class="metric-value" id="total-cost">-</div>
                <div class="metric-label">Total API Cost</div>
                <div class="metric-sublabel" id="cost-breakdown">-</div>
            </div>
            <div class="metric-card">
                <div class="metric-value" id="avg-response-time">-</div>
                <div class="metric-label">Avg Response Time</div>
                <div class="metric-sublabel" id="response-time-range">-</div>
            </div>
            <div class="metric-card">
                <div class="metric-value" id="pending-reviews">-</div>
                <div class="metric-label">Pending Reviews</div>
                <div class="metric-sublabel"><span id="new-feedback-count">-</span> new feedback</div>
            </div>
        </div>
        
        <div class="grid-2">
            <!-- Recent Conversations -->
            <div class="section">
                <div class="section-title">💬 Recent Conversations (Last 10)</div>
                <div id="recent-conversations">Loading...</div>
            </div>
            
            <!-- Topics Breakdown -->
            <div class="section">
                <div class="section-title">📊 Questions by Topic</div>
                <table>
                    <thead>
                        <tr>
                            <th>Topic</th>
                            <th>Count</th>
                            <th>%</th>
                        </tr>
                    </thead>
                    <tbody id="topics-table">
                        <tr><td colspan="3">Loading...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- Top Users -->
        <div class="section">
            <div class="section-title">👥 Most Active Users</div>
            <table>
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>User</th>
                        <th>Questions Asked</th>
                    </tr>
                </thead>
                <tbody id="top-users">
                    <tr><td colspan="3">Loading...</td></tr>
                </tbody>
            </table>
        </div>
        
        <!-- Top Questions -->
        <div class="section">
            <div class="section-title">❓ Most Asked Questions</div>
            <table>
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>Question</th>
                        <th>Times Asked</th>
                    </tr>
                </thead>
                <tbody id="top-questions">
                    <tr><td colspan="3">Loading...</td></tr>
                </tbody>
            </table>
        </div>
        
        <div class="grid-2">
            <!-- Failed Queries -->
            <div class="section">
                <div class="section-title">⚠️ Failed Queries (Need Attention)</div>
                <div id="failed-queries">Loading...</div>
            </div>
            
            <!-- Command Usage -->
            <div class="section">
                <div class="section-title">⚡ Slash Command Usage</div>
                <table>
                    <thead>
                        <tr>
                            <th>Command</th>
                            <th>Uses</th>
                        </tr>
                    </thead>
                    <tbody id="command-usage">
                        <tr><td colspan="2">Loading...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- Suggestions Queue -->
        <div class="section">
            <div class="section-title">📝 Suggestions Queue (Pending Review)</div>
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
                <tbody id="suggestions-queue">
                    <tr><td colspan="5">Loading...</td></tr>
                </tbody>
            </table>
        </div>
    </div>
    
    <!-- Conversation Detail Modal -->
    <div class="modal" id="conversation-modal">
        <div class="modal-content">
            <span class="modal-close" onclick="closeModal()">&times;</span>
            <div id="conversation-detail"></div>
        </div>
    </div>
        
        <!-- Suggestion Detail Modal -->
        <div class="modal" id="suggestion-modal">
            <div class="modal-content">
                <span class="modal-close" onclick="closeSuggestionModal()">&times;</span>
                <h2>📝 Suggestion Details</h2>
                
                <div style="margin: 20px 0; padding: 15px; background: #f9fafb; border-radius: 8px;">
                    <strong>Submitted by:</strong> <span id="suggestion-user"></span><br>
                    <strong>Date:</strong> <span id="suggestion-date"></span>
                </div>
                
                <div class="section" style="background: #fef2f2; border-left: 4px solid #ef4444;">
                    <h3 style="color: #991b1b;">❌ What Was Wrong:</h3>
                    <div class="response-box" id="suggestion-wrong" style="white-space: pre-wrap;"></div>
                </div>
                
                <div class="section" style="background: #f0fdf4; border-left: 4px solid #22c55e; margin-top: 15px;">
                    <h3 style="color: #166534;">✅ Correct Answer:</h3>
                    <div class="response-box" id="suggestion-correct" style="white-space: pre-wrap;"></div>
                </div>
                
                <div style="margin-top: 20px; text-align: right;">
                    <button onclick="approveSuggestion(window.currentSuggestionId); closeSuggestionModal();" 
                            style="background: #22c55e; color: white; padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; margin-right: 10px;">
                        ✓ Approve
                    </button>
                    <button onclick="rejectSuggestion(window.currentSuggestionId); closeSuggestionModal();" 
                            style="background: #ef4444; color: white; padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer;">
                        ✗ Reject
                    </button>
                </div>
            </div>
        </div>

    
    <script>
        let currentRange = { days: 7 };
        
        function setRange(range) {
            // Update active button
            document.querySelectorAll('.date-preset').forEach(btn => {
                btn.classList.remove('active');
            });
            event.target.classList.add('active');
            
            // Calculate date range
            const now = new Date();
            if (typeof range === 'number') {
                currentRange = { days: range };
            } else if (range === 'thismonth') {
                const start = new Date(now.getFullYear(), now.getMonth(), 1);
                currentRange = { start: start.toISOString(), end: now.toISOString() };
            } else if (range === 'lastmonth') {
                const start = new Date(now.getFullYear(), now.getMonth() - 1, 1);
                const end = new Date(now.getFullYear(), now.getMonth(), 0);
                currentRange = { start: start.toISOString(), end: end.toISOString() };
            } else if (range === 'thisyear') {
                const start = new Date(now.getFullYear(), 0, 1);
                currentRange = { start: start.toISOString(), end: now.toISOString() };
            } else if (range === 'all') {
                currentRange = {};
            }
            
            loadData();
        }
        
        
        // Clean up response text - remove escape characters and format nicely
        function cleanResponseText(text) {
            if (!text) return '';
            
            // Remove escape characters
            text = text.replace(/\\\\n/g, '\n')
                      .replace(/\\\\"/g, '"')
                      .replace(/\\\\/g, '');
            
            // Remove JSON structure artifacts
            text = text.replace(/^["']|["']$/g, '');
            
            // Truncate to reasonable length for preview
            const maxLength = 200;
            if (text.length > maxLength) {
                text = text.substring(0, maxLength) + '...';
            }
            
            return text;
        }
        
        // Parse sources and extract filenames
        function formatSources(sourcesJson) {
            if (!sourcesJson) return 'No sources';
            
            try {
                const sources = JSON.parse(sourcesJson);
                if (!Array.isArray(sources) || sources.length === 0) {
                    return 'No sources';
                }
                
                // Extract unique filenames or document titles
                const sourceNames = sources.map(s => {
                    // Try to extract filename from path
                    if (s.metadata && s.metadata.source) {
                        const path = s.metadata.source;
                        const filename = path.split('/').pop();
                        return filename;
                    }
                    // Fallback to document number
                    return s.document || 'Unknown';
                }).filter((v, i, a) => a.indexOf(v) === i); // unique only
                
                return sourceNames.slice(0, 3).join(', ');
            } catch (e) {
                return 'Sources available';
            }
        }

        
        // Suggestion modal functions
        window.currentSuggestionId = null;
        
        function viewSuggestion(id, wrongText, correctText, userName, timestamp) {
            window.currentSuggestionId = id;
            const modal = document.getElementById('suggestion-modal');
            document.getElementById('suggestion-user').textContent = userName;
            document.getElementById('suggestion-date').textContent = new Date(timestamp).toLocaleString();
            document.getElementById('suggestion-wrong').textContent = wrongText;
            document.getElementById('suggestion-correct').textContent = correctText;
            modal.classList.add('active');
        }
        
        function closeSuggestionModal() {
            document.getElementById('suggestion-modal').classList.remove('active');
            window.currentSuggestionId = null;
        }
        

        async function loadData() {
            try {
                const params = new URLSearchParams(currentRange);
                const response = await fetch('/api/dashboard?' + params);
                const data = await response.json();
                
                // Update metrics
                document.getElementById('total-questions').textContent = data.total_questions;
                
                const successRate = data.success_rate;
                const successEl = document.getElementById('success-rate');
                successEl.textContent = successRate + '%';
                successEl.className = 'metric-value success-rate ' + 
                    (successRate >= 80 ? 'high' : successRate >= 60 ? 'medium' : 'low');
                
                document.getElementById('answered-count').textContent = data.answered;
                document.getElementById('active-users').textContent = data.active_users;
                document.getElementById('total-cost').textContent = '$' + data.total_cost_usd.toFixed(2);
                
                // Cost breakdown
                const costParts = [];
                if (data.api_costs.anthropic) costParts.push(`Claude: $${data.api_costs.anthropic.toFixed(2)}`);
                if (data.api_costs.pinecone) costParts.push(`Pinecone: $${data.api_costs.pinecone.toFixed(2)}`);
                if (data.api_costs.voyage) costParts.push(`Voyage: $${data.api_costs.voyage.toFixed(2)}`);
                document.getElementById('cost-breakdown').textContent = costParts.join(' • ') || 'N/A';
                
                // Response time
                document.getElementById('avg-response-time').textContent = 
                    (data.response_time.avg_ms / 1000).toFixed(1) + 's';
                document.getElementById('response-time-range').textContent = 
                    `${(data.response_time.min_ms / 1000).toFixed(1)}s - ${(data.response_time.max_ms / 1000).toFixed(1)}s`;
                
                document.getElementById('pending-reviews').textContent = data.pending_suggestions;
                document.getElementById('new-feedback-count').textContent = data.new_feedback;
                
                // Date range display
                if (currentRange.days) {
                    document.getElementById('date-range-display').textContent = `Last ${currentRange.days} days`;
                } else if (currentRange.start) {
                    document.getElementById('date-range-display').textContent = 'Custom range';
                } else {
                    document.getElementById('date-range-display').textContent = 'All time';
                }
                
                // Recent conversations
                displayConversations(data.conversations);
                
                // Topics
                displayTopics(data.topics, data.total_questions);
                
                // Top users
                const usersHtml = data.top_users.map((user, i) => `
                    <tr>
                        <td>${i + 1}</td>
                        <td>${user.name}</td>
                        <td>${user.count}</td>
                    </tr>
                `).join('');
                document.getElementById('top-users').innerHTML = usersHtml || '<tr><td colspan="3">No data yet</td></tr>';
                
                // Top questions - handle both clustered and regular format
                let questionsHtml;
                if (data.question_clusters && data.question_clusters.length > 0) {
                    // Use clustered questions
                    questionsHtml = data.question_clusters.map((cluster, i) => {
                        const variationsText = cluster.variations && cluster.variations.length > 1 
                            ? ` <span style="color: #6b7280; font-size: 12px;">(+${cluster.variations.length - 1} similar)</span>`
                            : '';
                        return `
                        <tr title="${cluster.example_variations ? cluster.example_variations.slice(1, 3).join('; ') : ''}">
                            <td>${i + 1}</td>
                            <td>${cluster.representative}${variationsText}</td>
                            <td>${cluster.total_count}</td>
                        </tr>
                    `;
                    }).join('');
                } else if (data.top_questions && data.top_questions.length > 0) {
                    // Fall back to regular top questions
                    questionsHtml = data.top_questions.map((q, i) => `
                        <tr>
                            <td>${i + 1}</td>
                            <td>${q.question}</td>
                            <td>${q.count}</td>
                        </tr>
                    `).join('');
                } else {
                    questionsHtml = '';
                }
                document.getElementById('top-questions').innerHTML = questionsHtml || '<tr><td colspan="3">No questions yet</td></tr>';
                
                // Failed queries
                displayFailedQueries(data.failed_queries);
                
                // Command usage
                const commandHtml = data.command_usage.map(c => `
                    <tr>
                        <td>${c.command}</td>
                        <td>${c.count}</td>
                    </tr>
                `).join('');
                document.getElementById('command-usage').innerHTML = commandHtml || '<tr><td colspan="2">No commands used</td></tr>';
                
                // Suggestions
                const suggestionsHtml = data.suggestions.map(s => {
                    // Escape quotes in text for safe HTML
                    const wrongEscaped = s.wrong_answer.replace(/'/g, "&apos;").replace(/"/g, "&quot;");
                    const correctEscaped = s.correct_answer.replace(/'/g, "&apos;").replace(/"/g, "&quot;");
                    
                    return `
                    <tr onclick="viewSuggestion(${s.id}, '${wrongEscaped}', '${correctEscaped}', '${s.user_name}', '${s.timestamp}')" style="cursor: pointer;">
                        <td>${s.user_name}</td>
                        <td>${new Date(s.timestamp).toLocaleDateString()}</td>
                        <td>${s.wrong_answer.substring(0, 100)}${s.wrong_answer.length > 100 ? '...' : ''}</td>
                        <td>${s.correct_answer.substring(0, 100)}${s.correct_answer.length > 100 ? '...' : ''}</td>
                        <td onclick="event.stopPropagation();">
                            <button class="approve-btn" onclick="approveSuggestion(${s.id})">✓</button>
                            <button class="reject-btn" onclick="rejectSuggestion(${s.id})">✗</button>
                        </td>
                    </tr>
                `;
                }).join('');
                document.getElementById('suggestions-queue').innerHTML = suggestionsHtml || '<tr><td colspan="5">No pending suggestions</td></tr>';
                
            } catch (error) {
                console.error('Error loading dashboard data:', error);
            }
        }
        
        function displayConversations(conversations) {
            if (!conversations || conversations.length === 0) {
                document.getElementById('recent-conversations').innerHTML = '<p>No conversations yet</p>';
                return;
            }
            
            const html = conversations.slice(0, 10).map(conv => {
                const topicClass = 'topic-' + conv.topic.toLowerCase().replace(/ /g, '-');
                return `
                    <div class="conversation-item" onclick='showConversation(${JSON.stringify(conv)})'>
                        <div class="conversation-question">${conv.question}</div>
                        <div class="conversation-meta">
                            <span>👤 ${conv.user_name}</span>
                            <span>🕐 ${new Date(conv.timestamp).toLocaleString()}</span>
                            <span class="topic-pill ${topicClass}">${conv.topic}</span>
                        </div>
                    </div>
                `;
            }).join('');
            
            document.getElementById('recent-conversations').innerHTML = html;
        }
        
        function displayTopics(topics, total) {
            if (!topics || topics.length === 0) {
                document.getElementById('topics-table').innerHTML = '<tr><td colspan="3">No data yet</td></tr>';
                return;
            }
            
            const html = topics.map(t => {
                const pct = ((t.count / total) * 100).toFixed(1);
                return `
                    <tr>
                        <td>${t.topic}</td>
                        <td>${t.count}</td>
                        <td>${pct}%</td>
                    </tr>
                `;
            }).join('');
            
            document.getElementById('topics-table').innerHTML = html;
        }
        
        function displayFailedQueries(queries) {
            if (!queries || queries.length === 0) {
                document.getElementById('failed-queries').innerHTML = '<p>No failed queries - great job!</p>';
                return;
            }
            
            const html = queries.map(q => `
                <div class="conversation-item" style="border-left-color: #dc3545;">
                    <div class="conversation-question">${q.question}</div>
                    <div class="conversation-meta">
                        <span class="badge badge-danger">Confidence: ${q.confidence ? (q.confidence * 100).toFixed(0) + '%' : 'N/A'}</span>
                    </div>
                </div>
            `).join('');
            
            document.getElementById('failed-queries').innerHTML = html;
        }
        
        function showConversation(conv) {
            const sources = conv.sources && conv.sources.length > 0 ? 
                '<div class="sources-list"><strong>Sources:</strong><ul>' + 
                conv.sources.map(s => `<li>${s}</li>`).join('') +
                '</ul></div>' : '';
            
            const html = `
                <h2>Conversation Detail</h2>
                <div style="margin: 20px 0;">
                    <strong>👤 ${conv.user_name}</strong> • 
                    <span>${new Date(conv.timestamp).toLocaleString()}</span> • 
                    <span class="topic-pill topic-${conv.topic.toLowerCase().replace(/ /g, '-')}">${conv.topic}</span>
                </div>
                <div>
                    <h3>Question:</h3>
                    <div class="response-box">${conv.question}</div>
                </div>
                <div>
                    <h3>Response:</h3>
                    <div class="response-box">${conv.response || 'No response recorded'}</div>
                </div>
                ${sources}
                <div style="margin-top: 20px; font-size: 12px; color: #7f8c8d;">
                    ⏱️ Response time: ${conv.response_time_ms}ms • 
                    💰 Cost: $${(conv.cost_usd || 0).toFixed(4)}
                </div>
            `;
            
            document.getElementById('conversation-detail').innerHTML = html;
            document.getElementById('conversation-modal').classList.add('active');
        }
        
        function closeModal() {
            document.getElementById('conversation-modal').classList.remove('active');
        }
        
        async function approveSuggestion(id) {
            if (!confirm('Approve this suggestion? It will be applied immediately.')) return;
            
            try {
                const response = await fetch('/api/suggestions/' + id + '/approve', {
                    method: 'POST'
                });
                if (response.ok) {
                    alert('✅ Suggestion approved!');
                    loadData();
                } else {
                    alert('❌ Error approving suggestion');
                }
            } catch (error) {
                alert('❌ Error: ' + error.message);
            }
        }
        
        async function rejectSuggestion(id) {
            if (!confirm('Reject this suggestion?')) return;
            
            try {
                const response = await fetch('/api/suggestions/' + id + '/reject', {
                    method: 'POST'
                });
                if (response.ok) {
                    alert('✅ Suggestion rejected');
                    loadData();
                } else {
                    alert('❌ Error rejecting suggestion');
                }
            } catch (error) {
                alert('❌ Error: ' + error.message);
            }
        }
        
        // Load data on page load
        loadData();
        
        // Auto-refresh every 30 seconds
        setInterval(loadData, 30000);
        
        // Close modal on outside click
        window.onclick = function(event) {
            const modal = document.getElementById('conversation-modal');
            if (event.target == modal) {
                closeModal();
            }
        }
    </script>
</body>
</html>
"""


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
        
        return jsonify({
            **stats,
            "conversations": conversations,
            "suggestions": suggestions,
            "question_clusters": question_clusters
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
