"""The deterministic quality scan and its recommendations.

Assertions are on exact counts and on *which tier* a finding lands in, because
those two things are the contract: a SAFE repair happens without asking, and
everything else becomes a question. Getting the split wrong is how a tool starts
silently changing someone's numbers.
"""

from autoviz.services import dataset, quality


def _register(registry, tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    ds = dataset.register_dataset(p.as_posix(), registry)["dataset_id"]
    return registry.get(ds)


def _kinds(issues):
    return {i.kind for i in issues}


# --- scoping ------------------------------------------------------------------


def test_scan_ignores_columns_the_analysis_does_not_use(registry, tmp_path):
    """A filthy column nobody asked about must not generate findings.

    This is what keeps the interruption rate a function of the *request* rather
    than of the dataset — otherwise a wide CSV makes every question expensive.
    """
    rec = _register(
        registry, tmp_path, "scoped.csv",
        "dept,salary,comments\neng,100,  messy  \neng,200,\nsales,300,   \n",
    )
    scoped = quality.scan(rec, {"dept", "salary"})
    assert scoped == []

    unscoped = quality.scan(rec, {"comments"})
    assert _kinds(unscoped) == {"untrimmed_whitespace", "blank_as_text", "missing_values"}


def test_scan_of_everything_still_finds_everything(registry, tmp_path):
    rec = _register(registry, tmp_path, "all.csv", "a,b\n x ,1\n,\n")
    assert "untrimmed_whitespace" in _kinds(quality.scan(rec))


# --- what counts as a finding --------------------------------------------------


def test_case_variants_only_reported_when_folding_merges_groups(registry, tmp_path):
    """Mixed case is only a problem when it splits one category into several."""
    merging = _register(registry, tmp_path, "merge.csv", "sex\nMale\nmale\nMALE\nFemale\n")
    issue = next(i for i in quality.scan(merging, {"sex"}) if i.kind == "case_variants")
    assert issue.detail == {"distinct": 4, "after_folding": 2}
    assert issue.affected == 3  # the three non-lowercase spellings

    unambiguous = _register(registry, tmp_path, "nomerge.csv", "sex\nMale\nFemale\n")
    assert "case_variants" not in _kinds(quality.scan(unambiguous, {"sex"}))


def test_exact_counts_for_whitespace_and_blanks(registry, tmp_path):
    # A second column keeps the blank-ish rows alive; pandas drops a wholly empty
    # trailing line, so a single-column fixture would silently lose them.
    rec = _register(registry, tmp_path, "counts.csv", "c,n\n a,1\nb ,2\nc,3\n   ,4\n,5\n")
    issues = {i.kind: i for i in quality.scan(rec, {"c"})}
    assert issues["untrimmed_whitespace"].affected == 3  # " a", "b ", "   "
    assert issues["blank_as_text"].affected == 1  # "   " (the empty cell is already null)
    assert issues["missing_values"].affected == 1


def test_high_cardinality_is_offered_bucketing_never_applied(registry, tmp_path):
    """Too many categories is a readability problem, not a data defect — so it is
    a question, and folding the tail into "Other" is never done unasked."""
    rows = "\n".join(f"id{i}" for i in range(quality.HIGH_CARDINALITY + 5))
    rec = _register(registry, tmp_path, "wide.csv", f"k\n{rows}\n")
    issues = quality.scan(rec, {"k"})
    assert "high_cardinality" in _kinds(issues)

    auto, proposals = quality.recommend(issues, len(rec.df))
    assert auto == []  # nothing semantics-preserving to do
    bucket = next(p for p in proposals if p.slot == "cardinality:k")
    recommended = next(o for o in bucket.options if o.recommended)
    assert recommended.op["op"] == "group_rare_categories"
    assert recommended.op["top_n"] == quality.DEFAULT_TOP_CATEGORIES
    assert any(o.op is None for o in bucket.options)  # "show every value" stays


def test_cardinality_is_only_asked_about_for_a_dimension(registry, tmp_path):
    """200 values are unreadable as an axis and irrelevant as a filter."""
    rows = "\n".join(f"id{i},1" for i in range(quality.HIGH_CARDINALITY + 5))
    rec = _register(registry, tmp_path, "dim.csv", f"k,v\n{rows}\n")
    _auto, proposals = quality.recommend(quality.scan(rec, {"k"}), len(rec.df))
    bucket = next(p for p in proposals if p.slot == "cardinality:k")
    assert quality.is_worth_asking(bucket, dimensions={"k"}) is True
    assert quality.is_worth_asking(bucket, dimensions=set()) is False


# --- the tier split ------------------------------------------------------------


def test_safe_repairs_are_auto_applied_and_grouped(registry, tmp_path):
    """One op per problem, covering every affected column — eight separate trim
    steps would burn the 10-step budget for no benefit."""
    rec = _register(registry, tmp_path, "grouped.csv", "a,b\n x , y \n z ,w\n")
    auto, proposals = quality.recommend(quality.scan(rec), len(rec.df))
    trims = [op for op in auto if op["op"] == "trim_whitespace"]
    assert len(trims) == 1 and sorted(trims[0]["columns"]) == ["a", "b"]
    assert proposals == []  # nothing here changes meaning


def test_suggestions_never_push_a_plan_over_the_step_budget(registry, tmp_path):
    """A wide messy dataset yields one normalize_case per column. Letting those
    overflow MAX_PREPROCESSING_STEPS would fail validation on a plan the user
    wrote correctly — the tool's own helpfulness breaking their request."""
    cols = [f"c{i}" for i in range(12)]
    header = ",".join(cols)
    rows = "\n".join(",".join(f"{v}{i}" for i in range(12)) for v in ("A", "a", "B"))
    rec = _register(registry, tmp_path, "wide_messy.csv", f"{header}\n{rows}\n")

    auto, _proposals = quality.recommend(quality.scan(rec), len(rec.df))
    assert len(auto) > quality.MAX_PREPROCESSING_STEPS  # more repairs than room

    existing = [{"op": "drop_nulls", "columns": ["c0"], "how": "any"}]
    merged, dropped = quality.merge_auto_ops(existing, auto)
    assert len(merged) <= quality.MAX_PREPROCESSING_STEPS
    # The trimming falls on suggestions; the user's own op survives intact.
    assert existing[0] in merged
    # And what the budget cut is handed back, not swallowed: a column left
    # half-cleaned looks cleaned, so the caller has to be able to say otherwise.
    assert dropped
    assert len(merged) - len(existing) + len(dropped) == len(auto)


def test_a_full_plan_gets_no_suggestions_rather_than_an_invalid_one(registry, tmp_path):
    rec = _register(registry, tmp_path, "full.csv", "a\n x \n")
    existing = [{"op": "drop_exact_duplicates"} for _ in range(quality.MAX_PREPROCESSING_STEPS)]
    suggestion = {"op": "trim_whitespace", "columns": ["a"]}
    merged, dropped = quality.merge_auto_ops(existing, [suggestion])
    assert merged == existing
    assert dropped == [suggestion]


def test_missing_values_are_always_asked_about_even_when_tiny(registry, tmp_path):
    """The explicit correction to percentage-only gating: 1% of a measure column
    can still move a total, so it is a question, not a silent fix."""
    rows = "\n".join("a,1" for _ in range(99))
    rec = _register(registry, tmp_path, "tiny.csv", f"cls,v\n{rows}\na,\n")
    auto, proposals = quality.recommend(quality.scan(rec, {"v"}), len(rec.df))
    assert auto == []
    assert len(proposals) == 1
    assert proposals[0].issue.fraction == 0.01


def test_duplicates_default_to_keeping_them(registry, tmp_path):
    """Identical rows are often legitimate repeated events, so 'obviously dirty'
    is not the same as 'wrong'."""
    rec = _register(registry, tmp_path, "dups.csv", "a,b\n1,x\n1,x\n2,y\n")
    _auto, proposals = quality.recommend(quality.scan(rec), len(rec.df))
    dup = next(p for p in proposals if p.slot == "duplicates")
    recommended = [o for o in dup.options if o.recommended]
    assert len(recommended) == 1
    assert recommended[0].op is None  # the recommendation is to do nothing


# --- how the recommendation is chosen ------------------------------------------


def test_few_missing_rows_recommends_excluding_them(registry, tmp_path):
    rows = "\n".join("a,1" for _ in range(90))
    rec = _register(registry, tmp_path, "few.csv", f"cls,v\n{rows}\n" + "a,\n" * 10)
    _auto, proposals = quality.recommend(quality.scan(rec, {"v"}), len(rec.df))
    recommended = next(o for o in proposals[0].options if o.recommended)
    assert recommended.op["op"] == "drop_nulls"


def test_mostly_missing_recommends_filling_rather_than_gutting_the_data(registry, tmp_path):
    rows = "\n".join("a,1" for _ in range(30))
    rec = _register(registry, tmp_path, "many.csv", f"cls,v\n{rows}\n" + "a,\n" * 70)
    _auto, proposals = quality.recommend(quality.scan(rec, {"v"}), len(rec.df))
    recommended = next(o for o in proposals[0].options if o.recommended)
    assert recommended.op["op"] == "fill_nulls"
    assert recommended.op["strategy"] == "median"


def test_categorical_column_is_offered_mode_not_median(registry, tmp_path):
    rec = _register(registry, tmp_path, "cat.csv", "cls,n\na,1\n,2\nb,3\n")
    _auto, proposals = quality.recommend(quality.scan(rec, {"cls"}), len(rec.df))
    fills = [o for p in proposals for o in p.options if o.op and o.op["op"] == "fill_nulls"]
    assert fills and all(o.op["strategy"] == "mode" for o in fills)


def test_every_proposal_has_exactly_one_recommendation_and_a_do_nothing(registry, tmp_path):
    """The novice path is one click; the escape hatch is always present."""
    rec = _register(registry, tmp_path, "mix.csv", "cls,v\na,1\n,\nb,3\nb,3\n")
    _auto, proposals = quality.recommend(quality.scan(rec), len(rec.df))
    assert proposals
    for p in proposals:
        assert sum(1 for o in p.options if o.recommended) == 1
        assert any(o.op is None for o in p.options)


def test_options_lead_with_plain_language_and_keep_jargon_separate(registry, tmp_path):
    rec = _register(registry, tmp_path, "words.csv", "cls,salary\na,1\n,\nb,3\n")
    _auto, proposals = quality.recommend(quality.scan(rec, {"salary"}), len(rec.df))
    option = next(o for p in proposals for o in p.options if o.op and o.op["op"] == "fill_nulls")
    assert "median" not in option.label.lower()  # jargon is not the headline
    assert "median" in option.technique  # but it is still stated


def test_proposals_are_ordered_by_impact(registry, tmp_path):
    rec = _register(
        registry, tmp_path, "order.csv",
        "small,big\n1,1\n2,\n3,\n4,\n5,\n6,\n7,\n8,\n9,\n,\n",
    )
    _auto, proposals = quality.recommend(quality.scan(rec, {"small", "big"}), len(rec.df))
    assert [p.slot for p in proposals][0] == "missing:big"


# --- report shape --------------------------------------------------------------


def test_report_is_scoped_and_serialisable(registry, tmp_path):
    rec = _register(registry, tmp_path, "report.csv", "a,b\n x ,1\n,2\n")
    report = quality.analyze_data_quality(rec, {"a"})
    assert report["row_count"] == 2
    assert report["columns_inspected"] == ["a"]
    assert report["auto_apply"] == [{"op": "trim_whitespace", "columns": ["a"]}]
    # Wire form only, no dataclasses left in it.
    assert all(isinstance(i, dict) for i in report["issues"])
    assert all(isinstance(p, dict) for p in report["proposals"])


def test_empty_scope_produces_an_empty_report(registry, tmp_path):
    rec = _register(registry, tmp_path, "none.csv", "a\n x \n")
    assert quality.scan(rec, set()) == []


# --- case variants and cardinality are independent findings ----------------------


def _many_variants(n_categories: int, cased: bool) -> str:
    """A column of `n_categories` values, optionally with a case variant of each."""
    rows = [f"cat{i:03d}" for i in range(n_categories)]
    if cased:
        rows += [r.upper() for r in rows]
    return "k\n" + "".join(f"{r}\n" for r in rows)


def test_a_column_can_report_both_case_variants_and_high_cardinality(registry, tmp_path):
    """These were mutually exclusive, and the case finding won.

    The consequence was silent: normalize_case is a SAFE auto-repair, so it fixed
    the spellings without asking, the grouping proposal was never raised, and the
    user got an unreadable chart of 40 categories with nothing appearing to have
    gone wrong.
    """
    rec = _register(registry, tmp_path, "both.csv", _many_variants(40, cased=True))
    kinds = _kinds(quality.scan(rec, {"k"}))
    assert "case_variants" in kinds
    assert "high_cardinality" in kinds


def test_cardinality_is_counted_after_folding(registry, tmp_path):
    """30 spellings of 15 categories is 15 bars once normalize_case has run, and
    15 is legible — so counting the raw distinct values would raise a grouping
    question about a chart that does not have the problem."""
    rec = _register(registry, tmp_path, "folds.csv", _many_variants(15, cased=True))
    kinds = _kinds(quality.scan(rec, {"k"}))
    assert "case_variants" in kinds
    assert "high_cardinality" not in kinds


def test_cardinality_still_fires_without_case_variants(registry, tmp_path):
    rec = _register(registry, tmp_path, "clean_wide.csv", _many_variants(40, cased=False))
    kinds = _kinds(quality.scan(rec, {"k"}))
    assert kinds == {"high_cardinality"}


def test_both_findings_yield_a_repair_and_a_question(registry, tmp_path):
    """The pairing that was unreachable: the casing is repaired silently *and* the
    grouping decision still reaches the user."""
    rec = _register(registry, tmp_path, "pair.csv", _many_variants(40, cased=True))
    auto, proposals = quality.recommend(quality.scan(rec, {"k"}), len(rec.df))
    assert {op["op"] for op in auto} == {"normalize_case"}
    assert [p.slot for p in proposals] == ["cardinality:k"]


# --- magnitude floor on missing-value questions ------------------------------
#
# Found by bench/nl_suite.py T05: "Compare average fare across embarkation
# towns" stopped to ask about 2 missing values in 891 rows (0.2%). The question
# was legitimate and the interruption was not worth it.


def _missing_proposal(registry, tmp_path, present: int, missing: int):
    rows = "\n".join(["a,1"] * present + [",1"] * missing)
    rec = _register(registry, tmp_path, "miss.csv", f"k,v\n{rows}\n")
    _auto, proposals = quality.recommend(quality.scan(rec, {"k"}), len(rec.df))
    return next(p for p in proposals if p.issue.kind == "missing_values")


def test_tiny_missing_share_is_disclosed_not_asked(registry, tmp_path):
    proposal = _missing_proposal(registry, tmp_path, present=889, missing=2)
    assert proposal.issue.fraction < 0.05
    assert quality.is_worth_asking(proposal, dimensions={"k"}) is False


def test_material_missing_share_on_a_dimension_is_still_asked(registry, tmp_path):
    proposal = _missing_proposal(registry, tmp_path, present=80, missing=20)
    assert proposal.issue.fraction >= 0.05
    assert quality.is_worth_asking(proposal, dimensions={"k"}) is True


def test_high_cardinality_is_not_silenced_by_the_row_fraction_floor(registry, tmp_path):
    """Its `fraction` is 0.0 by construction — it counts values, not rows."""
    rows = "\n".join(f"v{i},1" for i in range(30))
    rec = _register(registry, tmp_path, "dim2.csv", f"k,v\n{rows}\n")
    _auto, proposals = quality.recommend(quality.scan(rec, {"k"}), len(rec.df))
    bucket = next(p for p in proposals if p.slot == "cardinality:k")
    assert bucket.issue.fraction == 0.0
    assert quality.is_worth_asking(bucket, dimensions={"k"}) is True
