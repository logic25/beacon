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
        "OER",                   # Office of Environmental Remediation: E-designation, brownfield, hazmat
        "Asbestos",              # DEP Asbestos Control: ACP-5/ACP-7 (gates demo/alteration)
        "OATH",                  # Office of Admin Trials & Hearings: violation hearings/cure/dismiss (ECB adjudication)
        "Utilities",             # Con Edison / National Grid: gas/electric service + sign-offs (gates CO)
        "Accessibility",         # MOPD / ADA / accessibility compliance
        "SCA",                   # School Construction Authority: school/DOE capital work
        "MTA",                   # MTA/NYCT: adjacent-to-transit "zone of influence" review
        "DOF",                   # Dept of Finance: BBL/tax-lot, property tax status
        "DSNY",                  # Sanitation: refuse/recycling rooms, C&D waste
        "DCWP",                  # Consumer & Worker Protection: HIC license, sidewalk cafe
        "DDC",                   # Dept of Design & Construction: city capital projects
        "EDC",                   # Economic Development Corp: city-owned/leased/waterfront
        "Loft Board",            # IMD units, loft-law legalization
        "Port Authority",        # PANYNJ facilities (airports, terminals, WTC)
        "DOB System Status",     # BIS / DOB NOW Build being down/glitchy (availability, NOT a filing)
        "Property Lookup",       # Address/BIN lookups, property info
        "Plans/Drawings",        # Architectural plans, blueprints
        "General",               # Genuine knowledge question that fits no specific topic
        # --- Non-knowledge intents (kept OUT of the knowledge heatmap) ---
        "Command",               # Slash commands: /help, /stats, /correct, /suggest, /feedback
        "App/Data Query",        # Questions about THIS firm's own live data/records (counts, status, tax id)
        "Bug Report",            # Something in the Ordino app is broken/erroring (lets us COUNT bugs via Beacon)
        "Feature/Feedback",      # Feature request or product feedback about the Ordino app
        "Test/Chitchat",         # Tests, greetings, jokes, off-topic
    ]
    
    SYSTEM_PROMPT = """You are a topic classifier for a NYC permit expediting firm.

FIRST decide the message's INTENT. Only a GENUINE NYC permitting / expediting
KNOWLEDGE question gets a domain topic. Everything else gets a non-knowledge tag
so it stays OUT of the knowledge heatmap:
- Command — a slash command (/help, /stats, /correct, /suggest, /feedback)
- App/Data Query — a question about THIS firm's own live data/records, e.g. "how
  many active projects", "who owes us money", "what's our tax id", "how is Manny
  doing this month", "what page am I on"
- Bug Report — something in the Ordino app is broken/erroring, e.g. "cannot save an
  application", "can't attach a photo", "this page won't load", "stats show -213m"
- Feature/Feedback — a feature request or product feedback about the app, e.g. "add a
  bulk-delete", "this text is too small", "can we sort by date"
- Test/Chitchat — a test, greeting, joke, or off-topic message ("2+2", "hello")

ONLY if it is a real knowledge question, categorize it into ONE topic from this list:
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
- OER (Office of Environmental Remediation: E-designation, brownfield, hazmat, Notice of Satisfaction)
- Asbestos (asbestos abatement / ACP-5 / ACP-7 — gates demo/alteration permits)
- OATH (violation HEARINGS / cure / dismiss / certify-correction — where ECB & DOB violations are adjudicated)
- Utilities (Con Edison / National Grid: gas & electric service, meter release, energization sign-off)
- Accessibility (MOPD / ADA / accessibility compliance)
- SCA (School Construction Authority: school / DOE capital work)
- MTA (MTA / NYCT: work adjacent to transit, "zone of influence" review)
- DOF (Dept of Finance: BBL / tax-lot, property tax status)
- DSNY (Sanitation: refuse/recycling rooms, C&D waste)
- DCWP (Consumer & Worker Protection: Home Improvement Contractor license, sidewalk cafe)
- DDC (Dept of Design & Construction: city capital projects)
- EDC (Economic Development Corp: city-owned/leased/waterfront sites)
- Loft Board (Interim Multiple Dwelling / IMD, loft-law legalization)
- Port Authority (PANYNJ facilities: airports, terminals, WTC)
- DOB System Status (BIS or DOB NOW Build is down/glitchy/not loading — system availability)
- Property Lookup (address lookups, BIN/BBL, property info)
- Plans/Drawings (architectural plans, blueprints, drawings)
- General (a genuine knowledge question that fits no specific topic)
- Command / App/Data Query / Bug Report / Feature/Feedback / Test/Chitchat (non-knowledge — use the INTENT step above)

Rules:
0. Apply the INTENT step FIRST. A live-data question, an app bug/feature request, a
   slash command, or a test is NOT a knowledge topic even if it mentions DOB,
   projects, or filings — tag it Command / App/Data Query / Bug Report / Feature/Feedback / Test/Chitchat.
1. Respond with ONLY the topic name, nothing else
2. Be specific - "What time can you work until?" is Noise/Hours, not General
3. Slash commands like "/feedback" or "/correct" are Command (not General)
4. If unclear, default to the most specific category that could apply
5. AGENCY over service-area: if a question is about another agency's permit (DEP/DOT/Parks/SAPO/DOH/HPD/OER/SCA/MTA/DOF/DSNY/DCWP/DDC/EDC/Utilities/Port Authority), tag the AGENCY, not DOB Filings
6. DOB System Status is ONLY for "is the system working / is it down" — a question about HOW to file in BIS/DOB NOW is DOB Filings, not System Status
7. BSA, CPC, DCP and "City Planning" route to Zoning (they are the bodies that grant variances / special permits / ULURP)
8. The violation TICKET (including ECB) is Violations; the HEARING / cure / dismiss / certify-correction at OATH is OATH
9. Asbestos / ACP-5 / ACP-7 is its own tag (Asbestos), not generic DEP
10. Con Edison / National Grid gas & electric service is Utilities

Examples:
Q: "What time can you work until?"
A: Noise/Hours

Q: "How do I file an ALT2?"
A: DOB Filings

Q: "What's the setback requirement for R6?"
A: Zoning

Q: "Can I get an agent to help with filing forms?"
A: General

Q: "How many active projects do we have?"
A: App/Data Query

Q: "/correct IBM is not a permit type"
A: Command

Q: "Cannot save an application" / "can't attach a photo"
A: Bug Report

Q: "Can we add a bulk-delete button?"
A: Feature/Feedback

Q: "What is 2+2?"
A: Test/Chitchat

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
A: HPD

Q: "Any update on the E-designation / OER Notice of Satisfaction?"
A: OER

Q: "Do we need an ACP-5 before we can pull the demo permit?"
A: Asbestos

Q: "What's the next hearing date to dismiss the ECB violation?"
A: OATH

Q: "Con Ed hasn't released the meter — who's following up?"
A: Utilities

Q: "Is this an SCA job or are we filing it with DOB?"
A: SCA

Q: "Do we need MTA zone-of-influence review next to the subway?"
A: MTA"""

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
            "Asbestos": ["asbestos", "acp-5", "acp5", "acp-7", "acp7"],
            "OER": ["oer", "e-designation", "e designation", "environmental remediation",
                    "notice of satisfaction", "brownfield", "vcp"],
            "Utilities": ["con ed", "con edison", "coned", "national grid", "meter release"],
            "Accessibility": ["mopd", "accessibility", "ada"],
            "SCA": ["sca", "school construction"],
            "MTA": ["mta", "nyct", "zone of influence", "transit authority"],
            "OATH": ["oath", "ecb hearing", "certify correction", "certify-correction"],
            "DOF": ["dof", "department of finance", "property tax", "tax lot", "tax-lot"],
            "DSNY": ["dsny", "sanitation"],
            "DCWP": ["dcwp", "dca", "consumer affairs", "home improvement contractor"],
            "DDC": ["ddc", "design and construction"],
            "EDC": ["edc", "economic development"],
            "Loft Board": ["loft board", "loft law", "imd"],
            "Port Authority": ["port authority", "panynj"],
            "Certificates": ["co", "certificate of occupancy", "tco", "temporary co", "sign-off"],
            "Violations": ["violation", "ecb", "dob violation", "penalty"],
            "DHCR": ["dhcr", "rent stabiliz", "rent-stabiliz", "rent regulat", "rent increase",
                     "rent control", "mci", "iai", "421-a", "j-51"],
            "DOB Filings": ["dob", "permit", "filing", "alt1", "alt2", "alt-1", "alt-2", "nb", "dm", "paa", "objection"],
            "Building Code": ["building code", "egress", "fire safety", "occupancy group", "means of egress"],
            "MDL": ["mdl", "multiple dwelling", "class a", "class b"],
            "Zoning": ["zoning", "use group", "far", "setback", "variance", "zr", "r6", "r7", "r8", "c4", "c6", "m1",
                       "bsa", "cpc", "dcp", "city planning", "ulurp"],
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
