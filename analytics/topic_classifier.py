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
        "DEP",                   # Dept of Environmental Protection: sewer/water connections, backflow
        "DOT",                   # Dept of Transportation: sidewalk sheds, roadway/sidewalk permits, canopy
        "Parks",                 # NYC Parks: work on/near parkland, tree removal/protection
        "SAPO",                  # Street Activity Permit Office: street activity/closure permits
        "DOH",                   # Dept of Health (DOHMH): food service, daycare, pools
        "HPD",                   # Housing Preservation & Development: registration, maintenance
        "DOB System Status",     # BIS / DOB NOW Build being down/glitchy (availability, NOT a filing)
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
- DEP (Dept of Environmental Protection: sewer/water/house connections, backflow, stormwater)
- DOT (Dept of Transportation: sidewalk sheds, roadway/sidewalk permits, canopies)
- Parks (NYC Parks Dept: work on/near parkland, tree removal/protection)
- SAPO (Street Activity Permit Office: street activity/closure permits)
- DOH (Dept of Health / DOHMH: food service, daycare, pool permits)
- HPD (Housing Preservation & Development: registration, housing maintenance)
- DOB System Status (BIS or DOB NOW Build is down/glitchy/not loading — system availability)
- Property Lookup (address lookups, BIN/BBL, property info)
- Plans/Drawings (architectural plans, blueprints, drawings)
- General (anything else)

Rules:
1. Respond with ONLY the topic name, nothing else
2. Be specific - "What time can you work until?" is Noise/Hours, not General
3. Commands like "/feedback" or "/correct" are General
4. If unclear, default to the most specific category that could apply
5. AGENCY over service-area: if a question is about another agency's permit (DEP/DOT/Parks/SAPO/DOH/HPD), tag the AGENCY, not DOB Filings
6. DOB System Status is ONLY for "is the system working / is it down" — a question about HOW to file in BIS/DOB NOW is DOB Filings, not System Status

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
A: FDNY

Q: "Is BIS working for anyone?"
A: DOB System Status

Q: "Is DOB NOW Build down again?"
A: DOB System Status

Q: "Did anyone file the DEP house/sewer connection?"
A: DEP

Q: "Sidewalk shed DOT permit renewal — who handles it?"
A: DOT

Q: "Do we need a SAPO permit for the street closure?"
A: SAPO

Q: "Got a contact at Parks for a tree removal?"
A: Parks

Q: "What does HPD registration require?"
A: HPD"""

    def __init__(self, settings: Optional[Settings] = None):
        """Initialize classifier."""
        self.settings = settings or get_settings()
        self.client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        # Current Haiku for this trivial classification task. Must match a model
        # this API key can actually serve — claude-3-haiku-20240307 AND
        # claude-3-5-haiku-20241022 both 404 here, which silently forced the
        # keyword fallback on EVERY call (the real cause of the DHCR over-tagging).
        # Use the same Haiku 4.5 the rest of Beacon uses (passive listener, plan
        # reader, email poller, config default).
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
        """Keyword-based classification when the LLM is unavailable.

        Matches WHOLE WORDS (not substrings) so common words can't trip a topic
        — e.g. "current"/"different"/"please" must NOT match the DHCR keywords.
        DHCR keywords are also kept specific (rent *regulation* terms, not a bare
        "rent"/"lease") since rent-stabilization is rarely discussed here. This
        is the path that over-tagged DHCR while the LLM model was 404'ing.
        """
        import re

        combined = (question + " " + response).lower()
        # NOTE: order matters — first match wins. System-status + agency tags are
        # checked BEFORE the generic "DOB Filings" (dob/permit/filing) so e.g.
        # "is BIS down" and "DEP permit" route correctly instead of being grabbed
        # by DOB Filings.
        topics = {
            "Noise/Hours": ["what time", "work until", "noise", "after hours", "construction hours"],
            "FDNY": ["fdny", "fire alarm", "sprinkler", "standpipe", "suppression", "ansul"],
            "DOB System Status": ["bis down", "bis working", "is bis", "bis a bust", "bis broken",
                                  "dob now down", "build down", "system down", "system is down",
                                  "dob glitch", "glitch", "glitches", "dob emails", "not loading"],
            "DEP": ["dep", "sewer connection", "house connection", "water connection", "backflow", "stormwater"],
            "DOT": ["dot", "sidewalk shed", "roadway", "sidewalk permit", "canopy"],
            "Parks": ["parks", "parkland", "tree removal", "parks dept"],
            "SAPO": ["sapo", "street activity"],
            "DOH": ["doh", "dohmh", "health department", "food service", "daycare"],
            "HPD": ["hpd", "housing preservation", "housing maintenance"],
            "Certificates": ["co", "certificate of occupancy", "tco", "temporary co", "sign-off"],
            "Violations": ["violation", "ecb", "dob violation", "penalty"],
            "DHCR": ["dhcr", "rent stabiliz", "rent-stabiliz", "rent regulat", "rent increase",
                     "rent control", "mci", "iai", "421-a", "j-51"],
            "DOB Filings": ["dob", "permit", "filing", "alt1", "alt2", "alt-1", "alt-2", "nb", "dm", "paa", "objection"],
            "Building Code": ["building code", "egress", "fire safety", "occupancy group", "means of egress"],
            "MDL": ["mdl", "multiple dwelling", "class a", "class b"],
            "Zoning": ["zoning", "use group", "far", "setback", "variance", "zr", "r6", "r7", "r8", "c4", "c6", "m1"],
            "Landmarks": ["landmark", "lpc", "historic"],
            "Property Lookup": ["lookup", "address", "bin", "block", "lot", "bbl"],
            "Plans/Drawings": ["plan", "drawing", "elevation", "floor plan", "blueprint"],
        }
        for topic, keywords in topics.items():
            for kw in keywords:
                if re.search(r"\b" + re.escape(kw) + r"\b", combined):
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
