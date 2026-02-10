"""
Flask routes for Content Intelligence dashboard
"""

from flask import Blueprint, render_template, request, jsonify
from content_engine.engine import ContentEngine
import traceback

content_bp = Blueprint('content', __name__)
engine = ContentEngine()


@content_bp.route('/content-intelligence')
def dashboard():
    """Main content intelligence dashboard"""
    return render_template('content_intelligence.html')


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
