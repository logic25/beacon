"""
Enhanced Dashboard v2 routes for Beacon analytics.
Full-featured dashboard with date ranges, conversations, topics, and insights.
"""

from flask import render_template_string, jsonify, request
from datetime import datetime, timedelta
from analytics import AnalyticsDB

# Dashboard HTML template with all features
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
            background: #f5f7fa;
            padding: 20px;
        }
        .container { max-width: 1600px; margin: 0 auto; }
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
        .metric-sublabel {
            color: #95a5a6;
            font-size: 12px;
            margin-top: 4px;
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
        tr:hover { background: #f8f9fa; }
        
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
            background: #f8f9fa;
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 15px;
            cursor: pointer;
            border-left: 4px solid #3498db;
        }
        .conversation-item:hover {
            background: #e9ecef;
        }
        .conversation-question {
            font-weight: 600;
            color: #2c3e50;
            margin-bottom: 8px;
        }
        .conversation-meta {
            font-size: 12px;
            color: #7f8c8d;
            display: flex;
            gap: 15px;
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
        <h1>🎯 Beacon Analytics Dashboard</h1>
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
                
                // Top questions
                const questionsHtml = data.top_questions.map((q, i) => `
                    <tr>
                        <td>${i + 1}</td>
                        <td>${q.question}</td>
                        <td>${q.count}</td>
                    </tr>
                `).join('');
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
                const suggestionsHtml = data.suggestions.map(s => `
                    <tr>
                        <td>${s.user_name}</td>
                        <td>${new Date(s.timestamp).toLocaleDateString()}</td>
                        <td>${s.wrong_answer.substring(0, 50)}...</td>
                        <td>${s.correct_answer.substring(0, 50)}...</td>
                        <td>
                            <button class="btn btn-approve" onclick="approveSuggestion(${s.id})">✓</button>
                            <button class="btn btn-reject" onclick="rejectSuggestion(${s.id})">✗</button>
                        </td>
                    </tr>
                `).join('');
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


def add_dashboard_v2_routes(app, analytics_db: AnalyticsDB):
    """Add enhanced dashboard routes to Flask app."""
    
    @app.route("/dashboard")
    def dashboard():
        """Main dashboard page."""
        return render_template_string(DASHBOARD_V2_HTML)
    
    @app.route("/api/dashboard")
    def api_dashboard():
        """Dashboard data API with date range support."""
        # Get query parameters
        days = request.args.get('days', type=int)
        start_date = request.args.get('start')
        end_date = request.args.get('end')
        
        # Get stats for date range
        stats = analytics_db.get_stats(
            start_date=start_date,
            end_date=end_date,
            days=days
        )
        
        # Get recent conversations
        conversations = analytics_db.get_recent_conversations(limit=20)
        
        # Get pending suggestions
        suggestions = analytics_db.get_pending_suggestions()
        
        return jsonify({
            **stats,
            "conversations": conversations,
            "suggestions": suggestions,
        })
    
    @app.route("/api/suggestions/<int:suggestion_id>/approve", methods=["POST"])
    def api_approve_suggestion(suggestion_id):
        """Approve a suggestion."""
        try:
            correction_data = analytics_db.approve_suggestion(
                suggestion_id,
                reviewed_by="dashboard_user"
            )
            
            # TODO: Apply the correction to knowledge base
            # knowledge_base.add_correction(...)
            
            return jsonify({"status": "ok", "message": "Suggestion approved"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 400
    
    @app.route("/api/suggestions/<int:suggestion_id>/reject", methods=["POST"])
    def api_reject_suggestion(suggestion_id):
        """Reject a suggestion."""
        try:
            analytics_db.reject_suggestion(
                suggestion_id,
                reviewed_by="dashboard_user"
            )
            return jsonify({"status": "ok", "message": "Suggestion rejected"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 400
