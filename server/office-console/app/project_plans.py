from __future__ import annotations

from copy import deepcopy
from typing import Any


def _lines(*values: str) -> list[str]:
    return [value.strip() for value in values if value and value.strip()]


PROJECT_PLAN_TEMPLATES: dict[str, dict[str, Any]] = {
    "basement-waterproofing": {
        "label": "Basement Waterproofing",
        "title": "Basement Waterproofing & Water Management",
        "summary": (
            "Control active moisture at the affected perimeter, collect and route water to a dependable sump and discharge system, "
            "protect adjacent finished areas, and leave the basement clean and ready for continued use."
        ),
        "estimated_duration": "3-6 days",
        "outcomes": _lines(
            "Manage water by collecting perimeter seepage and routing it to a dedicated sump and exterior discharge.",
            "Protect the structure by sealing documented cracks and coordinating any listed wall-stabilization work.",
            "Restore a healthy usable area with controlled demolition, HEPA cleaning, moisture verification, and final documentation.",
        ),
        "assumptions": _lines(
            "Accessible conditions observed during the inspection and recorded in RoomFlow.",
            "Normal access to electricity, water, and the listed basement work areas.",
            "Existing electrical service is adequate for the listed pump equipment unless otherwise noted.",
            "Final quantities and discharge routing may be field-verified before installation.",
        ),
        "exclusions": _lines(
            "Concealed conditions not reasonably visible during the inspection.",
            "Finish carpentry, painting, or flooring beyond the restoration items specifically listed.",
            "Hazardous-material testing or abatement unless listed as a separate scope item.",
            "Owner-requested additions after authorization unless approved through a Change Order.",
        ),
        "protections": _lines(
            "Controlled work area and protected access path.",
            "Daily housekeeping within the active work zone.",
            "Debris removal, moisture verification, and final photo documentation.",
        ),
        "options": _lines(
            "Battery-backup sump pump system.",
            "Wi-Fi pump and high-water monitoring.",
            "Permanent basement dehumidifier.",
            "Additional foundation reinforcement or crack repair identified during preparation.",
        ),
        "suggested_sections": _lines("Moisture Control and Drainage", "Foundation Stabilization", "Mold and Surface Treatment", "Site Protection and Completion"),
    },
    "crawlspace-encapsulation": {
        "label": "Crawlspace Encapsulation",
        "title": "Crawlspace Encapsulation & Moisture Control",
        "summary": (
            "Isolate ground moisture, seal accessible air and vapor pathways, manage humidity, and protect the crawlspace so the area remains "
            "cleaner, drier, and easier to inspect and maintain."
        ),
        "estimated_duration": "2-5 days",
        "outcomes": _lines(
            "Separate the home from ground moisture with a sealed reinforced liner system.",
            "Reduce uncontrolled air exchange by sealing listed vents, penetrations, seams, and foundation transitions.",
            "Maintain a dry serviceable space with drainage, humidity control, cleanup, and documentation as listed.",
        ),
        "assumptions": _lines(
            "The crawlspace is accessible through the existing access opening and has sufficient working clearance for the listed scope.",
            "Standing water or plumbing leaks are corrected or included as separate line items before liner installation.",
            "Foundation walls and framing are suitable for normal encapsulation attachment methods.",
            "Electrical service is available for listed dehumidification or sump equipment.",
        ),
        "exclusions": _lines(
            "Structural framing replacement, plumbing repair, or electrical upgrades unless specifically listed.",
            "Hazardous-material testing or abatement unless specifically listed.",
            "Removal of inaccessible debris or stored contents not identified before authorization.",
            "Exterior drainage or grading work unless listed as a separate header.",
        ),
        "protections": _lines(
            "Protected access route and controlled material handling.",
            "Cleaning and preparation of accessible liner attachment surfaces.",
            "Sealed seams, termination details, final humidity check, and completion photos.",
        ),
        "options": _lines(
            "Commercial-grade crawlspace dehumidifier.",
            "Interior drainage and sump system.",
            "Wireless humidity and high-water monitoring.",
            "Insulated wall or rim-joist treatment where appropriate.",
        ),
        "suggested_sections": _lines("Preparation and Cleanup", "Drainage and Water Control", "Encapsulation System", "Humidity Control and Completion"),
    },
    "mold-remediation": {
        "label": "Mold Remediation",
        "title": "Mold Remediation & Surface Restoration",
        "summary": (
            "Establish work-area controls, remove or clean listed affected materials, use HEPA filtration and detailed surface cleaning, "
            "apply the specified treatment, and document completion conditions."
        ),
        "estimated_duration": "2-5 days",
        "outcomes": _lines(
            "Control the work area with containment and HEPA-filtered air management.",
            "Remove listed unsalvageable materials and clean accessible affected surfaces using the approved method.",
            "Document final cleaning, moisture conditions, treatment, and completion photos for the customer file.",
        ),
        "assumptions": _lines(
            "The moisture source has been corrected or is included in the authorized scope.",
            "The listed work areas are accessible and contents are moved or included for handling.",
            "Visible conditions reasonably match the inspection and RoomFlow records.",
            "Post-remediation verification by a third party is not required unless listed.",
        ),
        "exclusions": _lines(
            "Laboratory testing, industrial hygiene services, or clearance testing unless listed.",
            "Asbestos, lead, or other hazardous-material abatement unless separately authorized.",
            "Reconstruction, painting, or finish replacement beyond listed restoration items.",
            "Hidden contamination outside the documented work area.",
        ),
        "protections": _lines(
            "Containment, negative-air or HEPA filtration, and protected access path as appropriate.",
            "Bagging and controlled removal of listed debris.",
            "Detailed HEPA cleaning, treatment record, and final photo documentation.",
        ),
        "options": _lines(
            "Third-party post-remediation verification.",
            "Additional air-scrubbing days.",
            "Contents cleaning or off-site storage.",
            "Reconstruction and finish restoration.",
        ),
        "suggested_sections": _lines("Containment and Air Control", "Selective Demolition", "Detailed Cleaning and Treatment", "Completion and Verification"),
    },
    "foundation-repair": {
        "label": "Foundation Repair",
        "title": "Foundation Stabilization & Crack Repair",
        "summary": (
            "Address the documented foundation movement or cracking with the listed stabilization and repair system, protect adjacent areas, "
            "and record final installation conditions for the property file."
        ),
        "estimated_duration": "2-6 days",
        "outcomes": _lines(
            "Stabilize the listed wall or foundation areas using the specified reinforcement system.",
            "Prepare and seal documented cracks within the authorized work area.",
            "Coordinate drainage or moisture-management work that affects the repaired area.",
        ),
        "assumptions": _lines(
            "The visible foundation conditions match the inspection and RoomFlow measurements.",
            "Normal access exists to the listed interior or exterior work areas.",
            "Engineering or permitting is not required unless included as a line item.",
            "Final reinforcement placement may be field-adjusted to avoid utilities or concealed obstructions.",
        ),
        "exclusions": _lines(
            "Engineering design, permits, excavation, or utility relocation unless listed.",
            "Repair of concealed structural damage outside the documented area.",
            "Finish restoration beyond listed patching or cleanup.",
            "Waterproofing or drainage work not specifically included.",
        ),
        "protections": _lines(
            "Protected access route and dust-control measures.",
            "Manufacturer-compliant surface preparation and installation.",
            "Final installation photos and customer-file documentation.",
        ),
        "options": _lines(
            "Structural engineering review.",
            "Additional crack injection or reinforcement.",
            "Interior drainage and sump system.",
            "Exterior excavation and waterproofing.",
        ),
        "suggested_sections": _lines("Preparation and Protection", "Foundation Stabilization", "Crack Repair", "Cleanup and Documentation"),
    },
    "water-damage-restoration": {
        "label": "Water Damage Restoration",
        "title": "Water Damage Mitigation & Drying",
        "summary": (
            "Remove standing water and listed damaged materials, establish controlled drying, monitor moisture conditions, and document the "
            "property until the authorized drying goals are reached."
        ),
        "estimated_duration": "3-7 days",
        "outcomes": _lines(
            "Stop or isolate the source and remove accessible standing water.",
            "Remove listed non-salvageable materials and establish air movement and dehumidification.",
            "Track drying progress with moisture readings, equipment records, and completion documentation.",
        ),
        "assumptions": _lines(
            "The water source is stopped or can be isolated before mitigation begins.",
            "Electrical service is safe and available for listed drying equipment.",
            "Affected contents are accessible for movement or included in the scope.",
            "Drying duration may change based on daily readings and concealed assemblies.",
        ),
        "exclusions": _lines(
            "Plumbing repair, roofing repair, or source correction unless listed.",
            "Hazardous-material testing or abatement unless listed.",
            "Reconstruction and finish replacement unless included as separate headers.",
            "Long-term storage or contents restoration not specifically listed.",
        ),
        "protections": _lines(
            "Protected access and controlled demolition area.",
            "Equipment placement and daily or scheduled monitoring.",
            "Moisture log, equipment log, and final photos.",
        ),
        "options": _lines(
            "Contents pack-out and storage.",
            "Additional drying equipment or extended monitoring.",
            "Mold remediation if discovered and authorized.",
            "Reconstruction and finish restoration.",
        ),
        "suggested_sections": _lines("Emergency Services", "Selective Demolition", "Drying Equipment and Monitoring", "Cleaning and Completion"),
    },
    "drainage-sump": {
        "label": "Drainage and Sump Systems",
        "title": "Drainage, Sump & Discharge Improvements",
        "summary": (
            "Collect water from the listed areas, route it to reliable sump equipment, and discharge it to the approved exterior location with "
            "serviceable components and clear final documentation."
        ),
        "estimated_duration": "2-5 days",
        "outcomes": _lines(
            "Capture water using the listed interior or exterior drainage components.",
            "Provide dependable pumping, check-valve, lid, and alarm components as specified.",
            "Route discharge to the approved termination and restore the affected work area.",
        ),
        "assumptions": _lines(
            "An acceptable discharge route can be established without unlisted utility relocation.",
            "Electrical service is available for the listed pumps and alarms.",
            "Final trench and termination locations may be field-adjusted for existing conditions.",
            "Municipal or association approvals are not required unless listed.",
        ),
        "exclusions": _lines(
            "Electrical circuit installation unless included.",
            "Major landscaping or hardscape restoration beyond listed allowances.",
            "Municipal permits or storm-system connections unless included.",
            "Excavation through unknown utilities or concealed obstructions.",
        ),
        "protections": _lines(
            "Protected work route and dust/debris controls.",
            "Functional pump and discharge test.",
            "Final cleanup, photographs, and customer orientation.",
        ),
        "options": _lines(
            "Battery-backup pump.",
            "Secondary pump and high-water alarm.",
            "Wi-Fi monitoring.",
            "Exterior drainage or grading improvements.",
        ),
        "suggested_sections": _lines("Drainage Collection", "Sump Equipment", "Exterior Discharge", "Restoration and Completion"),
    },
    "demolition-rebuild": {
        "label": "Demolition and Rebuild",
        "title": "Selective Demolition & Restoration",
        "summary": (
            "Remove the specifically listed materials, protect adjacent finishes, manage debris, and restore the authorized assemblies to the "
            "defined completion level."
        ),
        "estimated_duration": "3-10 days",
        "outcomes": _lines(
            "Protect occupied or finished areas and establish a controlled work route.",
            "Remove only the listed materials and manage debris through the approved disposal method.",
            "Rebuild or restore the authorized assemblies and document completion.",
        ),
        "assumptions": _lines(
            "The listed assemblies are accessible and reasonably match the inspection.",
            "Utilities can be safely isolated where required.",
            "Matching replacement materials are reasonably available unless allowances are listed.",
            "Permit or engineering requirements are excluded unless specifically included.",
        ),
        "exclusions": _lines(
            "Concealed structural, electrical, plumbing, or hazardous-material conditions.",
            "Owner upgrades or finish selections beyond the listed allowance.",
            "Temporary housing, contents storage, or business interruption costs.",
            "Unlisted permit, engineering, or code-upgrade work.",
        ),
        "protections": _lines(
            "Dust and access controls appropriate to the work area.",
            "Debris handling and disposal documentation.",
            "Final cleanup, walkthrough, and completion photos.",
        ),
        "options": _lines(
            "Upgraded finish selections.",
            "Additional painting or flooring.",
            "Contents handling and storage.",
            "Extended warranty or maintenance package.",
        ),
        "suggested_sections": _lines("Site Protection", "Selective Demolition", "Reconstruction", "Landfill Fees and Completion"),
    },
    "inspection-testing": {
        "label": "Inspection and Testing",
        "title": "Property Inspection & Diagnostic Testing",
        "summary": (
            "Inspect the listed systems and work areas, record measurements and photographs, complete the authorized diagnostic testing, and "
            "provide a clear Floodman findings record with recommended next steps."
        ),
        "estimated_duration": "1 day",
        "outcomes": _lines(
            "Document visible conditions, measurements, and areas of concern.",
            "Complete the specifically listed testing or sampling protocol.",
            "Provide findings and practical recommendations tied to the customer and service property file.",
        ),
        "assumptions": _lines(
            "The listed areas are accessible at the appointment time.",
            "Testing is limited to the samples, instruments, and locations specifically listed.",
            "Results from third-party laboratories follow their normal turnaround times.",
            "This service is not an engineering opinion unless explicitly stated.",
        ),
        "exclusions": _lines(
            "Destructive investigation unless listed.",
            "Engineering, legal, insurance-coverage, or code-compliance opinions.",
            "Testing outside the listed locations or sample count.",
            "Repair work unless separately estimated and authorized.",
        ),
        "protections": _lines(
            "Photo and measurement documentation.",
            "Chain-of-custody record where laboratory samples are used.",
            "Findings stored with the Floodman customer and property record.",
        ),
        "options": _lines(
            "Additional samples or testing locations.",
            "Thermal imaging or moisture mapping.",
            "Written repair estimate.",
            "Follow-up inspection after corrective work.",
        ),
        "suggested_sections": _lines("Inspection", "Testing and Sampling", "Documentation", "Recommended Next Steps"),
    },
    "general-restoration": {
        "label": "General Restoration",
        "title": "Property Restoration Plan",
        "summary": (
            "Complete the listed restoration work with clear site protection, documented materials and labor, controlled cleanup, and a final "
            "customer walkthrough."
        ),
        "estimated_duration": "To be confirmed",
        "outcomes": _lines(
            "Complete the listed work in the approved areas.",
            "Protect adjacent property and maintain a controlled work route.",
            "Provide cleanup, final documentation, and a customer walkthrough.",
        ),
        "assumptions": _lines(
            "Conditions reasonably match the inspection and RoomFlow documentation.",
            "Normal access to utilities and listed work areas.",
            "Quantities may be field-verified before installation.",
        ),
        "exclusions": _lines(
            "Concealed conditions not reasonably visible at inspection.",
            "Hazardous-material work unless listed.",
            "Owner-requested additions after authorization unless approved by Change Order.",
        ),
        "protections": _lines(
            "Protected access route and controlled work area.",
            "Daily housekeeping and debris handling.",
            "Final cleanup and photo documentation.",
        ),
        "options": _lines(
            "Additional repairs discovered during preparation.",
            "Upgraded materials or finishes.",
            "Extended monitoring or maintenance services.",
        ),
        "suggested_sections": _lines("Preparation and Protection", "Primary Work Scope", "Optional or Supplemental Work", "Completion and Documentation"),
    },
}


