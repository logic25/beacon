"""
Flask routes for Content Intelligence dashboard
Uses shared BASE_TEMPLATE from dashboard.py for consistent sidebar/navigation
"""

from flask import Blueprint, render_template_string, request, jsonify
from content_engine.engine import ContentEngine
import traceback

content_bp = Blueprint('content', __name__)
engine = ContentEngine()

# Import BASE_TEMPLATE from dashboard module
# This ensures Content Intelligence uses the same sidebar/navigation as other pages
try:
    from dashboard import BASE_TEMPLATE
except ImportError:
    # Fallback if dashboard module not available
    BASE_TEMPLATE = None

# Content Intelligence page using shared template
CONTENT_INTELLIGENCE_PAGE = '''{% block content %}
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
        <div style="text-align: center; padding: 60px 20px; color: var(--text-muted);">
            <svg width="48" height="48" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="margin: 0 auto 16px;">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
            <div style="font-size: 16px; font-weight: 600; margin-bottom: 8px;">No content opportunities yet</div>
            <div style="font-size: 14px;">AI will identify content based on team questions</div>
        </div>
    </div>
</div>

<!-- Published Tab -->
<div id="published-tab" class="tab-content">
    <div style="text-align: center; padding: 60px 20px; color: var(--text-muted);">
        <div style="font-size: 16px; font-weight: 600; margin-bottom: 8px;">Published content</div>
        <div style="font-size: 14px;">Coming soon</div>
    </div>
</div>

<!-- Newsletters Tab -->
<div id="newsletters-tab" class="tab-content">
    <div style="text-align: center; padding: 60px 20px; color: var(--text-muted);">
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
                    <div style="display: flex; gap: 16px; margin: 12px 0; font-size: 13px; flex-wrap: wrap;">
                        <div style="display: flex; align-items: center; gap: 4px; color: var(--text-muted);">⭐ ${c.relevance_score}% relevance</div>
                        <div style="display: flex; align-items: center; gap: 4px; color: var(--text-muted);">📈 ${c.search_interest} search interest</div>
                        <div style="display: flex; align-items: center; gap: 4px; color: var(--text-muted);">👥 ${c.team_questions_count} team questions</div>
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
{% endblock %}'''


@content_bp.route('/content-intelligence')
def dashboard():
    """Main content intelligence dashboard - uses shared BASE_TEMPLATE"""
    if BASE_TEMPLATE:
        # Use shared template from dashboard.py (includes sidebar)
        html = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', CONTENT_INTELLIGENCE_PAGE)
        return render_template_string(html, active_page='content', page_title='Content Intelligence')
    else:
        # Fallback: standalone page (shouldn't happen in production)
        return render_template_string(f'''
        <!DOCTYPE html>
        <html><head><title>Content Intelligence</title></head>
        <body><p>Error: Dashboard template not loaded</p></body></html>
        ''')


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
