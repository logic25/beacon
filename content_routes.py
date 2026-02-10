"""
Flask routes for Content Intelligence dashboard
"""

from flask import Blueprint, render_template_string, request, jsonify
from content_engine.engine import ContentEngine
import traceback

content_bp = Blueprint('content', __name__)
engine = ContentEngine()

# Lovable-styled Content Intelligence template (inline, no external file needed)
CONTENT_INTELLIGENCE_HTML = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
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
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            padding: 32px 24px;
            max-width: 1400px;
            margin: 0 auto;
        }
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
            transition: all 0.2s;
        }
        .card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.05); transform: translateY(-2px); }
        
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
        .badge-blog-post { background: #f3f4f6; color: #6b7280; }
        .badge-newsletter { background: #f3f4f6; color: #6b7280; }
        
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
        
        .metric-row {
            display: flex;
            gap: 16px;
            margin: 12px 0;
            font-size: 13px;
            flex-wrap: wrap;
        }
        .metric {
            display: flex;
            align-items: center;
            gap: 4px;
            color: var(--text-muted);
        }
        
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: var(--text-muted);
        }
        .empty-state svg {
            margin: 0 auto 16px;
        }
    </style>
</head>
<body>
    <div class="page-header">
        <div class="page-title">💡 Content Intelligence</div>
        <div class="page-subtitle">AI-identified content opportunities from team questions and trends</div>
    </div>
    
    <div class="tabs">
        <button class="tab active" onclick="showTab('pipeline')">🔍 Pipeline <span id="pipeline-count" style="background: #fef3c7; color: #f59e0b; padding: 2px 8px; border-radius: 12px; font-size: 10px; margin-left: 4px;">0</span></button>
        <button class="tab" onclick="showTab('published')">📊 Published</button>
        <button class="tab" onclick="showTab('newsletters')">📧 Newsletters</button>
    </div>
    
    <!-- Pipeline Tab -->
    <div id="pipeline-tab" class="tab-content active">
        <div id="candidates-container">
            <div class="empty-state">
                <svg width="48" height="48" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                </svg>
                <div style="font-size: 16px; font-weight: 600; margin-bottom: 8px;">No content opportunities yet</div>
                <div style="font-size: 14px;">AI will identify content based on team questions</div>
            </div>
        </div>
    </div>
    
    <!-- Published Tab -->
    <div id="published-tab" class="tab-content">
        <div class="empty-state">
            <div style="font-size: 16px; font-weight: 600; margin-bottom: 8px;">Published content</div>
            <div style="font-size: 14px;">Coming soon</div>
        </div>
    </div>
    
    <!-- Newsletters Tab -->
    <div id="newsletters-tab" class="tab-content">
        <div class="empty-state">
            <div style="font-size: 16px; font-weight: 600; margin-bottom: 8px;">Newsletter editions</div>
            <div style="font-size: 14px;">Coming soon</div>
        </div>
    </div>
    
    <script>
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
                                <span class="badge badge-${c.content_type.replace('_', '-')}">${c.content_type === 'blog_post' ? '📝 Blog Post' : '📧 Newsletter'}</span>
                            </div>
                            <h3 style="font-size: 16px; font-weight: 600; margin-bottom: 8px;">${c.title}</h3>
                            <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 12px;">${c.reasoning}</p>
                            <div class="metric-row">
                                <div class="metric">⭐ ${c.relevance_score}% relevance</div>
                                <div class="metric">📈 ${c.search_interest} search interest</div>
                                <div class="metric">👥 ${c.team_questions_count} team questions</div>
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
        
        // Load candidates on page load
        loadCandidates();
    </script>
</body>
</html>'''


@content_bp.route('/content-intelligence')
def dashboard():
    """Main content intelligence dashboard - Lovable styled inline template"""
    return render_template_string(CONTENT_INTELLIGENCE_HTML)


@content_bp.route('/api/content/candidates', methods=['GET'])
def get_candidates():
    """Get all pending candidates"""
    try:
        priority = request.args.get('priority')
        candidates = engine.get_pending_candidates(priority=priority)
        
        return jsonify({
            "success": True,
            "candidates": [
                {
                    "id": c.id,
                    "title": c.title,
                    "content_type": c.content_type,
                    "priority": c.priority,
                    "relevance_score": c.relevance_score,
                    "search_interest": c.search_interest,
                    "affects_services": c.affects_services,
                    "key_topics": c.key_topics,
                    "reasoning": c.reasoning,
                    "review_question": c.review_question,
                    "team_questions_count": c.team_questions_count,
                    "team_questions": c.team_questions,
                    "most_common_angle": c.most_common_angle,
                    "source_url": c.source_url,
                    "content_preview": c.content_preview,
                    "created_at": c.created_at
                }
                for c in candidates
            ]
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@content_bp.route('/api/content/generate', methods=['POST'])
def generate_content():
    """Generate blog post or newsletter"""
    try:
        data = request.json
        candidate_id = data.get('candidate_id')
        content_type = data.get('content_type', 'blog_post')
        
        if not candidate_id:
            return jsonify({"success": False, "error": "Missing candidate_id"}), 400
        
        if content_type == 'blog_post':
            content = engine.generate_blog_post(candidate_id)
        elif content_type == 'newsletter':
            content = engine.generate_newsletter(candidate_id)
        else:
            return jsonify({"success": False, "error": "Invalid content_type"}), 400
        
        return jsonify({
            "success": True,
            "content": content,
            "word_count": len(content.split())
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@content_bp.route('/api/content/analyze-test', methods=['POST'])
def analyze_test():
    """Test endpoint - analyze a sample DOB update"""
    try:
        data = request.json
        title = data.get('title', 'Test DOB Update')
        summary = data.get('summary', 'Test summary')
        source_url = data.get('source_url', 'https://example.com')
        
        candidate = engine.analyze_update(title, summary, source_url)
        
        return jsonify({
            "success": True,
            "candidate": {
                "id": candidate.id,
                "title": candidate.title,
                "content_type": candidate.content_type,
                "priority": candidate.priority,
                "relevance_score": candidate.relevance_score,
                "reasoning": candidate.reasoning,
                "team_questions_count": candidate.team_questions_count
            }
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@content_bp.route('/api/content/decide', methods=['POST'])
def decide():
    """User decision on candidate (skip/publish)"""
    try:
        data = request.json
        candidate_id = data.get('candidate_id')
        decision = data.get('decision')  # 'skip' or 'publish'
        
        # Update status in database
        import sqlite3
        conn = sqlite3.connect(engine.db_path)
        c = conn.cursor()
        
        if decision == 'skip':
            c.execute("UPDATE content_candidates SET status = 'skipped' WHERE id = ?", 
                     (candidate_id,))
        elif decision == 'publish':
            c.execute("UPDATE content_candidates SET status = 'published' WHERE id = ?",
                     (candidate_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({"success": True})
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
