"""
Topic classifier using Claude API.
Intelligently categorizes questions into GLE service areas.
"""

import logging
from typing import Optional
import anthropic
from config import Settings, get_settings

logger = logging.getLogger(__name__)


class TopicClassifier:
    """LLM-based topic classification for analytics."""
    
    # Available topic categories
    TOPICS = [
        "DOB Filings",           # Permits, ALT1/2/3, NB, PAA
        "Zoning",                # Use groups, FAR, setbacks, variances
        "DHCR",                  # Rent stabilization, MCI, IAI
        "Violations",            # ECB, DOB violations, penalties
        "Certificates",          # CO, TCO, sign-offs
        "Building Code",         # Egress, fire safety, structural
        "FDNY",                  # Fire alarms, sprinklers, suppression
        "MDL",                   # Multiple Dwelling Law, Class A/B
        "Noise/Hours",           # Construction hours, noise regulations
        "Landmarks",             # LPC, historic preservation
        "Property Lookup",       # Address/BIN lookups, property info
        "Plans/Drawings",        # Architectural plans, blueprints
        "General",               # Everything else
    ]
    
    SYSTEM_PROMPT = """You are a topic classifier for a NYC permit expediting firm.

Your job: Categorize questions into ONE topic from this list:
- DOB Filings (permits, ALT1/2/3, NB, PAA, objections)
- Zoning (use groups, FAR, setbacks, variances, ZR)
- DHCR (rent stabilization, MCI, IAI, rent increases)
- Violations (ECB, DOB violations, penalties)
- Certificates (CO, TCO, sign-offs, LOA)
- Building Code (egress, fire safety, structural, occupancy)
- FDNY (fire alarms, sprinklers, suppression, Ansul)
- MDL (Multiple Dwelling Law, Class A/B dwellings)
- Noise/Hours (construction hours, noise regulations, work times)
- Landmarks (LPC, historic preservation)
- Property Lookup (address lookups, BIN/BBL, property info)
- Plans/Drawings (architectural plans, blueprints, drawings)
- General (anything else)

Rules:
1. Respond with ONLY the topic name, nothing else
2. Be specific - "What time can you work until?" is Noise/Hours, not General
3. Commands like "/feedback" or "/correct" are General
4. If unclear, default to the most specific category that could apply

Examples:
Q: "What time can you work until?"
A: Noise/Hours

Q: "How do I file an ALT2?"
A: DOB Filings

Q: "What's the setback requirement for R6?"
A: Zoning

Q: "Can I get an agent to help with filing forms?"
A: General

Q: "What are the DHCR requirements for rent stabilization?"
A: DHCR

Q: "How long does FDNY withdrawal take?"
A: FDNY"""

    def __init__(self, settings: Optional[Settings] = None):
        """Initialize classifier."""
        self.settings = settings or get_settings()
        self.client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        # Use Haiku 4.5 for speed and cost efficiency
        self.model = "claude-haiku-4-5-20251001"
    
    def classify(self, question: str, response: str = "") -> str:
        """Classify a question into a topic category.
        
        Args:
            question: The user's question
            response: Optional response text for context
            
        Returns:
            Topic category name
        """
        try:
            # Build prompt with optional response context
            prompt = f"Question: {question}"
            if response:
                prompt += f"\n\nContext from answer: {response[:200]}"  # Limit response length
            
            # Call Claude API
            message = self.client.messages.create(
                model=self.model,
                max_tokens=20,  # Just need one word back
                temperature=0,  # Deterministic
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )
            
            # Extract topic from response
            topic = message.content[0].text.strip()
            
            # Validate it's a known topic
            if topic in self.TOPICS:
                logger.debug(f"Classified '{question[:50]}...' as {topic}")
                return topic
            else:
                logger.warning(f"Unknown topic '{topic}' for question '{question[:50]}...', defaulting to General")
                return "General"
                
        except anthropic.APIError as e:
            logger.error(f"Topic classification API error: {e}")
            # Fall through to keyword fallback below
            return self._keyword_fallback(question, response)
        except Exception as e:
            logger.error(f"Topic classification failed: {e}", exc_info=True)
            return self._keyword_fallback(question, response)

    def _keyword_fallback(self, question: str, response: str = "") -> str:
        """Keyword-based classification when LLM is unavailable."""
        combined = (question + " " + response).lower()
        topics = {
            "Noise/Hours": ["what time", "work until", "noise", "after hours", "construction hours"],
            "FDNY": ["fdny", "fire alarm", "sprinkler", "standpipe", "suppression", "ansul"],
            "Certificates": ["co ", "certificate of occupancy", "tco", "temporary co", "sign-off"],
            "Violations": ["violation", "ecb", "bis", "hpd violation", "dob violation", "penalty"],
            "DHCR": ["dhcr", "rent", "stabiliz", "mci", "iai", "lease", "rent increase"],
            "DOB Filings": ["dob", "permit", "filing", "alt1", "alt2", "alt-1", "alt-2", "nb", "dm", "paa", "objection"],
            "Building Code": ["building code", "egress", "fire safety", "occupancy group", "means of egress"],
            "MDL": ["mdl", "multiple dwelling", "class a", "class b"],
            "Zoning": ["zoning", "use group", "far ", "setback", "variance", "zr ", "r6", "r7", "r8", "c4", "c6", "m1"],
            "Landmarks": ["landmark", "lpc", "historic"],
            "Property Lookup": ["lookup", "address", "bin ", "block", "lot ", "bbl"],
            "Plans/Drawings": ["plan", "drawing", "elevation", "floor plan", "blueprint"],
        }
        for topic, keywords in topics.items():
            if any(kw in combined for kw in keywords):
                logger.info(f"Keyword fallback classified '{question[:50]}...' as {topic}")
                return topic
        return "General"


# Singleton instance
_classifier: Optional[TopicClassifier] = None


def get_classifier() -> TopicClassifier:
    """Get or create the global classifier instance."""
    global _classifier
    if _classifier is None:
        _classifier = TopicClassifier()
    return _classifier
# Force deploy
