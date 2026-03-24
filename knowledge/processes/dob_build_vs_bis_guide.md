---
category: processes
type: procedure
jurisdiction: NYC
department: DOB
status: active
---

# DOB Build vs BIS — System Navigation Guide

## Overview

New York City Department of Buildings (DOB) has transitioned from BIS (Building Information System), the legacy platform, to DOB Build, a modern cloud-based filing system. This transition is ongoing: many jobs and historical records remain in BIS, while all new construction filings are now processed through DOB Build. Understanding which system to use for a given task is critical for efficient project management and filing success.

The landscape includes three primary platforms:
- **BIS (a810-bisweb.nyc.gov)**: Legacy system, still the source of truth for historical records
- **DOB Build (a810-efiling.nyc.gov or NYC Build portal)**: New filing and examination platform
- **DOB NOW**: Specialized portal for certain trade-specific permits and inspections

---

## BIS (Building Information System) — Legacy Platform

### What BIS Is
BIS is the legacy system that has served NYC's building department since the 1990s. Despite ongoing transition to DOB Build, BIS remains operational and essential for many functions.

### Current BIS Functions
- **Property profiles**: Complete ownership, address, and tax lot information
- **Violation lookups**: Search active violations on a property
- **Certificate of Occupancy (CO) records**: Historical CO issuance dates and conditions
- **Permit history**: All permits issued prior to DOB Build transition
- **Job inquiry**: Status of permits filed under BIS
- **Legacy job amendments and supersedes**: Jobs filed in BIS may still be amended or superseded through BIS [VERIFY: Are amendments to BIS-era jobs now in Build or still in BIS?]

### Known Issues and Workarounds
- **System stability**: BIS experiences frequent downtime. Common team response: "Is BIS working?" Check status before directing clients or staff to use it.
- **Browser compatibility**: Microsoft Edge performs more reliably than Chrome or Firefox on BIS
- **Performance**: Slower response times, especially during peak hours
- **Character encoding**: Some special characters in property names may not display correctly

### How to Access BIS
Navigate to **a810-bisweb.nyc.gov** and use your DOB account credentials. No special authentication beyond standard NYC credentials required.

---

## DOB Build — New Filing Platform

### What DOB Build Is
DOB Build is the Department of Buildings' modern filing system launched to streamline permit applications, plan submissions, and examiner communication. This is now the primary platform for new construction permits.

### Filing Types in DOB Build
All new applications for the following should be filed in DOB Build:
- **ALT-1**: Alterations with change of use, occupancy group, or structural work
- **ALT-2**: Alterations without change of use (work on multiple building systems)
- **PAA**: Place of Assembly alteration (assembly occupancy for 75+ persons)
- **NB**: New Building construction
- **Amendments**: Amendments to applications already in Build
- **Supersedes**: Replacement filings for jobs on hold or withdrawn

### Key Features
- **Online plan upload**: PDF or image plans uploaded directly to portal
- **Digital signatures**: Electronic signatures for professional certification
- **Examiner messaging**: Direct portal communication with plan examiners
- **Real-time status tracking**: Application status updates displayed in portal
- **Expedited processing options**: Professional certification available for most applications

### Known Issues and Troubleshooting

#### Supersede Dropdown Not Appearing
When trying to file a supersede for a job on hold, the dropdown to select the job to supersede may not appear immediately.
- **Workaround**: Refresh the page, clear browser cache, or try a different browser
- **[VERIFY]**: Is there a specific waiting period before supersedes are available for on-hold jobs?

#### Filing Preview vs PW1 Certification
Confusion exists around whether DOB accepts the "filing preview" as proof of submission or requires a separate PW1 (Professional Witness certificate).
- **[VERIFY]**: Current DOB policy — does Build filing preview satisfy submission requirements, or is a PW1 still required for certain filing types?

#### Admin Holds
Applications sometimes receive "admin hold" status (administrative hold placed by DOB staff, not examiner).
- **Cause**: Missing documentation, fee issues, or system errors
- **[VERIFY]**: What is the current process to resolve admin holds in Build? Direct contact to Plan Desk or examiner communication?

#### Amendments in Build
Process for filing amendments to existing Build applications is sometimes unclear.
- **[VERIFY]**: Current amendment process — can amendments be filed through the application, or must new amendment application be created?

#### QA Failures
Quality Assurance (QA) reviews in Build sometimes flag technical issues with plan submissions that must be resolved before examination.
- **Common triggers**: File format, file size, missing pages, plan readability
- **Resolution**: Correct the flagged issue and resubmit; Build will notify examiner automatically

#### System Outages
DOB Build experiences planned and unplanned maintenance windows. During outages, filing and document uploads are blocked.
- **Workaround**: Check DOB's status page or social media before attempting submissions
- **[VERIFY]**: Are there any known maintenance windows? Preferred times to file?

### How to Access DOB Build
Navigate to either:
- **a810-efiling.nyc.gov** (direct link)
- **NYC Build portal** via nyc.gov (search "DOB Build")

Use your NYC credentials. First-time users must register and complete identity verification.

---

## DOB NOW — Trade-Specific and Inspection Portal

### What DOB NOW Is
DOB NOW is a specialized portal for electrical, plumbing, elevator, and certain other trade-specific permits. It also handles inspection scheduling and compliance tracking.