ALIASES = {
    "waterproofing": "basement-waterproofing",
    "basement waterproofing": "basement-waterproofing",
    "crawlspace": "crawlspace-encapsulation",
    "crawl space": "crawlspace-encapsulation",
    "crawlspace encapsulation": "crawlspace-encapsulation",
    "mold": "mold-remediation",
    "mold remediation": "mold-remediation",
    "foundation": "foundation-repair",
    "foundation repair": "foundation-repair",
    "water restoration": "water-damage-restoration",
    "water damage": "water-damage-restoration",
    "sump": "drainage-sump",
    "drainage": "drainage-sump",
    "demolition": "demolition-rebuild",
    "demo": "demolition-rebuild",
    "inspection": "inspection-testing",
    "testing": "inspection-testing",
}


def normalize_project_category(value: Any) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    text = " ".join(text.replace("-", " ").split())
    if text in ALIASES:
        return ALIASES[text]
    slug = text.replace(" ", "-")
    return slug if slug in PROJECT_PLAN_TEMPLATES else "general-restoration"


def project_plan(value: Any) -> dict[str, Any]:
    key = normalize_project_category(value)
    plan = deepcopy(PROJECT_PLAN_TEMPLATES[key])
    plan["key"] = key
    return plan


def project_plan_options() -> list[dict[str, str]]:
    return [{"key": key, "label": str(value["label"])} for key, value in PROJECT_PLAN_TEMPLATES.items()]


