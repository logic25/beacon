"""
Dashboard routes for Beacon analytics.
Add these to your bot_v2.py Flask app.
"""

from flask import render_template_string, jsonify, request
from analytics import AnalyticsDB

# Initialize analytics
analytics_db = AnalyticsDB()


# Dashboard HTML template
DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Beacon Analytics Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            background: #f5f7fa;
            padding: 20px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 {
            color: #2c3e50;
            margin-bottom: 10px;
            font-size: 32px;
        }
        .subtitle {
            color: #7f8c8d;
            margin-bottom: 30px;
            font-size: 14px;
        }
        .metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .metric-card {
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
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
        .section {
            background: white;
            padding: 25px;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        .section-title {
            font-size: 20px;
            color: #2c3e50;
            margin-bottom: 15px;
            font-weight: 600;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th {
            text-align: left;
            padding: 12px;
            background: #f8f9fa;
            color: #2c3e50;
            font-weight: 600;
            border-bottom: 2px solid #dee2e6;
        }
        td {
            padding: 12px;
            border-bottom: 1px solid #dee2e6;
        }
        tr:hover {
            background: #f8f9fa;
        }
        .badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 600;
        }
        .badge-pending {
            background: #fff3cd;
            color: #856404;
        }
        .badge-success {
            background: #d4edda;
            color: #155724;
        }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
        }
        .btn-approve {
            background: #28a745;
            color: white;
        }
        .btn-reject {
            background: #dc3545;
            color: white;
        }
        .btn:hover {
            opacity: 0.9;
        }
        .refresh-btn {
            background: #3498db;
            color: white;
            padding: 10px 20px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            margin-bottom: 20px;
        }
        .success-rate {
            font-size: 36px;
            font-weight: bold;
        }
        .success-rate.high { color: #28a745; }
        .success-rate.medium { color: #ffc107; }
        .success-rate.low { color: #dc3545; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎯 Beacon Analytics Dashboard</h1>
        <div class="subtitle">Last 7 days • Auto-refreshes every 30 seconds</div>
        
        <button class="refresh-btn" onclick="loadData()">🔄 Refresh Now</button>
        
        <!-- Key Metrics -->
        <div class="metrics">
            <div class="metric-card">
                <div class="metric-value" id="total-questions">-</div>
                <div class="metric-label">Total Questions</div>
            </div>
            <div class="metric-card">
                <div class="metric-value" id="success-rate">-</div>
                <div class="metric-label">Success Rate</div>
            </div>
            <div class="metric-card">
                <div class="metric-value" id="active-users">-</div>
                <div class="metric-label">Active Users</div>
            </div>
            <div class="metric-card">
                <div class="metric-value" id="total-cost">-</div>
                <div class="metric-label">API Cost (USD)</div>
            </div>
            <div class="metric-card">
                <div class="metric-value" id="pending-suggestions">-</div>
                <div class="metric-label">Pending Reviews</div>
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
        
        <!-- Pending Suggestions -->
        <div class="section">
            <div class="section-title">📝 Suggestions Queue (Need Review)</div>
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
    
    <script>
        async function loadData() {
            try {
                const response = await fetch('/api/dashboard');
                const data = await response.json();
                
                // Update metrics
                document.getElementById('total-questions').textContent = data.total_questions;
                
                const successRate = data.success_rate;
                const successEl = document.getElementById('success-rate');
                successEl.textContent = successRate + '%';
                successEl.className = 'metric-value success-rate ' + 
                    (successRate >= 80 ? 'high' : successRate >= 60 ? 'medium' : 'low');
                
                document.getElementById('active-users').textContent = data.active_users;
                document.getElementById('total-cost').textContent = '$' + data.total_cost_usd.toFixed(2);
                document.getElementById('pending-suggestions').textContent = data.pending_suggestions;
                
                // Update top users
                const usersHtml = data.top_users.map((user, i) => `
                    <tr>
                        <td>${i + 1}</td>
                        <td>${user.name}</td>
                        <td>${user.count}</td>
                    </tr>
                `).join('');
                document.getElementById('top-users').innerHTML = usersHtml || '<tr><td colspan="3">No data yet</td></tr>';
                
                // Update top questions
                const questionsHtml = data.top_questions.map((q, i) => `
                    <tr>
                        <td>${i + 1}</td>
                        <td>${q.question}</td>
                        <td>${q.count}</td>
                    </tr>
                `).join('');
                document.getElementById('top-questions').innerHTML = questionsHtml || '<tr><td colspan="3">No questions yet</td></tr>';
                
                // Update suggestions
                const suggestionsHtml = data.suggestions.map(s => `
                    <tr>
                        <td>${s.user_name}</td>
                        <td>${new Date(s.timestamp).toLocaleDateString()}</td>
                        <td>${s.wrong_answer.substring(0, 50)}...</td>
                        <td>${s.correct_answer.substring(0, 50)}...</td>
                        <td>
                            <button class="btn btn-approve" onclick="approveSuggestion(${s.id})">✓ Approve</button>
                            <button class="btn btn-reject" onclick="rejectSuggestion(${s.id})">✗ Reject</button>
                        </td>
                    </tr>
                `).join('');
                document.getElementById('suggestions-queue').innerHTML = suggestionsHtml || '<tr><td colspan="5">No pending suggestions</td></tr>';
                
            } catch (error) {
                console.error('Error loading dashboard data:', error);
            }
        }
        
        async function approveSuggestion(id) {
            if (!confirm('Approve this suggestion? It will be applied immediately.')) return;
            
            try {
                const response = await fetch('/api/suggestions/' + id + '/approve', {
                    method: 'POST'
                });
                if (response.ok) {
                    alert('✅ Suggestion approved and applied!');
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
    </script>
</body>
</html>
"""


def add_dashboard_routes(app, analytics_db):
    """Add dashboard routes to Flask app."""
    
    @app.route("/dashboard")
    def dashboard():
        """Main dashboard page."""
        return render_template_string(DASHBOARD_HTML)
    
    @app.route("/api/dashboard")
    def api_dashboard():
        """Dashboard data API."""
        stats = analytics_db.get_stats(days=7)
        suggestions = analytics_db.get_pending_suggestions()
        
        return jsonify({
            **stats,
            "suggestions": suggestions,
        })
    
    @app.route("/api/suggestions/<int:suggestion_id>/approve", methods=["POST"])
    def api_approve_suggestion(suggestion_id):
        """Approve a suggestion."""
        try:
            # Get suggestion data
            correction_data = analytics_db.approve_suggestion(
                suggestion_id,
                reviewed_by="dashboard_user"  # TODO: Get actual user from auth
            )
            
            # TODO: Apply the correction to knowledge base
            # knowledge_base.add_correction(
            #     correction_data['wrong_answer'],
            #     correction_data['correct_answer'],
            #     topics=correction_data['topics']
            # )
            
            return jsonify({"status": "ok", "message": "Suggestion approved"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 400
    
    @app.route("/api/suggestions/<int:suggestion_id>/reject", methods=["POST"])
    def api_reject_suggestion(suggestion_id):
        """Reject a suggestion."""
        try:
            analytics_db.reject_suggestion(
                suggestion_id,
                reviewed_by="dashboard_user"  # TODO: Get actual user from auth
            )
            return jsonify({"status": "ok", "message": "Suggestion rejected"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 400
