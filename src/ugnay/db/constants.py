SOURCE_CATEGORIES = (
    "government_directory",
    "university_directory",
    "research_repository",
    "language_catalog",
    "pdf_catalog",
)
COLLECTION_METHODS = (
    "api",
    "published_dataset",
    "sitemap",
    "html_public_page",
    "manual_entry",
)
SOURCE_REVIEW_STATUSES = ("pending", "approved", "rejected")
RUN_STATUSES = ("running", "succeeded", "partial", "failed")
OBSERVATION_ENTITY_TYPES = (
    "organization",
    "department",
    "contact",
    "contact_method",
    "language_resource",
)
ORG_TYPES = (
    "government_agency",
    "university",
    "college",
    "research_institute",
    "library_archive",
    "cultural_institution",
    "ngo",
    "community_org",
    "other",
)
QUALIFICATION_STATUSES = ("discovered", "under_review", "qualified", "disqualified")
PUBLICATION_STATUSES = ("private", "in_review", "publishable")


CONTACT_REVIEW_STATUSES = ("unreviewed", "reviewed", "rejected", "erased")
METHOD_TYPES = ("email", "phone", "contact_form")
METHOD_REVIEW_STATUSES = ("unreviewed", "reviewed", "rejected")
VERIFICATION_STATUSES = ("unverified", "verified", "bounced", "invalid")
SUPPRESSION_VALUE_TYPES = ("email", "domain", "phone")
SUPPRESSION_REASONS = (
    "opt_out",
    "erasure_request",
    "bounced",
    "complaint",
    "legal",
    "internal_policy",
)
SUPPRESSION_STATUSES = ("active", "lifted")
REQUEST_CHANNELS = ("email", "web_form", "phone", "in_person", "other")


RESOURCE_TYPES = (
    "dictionary",
    "vocabulary_list",
    "corpus",
    "learning_guide",
    "educational_pdf",
    "publication",
    "research_dataset",
    "other",
)
DOWNLOAD_STATUSES = ("not_downloaded", "downloaded", "failed")
EXTRACTION_STATUSES = ("not_extracted", "extracted", "failed")
PRODUCTION_STATUSES = ("not_approved", "approved_for_production", "revoked")
PERMISSION_STATUSES = (
    "unknown",
    "pending_request",
    "approved",
    "restricted",
    "denied",
    "revoked",
)
PERMITTED_USES = (
    "internal_research",
    "product_use",
    "redistribution",
    "model_training",
    "public_display",
)
OBSERVATION_ROLES = ("discovery", "metadata", "license_evidence")

OBJECTIVES = ("resource_acquisition", "institutional_partnership")
OPPORTUNITY_STAGES = (
    "discovered",
    "under_review",
    "qualified",
    "approved_for_outreach",
    "engaged",
    "meeting_scheduled",
    "partnership_established",
    "declined",
    "closed",
)
QUALIFIED_STAGES = (
    "qualified",
    "approved_for_outreach",
    "engaged",
    "meeting_scheduled",
    "partnership_established",
)
CAMPAIGN_STATUSES = ("draft", "active", "paused", "completed")
ACTIVITY_STATUSES = (
    "drafted",
    "approved",
    "sent",
    "replied",
    "meeting_scheduled",
    "closed",
    "cancelled",
    "blocked",
)