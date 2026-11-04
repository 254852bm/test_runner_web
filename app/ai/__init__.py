"""AI-assisted test case drafting.

The package is intentionally isolated from the Flask application until the
provider and privacy settings have been reviewed and explicitly enabled.
"""

from .schemas import validate_test_case_draft
from .service import generate_test_case_draft

__all__ = ["generate_test_case_draft", "validate_test_case_draft"]
