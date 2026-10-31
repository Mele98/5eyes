from routers.profiling import _canonical_risk_answer_section


def test_knowledge_answers_fall_back_to_risk_capacity_section_for_persistence():
    assert _canonical_risk_answer_section(1, "Kenntnisse & Erfahrungen") == "Risikofähigkeit"
    assert _canonical_risk_answer_section(2, "Kenntnisse & Erfahrungen") == "Risikofähigkeit"
    assert _canonical_risk_answer_section(3, "Kenntnisse & Erfahrungen") == "Risikofähigkeit"


def test_willingness_questions_keep_willingness_section():
    assert _canonical_risk_answer_section(9, "Kenntnisse & Erfahrungen") == "Risikobereitschaft"
    assert _canonical_risk_answer_section(11, "Risikobereitschaft") == "Risikobereitschaft"
