"""
Flask routes for Content Intelligence dashboard  
Includes inline BASE_TEMPLATE (no imports) to avoid circular dependencies
"""

from flask import Blueprint, render_template_string, request, jsonify
from content_engine.engine import ContentEngine
import traceback

content_bp = Blueprint('content', __name__)
engine = ContentEngine()

# Full template with sidebar (inline, no imports needed)
CONTENT_INTELLIGENCE_HTML = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Beacon - Content Intelligence</title>
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
            margin: 0;
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
            padding: 20px;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .logo {
            width: 32px;
            height: 32px;
            background: linear-gradient(135deg, var(--primary), #fb923c);
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 700;
            font-size: 18px;
            flex-shrink: 0;
        }
        
        .sidebar-title {
            font-weight: 600;
            font-size: 16px;
            white-space: nowrap;
            overflow: hidden;
        }
        
        .sidebar.collapsed .sidebar-title { opacity: 0; width: 0; }
        
        nav { flex: 1; padding: 16px 12px; }
        
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
            transition: all 0.2s;
            cursor: pointer;
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
            background: none;
            color: var(--text-muted);
            font-size: 14px;
            cursor: pointer;
            transition: all 0.2s;
            text-decoration: none;
        }
        
        .footer-btn:hover { background: var(--bg); }
        .footer-btn.logout { color: var(--danger); }
        .footer-btn.logout:hover { background: #fee2e2; }
        
        .main {
            margin-left: var(--sidebar-width);
            padding: 32px 24px;
            transition: margin-left 0.2s;
            min-height: 100vh;
        }
        
        .sidebar.collapsed + .main { margin-left: var(--sidebar-collapsed); }
        
        .page-header { margin-bottom: 32px; }
        .page-title { font-size: 24px; font-weight: 700; margin-bottom: 4px; }
        .page-subtitle { font-size: 14px; color: var(--text-muted); }
        
        .tabs {
            display: flex;
            gap: 8px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 24px;
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
        
        .tab:hover { color: var(--text); background: var(--bg); border-radius: 8px 8px 0 0; }
        .tab.active { color: var(--primary); border-bottom-color: var(--primary); }
        
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        
        .card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 16px;
        }
        
        .badge {
            padding: 4px 12px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
            display: inline-block;
            margin-right: 8px;
        }
        
        .badge-high { background: #fee2e2; color: var(--danger); }
        .badge-medium { background: #fef3c7; color: var(--primary); }
        
        .btn {
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            border: none;
            cursor: pointer;
            transition: all 0.2s;
            margin-right: 8px;
        }
        
        .btn-primary { background: var(--primary); color: white; }
        .btn-primary:hover { background: #d97706; }
        .btn-outline { background: white; border: 1px solid var(--border); color: var(--text); }
        .btn-outline:hover { background: var(--bg); }
        
        @media (max-width: 768px) {
            .sidebar {
                left: -240px;
                z-index: 1000;
            }
            .sidebar.mobile-open { left: 0; }
            .main { margin-left: 0; }
        }
    </style>
</head>
<body>
    <aside class="sidebar" id="sidebar">
        <div class="sidebar-header">
            <div class="logo">B</div>
            <div class="sidebar-title">Beacon</div>
        </div>
        
        <nav>
            <a href="/dashboard" class="nav-item">
                <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
                <span class="nav-label">Analytics</span>
            </a>
            <a href="/conversations" class="nav-item">
                <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
                <span class="nav-label">Conversations</span>
            </a>
            <a href="/feedback-page" class="nav-item">
                <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                </svg>
                <span class="nav-label">Feedback</span>
            </a>
            <a href="/content-intelligence" class="nav-item active">
                <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                </svg>
                <span class="nav-label">Content Engine</span>
            </a>
            <a href="/roadmap-page" class="nav-item">
                <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
                </svg>
                <span class="nav-label">Roadmap</span>
            </a>
        </nav>
        
        <div class="sidebar-footer">
            <button class="footer-btn" onclick="toggleDarkMode()">
                <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                </svg>
                <span class="nav-label">Dark Mode</span>
            </button>
            
            <button class="footer-btn" onclick="toggleSidebar()">
                <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
        <div class="page-header">
            <div class="page-title">💡 Content Intelligence</div>
            <div class="page-subtitle">AI-identified content opportunities from team questions and trends</div>
        </div>
        
        <div class="tabs">
            <button class="tab active" onclick="showTab('pipeline')">🔍 Pipeline <span id="pipeline-count" style="background: #fef3c7; color: #f59e0b; padding: 2px 8px; border-radius: 12px; font-size: 10px; margin-left: 4px;">0</span></button>
            <button class="tab" onclick="showTab('published')">📊 Published</button>
            <button class="tab" onclick="showTab('newsletters')">📧 Newsletters</button>
        </div>
        
        <div id="pipeline-tab" class="tab-content active">
            <div id="candidates-container">
                <div style="text-align: center; padding: 60px 20px; color: var(--text-muted);">
                    <svg width="48" height="48" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="margin: 0 auto 16px;">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                    </svg>
                    <div style="font-size: 16px; font-weight: 600; margin-bottom: 8px;">No content opportunities yet</div>
                    <div style="font-size: 14px;">AI will identify content based on team questions</div>
                </div>
            </div>
        </div>
        
        <div id="published-tab" class="tab-content">
            <div style="text-align: center; padding: 60px 20px; color: var(--text-muted);">
                <div style="font-size: 16px; font-weight: 600; margin-bottom: 8px;">Published content</div>
                <div style="font-size: 14px;">Coming soon</div>
            </div>
        </div>
        
        <div id="newsletters-tab" class="tab-content">
            <div style="text-align: center; padding: 60px 20px; color: var(--text-muted);">
                <div style="font-size: 16px; font-weight: 600; margin-bottom: 8px;">Newsletter editions</div>
                <div style="font-size: 14px;">Coming soon</div>
            </div>
        </div>
    </main>
    
    <script>
        function toggleSidebar() {
            document.getElementById('sidebar').classList.toggle('collapsed');
        }
        
        function toggleDarkMode() {
            document.body.classList.toggle('dark');
            localStorage.setItem('darkMode', document.body.classList.contains('dark'));
        }
        
        if (localStorage.getItem('darkMode') === 'true') {
            document.body.classList.add('dark');
        }
        
        function showTab(tabName) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(btn => btn.classList.remove('active'));
            document.getElementById(tabName + '-tab').classList.add('active');
            event.target.classList.add('active');
        }
        
        async function loadCandidates() {
            try {
                const response = await fetch('/api/content/candidates');
                const data = await response.json();
                
                if (data.success && data.candidates.length > 0) {
                    document.getElementById('pipeline-count').textContent = data.candidates.length;
                    const container = document.getElementById('candidates-container');
                    container.innerHTML = '';
                    
                    data.candidates.forEach(c => {
                        const card = document.createElement('div');
                        card.className = 'card';
                        card.innerHTML = `
                            <div style="margin-bottom: 12px;">
                                <span class="badge badge-${c.priority}">${c.priority}</span>
                                <span class="badge">${c.content_type === 'blog_post' ? '📝 Blog Post' : '📧 Newsletter'}</span>
                            </div>
                            <h3 style="font-size: 16px; font-weight: 600; margin-bottom: 8px;">${c.title}</h3>
                            <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 12px;">${c.reasoning}</p>
                            <div style="display: flex; gap: 16px; margin: 12px 0; font-size: 13px; flex-wrap: wrap;">
                                <div style="color: var(--text-muted);">⭐ ${c.relevance_score}% relevance</div>
                                <div style="color: var(--text-muted);">📈 ${c.search_interest} search interest</div>
                                <div style="color: var(--text-muted);">👥 ${c.team_questions_count} team questions</div>
                            </div>
                            ${c.review_question ? `<div style="background: #fef3c7; padding: 12px; border-radius: 8px; margin: 12px 0; font-size: 13px;">💡 <strong>Review Question:</strong> ${c.review_question}</div>` : ''}
                            <div style="margin-top: 16px;">
                                <button class="btn btn-primary" onclick="generateContent(${c.id}, 'blog_post')">✨ Generate</button>
                                <button class="btn btn-outline" onclick="viewSource('${c.source_url}')">🔗 Source</button>
                            </div>
                        `;
                        container.appendChild(card);
                    });
                }
            } catch (error) {
                console.error('Failed to load candidates:', error);
            }
        }
        
        async function generateContent(candidateId, contentType) {
            if (!confirm('Generate content?')) return;
            const btn = event.target;
            btn.disabled = true;
            btn.textContent = 'Generating...';
            try {
                const response = await fetch('/api/content/generate', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({candidate_id: candidateId, content_type: contentType})
                });
                const data = await response.json();
                if (data.success) {
                    alert(`Generated ${data.word_count} words!`);
                } else {
                    alert('Error: ' + data.error);
                }
            } catch (error) {
                alert('Error: ' + error);
            } finally {
                btn.disabled = false;
                btn.textContent = '✨ Generate';
            }
        }
        
        function viewSource(url) {
            if (url) window.open(url, '_blank');
        }
        
        loadCandidates();
    </script>
</body>
</html>'''


@content_bp.route('/content-intelligence')
def dashboard():
    """Content Intelligence dashboard with inline sidebar"""
    return render_template_string(CONTENT_INTELLIGENCE_HTML)


# Keep all API endpoints unchanged
@content_bp.route('/api/content/candidates', methods=['GET'])
def get_candidates():
    try:
        priority = request.args.get('priority')
        candidates = engine.get_pending_candidates(priority=priority)
        return jsonify({
            "success": True,
            "candidates": [{
                "id": c.id, "title": c.title, "content_type": c.content_type,
                "priority": c.priority, "relevance_score": c.relevance_score,
                "search_interest": c.search_interest, "reasoning": c.reasoning,
                "review_question": c.review_question, "team_questions_count": c.team_questions_count,
                "source_url": c.source_url
            } for c in candidates]
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@content_bp.route('/api/content/generate', methods=['POST'])
def generate_content():
    try:
        data = request.json
        candidate_id = data.get('candidate_id')
        content_type = data.get('content_type', 'blog_post')
        if not candidate_id:
            return jsonify({"success": False, "error": "Missing candidate_id"}), 400
        content = engine.generate_blog_post(candidate_id) if content_type == 'blog_post' else engine.generate_newsletter(candidate_id)
        return jsonify({"success": True, "content": content, "word_count": len(content.split())})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@content_bp.route('/api/content/decide', methods=['POST'])
def decide():
    try:
        data = request.json
        candidate_id = data.get('candidate_id')
        decision = data.get('decision')
        import sqlite3
        conn = sqlite3.connect(engine.db_path)
        c = conn.cursor()
        if decision == 'skip':
            c.execute("UPDATE content_candidates SET status = 'skipped' WHERE id = ?", (candidate_id,))
        elif decision == 'publish':
            c.execute("UPDATE content_candidates SET status = 'published' WHERE id = ?", (candidate_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