def merge_project_plan(record: dict[str, Any]) -> dict[str, Any]:
    result = dict(record or {})
    plan = project_plan(result.get("project_category") or result.get("category"))
    result.setdefault("project_category", plan["key"])
    result.setdefault("project_plan", plan)
    if not str(result.get("recommended_project_title") or "").strip():
        result["recommended_project_title"] = plan["title"]
    if not str(result.get("title") or "").strip():
        result["title"] = plan["title"]
    if not str(result.get("project_summary") or result.get("summary") or "").strip():
        result["project_summary"] = plan["summary"]
    if not str(result.get("estimated_duration") or "").strip():
        result["estimated_duration"] = plan["estimated_duration"]
    if not str(result.get("assumptions") or "").strip():
        result["assumptions"] = "\n".join(f"- {item}" for item in plan["assumptions"])
    if not str(result.get("exclusions") or "").strip():
        result["exclusions"] = "\n".join(f"- {item}" for item in plan["exclusions"])
    if not result.get("project_outcomes"):
        result["project_outcomes"] = plan["outcomes"]
    if not result.get("project_protections"):
        result["project_protections"] = plan["protections"]
    if not result.get("project_options"):
        result["project_options"] = plan["options"]
    if not result.get("protections"):
        result["protections"] = plan["protections"]
    if not result.get("optional_upgrades"):
        result["optional_upgrades"] = plan["options"]
    return result