### Current Functions
- **Electrical permits**: Certain electrical work applications (Electrical Worker Registration, EW)
- **Plumbing permits**: Stand-alone plumbing work (not embedded in ALT applications)
- **Elevator permits and inspections**: New elevator installations and periodic inspections
- **Inspection scheduling**: Booking inspections for work under DOB permits
- **Violation resolution**: Posting violation corrections and scheduling compliance inspections

### Current Limitations
- **[VERIFY]**: Have any filings previously in DOB NOW migrated to DOB Build? Which trade permits are still NOW-only?
- **[VERIFY]**: Is inspection scheduling for all permit types now in Build, or does it remain in DOB NOW?

### How to Access DOB NOW
Navigate to **now.dot.ny.gov** or search "DOB NOW" on nyc.gov. Use NYC credentials.

---

## Which System to Use — Decision Tree

### For New Filings
| Work Type | System | Notes |
|-----------|--------|-------|
| New ALT-1 (change of use/occupancy/structural) | **DOB Build** | All new ALT-1 filed in Build |
| New ALT-2 (multiple work types, no use change) | **DOB Build** | All new ALT-2 filed in Build |
| New PAA (assembly occupancy) | **DOB Build** | All new PAA filed in Build |
| New NB (new building) | **DOB Build** | All new NB filed in Build |
| Electrical work only | **DOB NOW** | [VERIFY: Or has this moved to Build?] |
| Plumbing work only | **DOB NOW** | [VERIFY: Or has this moved to Build?] |
| Elevator work | **DOB NOW** | [VERIFY: Confirmation of current location] |

### For Amendments and Supersedes
| Situation | System | Notes |
|-----------|--------|-------|
| Amend a BIS-era job (pre-2020) | **[VERIFY]**: Build or BIS? | Clarify current policy |
| Amend a Build job | **DOB Build** | File through application portal |
| Supersede a BIS-era job on hold | **[VERIFY]**: Build or BIS? | Clarify current process |
| Supersede a Build job on hold | **DOB Build** | Use supersede dropdown (may require page refresh) |

### For Lookups and Status Checks
| Task | System | Notes |
|------|--------|-------|
| Property profile (ownership, tax lot) | **BIS** | BIS is authoritative source |
| Active violations on property | **BIS** | BIS violation module |
| CO status and history | **BIS** | Historical CO records |
| Permit status (BIS-era permit) | **BIS** | Search by permit number |
| Permit status (Build filing) | **DOB Build** | Log into application, view status |
| Inspection scheduling | **DOB NOW** | Book inspection appointment |

### For Specialty Filings
| Filing Type | System | Notes |
|-------------|--------|-------|
| Limited Alteration Application (LAA) | **[VERIFY]**: Build or DOB NOW? | Clarify current location |
| Emergency Use Permit (EUP) | **[VERIFY]**: Current filing system? | Urgent clarification needed |
| Fence/fence alteration | **[VERIFY]**: What system and filing type? | Team question — needs research |
| Solar panel installation | **[VERIFY]**: What filing type and system? | Emerging filing type |
| After Hours Variance (AHV) | **[VERIFY]**: Current process and location? | Saturday work authorization |

---

## Pro Tips for System Navigation

### Avoid Common Mistakes
1. **Don't file new permits in BIS** — BIS-only filings will be rejected or ignored
2. **Don't assume a job is in Build** — Jobs filed before 2020 are in BIS; always verify location before attempting action
3. **Clear your cache before troubleshooting** — Browser cache often causes "page not loading" issues in both systems
4. **Save confirmation numbers immediately** — Both systems can be slow to confirm; don't rely on email confirmation alone

### System Navigation Shortcuts
- **[VERIFY]**: Are there keyboard shortcuts or quick-access features that save time in DOB Build?
- **[VERIFY]**: Direct URLs to common Build functions (e.g., "File New Application," "View My Applications")?

### When Systems Are Down
- Check **nyc.gov/buildings** homepage for status updates
- Try **a810-efiling.nyc.gov status** or DOB social media (Twitter/X: @nycdob)
- Have backup tasks ready (research, client communication, document prep)
- BIS downtime: more frequent; Build downtime: usually shorter-duration maintenance

### Examiner Assignment Timing
After filing in Build, allow **2–5 business days** before an examiner is assigned. Premature follow-up with Plan Desk wastes time.

---

## Summary Table: Systems at a Glance

| Aspect | BIS | DOB Build | DOB NOW |
|--------|-----|-----------|---------|
| **Purpose** | Legacy filings & lookups | New permit applications | Trade-specific permits & inspections |
| **URL** | a810-bisweb.nyc.gov | a810-efiling.nyc.gov | now.dot.ny.gov |
| **Status** | Legacy, ongoing maintenance | Primary active system | Active, trade-focused |
| **Best for** | Historical data, property info | New permits, current applications | Electrical, plumbing, elevator, inspections |
| **Stability** | Frequent downtime | More stable | Stable |
| **Timeline** | Slower, legacy systems | Faster, modern infrastructure | Varies by trade |

---

## When to Escalate

Contact GLE management or the Plan Desk if:
- You cannot determine whether a job is in BIS or Build
- System access is denied (credential or authentication issue)
- An application has been in status "Assigned to Examiner" for 7+ days with no activity
- You receive an error message that does not match any known troubleshooting steps

---

**Last Updated**: [Current Date]
**Next Review**: [Quarterly or as systems update]
