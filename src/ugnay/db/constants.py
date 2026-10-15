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