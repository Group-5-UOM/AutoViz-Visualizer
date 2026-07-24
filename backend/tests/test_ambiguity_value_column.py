"""Day 3: ambiguous column-reference and value-reference detectors."""

from autoviz.agent.ambiguity import detect_ambiguities
from autoviz.services import dataset as dataset_service

# Two categorical "city" columns sharing the value "London".
CITY_SCHEMA = [
    {"name": "home_city", "type": "string"},
    {"name": "work_city", "type": "string"},
    {"name": "revenue", "type": "number"},
]
CITY_PROFILE = {
    "cardinality": {"home_city": 3, "work_city": 3, "revenue": 900},
    "sample_values": {
        "home_city": ["Boston", "London", "Paris"],
        "work_city": ["Berlin", "London", "Tokyo"],
    },
}


def _detect(request, schema, profile=None):
    return detect_ambiguities(request, schema, profile or {})


# --- column-reference --------------------------------------------------------

def test_column_reference_when_concept_matches_two_columns():
    amb = next(a for a in _detect("total revenue by city", CITY_SCHEMA) if a.type == "column_reference")
    assert amb.slot == "dimension"
    assert [o.resolves_to["column"] for o in amb.options] == ["home_city", "work_city"]
    assert amb.detail["term"] == "city"


def test_column_reference_suppressed_by_exact_match():
    schema = CITY_SCHEMA + [{"name": "city", "type": "string"}]
    # "city" now names a real column exactly -> not ambiguous.
    assert not any(a.type == "column_reference" for a in _detect("count by city", schema))


def test_column_reference_ignores_stopwords():
    # "total"/"revenue" won't trigger; only a real shared concept would.
    assert not any(a.type == "column_reference" for a in _detect("show total revenue", CITY_SCHEMA))


def test_column_reference_skips_pure_date_clash():
    schema = [{"name": "start_date", "type": "datetime"}, {"name": "end_date", "type": "datetime"}]
    # "date" matches two datetime columns -> left to the time_column detector, not column_reference.
    ambs = _detect("trend by date over time", schema)
    assert not any(a.type == "column_reference" for a in ambs)


# --- value-reference ---------------------------------------------------------

def test_value_reference_when_literal_in_two_columns():
    amb = next(
        a for a in _detect("show revenue for London", CITY_SCHEMA, CITY_PROFILE)
        if a.type == "value_reference"
    )
    assert amb.slot == "filter_value"
    assert amb.detail["value"] == "london"
    assert [o.resolves_to["column"] for o in amb.options] == ["home_city", "work_city"]
    assert amb.options[0].resolves_to["value"] == "London"  # original casing preserved


def test_value_reference_not_triggered_for_single_column_value():
    # "Paris" only appears in home_city -> unambiguous.
    assert not any(
        a.type == "value_reference" for a in _detect("revenue for Paris", CITY_SCHEMA, CITY_PROFILE)
    )


def test_value_reference_needs_sample_values():
    # No profile sample_values -> detector is a no-op.
    assert not any(a.type == "value_reference" for a in _detect("revenue for London", CITY_SCHEMA))


# --- integration: real profile carries sample_values -------------------------

def test_profile_now_exposes_sample_values(registry, titanic_id):
    profile = dataset_service.get_dataset_profile(titanic_id, registry)
    assert "sample_values" in profile
    # Low-cardinality categoricals are captured; high-card / numeric are not.
    assert set(profile["sample_values"]["sex"]) == {"female", "male"}
    assert "fare" not in profile["sample_values"]  # numeric, excluded


def test_no_false_ambiguity_on_plain_titanic_request(registry, titanic_id):
    schema = dataset_service.get_dataset_schema(titanic_id, registry)["columns"]
    profile = dataset_service.get_dataset_profile(titanic_id, registry)
    # A fully-specified request must not trip any detector.
    assert detect_ambiguities("average fare by passenger class", schema, profile) == []
