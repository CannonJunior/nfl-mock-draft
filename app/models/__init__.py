# Re-export all core models from the parent models.py module.
# This makes `from app.models import Team` work regardless of whether
# Python resolves `app.models` as the package (this directory) or the
# adjacent models.py file.
from app.models_core import (  # noqa: F401
    BiographicalInfo,
    EnrichedPick,
    InjuryRecord,
    MediaLink,
    Pick,
    Player,
    StatView,
    Team,
)
