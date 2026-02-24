# Cross-Reference Scoring Engine - Specification

## Core Function:
Analyze team questions + knowledge base to intelligently score content opportunities

## Intelligence Flow:
```
1. Get trending questions from analytics DB (interactions table)
2. For each question cluster:
   - Query RAG for related knowledge base docs
   - Send to Claude with full context:
     * Question text + frequency
     * Retrieved knowledge base chunks
     * Existing published content
   - Claude returns intelligent scoring:
     * Relevance score (0-100)
     * Expertise score (do we have docs on this?)
     * Demand score (how many times asked?)
     * Content angle (what specifically to write about)
     * Recommended format (blog post, newsletter mention, guide)
```

## Stress Test Cases:

### Test 1: High Demand + High Expertise
- Input: "Alt-2 filing requirements" asked 12 times
- Knowledge base has: alt2_comprehensive_guide.md
- Expected: Score 95/100, recommend blog post

### Test 2: High Demand + No Expertise  
- Input: "Landmarks preservation rules" asked 8 times
- Knowledge base has: Nothing
- Expected: Score 40/100, recommend "create guide first"

### Test 3: Low Demand + High Expertise
- Input: "What is MDL?" asked 1 time
- Knowledge base has: mdl_complete_guide.md
- Expected: Score 50/100, recommend "newsletter mention"

### Test 4: Duplicate Content
- Input: "DOB permit process" asked 6 times
- Knowledge base has: dob_permits_guide.md
- Published content has: "How to Navigate DOB Permits" (3 weeks ago)
- Expected: Score 20/100, recommend "skip - already covered"

### Test 5: Related Questions Cluster
- Input: "Alt-2 timeline" (4x), "Alt-2 fees" (3x), "Alt-2 requirements" (5x)
- Should cluster as: "Alt-2 filing process" (12 total)
- Expected: Single content opportunity, not 3 separate ones

### Test 6: Edge Cases
- Empty analytics DB → Should return empty list, not crash
- No knowledge base results → Should still score based on demand
- Corrupted question text → Should skip gracefully
- 1000+ questions → Should process in batches, not timeout
- Concurrent requests → Should handle race conditions

### Test 7: Performance
- 50 questions → Process in < 30 seconds
- 200 questions → Process in < 2 minutes
- Should cache Claude responses for 1 hour
- Should deduplicate similar questions before sending to Claude

## API Design:

POST /api/content/analyze-opportunities
Response:
```json
{
  "opportunities": [
    {
      "title": "Guide to Alt-2 Filing Requirements in NYC",
      "cluster": ["alt-2 filing", "alt2 requirements", "alteration type 2"],
      "demand_score": 92,
      "expertise_score": 85,
      "relevance_score": 94,
      "overall_score": 90,
      "question_count": 12,
      "knowledge_docs": ["alt2_comprehensive_guide.md"],
      "content_angle": "Focus on recent changes and common mistakes",
      "recommended_format": "blog_post",
      "reasoning": "High demand + strong expertise + timely topic",
      "estimated_search_volume": 450,
      "time_to_write": "30 minutes (we have guide)",
      "priority": "HIGH"
    }
  ],
  "analysis_time_seconds": 12.3,
  "questions_analyzed": 47,
  "opportunities_found": 3
}
```

## Implementation Notes:
- Use Sonnet 4.5 for intelligence (not Haiku - needs reasoning)
- Cluster similar questions BEFORE sending to Claude (save API costs)
- Include published content context to avoid duplicates
- Cache results for 1 hour (analytics don't change that fast)
- Log all Claude reasoning for debugging
